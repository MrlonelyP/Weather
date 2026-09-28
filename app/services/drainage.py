"""Drainage / catchment intelligence for a point.

Combines three scales, each labelled with its source and method:
  local  (Copernicus 30 m window + OSM waterways) -> flow direction, path, first waterway reached,
                                                       possible accumulation zone
  basin  (HydroSHEDS 15" DIR/ACC)                   -> basin-scale upstream area / corridor
  units  (HydroBASINS levels 5 / 7 / 12)            -> basin, sub_basin, local catchment + topology
"""
from __future__ import annotations

import json
import math
import threading
from collections import Counter, OrderedDict
from functools import lru_cache
from pathlib import Path

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.engines import engine_config
from app.engines.flow import LIMITS_TH, analyze_flow
from app.engines.terrain import COMPASS_TH
from app.services.dem_download import dataset_info
from app.services.dem_reader import DemReader
from app.services.hydro_import import hydro_config, hydro_dir
from app.services.terrain_data import NO_DEM_INSTALLED
from app.services.waterways import TYPE_TH

_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_LOCK = threading.Lock()
# HydroSHEDS / ESRI D8 codes
D8_CODE = {1: "E", 2: "SE", 4: "S", 8: "SW", 16: "W", 32: "NW", 64: "N", 128: "NE"}


def _window_transform(w, res: float):
    from rasterio.transform import Affine

    west = w.cell_lon - w.col * res - res / 2
    north = w.cell_lat + w.row * res + res / 2
    return Affine(res, 0, west, 0, -res, north)


def waterway_grid(session: Session, w, res: float) -> tuple[np.ndarray, dict[int, dict]]:
    """Rasterize OSM waterways inside the DEM window; label k -> waterway record."""
    from rasterio.features import rasterize

    tr = _window_transform(w, res)
    h, wd = w.grid.shape
    west, north = tr.c, tr.f
    east, south = west + wd * res, north - h * res
    types = engine_config()["flow"]["waterway_types_as_outlets"]
    rows = session.execute(text("""
        SELECT id, osm_type, osm_id, waterway_type, name, ST_AsGeoJSON(ST_Intersection(geom, e.g)) AS gj
        FROM waterway, (SELECT ST_MakeEnvelope(:w, :s, :e, :n, 4326) AS g) e
        WHERE geom && e.g AND waterway_type = ANY(:types)"""),
        {"w": west, "s": south, "e": east, "n": north, "types": types}).all()
    meta, shapes = {}, []
    rows = [r for r in rows if r.gj and json.loads(r.gj).get("coordinates")]
    for k, r in enumerate(rows, start=1):
        meta[k] = {"waterway_id": r.id, "osm_id": r.osm_id, "osm_type": r.osm_type, "name": r.name,
                   "waterway_type": r.waterway_type, "waterway_type_th": TYPE_TH.get(r.waterway_type, r.waterway_type)}
        shapes.append((json.loads(r.gj), k))
    if not shapes:
        return np.zeros((h, wd), dtype=np.int32), meta
    grid = rasterize(shapes, out_shape=(h, wd), transform=tr, fill=0, all_touched=True, dtype="int32")
    return grid, meta


def _cell_latlon(w, r: int, c: int, res: float) -> dict:
    return {"lat": round(w.cell_lat - (r - w.row) * res, 6), "lon": round(w.cell_lon + (c - w.col) * res, 6)}


