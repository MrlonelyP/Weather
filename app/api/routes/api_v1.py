"""Dashboard API (/api/*). Reads only from our database - never from source APIs.

Every data block carries `freshness` (source_time, fetched_at, age, status) so the
UI can say how new the data is. Blocks without a connected source return
`available: false` with the reason, never placeholder values.
"""
from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.api.cache import cached
from app.config.settings import get_settings
from app.models import FloodExtent, Location, WaterLevelObservation, WaterStation, WeatherObservation, WeatherStation
from app.services import freshness as fr
from app.services.database import get_db
from app.services.forecast_data import consensus_for_location, get_location, latest_runs, model_series
from app.services.normalizer import utcnow
from app.services.rainfall import WINDOWS, gauge_windows, observed_hourly_near, synoptic_rain
from app.services.reservoir_data import reservoirs_overview
from app.services.warning_data import recent_warnings
from app.services.water_data import filter_stations, sort_stations, station_series, stations_state

router = APIRouter(prefix="/api")
TTL = 30  # seconds

FLOOD_RISK_UNAVAILABLE = {
    "available": False,
    "reason": "การประเมินความเสี่ยงน้ำท่วมโดยระบบ (Experimental Flood Risk v0.1) ยังไม่เปิดใช้งาน",
    "disclaimer": "เมื่อเปิดใช้ จะเป็นการประเมินความเสี่ยงโดยระบบ ไม่ใช่ประกาศเตือนภัยทางราชการ",
    "areas": [],
    # inputs already computed that the engine will explain with (none has a fixed weight)
    "prepared_signals": [
        {"name": "water_state", "endpoint": "/api/water/stations", "role": "primary"},
        {"name": "forecast_impact", "endpoint": "/api/water/stations/{code}", "role": "primary (qualitative)"},
        {"name": "terrain_signal", "endpoint": "/api/location/analyze", "role": "supporting only, no fixed weight"},
    ],
}


def _loc_or_404(db: Session, code: str) -> Location:
    loc = get_location(db, code)
    if loc is None:
        raise HTTPException(404, f"unknown location {code!r}")
    return loc


def _loc_view(loc: Location) -> dict:
    return {"code": loc.code, "name_th": loc.name_th, "name_en": loc.name_en, "province_code": loc.province_code,
            "lat": loc.lat, "lon": loc.lon}


# ---------------------------------------------------------------- sources / summary
@router.get("/sources/health")
def sources_health(db: Session = Depends(get_db)):
    return cached("sources", TTL, lambda: {"generated_at": utcnow(), "sources": fr.sources_freshness(db)})


def _rain24_summary(db: Session) -> dict:
    now = utcnow()
    cur = gauge_windows(db, "24h", now)
    top = max(cur["points"], key=lambda p: p["value_mm"], default=None)
    prev_max = None
    if top is not None:
        ref = top["observed_at"] - timedelta(hours=24)
        prev_max = db.execute(
            select(func.max(WaterLevelObservation.rain_mm))
            .join(WaterStation, WaterStation.id == WaterLevelObservation.station_id)
            .where(WaterLevelObservation.rain_mm.isnot(None),
                   WaterLevelObservation.observed_at.between(ref - timedelta(minutes=45),
                                                             ref + timedelta(minutes=45)))).scalar_one()
    return {
        "label": "ฝนสะสม 24 ชม. สูงสุด (สถานีวัดฝน)",
        "value": top["value_mm"] if top else None, "unit": "mm",
        "station": top["name"] if top else None, "province": top["province"] if top else None,
        "stations_reporting": cur["stations"],
        "previous_value": prev_max,
        "change": None if (top is None or prev_max is None) else round(top["value_mm"] - prev_max, 1),
        "change_basis": "เทียบค่าสูงสุดเมื่อ 24 ชม. ก่อน" if prev_max is not None else "ยังไม่มีข้อมูล 24 ชม. ก่อนสำหรับเทียบ",
        "freshness": fr.block_freshness(db, "thaiwater.rain"),
    }


