"""Location intelligence: terrain, nearby waterways, water and rain around a point."""
from __future__ import annotations

import json
from functools import lru_cache

from fastapi import APIRouter, Depends, Query
from shapely.geometry import Point, shape
from sqlalchemy.orm import Session

from app.api.cache import cached
from app.api.routes.water_api import _all_states, _impact, _rain_windows
from app.engines import engine_config, location_context
from app.services.database import get_db
from app.services import catchment_rain
from app.services.dem_download import CONFIG_DIR, terrain_config
from app.services.drainage import drainage_at, upstream_units
from app.services.hydro_import import hydro_config
from app.services.normalizer import utcnow
from app.services.relevance import relevant_station, relevant_waterway
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


def _nearby_stations(db: Session, lat: float, lon: float, radius_km: float, limit: int = 12) -> list[dict]:
    states = {x["station_code"]: x for x in _all_states(db)}
    out = []
    for st, d in nearest_stations(db, lat, lon, radius_km, "river", limit):
        base = states.get(st.station_code) or {"station_id": st.id, "station_code": st.station_code, "name": st.name_th,
                                               "lat": st.lat, "lon": st.lon, "river": (st.extra or {}).get("river_name"),
                                               "status": "UNKNOWN", "note": "ไม่มีค่าตรวจวัดล่าสุด"}
        out.append({**base, "distance_km": round(d / 1000, 2)})
    return out


def _location_catchment_rain(db: Session, drainage: dict, relevant: dict, lat: float, lon: float) -> dict | None:
    """Rain over the catchment that matters: the relevant station's when it is linked hydrologically,
    otherwise the point's own local catchment and everything upstream of it."""
    from app.models import WaterStation
    from app.services.station_network import link_for, station_catchment

    sel = relevant.get("selected")
    if sel and relevant["selection_method"] in ("same_waterway_and_catchment", "same_catchment"):
        catch = station_catchment(db, link_for(db, sel["station_id"]))
        st = db.get(WaterStation, sel["station_id"])
        units, basis, outlet = catch["units"], f"พื้นที่รับน้ำของสถานี {sel.get('name')}", (st.lat, st.lon)
    elif (drainage.get("catchment") or {}).get("available"):
        units = upstream_units(db, drainage["catchment"]["local_catchment"]["hybas_id"])
        basis, outlet = "พื้นที่รับน้ำย่อยของตำแหน่งนี้และพื้นที่ต้นน้ำ", (lat, lon)
    else:
        return None
    return {"basis_th": basis, "observed": catchment_rain.observed(db, units, _rain_windows(db)),
            "forecast": catchment_rain.forecast(db, units, outlet)}


@router.get("/drainage")
def drainage(lat: float = Query(..., ge=5, le=21), lon: float = Query(..., ge=97, le=106),
             db: Session = Depends(get_db)):
    """Terrain-derived flow, basin-scale flow and catchment units for one point."""
    return {"generated_at": utcnow(), "point": {"lat": lat, "lon": lon}, **drainage_at(db, lat, lon)}


@router.get("/location/analyze")
def analyze(lat: float = Query(..., ge=5, le=21), lon: float = Query(..., ge=97, le=106),
            radius_km: float = Query(None, gt=0, le=30), db: Session = Depends(get_db)):
    """Everything the system knows about one point, with plain-Thai explanation built from computed values."""
    radius_km = radius_km or engine_config()["catchment"]["station_search_km"]
    t = terrain_at(lat, lon)
    ww = nearby_waterways(db, lat, lon)
    dr = drainage_at(db, lat, lon)
    waterway = relevant_waterway(db, lat, lon, dr, ww)
    stations = _nearby_stations(db, lat, lon, radius_km)
    relevant = relevant_station(db, dr, waterway, stations)
    # a station is "related" to a nearby waterway only when the names match; distance alone is not enough
    names = {normalize_name(i["name"]): i for i in (ww.get("items") or []) if i.get("name")}
    for s in stations:
        hit = names.get(normalize_name(s.get("river")))
        if hit:
            s["related_waterway"] = {"name": hit["name"], "distance_m": hit["distance_m"], "selection_method": "name_matched"}
    focus = relevant.get("selected")
    focus_state = next((s for s in stations if focus and s["station_code"] == focus["station_code"]), None)
    impact = _impact(db, lat, lon, focus_state if focus_state and focus_state.get("current_m") is not None else None)
    catch_rain = _location_catchment_rain(db, dr, relevant, lat, lon)
    rain = {"observed_24h_max_mm": observed_rain_24h_max(db, lat, lon), "observed_radius_km": 10,
            "forecast": {k: impact["inputs"].get(k) for k in ("rain_6h", "rain_24h")},
            "forecast_point": impact.get("forecast_point"), "catchment": catch_rain}
    ctx = location_context.build(t, ww, stations, rain, impact,
                                 {"drainage": dr, "waterway": waterway, "relevant": relevant, "catchment_rain": catch_rain})
    wcfg = terrain_config()["waterways"]
    sources = [{"what": "terrain", "name": r["dataset"]["name"], "license": r["dataset"]["license"],
                "attribution": r["dataset"]["attribution"]} for r in t["datasets"].values()]
    sources.append({"what": "waterways", "name": wcfg["name"], "license": wcfg["license"], "attribution": wcfg["attribution"]})
    sources.append({"what": "hydrography", "name": "HydroSHEDS v1 (HydroBASINS, HydroRIVERS, 15s DIR/ACC)",
                    "license": hydro_config()["license"], "attribution": hydro_config()["license_attribution"]})
    sources.append({"what": "water_level_rain", "name": "ThaiWater (HII)", "license": None, "attribution": "สถาบันสารสนเทศทรัพยากรน้ำ (สสน.)"})
    flow = dr["local_flow"]
    return {
        "generated_at": utcnow(),
        "point": {"lat": lat, "lon": lon, "in_thailand": _in_thailand(lat, lon)},
        "summary_th": ctx["summary_th"],
        "terrain": {**t, "tiles": tile_provenance(db, t)},
        "terrain_signal": ctx["terrain_signal"],
        "drainage": dr,
        "relevant_waterway": waterway,
        "relevant_station": relevant,
        "waterways": ww,
        "water": {"radius_km": radius_km, "stations": stations, "impact_station": focus["station_code"] if focus else None},
        "rain": rain,
        "impact": impact,
        "flood_context": ctx["flood_context"],
        "reliability": [
            {"item": "flow_direction", "source": flow.get("source"), "selection_method": "terrain_derived_flow",
             "confidence": flow.get("confidence"), "data_freshness": "static (DEM)", "limitations": flow.get("limitations")},
            {"item": "catchment", "source": dr["catchment"].get("source"), "selection_method": "point_in_polygon",
             "confidence": dr["catchment"].get("confidence"), "data_freshness": "static (HydroBASINS v1c)",
             "limitations": [dr["catchment"].get("confidence_note")] if dr["catchment"].get("confidence_note") else []},
            {"item": "relevant_waterway", "source": waterway["source"], "selection_method": waterway["selection_method"],
             "confidence": (waterway.get("selected") or {}).get("confidence"),
             "data_freshness": f"OSM snapshot {ww.get('snapshot')}", "limitations": [waterway["reason_th"]]},
            {"item": "relevant_station", "source": "ThaiWater", "selection_method": relevant["selection_method"],
             "confidence": relevant["confidence"], "data_freshness": relevant.get("data_freshness"),
             "limitations": [relevant["reason_th"]]},
        ],
        "sources": sources,
    }
