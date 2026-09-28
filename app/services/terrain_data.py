"""Terrain for a point: read both DEMs, run the terrain engine, compare, keep provenance.

On-demand results are cached in memory by rounded coordinates (terrain does
not change); stations and forecast points are precomputed into
`terrain_profile` by `python -m app.cli terrain-precompute`.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.engines.terrain import POSITION_TH, analyze_grid, params
from app.models import DemTile, Location, TerrainProfile, WaterStation
from app.services.dem_download import dataset_info
from app.services.dem_reader import DemReader

log = logging.getLogger(__name__)
_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_CACHE_MAX = 2048
_LOCK = threading.Lock()

NO_DEM_INSTALLED = "เซิร์ฟเวอร์นี้ไม่ได้ติดตั้งไฟล์ DEM (เช่น เวอร์ชันฟรี) จึงวิเคราะห์ภูมิประเทศรายจุดไม่ได้"
LIMITS_TH = [
    "DEM ความละเอียด 30 ม. มีความคลาดเคลื่อนแนวดิ่งระดับเมตร พื้นที่ราบอย่างกรุงเทพฯ ความต่างที่น้อยกว่า ~1 ม. อาจเป็นเพียงความคลาดเคลื่อน",
    "Copernicus GLO-30 เป็น DSM (รวมความสูงอาคาร/ต้นไม้) ในเขตเมืองและป่าค่าพื้นอาจสูงกว่าจริงและเกิดแอ่งเทียมระหว่างอาคาร",
    "ความสูงอ้างอิง EGM2008 ไม่ใช่ ม.รทก. ของไทย จึงห้ามนำไปเทียบกับระดับน้ำ/ตลิ่งของสถานีโดยตรง",
    "ยังไม่รวมคันกั้นน้ำ ประตูระบายน้ำ ท่อระบายน้ำ และการสูบน้ำ ซึ่งมีผลมากในเขตเมือง",
    "การตรวจหาแอ่งทำในหน้าต่าง 2 กม. แอ่งที่ใหญ่กว่านั้นจะไม่ถูกตรวจพบ",
]


def dataset_meta(dataset: str) -> dict:
    info = dataset_info(dataset)
    return {k: info[k] for k in ("name", "version", "surface", "surface_note_th", "vertical_datum", "license",
                                 "commercial_use", "attribution", "resolution_m_approx")} | {"code": dataset}


def _window_half_m(p: dict) -> float:
    return max(max(p["radii_m"]), p["depression_window_m"]) + p["window_margin_m"]


def analyze_dataset(dataset: str, lat: float, lon: float) -> dict:
    p = params()
    reader = DemReader(dataset)
    if not reader.root.is_dir():
        return {"available": False, "dataset": dataset_meta(dataset), "reason": NO_DEM_INSTALLED}
    w = reader.read(lat, lon, _window_half_m(p))
    if w is None:
        return {"available": False, "dataset": dataset_meta(dataset),
                "reason": "ไม่มี DEM tile ของชุดข้อมูลนี้ที่ตำแหน่งนี้ (นอกพื้นที่ที่ดาวน์โหลด หรือเป็นทะเล)"}
    out = analyze_grid(w.grid, w.row, w.col, w.dx_m, w.dy_m, p)
    out["dataset"] = dataset_meta(dataset)
    out["dem_cell"] = {"lat": w.cell_lat, "lon": w.cell_lon}
    out["tiles"] = w.tiles
    if w.missing_tiles:
        out["missing_tiles"] = w.missing_tiles
        out["missing_tiles_note"] = "บางส่วนของหน้าต่างไม่มี tile (มักเป็นทะเล) ค่าส่วนนั้นถูกข้าม"
    return out


def compare(results: dict[str, dict], primary: str) -> dict:
    ok = {k: v for k, v in results.items() if v.get("available")}
    p = params()
    if len(ok) < 2:
        return {"datasets_compared": list(ok), "note": "มีผลจาก DEM ชุดเดียว เทียบความสอดคล้องไม่ได้"}
    (a_name, a), (b_name, b) = list(ok.items())[:2]
    diff = round(a["elevation_m"] - b["elevation_m"], 2)
    agree_pos = a["terrain_position"] == b["terrain_position"]
    agree_dep = a["local_depression"].get("possible_local_depression") == b["local_depression"].get("possible_local_depression")
    rel = {r: (a["relative_elevation"][r].get("relative_m"), b["relative_elevation"][r].get("relative_m"))
           for r in a["relative_elevation"]}
    note = None
    if not agree_pos or not agree_dep:
        note = "DEM สองชุดให้ผลไม่ตรงกัน (มักเกิดจากอาคาร/ต้นไม้ใน DSM) ให้ถือผลว่าไม่แน่นอน"
    elif abs(diff) > p["dataset_agreement_m"]:
        note = f"ความสูงสองชุดต่างกัน {abs(diff):.1f} ม. แต่ตำแหน่งเชิงเปรียบเทียบตรงกัน"
    return {"datasets_compared": [a_name, b_name], "elevation_diff_m": diff, "position_agree": agree_pos,
            "depression_agree": agree_dep, "relative_m_by_radius": rel, "note": note, "primary": primary}


def reliability(results: dict[str, dict], comparison: dict, primary: str) -> dict:
    """low / medium only: nothing here has been validated against ground survey yet."""
    res = results.get(primary) or {}
    reasons = []
    if not res.get("available"):
        return {"level": "none", "reasons": ["ไม่มีผลจาก DEM ที่ตำแหน่งนี้"]}
    rel500 = res["relative_elevation"].get("500", {})
    if rel500.get("within_noise"):
        reasons.append("ความต่างระดับกับพื้นที่รอบ ๆ อยู่ในช่วงความคลาดเคลื่อนของ DEM")
    if comparison.get("position_agree") is False or comparison.get("depression_agree") is False:
        reasons.append("DEM สองชุดให้ผลไม่ตรงกัน")
    if len(comparison.get("datasets_compared", [])) < 2:
        reasons.append("ไม่มี DEM ชุดที่สองไว้เทียบ")
    if res["dataset"]["surface"] == "DSM":
        reasons.append("ผลหลักมาจาก DSM ซึ่งรวมความสูงอาคาร/ต้นไม้")
    level = "low" if reasons else "medium"
    if not reasons:
        reasons.append("DEM สองชุดให้ผลสอดคล้องกันและความต่างระดับมากกว่าช่วงความคลาดเคลื่อน")
    return {"level": level, "reasons": reasons,
            "note": "ยังไม่ได้ตรวจสอบกับข้อมูลสำรวจภาคพื้นดิน จึงไม่มีระดับ high ใน v0.1"}


def license_warning(primary: str) -> str | None:
    info = dataset_info(primary)
    if info["commercial_use"]:
        return None
    return (f"DEM หลักถูกตั้งเป็น {info['name']} ซึ่งเป็น license {info['license']} (ห้ามใช้เชิงพาณิชย์) "
            "ค่าเริ่มต้นของ production คือ copernicus_glo30")


def terrain_at(lat: float, lon: float) -> dict:
    key = (round(lat, 4), round(lon, 4))  # ~11 m, finer than one DEM cell
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    settings = get_settings()
    primary = settings.terrain_primary_dataset
    results = {ds: analyze_dataset(ds, lat, lon) for ds in settings.terrain_dataset_list}
    for ds, r in results.items():  # comparison datasets never replace the primary, even when it is missing
        r["role"] = "primary" if ds == primary else "comparison_only"
    comparison = compare(results, primary)
    main = results.get(primary, {})
    out = {
        "available": bool(main.get("available")),
        "primary_dataset": primary,
        "method_version": params()["method_version"],
        "elevation_m": main.get("elevation_m"),
        "terrain_position": main.get("terrain_position", "UNKNOWN"),
        "terrain_position_th": POSITION_TH.get(main.get("terrain_position", "UNKNOWN")),
        "possible_local_depression": (main.get("local_depression") or {}).get("possible_local_depression"),
        "datasets": results,
        "comparison": comparison,
        "reliability": reliability(results, comparison, primary),
        "limits": LIMITS_TH,
        "license_warning": license_warning(primary),
        "computed_at": datetime.now(timezone.utc),
    }
    with _LOCK:
        _CACHE[key] = out
        if len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


def tile_provenance(session: Session, terrain: dict) -> list[dict]:
    wanted = {(ds, t) for ds, r in terrain.get("datasets", {}).items() for t in r.get("tiles", [])}
    if not wanted:
        return []
    rows = session.execute(select(DemTile).where(DemTile.dataset.in_({d for d, _ in wanted}),
                                                 DemTile.tile_id.in_({t for _, t in wanted}))).scalars().all()
    return [{"dataset": r.dataset, "tile_id": r.tile_id, "source_url": r.source_url, "source_member": r.source_member,
             "sha256": r.sha256, "fetched_at": r.fetched_at} for r in rows if (r.dataset, r.tile_id) in wanted]


def datasets_status(session: Session) -> dict:
    settings = get_settings()
    out = {}
    for ds in settings.terrain_dataset_list:
        rows = session.execute(select(DemTile.status, DemTile.fetched_at, DemTile.bytes).where(DemTile.dataset == ds)).all()
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        out[ds] = {**dataset_meta(ds), "tiles": counts, "bytes": sum(r.bytes or 0 for r in rows if r.status == "downloaded"),
                   "last_fetched_at": max((r.fetched_at for r in rows), default=None),
                   "role": "primary" if ds == settings.terrain_primary_dataset else "comparison_only"}
    return out


# ---------------------------------------------------------------- precompute
def _subjects(session: Session) -> list[tuple[str, str, float, float]]:
    subs = [("location", loc.code, loc.lat, loc.lon) for loc in session.execute(
        select(Location).where(Location.active.is_(True), Location.lat.isnot(None))).scalars()]
    subs += [("water_station", f"{st.source}:{st.station_code}", st.lat, st.lon) for st in session.execute(
        select(WaterStation).where(WaterStation.station_kind == "river", WaterStation.lat.isnot(None))).scalars()]
    return subs


def precompute(session: Session) -> dict:
    counts = {"subjects": 0, "rows": 0, "no_dem": 0}
    for kind, code, lat, lon in _subjects(session):
        counts["subjects"] += 1
        t = terrain_at(lat, lon)
        for ds, r in t["datasets"].items():
            if not r.get("available"):
                counts["no_dem"] += 1
                continue
            rel = r["relative_elevation"]
            dep = r["local_depression"]
            values = {
                "subject_type": kind, "subject_code": code, "dataset": ds, "method_version": r["method_version"],
                "lat": lat, "lon": lon, "elevation_m": r["elevation_m"],
                "rel_elev_250_m": rel["250"].get("relative_m"), "rel_elev_500_m": rel["500"].get("relative_m"),
                "rel_elev_1000_m": rel["1000"].get("relative_m"),
                "slope_deg": (r["slope"]["at_point"] or {}).get("slope_deg"),
                "terrain_position": r["terrain_position"],
                "possible_local_depression": dep.get("possible_local_depression"), "depression_depth_m": dep.get("depth_m"),
                "details": _jsonable(r), "computed_at": datetime.now(timezone.utc),
            }
            stmt = insert(TerrainProfile).values(**values)
            stmt = stmt.on_conflict_do_update(constraint="uq_terrain_profile_key", set_={
                k: stmt.excluded[k] for k in values if k not in ("subject_type", "subject_code", "dataset", "method_version")})
            session.execute(stmt.values(geom=f"SRID=4326;POINT({lon} {lat})"))
            counts["rows"] += 1
        if counts["subjects"] % 100 == 0:
            session.commit()
            log.info("terrain precompute: %d subjects", counts["subjects"])
    session.commit()
    return counts


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy scalar
        return obj.item()
    return obj

