"""OSM waterways: import the national extract and find waterways near a point.

Source: HOT Export Tool extract of OpenStreetMap for Thailand (HDX), GeoJSON
lines, ODbL. The zip is kept on disk next to the DEM so an import can be
repeated; its export timestamp is stored as `source_snapshot` on every row.

Nearest-waterway results are distance based only. OSM does not say which
canal a street drains to, so `selection_method` is always "distance_based".
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import zipfile
from pathlib import Path

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.engines import engine_config
from app.models import Waterway
from app.services.dem_download import terrain_config

log = logging.getLogger(__name__)
SOURCE = "osm_hotosm_hdx"
TYPE_TH = {"river": "แม่น้ำ", "canal": "คลอง", "stream": "ลำธาร/ลำห้วย", "drain": "ท่อ/รางระบายน้ำ",
           "ditch": "คูน้ำ", "tidal_channel": "ร่องน้ำขึ้นลง", "brook": "ลำธาร"}


def extract_path(settings: Settings) -> Path:
    return Path(settings.dem_data_dir).parent / "osm" / Path(terrain_config()["waterways"]["url"]).name


def download_extract(settings: Settings | None = None, force: bool = False) -> Path:
    settings = settings or get_settings()
    path = extract_path(settings)
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with httpx.Client(timeout=httpx.Timeout(settings.terrain_download_timeout_seconds, connect=30),
                      headers={"User-Agent": settings.http_user_agent}, follow_redirects=True) as client:
        with client.stream("GET", terrain_config()["waterways"]["url"]) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for block in r.iter_bytes(1 << 20):
                    f.write(block)
    tmp.replace(path)
    return path


def _snapshot(z: zipfile.ZipFile) -> str | None:
    for name in z.namelist():
        if name.lower().endswith("readme.txt"):
            m = re.search(r"Exported Timestamp \(UTC\+0000\):\s*([0-9-]+ [0-9:]+)", z.read(name).decode("utf-8", "replace"))
            if m:
                return m.group(1) + "Z"
    return None


def import_extract(session: Session, path: Path, batch: int = 2000) -> dict:
    types = set(terrain_config()["waterways"]["types"])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as z:
        snapshot = _snapshot(z)
        member = next(n for n in z.namelist() if n.endswith(".geojson"))
        data = json.load(z.open(member))
    rows, skipped = [], 0
    for f in data["features"]:
        p, g = f.get("properties") or {}, f.get("geometry")
        kind = p.get("waterway")
        if kind not in types or not g or p.get("osm_id") is None:
            skipped += 1
            continue
        rows.append({"source": SOURCE, "osm_type": str(p.get("osm_type") or "ways_line")[:16], "osm_id": int(p["osm_id"]),
                     "waterway_type": kind, "name": (p.get("name") or p.get("name:th") or None),
                     "name_en": p.get("name:en") or None, "geom": json.dumps(g), "source_snapshot": snapshot})
    written = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i: i + batch]
        for r in chunk:
            r["geom"] = func.ST_Multi(func.ST_SetSRID(func.ST_GeomFromGeoJSON(r["geom"]), 4326))
        stmt = insert(Waterway).values(chunk)
        stmt = stmt.on_conflict_do_update(constraint="uq_waterway_source_osm", set_={
            k: stmt.excluded[k] for k in ("waterway_type", "name", "name_en", "geom", "source_snapshot")
        } | {"ingested_at": func.now()}).returning(Waterway.id)
        written += len(session.execute(stmt).all())
        session.commit()
    # lines that disappeared from the new extract are removed so results follow the snapshot
    removed = session.execute(text("DELETE FROM waterway WHERE source = :s AND source_snapshot IS DISTINCT FROM :snap"),
                              {"s": SOURCE, "snap": snapshot}).rowcount
    session.commit()
    return {"file": str(path), "sha256": sha, "snapshot": snapshot, "features": len(data["features"]),
            "imported": written, "skipped_other_types": skipped, "removed_stale": removed}


def nearby_waterways(session: Session, lat: float, lon: float, radius_m: float | None = None,
                     limit: int | None = None) -> dict:
    cfg = engine_config()["waterway_context"]
    radius_m = radius_m or cfg["search_radius_m"]
    limit = limit or cfg["max_results"]
    total = session.execute(select(func.count()).select_from(Waterway)).scalar_one()
    wcfg = terrain_config()["waterways"]
    meta = {"source": wcfg["name"], "license": wcfg["license"], "attribution": wcfg["attribution"],
            "selection_method": "distance_based",
            "selection_note": "เลือกจากระยะทางเท่านั้น ยังไม่ยืนยันว่าน้ำจากตำแหน่งนี้ไหลลงทางน้ำนี้"}
    if not total:
        return {**meta, "available": False, "reason": "ยังไม่ได้นำเข้าข้อมูลทางน้ำ (python -m app.cli waterways-import)"}
    deg = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.1)) * 1.05
    rows = session.execute(text("""
        WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS g)
        SELECT w.osm_type, w.osm_id, w.waterway_type, w.name, w.name_en, w.source_snapshot,
               ST_Distance(w.geom::geography, p.g::geography) AS d,
               ST_Y(ST_ClosestPoint(w.geom, p.g)) AS clat, ST_X(ST_ClosestPoint(w.geom, p.g)) AS clon
        FROM waterway w, p
        WHERE ST_DWithin(w.geom, p.g, :deg)
        ORDER BY w.geom <-> p.g
        LIMIT 60"""), {"lat": lat, "lon": lon, "deg": deg}).all()
    items = sorted(({"osm_id": r.osm_id, "osm_type": r.osm_type, "waterway_type": r.waterway_type,
                     "waterway_type_th": TYPE_TH.get(r.waterway_type, r.waterway_type), "name": r.name,
                     "name_en": r.name_en, "distance_m": round(r.d), "closest_point": {"lat": round(r.clat, 6), "lon": round(r.clon, 6)},
                     "osm_url": f"https://www.openstreetmap.org/{'relation' if r.osm_type.startswith('relation') else 'way'}/{r.osm_id}",
                     "source_snapshot": r.source_snapshot}
                    for r in rows if r.d <= radius_m), key=lambda x: x["distance_m"])
    # one entry per named waterway (a canal is often many OSM ways); unnamed ones stay separate
    seen, unique = set(), []
    for it in items:
        key = it["name"] or f"#{it['osm_id']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    named = next((i for i in unique if i["name"]), None)
    major = next((i for i in unique if i["waterway_type"] in ("river", "canal")), None)
    return {**meta, "available": True, "search_radius_m": radius_m, "nearest": unique[0] if unique else None,
            "nearest_named": named, "nearest_river_or_canal": major, "items": unique[:limit],
            "snapshot": unique[0]["source_snapshot"] if unique else None}


def normalize_name(name: str | None) -> str:
    return re.sub(r"\s+", "", name or "").lower()