def _critical_water_summary(db: Session) -> dict:
    now = utcnow()
    current = stations_state(db, "all", now=now)
    crit = sum(1 for s in current if s["status"] == "CRITICAL")
    previous = stations_state(db, "all", now=now, at=now - timedelta(hours=24))
    comparable = len(previous) >= 0.5 * len(current) if current else False
    prev_crit = sum(1 for s in previous if s["status"] == "CRITICAL") if comparable else None
    return {
        "label": "สถานีระดับน้ำถึง/เกินตลิ่ง", "value": crit, "unit": "สถานี",
        "stations_evaluated": len(current),
        "change": None if prev_crit is None else crit - prev_crit,
        "change_basis": "เทียบ 24 ชม. ก่อน" if prev_crit is not None
        else "ยังมีประวัติ 24 ชม. ก่อนไม่พอสำหรับเทียบ",
        "status_basis": "ระบบคำนวณจากระดับน้ำเทียบระดับตลิ่งของสถานี (ไม่ใช่ประกาศทางราชการ)",
        "freshness": fr.block_freshness(db, "thaiwater.waterlevel"),
    }


@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    def build():
        res = reservoirs_overview(db)
        warns = recent_warnings(db, hours=48)
        active = [w for w in warns if w["active"]]
        return {
            "generated_at": utcnow(),
            "rain_24h": _rain24_summary(db),
            "critical_water": _critical_water_summary(db),
            "reservoirs": {
                "label": "เขื่อนขนาดใหญ่ (ปริมาณน้ำรวม)", "value": res["total_pct"], "unit": "%",
                "change": res["total_pct_change"], "change_basis": "เทียบรายงานวันก่อนหน้า",
                "count": len(res["reservoirs"]), "observed_date": res["observed_date"],
                "basis": res.get("total_basis"), "freshness": fr.block_freshness(db, "rid.dam"),
            },
            "flood_risk": {"label": "พื้นที่ที่ระบบประเมินว่าเสี่ยงสูง", "value": None, "unit": "พื้นที่",
                           **{k: FLOOD_RISK_UNAVAILABLE[k] for k in ("available", "reason")}},
            "warnings": {
                "active_public": sum(1 for w in active if w["severity"] != "info"),
                "active_aviation": sum(1 for w in active if w["severity"] == "info"),
                "total_48h": len(warns),
                "freshness": fr.block_freshness(db, "tmd.warning"),
            },
        }
    return cached("summary", TTL, build)


# ---------------------------------------------------------------- weather
@router.get("/weather/locations")
def weather_locations(db: Session = Depends(get_db)):
    locs = db.execute(select(Location).where(Location.active.is_(True), Location.kind == "forecast_point")
                      .order_by(Location.id)).scalars()
    return {"locations": [_loc_view(l) for l in locs]}


def _nearest_observation(db: Session, loc: Location, max_age_hours: int = 4) -> dict | None:
    point = func.ST_SetSRID(func.ST_MakePoint(loc.lon, loc.lat), 4326)
    dist = func.ST_Distance(cast(WeatherStation.geom, Geography), cast(point, Geography))
    row = db.execute(
        select(WeatherStation, WeatherObservation, dist.label("d"))
        .join(WeatherObservation, WeatherObservation.station_id == WeatherStation.id)
        .where(WeatherStation.geom.isnot(None),
               WeatherObservation.observed_at >= utcnow() - timedelta(hours=max_age_hours))
        .order_by(dist, WeatherObservation.observed_at.desc()).limit(1)).first()
    if row is None:
        return None
    st, o, d = row
    return {"kind": "observed", "source": "tmd", "station_code": st.station_code, "station_name": st.name_th,
            "distance_km": round(d / 1000, 1), "observed_at": o.observed_at, "temperature_c": o.temperature_c,
            "dew_point_c": o.dew_point_c, "humidity_pct": o.humidity_pct, "pressure_msl_hpa": o.pressure_msl_hpa,
            "wind_speed_kmh": o.wind_speed_kmh, "wind_direction_deg": o.wind_direction_deg,
            "visibility_km": o.visibility_km, "rain_mm": o.rain_mm, "rain_period_hours": o.rain_period_hours,
            "raw_payload_id": o.raw_payload_id}


