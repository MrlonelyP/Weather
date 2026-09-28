"""Local flow engine v0.1: where would surface water from this point go, on the DEM alone?

Terrain-derived flow only. It knows nothing about pipes, pumps, gates, dykes or
tides, and every output says so.

Method (pure numpy / Python over a DEM window read by the caller):
  1. 3x3 median smoothing (removes single-cell spikes/pits of the DSM)
  2. priority-flood (Barnes et al. 2014) seeded from outlets: window edges, no-data
     cells and cells on a mapped waterway; then D8 steepest descent on the filled
     surface. On flats and in filled pits (no lower neighbour) a cell drains to the
     cell the flood reached it from, i.e. towards the spill point.
  3. downstream path from the point by following receivers, until it reaches a
     waterway cell, the window edge or no-data
  4. local flow accumulation (cells draining through each cell, inside the window)
  5. confidence of the direction from the real drop along the first part of the path
     compared with the DEM's vertical noise, reduced by the share of the path that
     only exists because a pit or flat was filled. Below `min_confidence` the
     direction is NOT reported.
"""
from __future__ import annotations

import heapq
import math

import numpy as np

from app.engines import engine_config
from app.engines.terrain import COMPASS, COMPASS_TH, median3

NOT_RELIABLE_TH = "ไม่สามารถระบุทิศทางการระบายน้ำจาก DEM ได้อย่างน่าเชื่อถือ"
LIMITS_TH = [
    "เป็นทิศทางการไหลที่คำนวณจากความสูงของพื้นผิว (terrain-derived) เท่านั้น ไม่รวมท่อระบายน้ำ เครื่องสูบน้ำ ประตูระบายน้ำ คันกั้นน้ำ หรือน้ำขึ้นน้ำลง",
    "พื้นที่ราบมาก (เช่น กรุงเทพฯ) ความต่างระดับน้อยกว่าความคลาดเคลื่อนของ DEM ทำให้มักระบุทิศทางไม่ได้",
    "DEM หลัก (Copernicus) เป็น DSM อาคารอาจกั้นทางไหลหรือสร้างแอ่งเทียมระหว่างอาคาร",
    "คำนวณในหน้าต่างรอบจุด พื้นที่รับน้ำที่อยู่นอกหน้าต่างจะไม่ถูกนับในค่าการสะสมน้ำระดับพื้นที่",
]
D8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def params() -> dict:
    return engine_config()["flow"]


def bearing_deg(dr: float, dc: float, dx: float, dy: float) -> float:
    return (math.degrees(math.atan2(dc * dx, -dr * dy)) + 360) % 360


