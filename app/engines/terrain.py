"""Terrain engine v0.1: describe the ground around one point from a DEM window.

Pure numpy over an elevation grid the caller already read from a DEM (the
terrain service does the reading). Nothing is fitted or learned; every number
is a direct statistic of the DEM cells, and all thresholds come from
config/engines.json["terrain"].

Outputs (all descriptive, never a flood probability):
  elevation_m               median of the 3x3 cells at the point
  relative_elevation        point minus the median of the cells within 250 / 500 / 1000 m,
                            with the point's percentile rank among them
  slope                     Horn (1981) slope at the point and a least-squares plane over 250 m
                            giving the general downslope direction
  terrain_position          LOW_AREA / NORMAL / HIGH_AREA / MIXED from the three radii
  local_depression          priority-flood fill of a local window; depth of the fill at the point
Limits are returned with the result so the caller can show them.
"""
from __future__ import annotations

import heapq
import math
import warnings

import numpy as np

from app.engines import engine_config

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
COMPASS_TH = {"N": "ทิศเหนือ", "NE": "ทิศตะวันออกเฉียงเหนือ", "E": "ทิศตะวันออก", "SE": "ทิศตะวันออกเฉียงใต้",
              "S": "ทิศใต้", "SW": "ทิศตะวันตกเฉียงใต้", "W": "ทิศตะวันตก", "NW": "ทิศตะวันตกเฉียงเหนือ"}
POSITION_TH = {"LOW_AREA": "ต่ำกว่าพื้นที่โดยรอบ", "NORMAL": "ใกล้เคียงพื้นที่โดยรอบ",
               "HIGH_AREA": "สูงกว่าพื้นที่โดยรอบ", "MIXED": "ผลต่างกันตามรัศมี", "UNKNOWN": "ข้อมูลไม่พอ"}
M2_PER_RAI = 1600.0


def params() -> dict:
    return engine_config()["terrain"]


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), nd)


def median3(grid: np.ndarray) -> np.ndarray:
    """3x3 median filter that ignores NaN (edges padded with NaN)."""
    padded = np.pad(grid, 1, constant_values=np.nan)
    win = np.lib.stride_tricks.sliding_window_view(padded, (3, 3))
    with warnings.catch_warnings():  # all-NaN windows (sea) stay NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(win.reshape(*grid.shape, 9), axis=-1)


def disk_mask(shape: tuple[int, int], r: int, c: int, dx: float, dy: float, radius_m: float,
              inner_cells: int = 1) -> np.ndarray:
    rows, cols = np.indices(shape)
    dist = np.hypot((rows - r) * dy, (cols - c) * dx)
    mask = dist <= radius_m
    mask[max(r - inner_cells, 0): r + inner_cells + 1, max(c - inner_cells, 0): c + inner_cells + 1] = False
    return mask


def point_elevation(grid: np.ndarray, r: int, c: int) -> float | None:
    block = grid[max(r - 1, 0): r + 2, max(c - 1, 0): c + 2]
    vals = block[np.isfinite(block)]
    return float(np.median(vals)) if vals.size >= 5 else None


def relative_elevation(grid: np.ndarray, r: int, c: int, dx: float, dy: float, z: float,
                       radius_m: float, p: dict) -> dict:
    mask = disk_mask(grid.shape, r, c, dx, dy, radius_m)
    vals = grid[mask]
    finite = vals[np.isfinite(vals)]
    valid = finite.size / max(vals.size, 1)
    out = {"radius_m": radius_m, "cells": int(vals.size), "valid_fraction": _r(valid, 3)}
    if finite.size < 10 or valid < p["min_valid_fraction"]:
        return {**out, "relative_m": None, "position": "UNKNOWN",
                "note": "เซลล์ DEM ที่ใช้ได้ไม่พอ (อาจเป็นทะเล แหล่งน้ำ หรือขอบข้อมูล)"}
    median = float(np.median(finite))
    rel = z - median
    pct = float((finite < z).mean() * 100)
    t = p["relative_threshold_m"]
    if rel <= -t and pct <= p["low_percentile"]:
        position = "LOW_AREA"
    elif rel >= t and pct >= p["high_percentile"]:
        position = "HIGH_AREA"
    else:
        position = "NORMAL"
    return {**out, "relative_m": _r(rel), "surrounding_median_m": _r(median), "surrounding_mean_m": _r(finite.mean()),
            "surrounding_p10_m": _r(np.percentile(finite, 10)), "surrounding_p90_m": _r(np.percentile(finite, 90)),
            "percentile_rank": _r(pct, 1), "position": position, "within_noise": abs(rel) < t}


