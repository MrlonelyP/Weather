"""Download HydroSHEDS products and load the part covering Thailand into PostGIS / local rasters.

Only the zip members we need are streamed (HTTP range requests), every file is
recorded in `static_source_file` (URL, member, sha256, size, fetch time), and
nothing is edited: attributes are copied as published, geometries only get
ST_MakeValid.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.models import HydroBasin, HydroRiver, StaticSourceFile
from app.services.dem_download import CONFIG_DIR, _zip_members, stream_zip_member

log = logging.getLogger(__name__)
SHP_EXT = ("shp", "shx", "dbf", "prj")


@lru_cache
def hydro_config() -> dict:
    return json.loads((CONFIG_DIR / "hydro.json").read_text(encoding="utf-8"))


def hydro_dir(settings: Settings) -> Path:
    return Path(settings.dem_data_dir).parent / "hydro"


def basin_levels() -> list[int]:
    return get_settings().hydro_levels_list or hydro_config()["sources"]["hydrobasins_v1c"]["levels"]


def _members(dataset: str) -> list[str]:
    src = hydro_config()["sources"][dataset]
    tpl = src["members"]
    if dataset == "hydrobasins_v1c":
        return [tpl.format(level=lv, ext=e) for lv in basin_levels() for e in SHP_EXT]
    if "{ext}" in tpl:
        return [tpl.format(ext=e) for e in SHP_EXT]
    return [tpl]


def _record(session: Session, values: dict) -> None:
    stmt = insert(StaticSourceFile).values(**values, fetched_at=datetime.now(timezone.utc))
    stmt = stmt.on_conflict_do_update(constraint="uq_static_source_file_dataset_name", set_={
        k: stmt.excluded[k] for k in ("source_url", "source_member", "path", "bytes", "sha256", "status", "error",
                                      "fetched_at")})
    session.execute(stmt)
    session.commit()


def download(session: Session, datasets: list[str] | None = None, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    out: dict[str, int] = {}
    with httpx.Client(timeout=httpx.Timeout(settings.terrain_download_timeout_seconds, connect=30),
                      headers={"User-Agent": settings.http_user_agent}, follow_redirects=True) as client:
        for ds in datasets or list(hydro_config()["sources"]):
            url = hydro_config()["sources"][ds]["url"]
            index = {Path(k).name: v for k, v in _zip_members(client, url).items()}
            for name in _members(ds):
                dest = hydro_dir(settings) / "raw" / ds / name
                zi = index.get(name)
                base = {"dataset": ds, "name": name, "source_url": url, "source_member": zi.filename if zi else None,
                        "path": str(dest)}
                if zi is None:
                    _record(session, {**base, "status": "failed", "error": "member not in archive", "bytes": None,
                                      "sha256": None})
                    continue
                if dest.exists() and dest.stat().st_size == zi.file_size:
                    out[ds] = out.get(ds, 0) + 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    sha, size = stream_zip_member(client, url, zi, dest)
                    _record(session, {**base, "status": "downloaded", "bytes": size, "sha256": sha, "error": None})
                    out[ds] = out.get(ds, 0) + 1
                    log.info("%s %s %.1f MB", ds, name, size / 1e6)
                except Exception as exc:  # noqa: BLE001 - recorded, other files continue
                    _record(session, {**base, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:1000],
                                      "bytes": None, "sha256": None})
    return out


def _geojson(shape) -> str:
    return json.dumps(shape.__geo_interface__)


def _valid(geojson: str, kind: int):
    """kind 3 = polygons, 2 = lines."""
    return func.ST_Multi(func.ST_CollectionExtract(func.ST_MakeValid(
        func.ST_SetSRID(func.ST_GeomFromGeoJSON(geojson), 4326)), kind))


def import_basins(session: Session, settings: Settings | None = None, batch: int = 500) -> dict:
    import shapefile

    settings = settings or get_settings()
    bbox = hydro_config()["region_bbox"]
    counts = {}
    for level in basin_levels():
        path = hydro_dir(settings) / "raw" / "hydrobasins_v1c" / f"hybas_as_lev{level:02d}_v1c.shp"
        rows = []
        with shapefile.Reader(str(path)) as r:
            for sr in r.iterShapeRecords(bbox=bbox):
                a = sr.record.as_dict()
                rows.append({"hybas_id": int(a["HYBAS_ID"]), "level": level, "next_down": int(a["NEXT_DOWN"]),
                             "next_sink": int(a["NEXT_SINK"]), "main_bas": int(a["MAIN_BAS"]),
                             "pfaf_id": int(a["PFAF_ID"]), "sub_area_km2": float(a["SUB_AREA"]),
                             "up_area_km2": float(a["UP_AREA"]), "dist_main_km": float(a["DIST_MAIN"]),
                             "coast": int(a["COAST"]), "endo": int(a["ENDO"]),
                             "geom": _valid(_geojson(sr.shape), 3), "source_version": "v1c"})
        _upsert(session, HydroBasin, rows, "hybas_id", batch)
        counts[level] = len(rows)
        log.info("HydroBASINS level %d: %d units", level, len(rows))
    return counts


def import_rivers(session: Session, settings: Settings | None = None, batch: int = 1000) -> int:
    import shapefile

    settings = settings or get_settings()
    bbox = hydro_config()["region_bbox"]
    path = hydro_dir(settings) / "raw" / "hydrorivers_v10" / "HydroRIVERS_v10_as.shp"
    rows = []
    with shapefile.Reader(str(path)) as r:
        for sr in r.iterShapeRecords(bbox=bbox):
            a = sr.record.as_dict()
            rows.append({"hyriv_id": int(a["HYRIV_ID"]), "next_down": int(a["NEXT_DOWN"]),
                         "main_riv": int(a["MAIN_RIV"]), "length_km": float(a["LENGTH_KM"]),
                         "dist_dn_km": float(a["DIST_DN_KM"]), "dist_up_km": float(a["DIST_UP_KM"]),
                         "catch_km2": float(a["CATCH_SKM"]), "upland_km2": float(a["UPLAND_SKM"]),
                         "dis_av_cms": float(a["DIS_AV_CMS"]), "ord_stra": int(a["ORD_STRA"]),
                         "ord_clas": int(a["ORD_CLAS"]), "hybas_l12": int(a["HYBAS_L12"]),
                         "geom": _valid(_geojson(sr.shape), 2), "source_version": "v1.0"})
    _upsert(session, HydroRiver, rows, "hyriv_id", batch)
    return len(rows)


def _upsert(session: Session, model, rows: list[dict], key: str, batch: int) -> None:
    for i in range(0, len(rows), batch):
        stmt = insert(model).values(rows[i: i + batch])
        stmt = stmt.on_conflict_do_update(index_elements=[key], set_={
            c: stmt.excluded[c] for c in rows[0] if c != key})
        session.execute(stmt)
        session.commit()


def clip_rasters(settings: Settings | None = None) -> dict:
    """Cut the Asia-wide 15" rasters to the region box (the only part we read)."""
    import rasterio
    from rasterio.windows import from_bounds

    settings = settings or get_settings()
    out = {}
    for ds in ("hydrosheds_dir_15s", "hydrosheds_acc_15s"):
        src_path = hydro_dir(settings) / "raw" / ds / _members(ds)[0]
        dst_path = hydro_dir(settings) / f"{ds}_region.tif"
        with rasterio.open(src_path) as src:
            win = from_bounds(*hydro_config()["region_bbox"], transform=src.transform).round_offsets().round_lengths()
            data = src.read(1, window=win)
            profile = src.profile | {"width": data.shape[1], "height": data.shape[0],
                                     "transform": src.window_transform(win), "compress": "deflate", "tiled": True,
                                     "blockxsize": 256, "blockysize": 256}
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(data, 1)
            dst.update_tags(source=str(src_path.name), clipped_to=json.dumps(hydro_config()["region_bbox"]))
        out[ds] = {"path": str(dst_path), "shape": list(data.shape)}
    return out