def compass(bearing: float) -> str:
    return COMPASS[int((bearing + 22.5) // 45) % 8]


def route(z: np.ndarray, outlets: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Priority-flood from outlets, then steepest-descent D8 on the filled surface.

    Returns (filled, receiver index or -1, processing order with receivers before donors).
    Cells with a strictly lower neighbour drain to the steepest one; cells on flats / filled
    pits keep the neighbour the flood reached them from (flow towards the spill point).
    """
    h, w = z.shape
    n = h * w
    zf = np.where(np.isfinite(z), z, -np.inf).ravel().astype(np.float64)
    filled = zf.copy()
    receiver = np.full(n, -1, dtype=np.int64)
    done = np.zeros(n, dtype=bool)
    heap: list[tuple[float, int, int]] = []
    counter = 0
    seeds = outlets.copy()
    seeds[0, :] = seeds[-1, :] = seeds[:, 0] = seeds[:, -1] = True
    seeds |= ~np.isfinite(z)
    for idx in np.flatnonzero(seeds.ravel()):
        heapq.heappush(heap, (filled[idx], counter, int(idx)))
        counter += 1
        done[idx] = True
    pop_index = np.zeros(n, dtype=np.int64)
    k = 0
    while heap:
        zc, _, idx = heapq.heappop(heap)
        pop_index[idx] = k
        k += 1
        r, c = divmod(idx, w)
        for dr, dc in D8:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w:
                j = nr * w + nc
                if not done[j]:
                    done[j] = True
                    receiver[j] = idx
                    if filled[j] < zc:
                        filled[j] = zc
                    heapq.heappush(heap, (filled[j], counter, j))
                    counter += 1
    fgrid = filled.reshape(h, w)
    # steepest descent where the filled surface actually slopes
    finite = np.where(np.isfinite(fgrid), fgrid, np.nanmin(np.where(np.isfinite(fgrid), fgrid, np.nan)) - 1000.0)
    pad = np.pad(finite, 1, constant_values=np.inf)
    best_slope = np.zeros((h, w))
    best_dir = np.full((h, w), -1, dtype=np.int64)
    for k8, (dr, dc) in enumerate(D8):
        nb = pad[1 + dr: 1 + dr + h, 1 + dc: 1 + dc + w]
        slope = (finite - nb) / math.hypot(dr, dc)
        better = slope > best_slope + 1e-9
        best_slope[better] = slope[better]
        best_dir[better] = k8
    rows, cols = np.indices((h, w))
    steep = (best_dir >= 0) & ~seeds
    dr = np.array([d[0] for d in D8])[best_dir.clip(0)]
    dc = np.array([d[1] for d in D8])[best_dir.clip(0)]
    target = (rows + dr) * w + (cols + dc)
    receiver = np.where(steep.ravel(), target.ravel(), receiver)
    receiver[seeds.ravel()] = -1
    order = np.lexsort((pop_index, filled))  # lower (then earlier-flooded) cells first = receivers first
    return fgrid, receiver, order


def accumulate(receiver: np.ndarray, order) -> np.ndarray:
    """Number of cells (incl. itself) draining through each cell. Receivers are processed before donors."""
    acc = np.ones(receiver.size, dtype=np.int64)
    for idx in reversed(order):
        rcv = receiver[idx]
        if rcv >= 0:
            acc[rcv] += acc[idx]
    return acc


def analyze_flow(grid: np.ndarray, row: int, col: int, dx: float, dy: float, waterway_labels: np.ndarray | None,
                 noise_m: float, p: dict | None = None) -> dict:
    """waterway_labels: int grid, 0 = no waterway, k = index of a mapped waterway (outlet)."""
    p = p or params()
    h, w = grid.shape
    if not np.isfinite(grid[row, col]):
        return {"available": False, "reason": "ไม่มีค่า DEM ที่ตำแหน่งนี้"}
    z = median3(grid)
    labels = waterway_labels if waterway_labels is not None else np.zeros(grid.shape, dtype=np.int32)
    outlets = labels > 0
    start_on_waterway = bool(outlets[row, col])
    outlets[row, col] = False  # route the point itself even when it sits on a mapped line
    filled, receiver, order = route(z, outlets)
    acc = accumulate(receiver, order).reshape(h, w)
    cell_m2 = dx * dy

    # --- downstream path
    path = [(row, col)]
    idx = row * w + col
    seen = {idx}
    while receiver[idx] >= 0 and len(path) < h * w:
        idx = int(receiver[idx])
        if idx in seen:
            break
        seen.add(idx)
        path.append(divmod(idx, w))
        r, c = path[-1]
        if labels[r, c] > 0 or not np.isfinite(z[r, c]) or r in (0, h - 1) or c in (0, w - 1):
            break
    steps = [math.hypot((b[0] - a[0]) * dy, (b[1] - a[1]) * dx) for a, b in zip(path, path[1:])]
    dist = np.concatenate([[0.0], np.cumsum(steps)]) if steps else np.array([0.0])
    end_r, end_c = path[-1]
    if labels[end_r, end_c] > 0:
        reached = {"type": "waterway", "label": int(labels[end_r, end_c])}
    elif not np.isfinite(z[end_r, end_c]):
        reached = {"type": "no_data", "note": "ทะเล แหล่งน้ำ หรือพื้นที่ไม่มีข้อมูล DEM"}
    else:
        reached = {"type": "window_edge", "note": "ทางไหลออกนอกหน้าต่างที่วิเคราะห์"}

    # --- confidence of the direction (first `confidence_length_m` of the path)
    L = p["confidence_length_m"]
    k = int(np.searchsorted(dist, min(L, dist[-1]), side="left"))
    k = max(k, min(1, len(path) - 1))
    seg = path[: k + 1]
    zs = np.array([z[r, c] for r, c in seg], dtype=float)
    zfill = np.array([filled[r, c] for r, c in seg], dtype=float)
    drop = float(zs[0] - zs[-1]) if np.isfinite(zs).all() and len(zs) > 1 else 0.0
    filled_share = float(np.mean((zfill - zs) > p["filled_cell_m"])) if len(zs) else 1.0
    confidence = 0.0 if drop <= 0 else drop / (drop + 2 * noise_m) * (1 - filled_share)
    confidence = round(min(confidence, p["max_confidence"]), 2)

    # direction = bearing from the point to where the path is after `direction_length_m`
    kd = int(np.searchsorted(dist, min(p["direction_length_m"], dist[-1]), side="left"))
    kd = max(kd, min(1, len(path) - 1))
    dr, dc = path[kd][0] - row, path[kd][1] - col
    reliable = confidence >= p["min_confidence"] and (dr or dc)
    direction = None
    if reliable:
        b = bearing_deg(dr, dc, dx, dy)
        direction = {"flow_direction": compass(b), "flow_direction_th": COMPASS_TH[compass(b)],
                     "bearing_deg": round(b)}

    # --- where water may collect along the path: first filled pit deeper than the threshold
    depth = filled - z
    accum_zone = None
    for i, (r, c) in enumerate(path):
        if np.isfinite(depth[r, c]) and depth[r, c] >= p["zone_min_depth_m"]:
            region = _region(depth > p["zone_cell_depth_m"], r, c)
            accum_zone = {"distance_m": round(float(dist[i])), "row": r, "col": c,
                          "max_depth_m": round(float(np.nanmax(np.where(region, depth, np.nan))), 2),
                          "area_m2": round(float(region.sum() * cell_m2)), "at_point": i == 0}
            break

    upstream_m2 = float(acc[row, col] * cell_m2)
    step_every = max(1, int(p["path_sample_m"] / max(dx, dy)))
    sampled = path[::step_every] + ([path[-1]] if (len(path) - 1) % step_every else [])
    return {
        "available": True,
        "method": "priority-flood routing (D8) on 3x3-median DEM, outlets = window edge / no-data / mapped waterways",
        "flow_direction": direction["flow_direction"] if direction else None,
        "flow_direction_th": direction["flow_direction_th"] if direction else None,
        "bearing_deg": direction["bearing_deg"] if direction else None,
        "reliable": bool(reliable),
        "message_th": None if reliable else NOT_RELIABLE_TH,
        "confidence": confidence,
        "confidence_basis": {"drop_m": round(drop, 2), "over_m": round(float(dist[k])), "dem_noise_m": noise_m,
                             "filled_share": round(filled_share, 2), "min_confidence": p["min_confidence"]},
        "start_on_mapped_waterway": start_on_waterway,
        "path_cells": [[int(r), int(c)] for r, c in sampled],
        "path_length_m": round(float(dist[-1])),
        "path_drop_m": round(float(z[row, col] - z[end_r, end_c]), 2) if np.isfinite(z[end_r, end_c]) else None,
        "reached": reached,
        "local_upstream_area_m2": round(upstream_m2),
        "local_corridor": upstream_m2 >= p["corridor_min_m2"],
        "accumulation_zone": accum_zone,
        "window_m": [round(w * dx), round(h * dy)],
        "kind": "terrain_derived_flow",
    }


def _region(mask: np.ndarray, r: int, c: int) -> np.ndarray:
    out = np.zeros_like(mask, dtype=bool)
    if not mask[r, c]:
        out[r, c] = True
        return out
    stack = [(r, c)]
    out[r, c] = True
    while stack:
        rr, cc = stack.pop()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = rr + dr, cc + dc
            if 0 <= nr < mask.shape[0] and 0 <= nc < mask.shape[1] and mask[nr, nc] and not out[nr, nc]:
                out[nr, nc] = True
                stack.append((nr, nc))
    return out