def combine_positions(positions: list[str]) -> str:
    known = [x for x in positions if x != "UNKNOWN"]
    if not known:
        return "UNKNOWN"
    lows, highs = known.count("LOW_AREA"), known.count("HIGH_AREA")
    if lows and highs:
        return "MIXED"
    if lows >= 2 or (lows and lows == len(known)):
        return "LOW_AREA"
    if highs >= 2 or (highs and highs == len(known)):
        return "HIGH_AREA"
    return "NORMAL"


def horn_slope(grid: np.ndarray, r: int, c: int, dx: float, dy: float) -> dict | None:
    """Slope at one cell with Horn's 3x3 weighted differences."""
    if r < 1 or c < 1 or r + 2 > grid.shape[0] or c + 2 > grid.shape[1]:
        return None
    w = grid[r - 1: r + 2, c - 1: c + 2]
    if not np.isfinite(w).all():
        return None
    dzdx = ((w[0, 2] + 2 * w[1, 2] + w[2, 2]) - (w[0, 0] + 2 * w[1, 0] + w[2, 0])) / (8 * dx)
    dzdy = ((w[2, 0] + 2 * w[2, 1] + w[2, 2]) - (w[0, 0] + 2 * w[0, 1] + w[0, 2])) / (8 * dy)  # +south
    g = math.hypot(dzdx, dzdy)
    return {"slope_deg": _r(math.degrees(math.atan(g))), "slope_pct": _r(g * 100)}