def _hour_view(h: dict) -> dict:
    def c(var):
        return h[var]["consensus"] if isinstance(h.get(var), dict) else None
    return {
        "time": h["forecast_time"], "temperature_c": c("temperature_c"), "feels_like_c": h["feels_like_c"],
        "humidity_pct": c("humidity_pct"), "precipitation_mm": c("precipitation_mm"),
        "rain_probability_pct": h["rain_probability"]["value_pct"],
        "rain_probability_basis": h["rain_probability"]["basis"],
        "wind_speed_kmh": c("wind_speed_kmh"), "wind_direction_deg": c("wind_direction_deg"),
        "pressure_msl_hpa": c("pressure_msl_hpa"), "cloud_cover_pct": c("cloud_cover_pct"),
        "condition": h["condition"],
        "confidence": {k: h[k].get("confidence") for k in ("temperature_c", "precipitation_mm", "wind_speed_kmh")},
        "n_models": h["temperature_c"]["n_models"],
    }


def _forecast_freshness(db: Session) -> list[dict]:
    return [f for f in (fr.block_freshness(db, f"openmeteo.forecast.{m}") for m in ("ECMWF", "GFS", "JMA")) if f]


@router.get("/weather/current")
def weather_current(location: str = Query("bangkok"), db: Session = Depends(get_db)):
    def build():
        loc = _loc_or_404(db, location)
        cons = consensus_for_location(db, loc, horizon_hours=24)
        now_hour = cons["hourly"][0] if cons["hourly"] else None
        return {
            "location": _loc_view(loc), "generated_at": utcnow(),
            "observed": _nearest_observation(db, loc),
            "forecast_now": _hour_view(now_hour) if now_hour and now_hour["temperature_c"]["n_models"] else None,
            "forecast_basis": "Consensus ของระบบจาก ECMWF/GFS/JMA (ค่าคาดการณ์ ไม่ใช่ค่าตรวจวัด)",
            "hourly": [_hour_view(h) for h in cons["hourly"][1:25] if h["temperature_c"]["n_models"]],
            "models": cons["runs"],
            "freshness": {"observed": fr.block_freshness(db, "tmd.synoptic"), "forecast": _forecast_freshness(db)},
        }
    return cached(f"current:{location}", TTL, build)


@router.get("/weather/forecast")
def weather_forecast(location: str = Query("bangkok"), hours: int = Query(48, ge=1, le=240),
                     db: Session = Depends(get_db)):
    def build():
        loc = _loc_or_404(db, location)
        cons = consensus_for_location(db, loc, horizon_hours=hours)
        return {"location": _loc_view(loc), "generated_at": utcnow(), "hour0": cons["hour0"],
                "weights": cons["weights"], "weights_basis": cons["weights_basis"], "models": cons["runs"],
                "hourly": [_hour_view(h) for h in cons["hourly"] if h["temperature_c"]["n_models"]],
                "freshness": _forecast_freshness(db)}
    return cached(f"forecast:{location}:{hours}", TTL, build)


@router.get("/weather/consensus")
def weather_consensus(location: str = Query("bangkok"), hours: int = Query(48, ge=1, le=240),
                      db: Session = Depends(get_db)):
    """Full consensus detail: per-model values, consensus, min/max/median/spread/confidence."""
    def build():
        loc = _loc_or_404(db, location)
        cons = consensus_for_location(db, loc, horizon_hours=hours)
        return {"location": _loc_view(loc), "generated_at": utcnow(), **cons,
                "method": "weighted mean; confidence = coverage x agreement (see app/engines/forecast_consensus.py)",
                "freshness": _forecast_freshness(db)}
    return cached(f"consensus:{location}:{hours}", TTL, build)


@router.get("/weather/stations")
def weather_stations(db: Session = Depends(get_db)):
    """TMD stations with their newest observation (last 6 h) - for the map."""
    def build():
        since = utcnow() - timedelta(hours=6)
        sub = (select(WeatherObservation.station_id, func.max(WeatherObservation.observed_at).label("t"))
               .where(WeatherObservation.observed_at >= since).group_by(WeatherObservation.station_id).subquery())
        rows = db.execute(select(WeatherStation, WeatherObservation)
                          .join(sub, sub.c.station_id == WeatherStation.id)
                          .join(WeatherObservation, (WeatherObservation.station_id == sub.c.station_id)
                                & (WeatherObservation.observed_at == sub.c.t))
                          .where(WeatherStation.lat.isnot(None))).all()
        return {"generated_at": utcnow(), "stations": [
            {"station_code": st.station_code, "name": st.name_th, "province_code": st.province_code,
             "lat": st.lat, "lon": st.lon, "observed_at": o.observed_at, "temperature_c": o.temperature_c,
             "rain_mm": o.rain_mm, "rain_period_hours": o.rain_period_hours, "wind_speed_kmh": o.wind_speed_kmh,
             "source": "tmd", "kind": "observed"} for st, o in rows],
            "freshness": fr.block_freshness(db, "tmd.synoptic")}
    return cached("wstations", TTL, build)


