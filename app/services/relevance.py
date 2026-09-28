"""Which waterway and which water station are relevant to a location - by hierarchy, not distance alone.

Relevant waterway (first that applies):
  drainage_based   local DEM flow path from the point reaches a mapped waterway with confidence >= min
  catchment_based  the main HydroRIVERS reach of the point's local catchment, named by the OSM
                   river/canal running along it, within `catchment_waterway_max_m` of the point
  distance_based   nearest named river/canal (then any waterway) - stated as a fallback
  unknown

Relevant station (first tier with a candidate; fresher readings first, then distance):
  1 same_waterway_and_catchment  station on the relevant waterway AND the point's local catchment
                                 drains to the station (or it is the same local catchment)
  2 same_waterway                station on the relevant waterway (by name)
  3 same_catchment               the point's local catchment drains to the station's catchment
  4 nearby                       nearest station within the search radius
  5 none
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.engines import engine_config
from app.models import StationHydroLink
from app.services.station_network import station_catchment
from app.services.waterways import TYPE_TH, normalize_name

CATCHMENT_WATERWAY_MAX_M = 2000
REASON_TH = {
    "same_waterway_and_catchment": "อยู่บนทางน้ำเดียวกัน และพื้นที่นี้ระบายน้ำลงสู่ตำแหน่งสถานี",
    "same_waterway": "อยู่บนทางน้ำเดียวกัน (ชื่อตรงกัน)",
    "same_catchment": "พื้นที่รับน้ำของตำแหน่งนี้ไหลลงสู่ตำแหน่งสถานี (ตามขอบเขตลุ่มน้ำ HydroBASINS)",
    "nearby": "เลือกจากสถานีใกล้เคียง เนื่องจากยังไม่มีข้อมูลทางน้ำหรือพื้นที่รับน้ำที่เชื่อมกันได้",
    "none": "ไม่พบสถานีวัดระดับน้ำที่เหมาะสมในรัศมีที่ค้นหา",
}
WATERWAY_REASON_TH = {
    "drainage_based": "ทางไหลของน้ำจาก DEM ไปถึงทางน้ำนี้",
    "catchment_based": "เป็นทางน้ำสายหลักของพื้นที่รับน้ำย่อยที่ตำแหน่งนี้อยู่",
    "distance_based": "เลือกจากระยะทางที่ใกล้ที่สุด (ข้อมูลทางไหลของน้ำไม่พอ) ยังไม่ยืนยันว่าพื้นที่นี้ระบายน้ำลงทางน้ำนี้",
    "unknown": "ไม่พบทางน้ำที่เกี่ยวข้อง",
}


def relevant_waterway(session: Session, lat: float, lon: float, drainage: dict, waterways: dict) -> dict:
    flow = drainage.get("local_flow") or {}
    candidates: list[dict] = []
    reached = flow.get("reached") or {}
    if flow.get("available") and reached.get("type") == "waterway":
        candidates.append({"selection_method": "drainage_based", "name": reached.get("name"),
                           "waterway_type": reached.get("waterway_type"),
                           "waterway_type_th": reached.get("waterway_type_th"), "osm_id": reached.get("osm_id"),
                           "path_length_m": flow.get("path_length_m"), "confidence": flow.get("confidence"),
                           "usable": bool(flow.get("reliable")),
                           "note": None if flow.get("reliable") else flow.get("message_th")})
    catch = drainage.get("catchment") or {}
    if catch.get("available"):
        c = _catchment_waterway(session, lat, lon, catch["local_catchment"]["hybas_id"])
        if c:
            candidates.append(c)
    if waterways.get("available"):
        items = waterways.get("items") or []
        named_main = next((i for i in items if i.get("name") and i["waterway_type"] in ("river", "canal")), None)
        pick = named_main or waterways.get("nearest_named") or waterways.get("nearest")
        if pick:
            candidates.append({"selection_method": "distance_based", "name": pick.get("name"),
                               "waterway_type": pick["waterway_type"], "waterway_type_th": pick["waterway_type_th"],
                               "osm_id": pick["osm_id"], "distance_m": pick["distance_m"], "confidence": 0.3,
                               "usable": True, "note": WATERWAY_REASON_TH["distance_based"]})
    selected = next((c for c in candidates if c["usable"] and c.get("name")), None) \
        or next((c for c in candidates if c["usable"]), None)
    method = selected["selection_method"] if selected else "unknown"
    return {"selected": selected, "selection_method": method, "reason_th": WATERWAY_REASON_TH[method],
            "candidates": candidates, "source": "OpenStreetMap waterways + Copernicus DEM flow + HydroRIVERS"}


def _catchment_waterway(session: Session, lat: float, lon: float, hybas12: int) -> dict | None:
    row = session.execute(text("""
        WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) g),
             r AS (SELECT hyriv_id, upland_km2, geom FROM hydro_river WHERE hybas_l12 = :h
                   ORDER BY upland_km2 DESC LIMIT 1)
        SELECT r.hyriv_id, r.upland_km2, ST_Distance(r.geom::geography, p.g::geography) d,
               ST_Y(ST_ClosestPoint(r.geom, p.g)) clat, ST_X(ST_ClosestPoint(r.geom, p.g)) clon
        FROM r, p"""), {"lat": lat, "lon": lon, "h": hybas12}).one_or_none()
    if row is None:
        return None
    usable = row.d <= CATCHMENT_WATERWAY_MAX_M
    osm = session.execute(text("""
        WITH q AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) g)
        SELECT w.osm_id, w.name, w.waterway_type, ST_Distance(w.geom::geography, q.g::geography) d
        FROM waterway w, q WHERE w.name IS NOT NULL AND w.waterway_type IN ('river', 'canal')
          AND ST_DWithin(w.geom, q.g, 0.006) ORDER BY w.geom <-> q.g LIMIT 1"""),
        {"lat": row.clat, "lon": row.clon}).one_or_none()
    return {"selection_method": "catchment_based", "name": osm.name if osm else None,
            "waterway_type": osm.waterway_type if osm else "river",
            "waterway_type_th": TYPE_TH.get(osm.waterway_type if osm else "river"),
            "osm_id": osm.osm_id if osm else None, "hyriv_id": row.hyriv_id,
            "reach_upland_km2": row.upland_km2, "distance_m": round(row.d),
            "confidence": 0.4 if usable else 0.2, "usable": usable,
            "note": None if usable else f"ทางน้ำหลักของพื้นที่รับน้ำอยู่ห่าง {row.d / 1000:.1f} กม. ไกลเกินจะถือว่าเกี่ยวข้องโดยตรง"}


def relevant_station(session: Session, drainage: dict, waterway: dict, stations: list[dict]) -> dict:
    """stations: nearby river stations (state dicts with station_id, distance_km, river, observed_at...)."""
    catch = drainage.get("catchment") or {}
    local = catch["local_catchment"]["hybas_id"] if catch.get("available") else None
    wname = normalize_name((waterway.get("selected") or {}).get("name"))
    links = {}
    ids = [s["station_id"] for s in stations if s.get("station_id")]
    if ids:
        for link in session.query(StationHydroLink).filter(
                StationHydroLink.station_id.in_(ids),
                StationHydroLink.method_version == engine_config()["catchment"]["method_version"]):
            links[link.station_id] = link
    tiers: dict[str, list[dict]] = {k: [] for k in ("same_waterway_and_catchment", "same_waterway", "same_catchment", "nearby")}
    for s in stations:
        link = links.get(s.get("station_id"))
        same_way = bool(wname) and normalize_name(s.get("river")) == wname
        drains_to = False
        if local and link and link.hybas_l12:
            drains_to = local in station_catchment(session, link)["units"]
        tier = ("same_waterway_and_catchment" if same_way and drains_to else "same_waterway" if same_way
                else "same_catchment" if drains_to else "nearby")
        tiers[tier].append({**s, "catchment_link": {"hybas_l12": link.hybas_l12 if link else None,
                                                    "drains_from_location": drains_to}})
    for tier in tiers.values():
        tier.sort(key=lambda s: (s.get("current_m") is None, s.get("distance_km") or 99))
    for method, items in tiers.items():
        if items:
            best = items[0]
            conf = {"same_waterway_and_catchment": 0.7, "same_waterway": 0.55, "same_catchment": 0.45, "nearby": 0.25}[method]
            conf *= (waterway.get("selected") or {}).get("confidence", 0.5) / 0.5 if method.startswith("same_waterway") else 1
            return {"selected": _brief(best), "selection_method": method, "reason_th": REASON_TH[method],
                    "confidence": round(min(conf, 0.9), 2),
                    "data_freshness": {"observed_at": best.get("observed_at"),
                                       "has_current_reading": best.get("current_m") is not None},
                    "alternatives": [dict(_brief(x), selection_method=m) for m, xs in tiers.items() for x in xs
                                     if x is not best][:4]}
    return {"selected": None, "selection_method": "none", "reason_th": REASON_TH["none"], "confidence": 0.0,
            "alternatives": []}


def _brief(s: dict) -> dict:
    return {k: s.get(k) for k in ("station_id", "station_code", "name", "river", "distance_km", "status",
                                  "status_label_th", "current_m", "distance_to_bank_m", "trend", "trend_label_th",
                                  "rate_cm_per_h", "observed_at", "catchment_link")}
