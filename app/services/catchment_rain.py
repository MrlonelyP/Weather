"""Rainfall over a catchment (set of HydroBASINS level-12 units), observed and forecast.

Observed (ThaiWater gauges, windows 1h / 3h / 6h / 24h ending at `as_of`):
  gauge_mean      plain mean over gauges inside the catchment
  gauge_max       highest gauge
  area_weighted   mean per level-12 unit that has gauges, weighted by unit area
  coverage        share of the catchment area whose unit has at least one reporting gauge
Units without a gauge are NOT filled in; low coverage is reported, not hidden.

Forecast (our consensus of ECMWF/GFS/JMA at the system's forecast points):
  only points located inside the catchment are used (method = points_in_catchment); when none is
  inside, the nearest point within 30 km of the catchment outlet is used and labelled
  proxy_nearest_point; otherwise unavailable.
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Location
from app.services.forecast_data import consensus_for_location
from app.services.normalizer import utcnow
from app.services.rainfall import gauge_windows

WINDOWS = ("1h", "3h", "6h", "24h")
FORECAST_WINDOWS = ("rain_1h", "rain_3h", "rain_6h")
PROXY_MAX_KM = 30
_UNITS: dict = {"at": 0.0, "gauge": {}, "area": {}, "points": {}}
_CONS: dict = {}  # (location id, as_of minute) -> consensus, so a snapshot of 800 stations computes each point once


def _unit_maps(session: Session) -> dict:
    """gauge station_id -> level-12 unit, unit -> area, forecast point -> unit (refreshed hourly)."""
    if time.time() - _UNITS["at"] > 3600 or not _UNITS["area"]:
        _UNITS["gauge"] = dict(session.execute(text("""
            SELECT ws.id, b.hybas_id FROM water_station ws JOIN hydro_basin b
              ON b.level = 12 AND ST_Contains(b.geom, ws.geom)
            WHERE ws.source = 'thaiwater' AND ws.station_kind = 'rain_gauge'""")).all())
        _UNITS["area"] = dict(session.execute(text("SELECT hybas_id, sub_area_km2 FROM hydro_basin WHERE level = 12")).all())
        _UNITS["points"] = dict(session.execute(text("""
            SELECT l.id, b.hybas_id FROM location l JOIN hydro_basin b ON b.level = 12 AND ST_Contains(b.geom, l.geom)
            WHERE l.active AND l.kind = 'forecast_point'""")).all())
        _UNITS["at"] = time.time()
    return _UNITS


def reset_cache() -> None:
    _UNITS["at"] = 0.0
    _CONS.clear()


def observed_windows(session: Session, as_of: datetime | None = None) -> dict[str, dict[int, dict]]:
    """All gauges' window values once (reuse for many catchments)."""
    as_of = as_of or utcnow()
    return {w: {p["station_id"]: p for p in gauge_windows(session, w, as_of)["points"]} for w in WINDOWS}


def observed(session: Session, units: set[int], windows: dict[str, dict[int, dict]]) -> dict:
    maps = _unit_maps(session)
    total_area = sum(maps["area"].get(u, 0) for u in units)
    out = {}
    for w, points in windows.items():
        vals, per_unit = [], {}
        for sid, p in points.items():
            u = maps["gauge"].get(sid)
            if u in units:
                vals.append(p["value_mm"])
                per_unit.setdefault(u, []).append(p["value_mm"])
        if not vals:
            out[w] = {"gauges": 0, "gauge_mean_mm": None, "gauge_max_mm": None, "area_weighted_mm": None,
                      "coverage": 0.0}
            continue
        covered = sum(maps["area"].get(u, 0) for u in per_unit)
        weighted = sum(sum(v) / len(v) * maps["area"].get(u, 0) for u, v in per_unit.items()) / covered if covered else None
        out[w] = {"gauges": len(vals), "gauge_mean_mm": round(sum(vals) / len(vals), 1),
                  "gauge_max_mm": round(max(vals), 1),
                  "area_weighted_mm": round(weighted, 1) if weighted is not None else None,
                  "coverage": round(covered / total_area, 2) if total_area else 0.0}
    return {"source": "ThaiWater rain gauges", "kind": "observed", "catchment_area_km2": round(total_area, 1),
            "units": len(units), "windows": out,
            "method": "gauge mean / max / level-12-unit area-weighted mean; units without gauges are not filled"}


def forecast(session: Session, units: set[int], outlet: tuple[float, float] | None,
             as_of: datetime | None = None) -> dict:
    maps = _unit_maps(session)
    inside = [lid for lid, u in maps["points"].items() if u in units]
    method = "points_in_catchment"
    locs = [session.get(Location, lid) for lid in inside]
    if not locs and outlet:
        row = session.execute(text("""
            SELECT id, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) d
            FROM location WHERE active AND kind = 'forecast_point' ORDER BY d LIMIT 1"""),
            {"lat": outlet[0], "lon": outlet[1]}).one_or_none()
        if row is not None and row.d <= PROXY_MAX_KM * 1000:
            locs, method = [session.get(Location, row.id)], "proxy_nearest_point"
    base = {"source": "system consensus forecast (ECMWF / GFS / JMA via Open-Meteo)", "kind": "forecast"}
    if not locs:
        return {**base, "available": False, "method": None,
                "reason": "ยังไม่มีจุดพยากรณ์ของระบบในหรือใกล้พื้นที่รับน้ำนี้ (ระบบพยากรณ์ครอบคลุมพื้นที่ทดสอบเท่านั้น)"}
    windows: dict[str, dict] = {}
    for loc in locs:
        key = (loc.id, (as_of or utcnow()).replace(second=0, microsecond=0))
        if key not in _CONS:
            if len(_CONS) > 256:
                _CONS.clear()
            _CONS[key] = consensus_for_location(session, loc, horizon_hours=24, now=as_of)
        cons = _CONS[key]
        for k in FORECAST_WINDOWS:
            v = (cons.get("windows") or {}).get(k)
            if v and v.get("consensus") is not None:
                windows.setdefault(k, []).append(v)
    out = {k: {"mean_mm": round(sum(x["consensus"] for x in v) / len(v), 1),
               "max_mm": round(max(x["consensus"] for x in v), 1),
               "confidence": round(min(x.get("confidence") or 0 for x in v), 2), "points": len(v)}
           for k, v in windows.items()}
    return {**base, "available": bool(out), "method": method, "points": [l.code for l in locs], "windows": out,
            "reason": None if out else "ไม่มีผลพยากรณ์ที่ยังใหม่พอ",
            "note": "ใช้จุดพยากรณ์ใกล้ทางออกของพื้นที่รับน้ำแทน (ไม่ได้อยู่ในพื้นที่รับน้ำ)" if method == "proxy_nearest_point" else None}
