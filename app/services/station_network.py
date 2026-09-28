"""Water stations on the river network: station -> HydroRIVERS reach, and upstream/downstream pairs.

Linking (per station, method recorded in station_hydro_link.reach_method):
  name_and_distance  an OSM waterway with the station's river name runs within 500 m of the station;
                     the HydroRIVERS reach closest to that named line (near the station) is chosen
  distance_only      no name match; the nearest reach within 1.5 km is chosen (lower confidence)
  none               no reach nearby (small canals are not in HydroRIVERS)

Relations: walk NEXT_DOWN from each linked station's reach; every station met on the way is
downstream of it (and it is upstream of them). River distance uses the position along the
reach (HydroRIVERS lines are digitised in flow direction). HydroRIVERS is a tree, so river
bifurcations / distributaries (e.g. Tha Chin, Noi, delta canals) cannot be represented: pairs
with different river names get half the confidence. Travel time is NOT estimated:
lag_hours stays null with lag_basis = "not_estimated" until historical data supports it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.engines import engine_config
from app.models import StationHydroLink, StationRelation, WaterStation
from app.services.waterways import normalize_name

log = logging.getLogger(__name__)
NETWORK = "hydrorivers_v10"


def _cfg() -> dict:
    return engine_config()["catchment"]


def link_station(session: Session, st: WaterStation) -> dict:
    cfg = _cfg()
    river = (st.extra or {}).get("river_name")
    pt = {"lat": st.lat, "lon": st.lon}
    osm = None
    if river:
        osm = session.execute(text("""
            WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) g)
            SELECT w.id, w.name, ST_Distance(w.geom::geography, p.g::geography) d
            FROM waterway w, p
            WHERE ST_DWithin(w.geom, p.g, 0.01) AND regexp_replace(lower(w.name), '\\s', '', 'g') = :n
            ORDER BY w.geom <-> p.g LIMIT 1"""), {**pt, "n": normalize_name(river)}).one_or_none()
        if osm is not None and osm.d > cfg["reach_name_match_osm_m"]:
            osm = None
    if osm is not None:
        # the reach that runs ALONG the named line near the station (small Hausdorff distance),
        # not one that merely touches it at a confluence
        reach = session.execute(text("""
            WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) g),
                 b AS (SELECT ST_Buffer(p.g::geography, 1000)::geometry g FROM p),
                 seg AS (SELECT ST_Intersection(w.geom, b.g) g FROM waterway w, b WHERE w.id = :wid)
            SELECT r.hyriv_id, r.upland_km2, ST_Distance(r.geom::geography, p.g::geography) d,
                   ST_HausdorffDistance(ST_Intersection(r.geom, b.g), seg.g) * 111000 AS dseg
            FROM hydro_river r, p, b, seg
            WHERE r.geom && ST_Expand(p.g, 0.02) AND ST_DWithin(r.geom::geography, p.g::geography, :rad)
              AND NOT ST_IsEmpty(ST_Intersection(r.geom, b.g))
            ORDER BY dseg, d LIMIT 1"""), {**pt, "wid": osm.id, "rad": cfg["reach_search_m"]}).one_or_none()
        method = "name_and_distance"
        confidence = 0.7 if reach is not None and reach.dseg < 450 else 0.5
    else:
        reach = session.execute(text("""
            WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) g)
            SELECT r.hyriv_id, r.upland_km2, ST_Distance(r.geom::geography, p.g::geography) d
            FROM hydro_river r, p WHERE r.geom && ST_Expand(p.g, 0.02) AND ST_DWithin(r.geom::geography, p.g::geography, :rad)
            ORDER BY d LIMIT 1"""), {**pt, "rad": cfg["reach_search_m"]}).one_or_none()
        method = "distance_only"
        confidence = 0.4 if reach is not None and reach.d < 500 else 0.25
    if reach is None:
        method, confidence = "none", None
    unit = session.execute(text("""
        SELECT hybas_id FROM hydro_basin WHERE level = 12
        AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) LIMIT 1"""), pt).scalar_one_or_none()
    pos = None
    if reach is not None:
        pos = session.execute(text("""
            SELECT ST_LineLocatePoint(ST_LineMerge(geom), ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
            FROM hydro_river WHERE hyriv_id = :h AND GeometryType(ST_LineMerge(geom)) = 'LINESTRING'"""),
            {**pt, "h": reach.hyriv_id}).scalar_one_or_none()
    return {"station_id": st.id, "method_version": _cfg()["method_version"],
            "hyriv_id": reach.hyriv_id if reach is not None else None,
            "reach_distance_m": round(reach.d) if reach is not None else None,
            "reach_upland_km2": reach.upland_km2 if reach is not None else None,
            "reach_method": method, "hybas_l12": unit,
            "osm_waterway_name": osm.name if osm is not None else None,
            "osm_waterway_distance_m": round(osm.d) if osm is not None else None,
            "confidence": confidence,
            "details": {"river_name_thaiwater": river, "position_along_reach": pos},
            "computed_at": datetime.now(timezone.utc)}


def link_all(session: Session) -> dict:
    stations = session.execute(select(WaterStation).where(
        WaterStation.source == "thaiwater", WaterStation.station_kind == "river",
        WaterStation.lat.isnot(None))).scalars().all()
    counts: dict[str, int] = {}
    for i, st in enumerate(stations, start=1):
        values = link_station(session, st)
        stmt = insert(StationHydroLink).values(**values)
        stmt = stmt.on_conflict_do_update(constraint="uq_station_hydro_link_station",
                                          set_={k: stmt.excluded[k] for k in values if k not in ("station_id", "method_version")})
        session.execute(stmt)
        counts[values["reach_method"]] = counts.get(values["reach_method"], 0) + 1
        if i % 100 == 0:
            session.commit()
            log.info("linked %d stations", i)
    session.commit()
    return counts


def link_missing(session: Session) -> dict:
    """Link river stations that appeared since the last full link (new stations, re-labelled ones)."""
    linked = select(StationHydroLink.station_id).where(StationHydroLink.method_version == _cfg()["method_version"])
    todo = session.execute(select(WaterStation).where(
        WaterStation.source == "thaiwater", WaterStation.station_kind == "river", WaterStation.lat.isnot(None),
        WaterStation.id.not_in(linked))).scalars().all()
    if not todo or not session.execute(text("SELECT EXISTS (SELECT 1 FROM hydro_river)")).scalar():
        return {"linked": 0}
    for st in todo:
        values = link_station(session, st)
        stmt = insert(StationHydroLink).values(**values)
        stmt = stmt.on_conflict_do_update(constraint="uq_station_hydro_link_station",
                                          set_={k: stmt.excluded[k] for k in values if k not in ("station_id", "method_version")})
        session.execute(stmt)
    session.commit()
    return {"linked": len(todo), **build_relations(session)}


def build_relations(session: Session) -> dict:
    cfg = _cfg()
    reaches = {r.hyriv_id: (r.next_down, r.length_km) for r in session.execute(
        text("SELECT hyriv_id, next_down, length_km FROM hydro_river"))}
    links = session.execute(select(StationHydroLink, WaterStation).join(
        WaterStation, WaterStation.id == StationHydroLink.station_id).where(
        StationHydroLink.method_version == cfg["method_version"], StationHydroLink.hyriv_id.isnot(None))).all()
    on_reach: dict[int, list] = {}
    for link, st in links:
        on_reach.setdefault(link.hyriv_id, []).append((link, st))
    session.execute(delete(StationRelation).where(StationRelation.network == NETWORK))
    rows = []
    for link, st in links:
        pos = (link.details or {}).get("position_along_reach")
        pos = 0.5 if pos is None else pos
        name = normalize_name((st.extra or {}).get("river_name"))
        reach, dist, hops = link.hyriv_id, 0.0, 0
        while reach and reach in reaches and dist <= cfg["relation_max_river_km"]:
            nd, length = reaches[reach]
            for other_link, other in on_reach.get(reach, []):
                if other.id == st.id:
                    continue
                opos = (other_link.details or {}).get("position_along_reach")
                opos = 0.5 if opos is None else opos
                if hops == 0 and opos <= pos:
                    continue  # same reach but not below this station
                d = dist + (opos - pos if hops == 0 else opos) * (length or 0)
                same = bool(name) and name == normalize_name((other.extra or {}).get("river_name"))
                # different names: tributary, or a distributary that the tree network cannot represent
                conf = round(min(link.confidence or 0, other_link.confidence or 0) * (1.0 if same else 0.5), 2)
                base = {"network": NETWORK, "river_distance_km": round(d, 1), "hops": hops,
                        "same_river_name": same, "lag_hours": None, "lag_basis": "not_estimated",
                        "confidence": conf, "method_version": cfg["method_version"],
                        "computed_at": datetime.now(timezone.utc)}
                rows.append({**base, "station_id": st.id, "other_station_id": other.id, "relation": "downstream"})
                rows.append({**base, "station_id": other.id, "other_station_id": st.id, "relation": "upstream"})
            dist += (length or 0) * ((1 - pos) if hops == 0 else 1)
            reach, hops = nd, hops + 1
    for i in range(0, len(rows), 1000):
        stmt = insert(StationRelation).values(rows[i: i + 1000]).on_conflict_do_nothing(
            constraint="uq_station_relation_pair")
        session.execute(stmt)
    session.commit()
    return {"pairs": len(rows) // 2, "linked_stations": len(links)}


def relations_for(session: Session, station_id: int, limit: int = 5) -> dict:
    rows = session.execute(select(StationRelation, WaterStation).join(
        WaterStation, WaterStation.id == StationRelation.other_station_id).where(
        StationRelation.station_id == station_id).order_by(StationRelation.river_distance_km)).all()
    out: dict[str, list] = {"upstream": [], "downstream": []}
    for rel, st in rows:
        if len(out[rel.relation]) < limit:
            out[rel.relation].append({"station_id": st.id, "station_code": st.station_code, "name": st.name_th,
                                      "river": (st.extra or {}).get("river_name"),
                                      "river_distance_km": rel.river_distance_km, "same_river_name": rel.same_river_name,
                                      "confidence": rel.confidence, "lag_hours": rel.lag_hours, "lag_basis": rel.lag_basis})
    return out


def link_for(session: Session, station_id: int) -> StationHydroLink | None:
    return session.execute(select(StationHydroLink).where(
        StationHydroLink.station_id == station_id,
        StationHydroLink.method_version == _cfg()["method_version"])).scalar_one_or_none()


# ------------------------------------------------------------------ station catchments
_REACH_GRAPH: dict = {}


def _reach_graph(session: Session) -> dict:
    if not _REACH_GRAPH:
        up: dict[int, list[int]] = {}
        unit: dict[int, int] = {}
        for rid, nd, h in session.execute(text("SELECT hyriv_id, next_down, hybas_l12 FROM hydro_river")):
            up.setdefault(nd, []).append(rid)
            unit[rid] = h
        _REACH_GRAPH.update(up=up, unit=unit)
    return _REACH_GRAPH


def station_catchment(session: Session, link: StationHydroLink | None) -> dict:
    """Level-12 units that drain to the station.

    reach_network    units crossed by every HydroRIVERS reach upstream of the station's reach (plus its own)
    local_unit_only  the station is on a channel HydroRIVERS does not contain (small canal): only the
                     level-12 unit around the station is used
    """
    if link is None or link.hybas_l12 is None:
        return {"units": set(), "method": None, "area_km2": None,
                "note": "สถานียังไม่ถูกผูกกับพื้นที่รับน้ำ"}
    if link.hyriv_id is None:
        return {"units": {link.hybas_l12}, "method": "local_unit_only", "area_km2": None,
                "note": "สถานีอยู่บนทางน้ำขนาดเล็กที่ไม่อยู่ในเครือข่าย HydroRIVERS จึงใช้เฉพาะพื้นที่รับน้ำย่อยที่สถานีตั้งอยู่"}
    g = _reach_graph(session)
    seen, stack = {link.hyriv_id}, [link.hyriv_id]
    while stack:
        for r in g["up"].get(stack.pop(), ()):
            if r not in seen:
                seen.add(r)
                stack.append(r)
    units = {g["unit"][r] for r in seen if g["unit"].get(r)} | {link.hybas_l12}
    return {"units": units, "method": "reach_network", "area_km2": link.reach_upland_km2,
            "reaches": len(seen),
            "note": "พื้นที่รับน้ำจากเครือข่ายแม่น้ำ HydroRIVERS (หน่วยย่อยที่มีลำน้ำต้นน้ำไหลผ่านถูกนับทั้งหน่วย)"}
