"""Water-first endpoints: station detail, watch-list filters, nearby, search, tide."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import Geography
from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.cache import cached
from app.engines.water_impact import assess
from app.models import Location, Reservoir, WaterLevelObservation, WaterStation, WeatherStation
from app.services import catchment_rain
from app.services import freshness as fr
from app.services.database import get_db
from app.services.forecast_data import consensus_for_location
from app.services.normalizer import utcnow
from app.services.water_data import (filter_options, nearest_stations, observed_rain_24h_max, sort_stations,
                                     station_detail, stations_state)

router = APIRouter(prefix="/api")
TTL = 30
FORECAST_POINT_MAX_KM = 30


def _rain_windows(db: Session) -> dict:
    """Observed gauge windows (1/3/6/24 h) for the whole country, shared by catchment rain requests."""
    return cached("rain:windows", 120, lambda: catchment_rain.observed_windows(db))


def station_network(db: Session, st: WaterStation) -> dict:
    """Catchment, river-network link, upstream/downstream stations and catchment rain of one station."""
    from app.services.drainage import catchment_assignment
    from app.services.station_network import link_for, relations_for, station_catchment

    link = link_for(db, st.id)
    catch = station_catchment(db, link)
    rain = None
    if catch["units"]:
        rain = {"observed": catchment_rain.observed(db, catch["units"], _rain_windows(db)),
                "forecast": catchment_rain.forecast(db, catch["units"], (st.lat, st.lon))}
    units = catchment_assignment(db, st.lat, st.lon, flat=False) if st.lat is not None else {"available": False}
    return {
        "source": "HydroSHEDS (HydroBASINS v1c, HydroRIVERS v1.0) + OpenStreetMap + ThaiWater",
        "catchment": {k: units.get(k) for k in ("available", "basin", "sub_basin", "local_catchment", "catchment_id",
                                                 "thai_basin")},
        "catchment_method": catch["method"], "catchment_note": catch["note"],
        "catchment_area_km2": catch["area_km2"],
        "river_link": None if link is None else {
            "reach_method": link.reach_method, "hyriv_id": link.hyriv_id, "reach_distance_m": link.reach_distance_m,
            "reach_upland_km2": link.reach_upland_km2, "osm_waterway_name": link.osm_waterway_name,
            "confidence": link.confidence, "computed_at": link.computed_at},
        "relations": relations_for(db, st.id),
        "relations_note": "ยังไม่ประเมินเวลาที่น้ำเดินทางระหว่างสถานี (lag) จนกว่าจะมีข้อมูลย้อนหลังเพียงพอ",
        "catchment_rain": rain,
    }


def _all_states(db: Session) -> list[dict]:
    return cached("water:states:all", TTL, lambda: stations_state(db, "all"))


def _nearest_forecast_point(db: Session, lat: float, lon: float) -> tuple[Location, float] | None:
    point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    dist = func.ST_Distance(cast(Location.geom, Geography), cast(point, Geography))
    row = db.execute(select(Location, dist).where(Location.active.is_(True), Location.kind == "forecast_point",
                                                  Location.geom.isnot(None))
                     .order_by(dist).limit(1)).first()
    if row is None or row[1] > FORECAST_POINT_MAX_KM * 1000:
        return None
    return row[0], row[1]


def _impact(db: Session, lat: float | None, lon: float | None, state: dict | None) -> dict:
    fp = _nearest_forecast_point(db, lat, lon) if lat is not None and lon is not None else None
    windows = {}
    point = None
    if fp:
        loc, d = fp
        cons = cached(f"cons:{loc.code}", 60, lambda: consensus_for_location(db, loc, horizon_hours=24))
        windows = cons["windows"]
        point = {"code": loc.code, "name_th": loc.name_th, "distance_km": round(d / 1000, 1)}
    observed = observed_rain_24h_max(db, lat, lon) if lat is not None and lon is not None else None
    return assess(state, windows.get("rain_6h"), windows.get("rain_24h"), observed, point)


@router.get("/water/filters")
def water_filters(db: Session = Depends(get_db)):
    return {"generated_at": utcnow(), **filter_options(_all_states(db))}


@router.get("/water/stations/{station_code}")
def water_station_detail(station_code: str, range: str = Query("24h", pattern="^(6h|24h|3d|7d)$"),
                         db: Session = Depends(get_db)):
    def build():
        d = station_detail(db, station_code, range)
        if d is None:
            return None
        d["impact"] = _impact(db, d["lat"], d["lon"], d["state"])
        st = db.execute(select(WaterStation).where(WaterStation.source == "thaiwater",
                                                   WaterStation.station_code == station_code)).scalar_one_or_none()
        d["network"] = station_network(db, st) if st is not None else None
        d["freshness"] = fr.block_freshness(db, "thaiwater.waterlevel")
        return d
    data = cached(f"wdetail:{station_code}:{range}", TTL, build)
    if data is None:
        raise HTTPException(404, f"unknown station {station_code!r}")
    return data


@router.get("/water/nearby")
def water_nearby(lat: float = Query(..., ge=5, le=21), lon: float = Query(..., ge=97, le=106),
                 radius_km: float = Query(10, gt=0, le=50), db: Session = Depends(get_db)):
    """What matters around a point: nearest water stations, their rivers/canals, rain gauges, rain impact."""
    states = {s["station_code"]: s for s in _all_states(db)}
    near = nearest_stations(db, lat, lon, radius_km, "river", 10)
    stations = [{**states[st.station_code], "distance_km": round(d / 1000, 2)} if st.station_code in states else
                {"station_code": st.station_code, "name": st.name_th, "lat": st.lat, "lon": st.lon,
                 "distance_km": round(d / 1000, 2), "status": "UNKNOWN", "note": "ไม่มีค่าตรวจวัดล่าสุด"}
                for st, d in near]
    rivers: dict = defaultdict(list)
    for s in stations:
        if s.get("river"):
            rivers[s["river"]].append(s["station_code"])
    gauges = []
    for st, d in nearest_stations(db, lat, lon, radius_km, "rain_gauge", 8):
        obs = _latest_rain(db, st.id)
        gauges.append({"station_code": st.station_code, "name": st.name_th, "lat": st.lat, "lon": st.lon,
                       "distance_km": round(d / 1000, 2), "rain_24h_mm": obs.rain_mm if obs else None,
                       "rain_1h_mm": obs.rain_1h_mm if obs else None, "observed_at": obs.observed_at if obs else None})
    focus = next((s for s in stations if s.get("current_m") is not None), None)
    return {"generated_at": utcnow(), "center": {"lat": lat, "lon": lon}, "radius_km": radius_km,
            "stations": stations, "rivers": [{"name": k, "station_codes": v} for k, v in rivers.items()],
            "rain_gauges": gauges,
            "impact": _impact(db, lat, lon, focus),
            "impact_station": focus["station_code"] if focus else None,
            "flood_extent": {"available": False, "reason": "GISTDA ต้องใช้ API key"},
            "freshness": fr.block_freshness(db, "thaiwater.waterlevel")}


def _latest_rain(db: Session, station_id: int):
    return db.execute(select(WaterLevelObservation).where(WaterLevelObservation.station_id == station_id)
                      .order_by(WaterLevelObservation.observed_at.desc()).limit(1)).scalar_one_or_none()


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=80), db: Session = Depends(get_db)):
    """Water stations, rivers/canals, districts/provinces, dams, rain gauges nearby.

    When a district has no water-level station, the nearest stations (within 8 km) are
    returned instead and flagged `nearby`, so the user still sees what matters there.
    """
    like = f"%{q}%"
    ex = WaterStation.extra
    matches = db.execute(select(WaterStation).where(
        WaterStation.source == "thaiwater",
        or_(WaterStation.name_th.ilike(like), ex["river_name"].astext.ilike(like), ex["amphoe"].astext.ilike(like),
            ex["tumbon"].astext.ilike(like), ex["province_name"].astext.ilike(like),
            WaterStation.river_basin.ilike(like))).limit(500)).scalars().all()
    river_matches = [m for m in matches if m.station_kind == "river"]
    states = {s["station_code"]: s for s in _all_states(db)}

    # areas (district / province) from every station kind
    groups: dict = defaultdict(list)
    for st in matches:
        e = st.extra or {}
        for key, kind in (("amphoe", "district"), ("province_name", "province")):
            v = e.get(key)
            if v and q.lower() in v.lower():
                groups[(kind, v, e.get("province_name"))].append(st)
    areas = []
    for (kind, name, prov), sts in groups.items():
        pts = [(s.lat, s.lon) for s in sts if s.lat is not None]
        areas.append({"type": kind, "name": name, "province": prov,
                      "water_stations": sum(1 for s in sts if s.station_kind == "river"),
                      "rain_gauges": sum(1 for s in sts if s.station_kind == "rain_gauge"),
                      "center": {"lat": sum(p[0] for p in pts) / len(pts), "lon": sum(p[1] for p in pts) / len(pts)}
                      if pts else None,
                      "bbox": [min(p[1] for p in pts), min(p[0] for p in pts), max(p[1] for p in pts),
                               max(p[0] for p in pts)] if pts else None})
    areas.sort(key=lambda a: (a["type"] != "district", -(a["water_stations"] + a["rain_gauges"])))

    all_pts = [(s.lat, s.lon) for s in matches if s.lat is not None]
    center = areas[0]["center"] if areas and areas[0]["center"] else (
        {"lat": sum(p[0] for p in all_pts) / len(all_pts), "lon": sum(p[1] for p in all_pts) / len(all_pts)}
        if all_pts else None)

    stations = [dict(states[m.station_code], match="direct") for m in river_matches if m.station_code in states]
    nearby_note = None
    if not stations and center:
        for st, d in nearest_stations(db, center["lat"], center["lon"], 8, "river", 6):
            if st.station_code in states:
                stations.append(dict(states[st.station_code], match="nearby", distance_km=round(d / 1000, 2)))
        in_bangkok = any(a.get("province") == "กรุงเทพมหานคร" for a in areas) or any(
            (m.extra or {}).get("province_name") == "กรุงเทพมหานคร" for m in matches)
        nearby_note = "ไม่มีสถานีวัดระดับน้ำ (ThaiWater) ที่ตรงกับคำค้น แสดงสถานีใกล้เคียงแทน" + (
            "; สถานีวัดน้ำในคลองของ กทม. (BMA) ยังไม่ได้เชื่อมต่อ" if in_bangkok else "")
    stations = sort_stations([s for s in stations if s.get("match") == "direct"], "risk") + \
        [s for s in stations if s.get("match") == "nearby"]

    rivers: dict = defaultdict(int)
    for s in stations:
        if s.get("river"):
            rivers[s["river"]] += 1
    gauges = []
    if center:
        for st, d in nearest_stations(db, center["lat"], center["lon"], 5, "rain_gauge", 8):
            obs = _latest_rain(db, st.id)
            gauges.append({"station_code": st.station_code, "name": st.name_th, "lat": st.lat, "lon": st.lon,
                           "distance_km": round(d / 1000, 2), "rain_24h_mm": obs.rain_mm if obs else None,
                           "rain_1h_mm": obs.rain_1h_mm if obs else None,
                           "observed_at": obs.observed_at if obs else None})
    dams = db.execute(select(Reservoir).where(Reservoir.name_th.ilike(like)).limit(10)).scalars().all()
    wst = db.execute(select(WeatherStation).where(WeatherStation.name_th.ilike(like)).limit(10)).scalars().all()
    return {
        "query": q, "generated_at": utcnow(), "center": center, "areas": areas[:10],
        "stations": stations[:30], "stations_note": nearby_note,
        "rivers": [{"name": k, "stations": v} for k, v in sorted(rivers.items(), key=lambda x: -x[1])],
        "reservoirs": [{"reservoir_code": d.reservoir_code, "name": d.name_th, "region": d.region,
                        "lat": d.lat, "lon": d.lon} for d in dams],
        "weather_stations": [{"station_code": s.station_code, "name": s.name_th, "lat": s.lat, "lon": s.lon}
                             for s in wst],
        "rain_gauges_nearby": gauges,
        "flood_extent_nearby": {"available": False, "reason": "GISTDA ต้องใช้ API key"},
    }


@router.get("/tide")
def tide():
    return {"available": False, "stations": [], "generated_at": utcnow(),
            "reason": "ยังไม่มีแหล่งข้อมูลระดับน้ำทะเล/น้ำหนุนแบบใกล้เวลาจริงที่เปิดใช้ได้ "
                      "(หน้า sea level ของ HII มีข้อมูลล่าสุดปี 2019; ThaiWater public API ไม่มีบริการนี้)"}
