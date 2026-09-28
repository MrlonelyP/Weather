"""Read a small elevation window around a lat/lon from the DEM tiles on disk.

Both datasets use the same 1 arc-second global grid (pixel-is-point, so a tile's
first pixel centre sits on the whole degree). We index every tile by its global
pixel offset and copy exact integer windows, so a window that crosses a tile
edge is stitched without resampling. Missing tiles (sea, not downloaded) and
nodata cells stay NaN.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

from app.config.settings import Settings, get_settings
from app.services.dem_download import tile_id

M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQ = 111_320.0


@dataclass
class DemWindow:
    dataset: str
    grid: np.ndarray  # float32 metres, NaN = no data
    row: int  # the point's cell
    col: int
    dx_m: float
    dy_m: float
    res_deg: float
    cell_lat: float  # centre of the point's cell
    cell_lon: float
    tiles: list[str]
    missing_tiles: list[str]


class DemReader:
    def __init__(self, dataset: str, settings: Settings | None = None, res_deg: float = 1 / 3600):
        self.dataset = dataset
        self.settings = settings or get_settings()
        self.res = res_deg
        self.root = Path(self.settings.dem_data_dir) / dataset

    def tile_file(self, lat_i: int, lon_i: int) -> Path:
        return self.root / f"{tile_id(lat_i, lon_i)}.tif"

    def has_tile_for(self, lat: float, lon: float) -> bool:
        return self.tile_file(math.floor(lat), math.floor(lon)).exists()

    def read(self, lat: float, lon: float, half_m: float) -> DemWindow | None:
        """Window of +/- half_m around the cell containing (lat, lon); None if the point's own tile is missing."""
        if not self.has_tile_for(lat, lon):
            return None
        res = self.res
        gc, gr = round(lon / res), round((90 - lat) / res)  # global col/row of the nearest cell centre
        dy = res * M_PER_DEG_LAT
        dx = res * M_PER_DEG_LON_EQ * math.cos(math.radians(lat))
        hr, hc = math.ceil(half_m / dy), math.ceil(half_m / dx)
        r0, r1, c0, c1 = gr - hr, gr + hr + 1, gc - hc, gc + hc + 1
        grid = np.full((r1 - r0, c1 - c0), np.nan, dtype=np.float32)
        lat_hi, lat_lo = 90 - r0 * res, 90 - (r1 - 1) * res
        lon_lo, lon_hi = c0 * res, (c1 - 1) * res
        used, missing = [], []
        for la in range(math.floor(lat_lo), math.floor(lat_hi) + 1):
            for lo in range(math.floor(lon_lo), math.floor(lon_hi) + 1):
                path = self.tile_file(la, lo)
                if not path.exists():
                    missing.append(tile_id(la, lo))
                    continue
                with rasterio.open(path) as ds:
                    t = ds.transform
                    tc0 = round(t.c / res + 0.5)
                    tr0 = round((90 - t.f) / res + 0.5)
                    rr0, rr1 = max(r0, tr0), min(r1, tr0 + ds.height)
                    cc0, cc1 = max(c0, tc0), min(c1, tc0 + ds.width)
                    if rr0 >= rr1 or cc0 >= cc1:
                        continue
                    data = ds.read(1, window=Window(cc0 - tc0, rr0 - tr0, cc1 - cc0, rr1 - rr0)).astype(np.float32)
                    if ds.nodata is not None:
                        data[data == ds.nodata] = np.nan
                    grid[rr0 - r0: rr1 - r0, cc0 - c0: cc1 - c0] = data
                used.append(tile_id(la, lo))
        return DemWindow(self.dataset, grid, hr, hc, dx, dy, res, round(90 - gr * res, 6), round(gc * res, 6),
                         used, missing)