# ---------------------------------------------------------------- rainfall
@router.get("/rainfall")
def rainfall(window: str = Query("1h", pattern="^(1h|3h|6h|24h)$"), db: Session = Depends(get_db)):
    """Observed rainfall per gauge for a window (the map's time selector)."""
    def build():
        data = gauge_windows(db, window)
        tmd = synoptic_rain(db, WINDOWS[window]) if window in ("3h", "6h", "24h") else []
        return {**data, "points": data["points"] + tmd, "generated_at": utcnow(),
                "freshness": {"gauges": fr.block_freshness(db, "thaiwater.rain"),
                              "synoptic": fr.block_freshness(db, "tmd.synoptic")}}
    return cached(f"rain:{window}", TTL, build)


@router.get("/rainfall/comparison")
def rainfall_comparison(location: str = Query("bangkok"), past_hours: int = Query(24, ge=1, le=72),
                        future_hours: int = Query(24, ge=1, le=72), radius_km: float = Query(10, gt=0, le=50),
                        db: Session = Depends(get_db)):
    """Observed (left of NOW) vs ECMWF/GFS/JMA + consensus (right of NOW), hourly mm."""
    def build():
        loc = _loc_or_404(db, location)
        now = utcnow()
        hour0 = now.replace(minute=0, second=0, microsecond=0)
        runs = latest_runs(db, now)
        series = model_series(db, loc, runs, hour0 - timedelta(hours=past_hours), hour0 + timedelta(hours=future_hours))
        models = {s.model: [{"time": t, "mm": v.get("precipitation_mm")} for t, v in sorted(s.points.items())]
                  for s in series}
        cons = consensus_for_location(db, loc, horizon_hours=future_hours, now=now)
        return {
            "location": _loc_view(loc), "generated_at": now, "now": now, "hour0": hour0,
            "observed": observed_hourly_near(db, loc, past_hours, radius_km, now),
            "models": models,
            "model_runs": [{"model": r.model, "model_run_time": r.model_run_time} for r in runs],
            "consensus": [{"time": h["forecast_time"], "mm": h["precipitation_mm"]["consensus"],
                           "confidence": h["precipitation_mm"].get("confidence")}
                          for h in cons["hourly"] if h["precipitation_mm"]["n_models"]],
            "windows": cons["windows"],
            "freshness": {"observed": fr.block_freshness(db, "thaiwater.rain"), "forecast": _forecast_freshness(db)},
        }
    return cached(f"cmp:{location}:{past_hours}:{future_hours}:{radius_km}", TTL, build)


# ---------------------------------------------------------------- water
@router.get("/water/stations")
def water_stations(scope: str = Query("all", pattern="^(all|key|area)$"),
                   sort: str = Query("risk", pattern="^(risk|level|trend)$"),
                   province: str | None = None, basin: str | None = None, river: str | None = None,
                   status: str | None = Query(None, description="comma separated, e.g. CRITICAL,WARNING"),
                   q: str | None = None,
                   limit: int = Query(1000, ge=1, le=2000), db: Session = Depends(get_db)):
    def build():
        items = stations_state(db, scope, get_settings().thaiwater_history_provinces_list)
        items = filter_stations(items, province, basin, river, status, q)
        items = sort_stations(items, sort)[:limit]
        counts = {k: sum(1 for s in items if s["status"] == k) for k in ("CRITICAL", "WARNING", "WATCH", "NORMAL",
                                                                          "UNKNOWN")}
        return {"generated_at": utcnow(), "scope": scope, "sort": sort, "counts": counts, "stations": items,
                "status_basis": "system_computed_v0.1 (ระยะถึงตลิ่ง + อัตราการขึ้น) - ไม่ใช่ประกาศทางราชการ",
                "freshness": fr.block_freshness(db, "thaiwater.waterlevel")}
    return cached(f"water:{scope}:{sort}:{limit}:{province}:{basin}:{river}:{status}:{q}", TTL, build)


