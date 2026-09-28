"""Location intelligence: terrain, nearby waterways, water and rain around a point."""
from __future__ import annotations

import json
from functools import lru_cache

from fastapi import APIRouter, Depends, Query
from shapely.geometry import Point, shape
from sqlalchemy.orm import Session

from app.api.cache import cached
from app.api.routes.water_api import _all_states, _impact
from app.engines import location_context
from app.services.database import get_db
from app.services.dem_download import CONFIG_DIR, terrain_config
from app.services.normalizer import utcnow
from app.services.terrain_data import datasets_status, terrain_at, tile_provenance
from app.services.water_data import nearest_stations, observed_rain_24h_max
from app.services.waterways import nearby_waterways, normalize_name

router = APIRouter(prefix="/api")


@lru_cache
def _thailand():
    fc = json.loads((CONFIG_DIR / terrain_config()["coverage"]["boundary_file"]).read_text(encoding="utf-8"))
    return shape(fc["features"][0]["geometry"])


def _in_thailand(lat: float, lon: float) -> bool:
    return _thailand().buffer(0.01).contains(Point(lon, lat))


@router.get("/terrain/datasets")
def terrain_datasets(db: Session = Depends(get_db)):
    return {"generated_at": utcnow(), "datasets": cached("terrain:datasets", 300, lambda: datasets_status(db))}


@router.get("/terrain")
def terrain(lat: float = Query(..., ge=5, le=21), lon: float = Query(..., ge=97, le=106),
            db: Session = Depends(get_db)):
    t = terrain_at(lat, lon)
    return {"generated_at": utcnow(), "point": {"lat": lat, "lon": lon}, **t, "tiles": tile_provenance(db, t)}


@router.get("/location/analyze")
def analyze(lat: float = Query(..., ge=5, le=21), lon: float = Query(..., ge=97, le=106),
            radius_km: float = Query(10, gt=0, le=30), db: Session = Depends(get_db)):
    """Everything the system knows about one point, with plain-Thai explanation built from computed values."""
    t = terrain_at(lat, lon)
    ww = nearby_waterways(db, lat, lon)
    states = {s["station_code"]: s for s in _all_states(db)}
    stations = []
    for st, d in nearest_stations(db, lat, lon, radius_km, "river", 8):
        base = states.get(st.station_code) or {"station_code": st.station_code, "name": st.name_th, "lat": st.lat,
                                               "lon": st.lon, "river": (st.extra or {}).get("river_name"),
                                               "status": "UNKNOWN", "note": "ไม่มีค่าตรวจวัดล่าสุด"}
        stations.append({**base, "distance_km": round(d / 1000, 2)})
    # a station is "related" to a nearby waterway only when the names match; distance alone is not enough
    names = {normalize_name(i["name"]): i for i in (ww.get("items") or []) if i.get("name")}
    for s in stations:
        hit = names.get(normalize_name(s.get("river")))
        if hit:
            s["related_waterway"] = {"name": hit["name"], "distance_m": hit["distance_m"], "selection_method": "name_match"}
    focus = next((s for s in stations if s.get("current_m") is not None), None)
    impact = _impact(db, lat, lon, focus)
    observed = observed_rain_24h_max(db, lat, lon)
    rain = {"observed_24h_max_mm": observed, "observed_radius_km": 10,
            "forecast": {k: impact["inputs"].get(k) for k in ("rain_6h", "rain_24h")},
            "forecast_point": impact.get("forecast_point")}
    ctx = location_context.build(t, ww, stations, rain, impact)
    wcfg = terrain_config()["waterways"]
    sources = [{"what": "terrain", "name": r["dataset"]["name"], "license": r["dataset"]["license"],
                "attribution": r["dataset"]["attribution"]} for r in t["datasets"].values()]
    sources.append({"what": "waterways", "name": wcfg["name"], "license": wcfg["license"], "attribution": wcfg["attribution"]})
    sources.append({"what": "water_level_rain", "name": "ThaiWater (HII)", "license": None, "attribution": "สถาบันสารสนเทศทรัพยากรน้ำ (สสน.)"})
    return {
        "generated_at": utcnow(),
        "point": {"lat": lat, "lon": lon, "in_thailand": _in_thailand(lat, lon)},
        "summary_th": ctx["summary_th"],
        "terrain": {**t, "tiles": tile_provenance(db, t)},
        "terrain_signal": ctx["terrain_signal"],
        "waterways": ww,
        "water": {"radius_km": radius_km, "stations": stations, "impact_station": focus["station_code"] if focus else None},
        "rain": rain,
        "impact": impact,
        "flood_context": ctx["flood_context"],
        "sources": sources,
    }