def local_flow(session: Session, lat: float, lon: float) -> dict:
    settings = get_settings()
    ds = settings.terrain_primary_dataset
    p = engine_config()["flow"]
    reader = DemReader(ds)
    w = reader.read(lat, lon, p["window_half_m"]) if reader.root.is_dir() else None
    base = {"source": f"{dataset_info(ds)['name']} + OpenStreetMap waterways", "dataset": ds,
            "method_version": p["method_version"], "limitations": LIMITS_TH}
    if w is None:
        reason = "ไม่มี DEM ที่ตำแหน่งนี้" if reader.root.is_dir() else NO_DEM_INSTALLED
        return {**base, "available": False, "reason": reason, "message_th": reason, "confidence": 0.0}
    labels, meta = waterway_grid(session, w, reader.res)
    out = analyze_flow(w.grid, w.row, w.col, w.dx_m, w.dy_m, labels, p["dem_noise_m"].get(ds, 1.5), p)
    if not out.get("available"):
        return {**base, **out, "confidence": 0.0}
    out["downstream_path"] = [_cell_latlon(w, r, c, reader.res) for r, c in out.pop("path_cells")]
    if out["reached"]["type"] == "waterway":
        out["reached"] |= meta.get(out["reached"].pop("label"), {})
        out["reached"]["at"] = out["downstream_path"][-1]
    zone = out.get("accumulation_zone")
    if zone:
        zone |= _cell_latlon(w, zone.pop("row"), zone.pop("col"), reader.res)
    return {**base, **out}


# ------------------------------------------------------------------ basin-scale rasters
@lru_cache
def _raster(name: str):
    import rasterio

    path = hydro_dir(get_settings()) / f"{name}_region.tif"
    return rasterio.open(path) if path.exists() else None


_RLOCK = threading.Lock()


def basin_scale(lat: float, lon: float) -> dict:
    acc, dr = _raster("hydrosheds_acc_15s"), _raster("hydrosheds_dir_15s")
    base = {"source": "HydroSHEDS v1 15 arc-second (~450 m) flow direction / accumulation",
            "kind": "terrain_derived_flow (basin scale, hydrologically conditioned)"}
    if acc is None or dr is None:
        return {**base, "available": False, "reason": "ยังไม่ได้นำเข้า HydroSHEDS (python -m app.cli hydro-import)"}
    with _RLOCK:
        r, c = acc.index(lon, lat)
        if not (0 <= r < acc.height and 0 <= c < acc.width):
            return {**base, "available": False, "reason": "อยู่นอกพื้นที่ที่นำเข้า"}
        from rasterio.windows import Window

        a = acc.read(1, window=Window(c - 1, r - 1, 3, 3), boundless=True, fill_value=0).astype(float)
        d = int(dr.read(1, window=Window(c, r, 1, 1))[0, 0])
    res_m = 15 / 3600 * 110_574
    cell_km2 = res_m * res_m * math.cos(math.radians(lat)) / 1e6
    at_point = float(a[1, 1]) * cell_km2
    corridor = engine_config()["catchment"]["basin_acc_corridor_km2"]
    return {**base, "available": True, "upstream_area_km2": round(at_point, 1),
            "max_upstream_area_nearby_km2": round(float(a.max()) * cell_km2, 1),
            "flow_direction": D8_CODE.get(d), "flow_direction_th": COMPASS_TH.get(D8_CODE.get(d, ""), None),
            "on_drainage_corridor": bool(at_point >= corridor), "corridor_threshold_km2": corridor,
            "note": "ความละเอียด ~450 ม. ใช้ดูเส้นทางน้ำระดับลุ่มน้ำ ไม่ใช่ระดับถนน/ซอย"}


# ------------------------------------------------------------------ catchment units
def unit_at(session: Session, lat: float, lon: float, level: int):
    return session.execute(text("""
        SELECT hybas_id, next_down, main_bas, sub_area_km2, up_area_km2, pfaf_id FROM hydro_basin
        WHERE level = :lv AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) LIMIT 1"""),
        {"lv": level, "lat": lat, "lon": lon}).one_or_none()


def thai_basin_name(session: Session, hybas_id: int) -> dict | None:
    """Most common ThaiWater `river_basin` among stations inside the unit (ThaiWater's own labels)."""
    rows = session.execute(text("""
        SELECT ws.river_basin FROM water_station ws JOIN hydro_basin b ON ST_Contains(b.geom, ws.geom)
        WHERE b.hybas_id = :h AND ws.source = 'thaiwater' AND ws.river_basin IS NOT NULL
          AND ws.river_basin NOT IN ('ไม่ระบุ', 'นอกประเทศไทย')"""), {"h": hybas_id}).scalars().all()
    if not rows:
        return None
    name, n = Counter(rows).most_common(1)[0]
    return {"name": name, "share": round(n / len(rows), 2), "stations": len(rows),
            "method": "majority of ThaiWater station basin labels inside the unit"}