@router.get("/water/trend")
def water_trend(station: str, hours: int = Query(48, ge=1, le=168), db: Session = Depends(get_db)):
    data = station_series(db, station, hours)
    if data is None:
        raise HTTPException(404, f"unknown station {station!r}")
    return {**data, "freshness": fr.block_freshness(db, "thaiwater.waterlevel")}


# ---------------------------------------------------------------- reservoirs / warnings / flood / news
@router.get("/reservoirs")
def reservoirs(db: Session = Depends(get_db)):
    return cached("reservoirs", TTL, lambda: {**reservoirs_overview(db), "generated_at": utcnow(),
                                              "freshness": fr.block_freshness(db, "rid.dam")})


@router.get("/warnings")
def warnings(hours: int = Query(48, ge=1, le=720), db: Session = Depends(get_db)):
    def build():
        items = recent_warnings(db, hours=hours)
        return {"generated_at": utcnow(), "warnings": items,
                "active_public": sum(1 for w in items if w["active"] and w["severity"] != "info"),
                "active_aviation": sum(1 for w in items if w["active"] and w["severity"] == "info"),
                "note": "ประกาศทางการจากหน่วยงานต้นทาง ระดับความรุนแรงที่แสดงจัดจากประเภทประกาศ",
                "freshness": fr.block_freshness(db, "tmd.warning")}
    return cached(f"warnings:{hours}", TTL, build)


@router.get("/flood/extent")
def flood_extent(db: Session = Depends(get_db)):
    def build():
        health = [fr.block_freshness(db, j) for j in ("gistda.flood_polygon", "gistda.flood_point_check")]
        rows = db.execute(select(FloodExtent.source_feature_id, FloodExtent.observed_at,
                                 func.ST_AsGeoJSON(FloodExtent.geometry)).limit(5000)).all()
        features = [{"type": "Feature", "id": fid, "properties": {"observed_at": t.isoformat() if t else None},
                     "geometry": json.loads(g)} for fid, t, g in rows]
        available = bool(features)
        reason = None
        if not available:
            statuses = [h["status"] for h in health if h]
            reason = ("GISTDA ต้องใช้ API key" if "NO_API_KEY" in statuses
                      else "ยังไม่มีข้อมูลพื้นที่น้ำท่วมจากดาวเทียม")
        return {"available": available, "reason": reason, "generated_at": utcnow(),
                "geojson": {"type": "FeatureCollection", "features": features}, "freshness": health}
    return cached("flood_extent", TTL, build)


@router.get("/flood/risk")
def flood_risk():
    return {**FLOOD_RISK_UNAVAILABLE, "generated_at": utcnow()}


@router.get("/news")
def news():
    return {"available": False, "items": [], "generated_at": utcnow(),
            "reason": "ยังไม่มีแหล่งข่าวที่เชื่อมต่อ (ข่าวจะแสดงแยกจากประกาศทางการ)"}


@router.get("/rainfall/forecast")
def rainfall_forecast(window: str = Query("6h", pattern="^(1h|3h|6h|12h|24h|48h)$"), db: Session = Depends(get_db)):
    """Consensus forecast rain for the next window at every forecast point (for the map's forecast mode)."""
    def build():
        locs = db.execute(select(Location).where(Location.active.is_(True), Location.kind == "forecast_point")
                          .order_by(Location.id)).scalars().all()
        points = []
        for loc in locs:
            cons = cached(f"cons:{loc.code}", 60, lambda loc=loc: consensus_for_location(db, loc, horizon_hours=48))
            w = cons["windows"].get(f"rain_{window}")
            if w and w.get("consensus") is not None:
                points.append({"code": loc.code, "name": loc.name_th, "lat": loc.lat, "lon": loc.lon,
                               "value_mm": w["consensus"], "min": w["min"], "max": w["max"],
                               "confidence": w["confidence"], "n_models": w["n_models"], "kind": "forecast"})
        return {"window": window, "kind": "forecast", "points": points, "generated_at": utcnow(),
                "note": "ฝนคาดการณ์ (consensus ECMWF/GFS/JMA) เฉพาะจุดพยากรณ์ในพื้นที่ทดสอบ",
                "freshness": _forecast_freshness(db)}
    return cached(f"rainfc:{window}", TTL, build)
