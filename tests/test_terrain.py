"""Terrain engine, DEM reader/downloader, waterways and /api/location/analyze.

All grids and tiles here are synthetic shapes (cone, plane, ramp) built in the
test to check the maths and the stitching. They are written to a temp dir only.
"""
from __future__ import annotations

import io
import json
import math
import zipfile

import httpx
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import Affine

from app.api import cache
from app.config.settings import get_settings
from app.engines import location_context
from app.engines.terrain import analyze_grid, combine_positions, params, priority_flood
from app.main import app
from app.services import dem_download, terrain_data
from app.services.dem_reader import DemReader
from app.services.waterways import import_extract, nearby_waterways

RES = 1 / 3600
D = 30.0
client = TestClient(app)


def _dist_grid(n: int = 81) -> np.ndarray:
    r, c = np.indices((n, n))
    return np.hypot(r - n // 2, c - n // 2) * D


@pytest.mark.nodb
def test_cone_is_low_area_and_depression():
    grid = (5 + 10 * _dist_grid() / 1000).astype(np.float32)
    out = analyze_grid(grid, 40, 40, D, D)
    assert out["terrain_position"] == "LOW_AREA"
    assert all(v["position"] == "LOW_AREA" for v in out["relative_elevation"].values())
    assert out["relative_elevation"]["500"]["relative_m"] < -1 and out["relative_elevation"]["500"]["percentile_rank"] == 0
    dep = out["local_depression"]
    assert dep["possible_local_depression"] is True and dep["depth_m"] > 5 and dep["area_rai"] > 1
    assert "flow_accumulation" in out["not_computed"]


@pytest.mark.nodb
def test_hill_is_high_area_without_depression():
    grid = (50 - 10 * _dist_grid() / 1000).astype(np.float32)
    out = analyze_grid(grid, 40, 40, D, D)
    assert out["terrain_position"] == "HIGH_AREA"
    assert out["local_depression"]["possible_local_depression"] is False


@pytest.mark.nodb
def test_plane_slope_and_downslope_direction():
    _, cols = np.indices((81, 81))
    grid = (10 - 0.01 * cols * D).astype(np.float32)  # falls towards the east, 10 m per km
    out = analyze_grid(grid, 40, 40, D, D)
    assert out["slope"]["at_point"]["slope_deg"] == pytest.approx(math.degrees(math.atan(0.01)), abs=0.01)
    pf = out["slope"]["plane_fit"]
    assert pf["downslope_direction"] == "E" and pf["gradient_m_per_km"] == pytest.approx(10, abs=0.01)
    assert out["terrain_position"] == "NORMAL"  # symmetric around the point


@pytest.mark.nodb
def test_flat_noise_stays_normal_within_noise():
    rng = np.random.default_rng(1)
    grid = (2 + rng.uniform(-0.05, 0.05, (81, 81))).astype(np.float32)
    out = analyze_grid(grid, 40, 40, D, D)
    assert out["terrain_position"] == "NORMAL"
    assert out["relative_elevation"]["500"]["within_noise"] is True
    assert out["local_depression"]["possible_local_depression"] is False
    assert out["slope"]["plane_fit"]["downslope_direction"] is None


@pytest.mark.nodb
def test_missing_point_and_sea_are_not_filled():
    grid = np.full((81, 81), np.nan, dtype=np.float32)
    assert analyze_grid(grid, 40, 40, D, D)["available"] is False
    grid = (5 + 10 * _dist_grid() / 1000).astype(np.float32)
    grid[:, 43:] = np.nan  # east half of the window is sea
    rel = analyze_grid(grid, 40, 40, D, D)["relative_elevation"]["1000"]
    assert rel["position"] == "UNKNOWN" and rel["relative_m"] is None


@pytest.mark.nodb
def test_priority_flood_and_combine():
    g = np.array([[5, 5, 5, 5], [5, 1, 2, 5], [5, 2, 1, 5], [5, 5, 4, 5]], dtype=np.float32)
    f = priority_flood(g)
    assert f[1, 1] == 4 and f[2, 2] == 4 and f[0, 0] == 5  # spills over the 4 m outlet
    assert combine_positions(["LOW_AREA", "LOW_AREA", "NORMAL"]) == "LOW_AREA"
    assert combine_positions(["LOW_AREA", "HIGH_AREA", "NORMAL"]) == "MIXED"
    assert combine_positions(["UNKNOWN"] * 3) == "UNKNOWN"


def _write_tile(path, col0: int, row0: int, w: int, h: int, fn, nodata=None):
    """Tile on the global 1" grid: first pixel centre at global (col0, row0); value fn(global_col, global_row)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, cols = np.indices((h, w))
    data = fn(cols + col0, rows + row0).astype(np.float32)
    tr = Affine(RES, 0, col0 * RES - RES / 2, 0, -RES, 90 - row0 * RES + RES / 2)
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32", crs="EPSG:4326",
                       transform=tr, nodata=nodata) as ds:
        ds.write(data, 1)


@pytest.fixture
def dem_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DEM_DATA_DIR", str(tmp_path / "dem"))
    get_settings.cache_clear()
    terrain_data._CACHE.clear()
    yield tmp_path / "dem"
    get_settings.cache_clear()
    terrain_data._CACHE.clear()


def _ramp_tiles(root, dataset: str):
    # two tiles meeting at lon 101: N13E100 holds global cols just west of 101, N13E101 the cols from 101
    top = (90 - 14) * 3600
    _write_tile(root / dataset / "N13E100.tif", 101 * 3600 - 100, top, 100, 100, lambda c, r: c - 101 * 3600 + 1000.0)
    _write_tile(root / dataset / "N13E101.tif", 101 * 3600, top, 100, 100, lambda c, r: c - 101 * 3600 + 1000.0)


@pytest.mark.nodb
def test_reader_stitches_tiles_exactly(dem_dir):
    _ramp_tiles(dem_dir, "copernicus_glo30")
    w = DemReader("copernicus_glo30").read(14 - 50 * RES, 101.0, 900)
    assert set(w.tiles) == {"N13E100", "N13E101"} and not np.isnan(w.grid).any()
    assert np.all(np.diff(w.grid, axis=1) == 1)  # continuous across the tile edge, no resampling
    assert w.grid[w.row, w.col] == 1000.0 and w.cell_lon == 101.0
    assert DemReader("copernicus_glo30").read(15.5, 101.5, 900) is None  # tile not on disk


@pytest.mark.nodb
def test_zip_member_download_streams_only_the_tile(dem_dir, monkeypatch):
    buf = io.BytesIO()
    tif = dem_dir.parent / "src.tif"
    _write_tile(tif, 100 * 3600, 76 * 3600, 20, 20, lambda c, r: c * 0 + 3.0, nodata=-9999)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("other/N12E100_FABDEM_V1-2.tif", b"x" * 1000)
        z.write(tif, "N10E100-N20E110_FABDEM_V1-2/N13E100_FABDEM_V1-2.tif")
    blob = buf.getvalue()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.headers.get("range")))
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(blob))})
        start, end = map(int, request.headers["range"].split("=")[1].split("-"))
        return httpx.Response(206, content=blob[start: end + 1])

    dem_download._zip_index.clear()
    c = httpx.Client(transport=httpx.MockTransport(handler))
    res = dem_download.download_zip_member(c, get_settings(), "fabdem_v1_2", 13, 100)
    assert res.status == "downloaded" and res.source_member == "N13E100_FABDEM_V1-2.tif"
    assert res.width == 20 and res.nodata == -9999 and res.sha256
    assert (dem_dir / "fabdem_v1_2" / "N13E100.tif").exists()
    assert all(m == "HEAD" or r for m, r in seen)  # every GET was a range request
    missing = dem_download.download_zip_member(c, get_settings(), "fabdem_v1_2", 14, 100)
    assert missing.status == "not_at_source"


@pytest.mark.nodb
def test_coverage_tiles_cover_thailand():
    tiles = dem_download.coverage_tiles()
    assert (13, 100) in tiles and (18, 98) in tiles and (5, 101) in tiles
    assert (20, 105) not in tiles  # Laos only


@pytest.mark.nodb
def test_location_text_only_from_inputs():
    empty = location_context.build({"available": False}, {"available": False}, [], {}, None)
    assert empty["terrain_signal"]["signal"] == "unknown"
    assert not any(ch.isdigit() for line in empty["summary_th"] for ch in line)  # no numbers without data
    terrain = {"available": True, "primary_dataset": "a", "terrain_position_th": "ต่ำกว่าพื้นที่โดยรอบ",
               "comparison": {"position_agree": False, "depression_agree": True, "note": "ไม่ตรงกัน"},
               "reliability": {"level": "low"},
               "datasets": {"a": {"dataset": {"name": "DEM-A"}, "elevation_m": 1.5, "terrain_position": "LOW_AREA",
                                  "relative_elevation": {"500": {"relative_m": -1.8, "percentile_rank": 10.0,
                                                                 "within_noise": False}},
                                  "local_depression": {"possible_local_depression": False},
                                  "slope": {"plane_fit": {"note": "ค่อนข้างราบ ไม่มีทิศลาดชัดเจน"}}}}}
    out = location_context.build(terrain, {"available": False}, [], {}, None)
    assert out["terrain_signal"]["signal"] == "uncertain"  # datasets disagree
    assert any("1.8 ม." in s for s in out["summary_th"])
    assert "ไม่ใช่การประเมินความเสี่ยง" in out["flood_context"]["disclaimer"]


def _waterways_zip(path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"osm_id": 1, "osm_type": "ways_line", "waterway": "canal", "name": "คลองทดสอบ"},
         "geometry": {"type": "LineString", "coordinates": [[100.99, 13.985], [101.01, 13.985]]}},
        {"type": "Feature", "properties": {"osm_id": 2, "osm_type": "ways_line", "waterway": "weir", "name": "ฝาย"},
         "geometry": {"type": "LineString", "coordinates": [[101.0, 13.98], [101.0, 13.99]]}},
    ]}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("x.geojson", json.dumps(fc))
        z.writestr("Readme.txt", "Exported Timestamp (UTC+0000): 2026-05-05 12:33:30\n")


@pytest.mark.nodb
def test_production_default_is_copernicus_and_fabdem_never_primary(dem_dir, monkeypatch):
    assert get_settings().terrain_primary_dataset == "copernicus_glo30"
    assert get_settings().terrain_dataset_list == ["copernicus_glo30"]
    monkeypatch.setenv("TERRAIN_COMPARISON_DATASETS", "fabdem_v1_2")
    get_settings.cache_clear()
    _ramp_tiles(dem_dir, "fabdem_v1_2")  # only the comparison DEM exists on disk
    t = terrain_data.terrain_at(14 - 50 * RES, 101.0)
    assert t["primary_dataset"] == "copernicus_glo30" and t["available"] is False
    assert t["datasets"]["fabdem_v1_2"]["role"] == "comparison_only" and t["license_warning"] is None
    monkeypatch.setenv("TERRAIN_PRIMARY_DATASET", "fabdem_v1_2")
    get_settings.cache_clear()
    assert "ห้ามใช้เชิงพาณิชย์" in terrain_data.license_warning("fabdem_v1_2")


def test_waterways_import_nearby_and_location_api(dem_dir, tmp_path, monkeypatch):
    from app.services.database import session_scope

    monkeypatch.setenv("TERRAIN_COMPARISON_DATASETS", "fabdem_v1_2")
    get_settings.cache_clear()

    _ramp_tiles(dem_dir, "copernicus_glo30")
    _ramp_tiles(dem_dir, "fabdem_v1_2")
    zp = tmp_path / "ww.zip"
    _waterways_zip(zp)
    with session_scope() as s:
        r = import_extract(s, zp)
        assert r["imported"] == 1 and r["skipped_other_types"] == 1 and r["snapshot"] == "2026-05-05 12:33:30Z"
        ww = nearby_waterways(s, 13.986, 101.0)
    assert ww["nearest"]["name"] == "คลองทดสอบ" and 100 < ww["nearest"]["distance_m"] < 130
    assert ww["selection_method"] == "distance_based"
    cache.clear()
    lat = 14 - 50 * RES
    d = client.get("/api/location/analyze", params={"lat": lat, "lon": 101.0}).json()
    assert d["terrain"]["available"] and d["terrain"]["primary_dataset"] == "copernicus_glo30"
    assert set(d["terrain"]["datasets"]) == {"copernicus_glo30", "fabdem_v1_2"}
    assert d["terrain"]["reliability"]["level"] in ("low", "medium")
    assert any("คลองทดสอบ" in s for s in d["summary_th"]) and any("เลือกจากระยะทาง" in s for s in d["summary_th"])
    assert d["impact"]["outlook"] == "insufficient_data"
    assert {x["what"] for x in d["sources"]} >= {"terrain", "waterways"}
    far = client.get("/api/location/analyze", params={"lat": 16.5, "lon": 102.5}).json()
    assert far["terrain"]["available"] is False and far["terrain_signal"]["signal"] == "unknown"
    assert params()["method_version"] == d["terrain"]["method_version"]