def catchment_assignment(session: Session, lat: float, lon: float, flat: bool) -> dict:
    lv = hydro_config()["catchment_levels"]
    units = {role: unit_at(session, lat, lon, level) for role, level in
             (("basin", lv["basin"]), ("sub_basin", lv["sub_basin"]), ("local_catchment", lv["local_catchment"]))}
    base = {"source": "HydroBASINS v1c (HydroSHEDS)", "levels": {k: v for k, v in lv.items() if not k.startswith("_")}}
    if units["local_catchment"] is None:
        return {**base, "available": False, "reason": "ไม่มีข้อมูลลุ่มน้ำที่ตำแหน่งนี้ (ยังไม่นำเข้าหรืออยู่ในทะเล)",
                "confidence": 0.0}

    def unit(u):
        return None if u is None else {"hybas_id": u.hybas_id, "area_km2": u.sub_area_km2,
                                       "upstream_area_km2": u.up_area_km2, "next_down": u.next_down}
    thai = thai_basin_name(session, units["sub_basin"].hybas_id) if units["sub_basin"] else None
    if not thai or thai["stations"] < 3:
        thai = thai_basin_name(session, units["basin"].hybas_id) if units["basin"] else thai
    confidence = 0.3 if flat else 0.6
    return {**base, "available": True,
            "basin": unit(units["basin"]), "sub_basin": unit(units["sub_basin"]),
            "local_catchment": unit(units["local_catchment"]),
            "catchment_id": f"hybas12:{units['local_catchment'].hybas_id}",
            "thai_basin": thai,
            "confidence": confidence,
            "confidence_note": ("พื้นที่ราบ ขอบเขตลุ่มน้ำจาก DEM 15″ อาจไม่ตรงกับระบบระบายน้ำจริง" if flat else
                                "ขอบเขตลุ่มน้ำจาก HydroSHEDS 15″ (~450 ม.) ใกล้ขอบเขตอาจคลาดเคลื่อน")}


def upstream_units(session: Session, hybas_id: int, level: int = 12) -> set[int]:
    """The unit plus every unit of the same level that drains into it (within the imported region)."""
    graph = _level_graph(session, level)
    out, stack = {hybas_id}, [hybas_id]
    while stack:
        for up in graph.get(stack.pop(), ()):
            if up not in out:
                out.add(up)
                stack.append(up)
    return out


_GRAPHS: dict[int, dict[int, list[int]]] = {}


def _level_graph(session: Session, level: int) -> dict[int, list[int]]:
    if level not in _GRAPHS:
        g: dict[int, list[int]] = {}
        for hid, nd in session.execute(text("SELECT hybas_id, next_down FROM hydro_basin WHERE level = :l"), {"l": level}):
            g.setdefault(nd, []).append(hid)
        _GRAPHS[level] = g
    return _GRAPHS[level]


def reset_caches() -> None:
    _GRAPHS.clear()
    _CACHE.clear()
    _raster.cache_clear()


def drainage_at(session: Session, lat: float, lon: float) -> dict:
    key = (round(lat, 4), round(lon, 4))
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    flow = local_flow(session, lat, lon)
    flat = not flow.get("reliable", False)
    out = {"local_flow": flow, "basin_scale": basin_scale(lat, lon),
           "catchment": catchment_assignment(session, lat, lon, flat),
           "attribution": hydro_config()["license_attribution"]}
    with _LOCK:
        _CACHE[key] = out
        if len(_CACHE) > 1024:
            _CACHE.popitem(last=False)
    return out


def data_available() -> bool:
    return (hydro_dir(get_settings()) / "hydrosheds_acc_15s_region.tif").exists()


def raw_files(settings=None) -> list[Path]:
    return sorted((hydro_dir(settings or get_settings()) / "raw").glob("*/*"))