def plane_fit(grid: np.ndarray, r: int, c: int, dx: float, dy: float, radius_m: float, flat: float) -> dict:
    """Least-squares plane z = a*east + b*north + c over the disk: general tilt and downslope direction."""
    mask = disk_mask(grid.shape, r, c, dx, dy, radius_m, inner_cells=-1) & np.isfinite(grid)
    if mask.sum() < 10:
        return {"gradient": None, "downslope_direction": None}
    rows, cols = np.nonzero(mask)
    east = (cols - c) * dx
    north = (r - rows) * dy
    A = np.column_stack([east, north, np.ones_like(east, dtype=float)])
    (a, b, _), *_ = np.linalg.lstsq(A, grid[mask], rcond=None)
    g = math.hypot(a, b)
    out = {"radius_m": radius_m, "gradient": _r(g, 5), "gradient_m_per_km": _r(g * 1000), "slope_deg": _r(math.degrees(math.atan(g)), 3)}
    if g < flat:
        return {**out, "downslope_direction": None, "note": "ค่อนข้างราบ ไม่มีทิศลาดชัดเจน"}
    bearing = (math.degrees(math.atan2(-a, -b)) + 360) % 360  # direction of steepest descent
    d = COMPASS[int((bearing + 22.5) // 45) % 8]
    return {**out, "downslope_bearing_deg": _r(bearing, 0), "downslope_direction": d, "downslope_direction_th": COMPASS_TH[d]}


def priority_flood(grid: np.ndarray) -> np.ndarray:
    """Fill depressions (Barnes et al. 2014). Window edges and NaN cells act as outlets."""
    h, w = grid.shape
    filled = np.where(np.isfinite(grid), grid, -np.inf)
    done = np.zeros((h, w), dtype=bool)
    heap: list[tuple[float, int, int]] = []
    for rr in range(h):
        for cc in range(w):
            if rr in (0, h - 1) or cc in (0, w - 1) or not np.isfinite(grid[rr, cc]):
                heapq.heappush(heap, (float(filled[rr, cc]), rr, cc))
                done[rr, cc] = True
    while heap:
        z, rr, cc = heapq.heappop(heap)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = rr + dr, cc + dc
                if (dr or dc) and 0 <= nr < h and 0 <= nc < w and not done[nr, nc]:
                    done[nr, nc] = True
                    if filled[nr, nc] < z:
                        filled[nr, nc] = z
                    heapq.heappush(heap, (float(filled[nr, nc]), nr, nc))
    return filled


def local_depression(smooth: np.ndarray, r: int, c: int, dx: float, dy: float, p: dict) -> dict:
    half_r = int(round(p["depression_window_m"] / dy))
    half_c = int(round(p["depression_window_m"] / dx))
    r0, c0 = max(r - half_r, 0), max(c - half_c, 0)
    win = smooth[r0: r + half_r + 1, c0: c + half_c + 1]
    pr, pc = r - r0, c - c0
    base = {"method": "priority-flood fill of a local window on the 3x3-median DEM; window edges treated as outlets",
            "window_m": p["depression_window_m"] * 2}
    if not np.isfinite(win[pr, pc]):
        return {**base, "possible_local_depression": None, "depth_m": None, "note": "ไม่มีค่า DEM ที่จุดนี้"}
    filled = priority_flood(win)
    depth = filled - np.where(np.isfinite(win), win, filled)
    d_point = float(depth[pr, pc])
    wet = depth > p["depression_cell_depth_m"]
    area_cells = 0
    if wet[pr, pc]:  # connected wet cells containing the point
        seen = np.zeros_like(wet)
        stack = [(pr, pc)]
        seen[pr, pc] = True
        while stack:
            rr, cc = stack.pop()
            area_cells += 1
            for nr, nc in ((rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1)):
                if 0 <= nr < wet.shape[0] and 0 <= nc < wet.shape[1] and wet[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    stack.append((nr, nc))
    flag = d_point >= p["depression_min_depth_m"] and area_cells >= p["depression_min_cells"]
    area_m2 = area_cells * dx * dy
    return {**base, "possible_local_depression": bool(flag), "depth_m": _r(d_point),
            "fill_level_m": _r(filled[pr, pc]), "area_m2": _r(area_m2, 0), "area_rai": _r(area_m2 / M2_PER_RAI, 1),
            "thresholds": {"min_depth_m": p["depression_min_depth_m"], "min_cells": p["depression_min_cells"]}}


def analyze_grid(grid: np.ndarray, r: int, c: int, dx: float, dy: float, p: dict | None = None) -> dict:
    """Full terrain description for cell (r, c) of `grid` (metres, NaN = no data)."""
    p = p or params()
    smooth = median3(grid)
    z = point_elevation(grid, r, c)
    if z is None:
        return {"available": False, "reason": "ไม่มีค่า DEM ที่ตำแหน่งนี้ (อาจเป็นทะเลหรือแหล่งน้ำ)"}
    rel = {str(int(rad)): relative_elevation(grid, r, c, dx, dy, z, rad, p) for rad in p["radii_m"]}
    position = combine_positions([v["position"] for v in rel.values()])
    return {
        "available": True,
        "method_version": p["method_version"],
        "elevation_m": _r(z),
        "elevation_center_cell_m": _r(grid[r, c]),
        "relative_elevation": rel,
        "terrain_position": position,
        "terrain_position_th": POSITION_TH[position],
        "slope": {"at_point": horn_slope(smooth, r, c, dx, dy),
                  "plane_fit": plane_fit(smooth, r, c, dx, dy, p["plane_fit_radius_m"], p["flat_gradient"])},
        "local_depression": local_depression(smooth, r, c, dx, dy, p),
        "grid": {"cell_dx_m": _r(dx), "cell_dy_m": _r(dy), "shape": list(grid.shape)},
        "not_computed": {
            "flow_accumulation": "ต้องประมวลผลระดับลุ่มน้ำทั้งผืน (v0.2) ไม่คำนวณจากหน้าต่างเล็ก",
            "terrain_drainage_score": "ยังไม่มีข้อมูลตรวจสอบย้อนหลัง จึงยังไม่ให้คะแนน",
        },
    }
