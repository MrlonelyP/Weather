"""Download DEM tiles that cover Thailand and register them in `dem_tile`.

- copernicus_glo30: one Cloud Optimized GeoTIFF per 1x1 degree tile on AWS.
- fabdem_v1_2:      tiles are packed in 10x10 degree zip archives (0.4-2.9 GB each).
                    We read the zip's central directory with HTTP range requests and
                    stream only the members we need, so the archives are never
                    downloaded whole.

Every tile gets a row with its source URL, size, sha256, fetch time and the GeoTIFF
tags as published. Tiles the source does not have (open sea) are recorded as
`not_at_source`, never filled in.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import struct
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.models import DemTile

log = logging.getLogger(__name__)
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CHUNK = 1 << 20


@lru_cache
def terrain_config() -> dict:
    return json.loads((CONFIG_DIR / "terrain.json").read_text(encoding="utf-8"))


def dataset_info(dataset: str) -> dict:
    try:
        return terrain_config()["datasets"][dataset]
    except KeyError:
        raise ValueError(f"unknown DEM dataset {dataset!r}") from None


def tile_id(lat: int, lon: int) -> str:
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"


def coverage_tiles() -> list[tuple[int, int]]:
    """1x1 degree tiles (south-west corners) intersecting the buffered Thailand boundary."""
    from shapely.geometry import box, shape

    cov = terrain_config()["coverage"]
    fc = json.loads((CONFIG_DIR / cov["boundary_file"]).read_text(encoding="utf-8"))
    area = shape(fc["features"][0]["geometry"]).buffer(cov["boundary_buffer_deg"])
    minx, miny, maxx, maxy = area.bounds
    return [(la, lo) for la in range(math.floor(miny), math.ceil(maxy))
            for lo in range(math.floor(minx), math.ceil(maxx)) if area.intersects(box(lo, la, lo + 1, la + 1))]


def tile_path(settings: Settings, dataset: str, tid: str) -> Path:
    return Path(settings.dem_data_dir) / dataset / f"{tid}.tif"


@dataclass
class TileResult:
    dataset: str
    tile_id: str
    status: str
    source_url: str
    source_member: str | None = None
    path: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    nodata: float | None = None
    source_metadata: dict | None = None
    error: str | None = None


def _client(settings: Settings) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(settings.terrain_download_timeout_seconds, connect=30),
                        headers={"User-Agent": settings.http_user_agent}, follow_redirects=True)


def _inspect(path: Path) -> dict:
    """Open the file as a raster (proves it is valid) and read its published tags."""
    import rasterio

    with rasterio.open(path) as ds:
        return {"width": ds.width, "height": ds.height, "nodata": ds.nodata,
                "metadata": {"tags": ds.tags(), "crs": str(ds.crs), "transform": list(ds.transform)[:6],
                             "dtype": ds.dtypes[0]}}


def _finish(res: TileResult, tmp: Path, final: Path, sha: str, size: int, settings: Settings) -> TileResult:
    tmp.replace(final)
    meta = _inspect(final)
    res.status, res.sha256, res.bytes = "downloaded", sha, size
    res.path = str(final.relative_to(settings.dem_data_dir))
    res.width, res.height, res.nodata, res.source_metadata = meta["width"], meta["height"], meta["nodata"], meta["metadata"]
    return res


def _existing(final: Path, settings: Settings, res: TileResult) -> TileResult | None:
    if not final.exists():
        return None
    try:
        meta = _inspect(final)
    except Exception:  # noqa: BLE001 - corrupt/partial file, fetch again
        final.unlink()
        return None
    h = hashlib.sha256()
    with final.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    res.status, res.sha256, res.bytes = "downloaded", h.hexdigest(), final.stat().st_size
    res.path = str(final.relative_to(settings.dem_data_dir))
    res.width, res.height, res.nodata, res.source_metadata = meta["width"], meta["height"], meta["nodata"], meta["metadata"]
    return res


def download_direct(client: httpx.Client, settings: Settings, dataset: str, lat: int, lon: int) -> TileResult:
    info = dataset_info(dataset)
    tid = tile_id(lat, lon)
    lat_tag, lon_tag = tid[:3], tid[3:]
    url = info["url_template"].format(lat_tag=lat_tag, lon_tag=lon_tag)
    res = TileResult(dataset, tid, "failed", url)
    final = tile_path(settings, dataset, tid)
    if (done := _existing(final, settings, res)) is not None:
        return done
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(".part")
    with client.stream("GET", url) as r:
        if r.status_code in (403, 404):  # S3 answers 403/404 for tiles that do not exist (sea)
            res.status, res.error = "not_at_source", f"HTTP {r.status_code}"
            return res
        r.raise_for_status()
        expected = int(r.headers.get("content-length") or 0)
        h, size = hashlib.sha256(), 0
        with tmp.open("wb") as f:
            for block in r.iter_bytes(CHUNK):
                f.write(block)
                h.update(block)
                size += len(block)
    if expected and size != expected:
        tmp.unlink(missing_ok=True)
        raise OSError(f"incomplete download {size}/{expected} bytes")
    return _finish(res, tmp, final, h.hexdigest(), size, settings)


def _range_get(client: httpx.Client, url: str, start: int, length: int) -> bytes:
    r = client.get(url, headers={"Range": f"bytes={start}-{start + length - 1}"})
    if r.status_code != 206:
        raise OSError(f"range request not honoured (HTTP {r.status_code})")
    return r.content


class HttpRangeFile(io.RawIOBase):
    """Read-only seekable file over HTTP range requests (enough for zipfile's central directory)."""

    def __init__(self, client: httpx.Client, url: str):
        self.client, self.url, self.pos = client, url, 0
        # size from a 1-byte ranged GET: some CDNs refuse HEAD from cloud runners
        r = client.get(url, headers={"Range": "bytes=0-0"})
        r.raise_for_status()
        total = r.headers.get("content-range", "").rpartition("/")[2]
        self.size = int(total) if total.isdigit() else int(r.headers["content-length"])

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size:
            return 0
        n = min(len(b), self.size - self.pos)
        data = _range_get(self.client, self.url, self.pos, n)
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


_zip_index: dict[str, dict[str, zipfile.ZipInfo]] = {}


def _zip_members(client: httpx.Client, url: str) -> dict[str, zipfile.ZipInfo]:
    if url not in _zip_index:
        raw = HttpRangeFile(client, url)
        with zipfile.ZipFile(io.BufferedReader(raw, buffer_size=256 * 1024)) as z:
            _zip_index[url] = {Path(i.filename).name: i for i in z.infolist()}
    return _zip_index[url]


def stream_zip_member(client: httpx.Client, url: str, zi: zipfile.ZipInfo, dest: Path) -> tuple[str, int]:
    """Download one member of a remote zip with a single range request; verify size and CRC32."""
    if zi.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise OSError(f"unsupported zip compression {zi.compress_type}")
    # local file header: 30 bytes + name + extra, then the compressed data
    header = _range_get(client, url, zi.header_offset, 30)
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    start = zi.header_offset + 30 + name_len + extra_len
    inflater = zlib.decompressobj(-15) if zi.compress_type == zipfile.ZIP_DEFLATED else None
    h, size, crc = hashlib.sha256(), 0, 0
    with client.stream("GET", url, headers={"Range": f"bytes={start}-{start + zi.compress_size - 1}"}) as r:
        if r.status_code != 206:
            raise OSError(f"range request not honoured (HTTP {r.status_code})")
        with dest.open("wb") as f:
            for block in r.iter_bytes(CHUNK):
                data = inflater.decompress(block) if inflater else block
                f.write(data)
                h.update(data)
                crc = zlib.crc32(data, crc)
                size += len(data)
            if inflater:
                tail = inflater.flush()
                f.write(tail)
                h.update(tail)
                crc = zlib.crc32(tail, crc)
                size += len(tail)
    if size != zi.file_size or crc != zi.CRC:
        dest.unlink(missing_ok=True)
        raise OSError(f"zip member check failed (size {size}/{zi.file_size}, crc match {crc == zi.CRC})")
    return h.hexdigest(), size


def _zip_group(lat: int, lon: int) -> str:
    la, lo = lat - lat % 10, lon - lon % 10
    return f"{tile_id(la, lo)}-{tile_id(la + 10, lo + 10)}"


def download_zip_member(client: httpx.Client, settings: Settings, dataset: str, lat: int, lon: int) -> TileResult:
    info = dataset_info(dataset)
    tid = tile_id(lat, lon)
    url = info["zip_url_template"].format(zip_group=_zip_group(lat, lon))
    member = info["member_template"].format(lat_tag=tid[:3], lon_tag=tid[3:])
    res = TileResult(dataset, tid, "failed", url, source_member=member)
    final = tile_path(settings, dataset, tid)
    if (done := _existing(final, settings, res)) is not None:
        return done
    members = _zip_members(client, url)
    zi = members.get(member)
    if zi is None:
        res.status, res.error = "not_at_source", "tile not in archive"
        return res
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(".part")
    sha, size = stream_zip_member(client, url, zi, tmp)
    return _finish(res, tmp, final, sha, size, settings)


def save_tile(session: Session, res: TileResult) -> None:
    values = {k: getattr(res, k) for k in ("dataset", "tile_id", "status", "source_url", "source_member", "path",
                                           "bytes", "sha256", "width", "height", "nodata", "source_metadata")}
    values["error"] = (res.error or "")[:1000] or None
    values["fetched_at"] = datetime.now(timezone.utc)
    stmt = insert(DemTile).values(**values)
    stmt = stmt.on_conflict_do_update(constraint="uq_dem_tile_dataset_tile",
                                      set_={k: stmt.excluded[k] for k in values if k not in ("dataset", "tile_id")})
    session.execute(stmt)
    session.commit()


def download_dataset(session: Session, dataset: str, settings: Settings | None = None,
                     tiles: list[tuple[int, int]] | None = None, retries: int = 3) -> dict:
    settings = settings or get_settings()
    info = dataset_info(dataset)
    fn = download_direct if info["access"] == "direct" else download_zip_member
    tiles = tiles if tiles is not None else coverage_tiles()
    counts: dict[str, int] = {}

    def one(lat: int, lon: int) -> TileResult:
        last: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                with _client(settings) as client:
                    return fn(client, settings, dataset, lat, lon)
            except Exception as exc:  # noqa: BLE001 - recorded on the tile row
                last = exc
                log.warning("%s %s attempt %d failed: %s", dataset, tile_id(lat, lon), attempt, exc)
        return TileResult(dataset, tile_id(lat, lon), "failed", "", error=f"{type(last).__name__}: {last}")

    if info["access"] == "zip_member":  # read each archive's directory once, serially
        with _client(settings) as client:
            for url in sorted({info["zip_url_template"].format(zip_group=_zip_group(la, lo)) for la, lo in tiles}):
                _zip_members(client, url)
    with ThreadPoolExecutor(max_workers=settings.terrain_download_workers) as pool:
        futures = {pool.submit(one, la, lo): (la, lo) for la, lo in tiles}
        for fut in as_completed(futures):
            res = fut.result()
            if res.status == "failed" and not res.source_url:
                la, lo = futures[fut]
                res.source_url = (info.get("url_template") or info.get("zip_url_template", "")).format(
                    lat_tag=res.tile_id[:3], lon_tag=res.tile_id[3:], zip_group=_zip_group(la, lo))
            save_tile(session, res)
            counts[res.status] = counts.get(res.status, 0) + 1
            log.info("%s %s %s %s", dataset, res.tile_id, res.status, res.bytes or res.error or "")
    return {"dataset": dataset, "tiles": len(tiles), **counts}
