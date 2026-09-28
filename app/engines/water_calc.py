"""Water level calculations for one station (system-computed, v0.1).

From the stored series of (observed_at, level):
  current level, change over ~1 h, rate of rise (least-squares slope over the
  last N hours), trend (rising / falling / steady), distance to bank, and a
  system status NORMAL / WATCH / WARNING / CRITICAL.

The status is computed by THIS system from the source's bank level and our
thresholds (config/engines.json -> water). It is not an official warning and is
reported next to - never instead of - the level the source itself assigns
(ThaiWater situation_level / diff_wl_bank).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.engines import engine_config

STATUS_LABEL_TH = {"NORMAL": "ปกติ", "WATCH": "เฝ้าระวัง", "WARNING": "เสี่ยงสูง", "CRITICAL": "วิกฤต",
                   "UNKNOWN": "ไม่ทราบระดับตลิ่ง"}
STATUS_RANK = {"CRITICAL": 0, "WARNING": 1, "WATCH": 2, "NORMAL": 3, "UNKNOWN": 4}
TREND_LABEL_TH = {"rising": "สูงขึ้น", "falling": "ลดลง", "steady": "ทรงตัว", None: "ข้อมูลไม่พอ"}


def rate_of_rise_m_per_h(series: list[tuple[datetime, float]], window_hours: float) -> float | None:
    """Least-squares slope (m/h) over the last `window_hours`; needs >= 2 points spanning >= 30 min."""
    if not series:
        return None
    end = series[-1][0]
    pts = [(t, v) for t, v in series if t >= end - timedelta(hours=window_hours)]
    if len(pts) < 2 or (pts[-1][0] - pts[0][0]) < timedelta(minutes=30):
        return None
    xs = [(t - pts[0][0]).total_seconds() / 3600 for t, _ in pts]
    ys = [v for _, v in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def change_over(series: list[tuple[datetime, float]], hours: float, tolerance_min: int = 20) -> float | None:
    """Level change vs the reading closest to `hours` ago (within tolerance)."""
    if len(series) < 2:
        return None
    t_end, v_end = series[-1]
    target = t_end - timedelta(hours=hours)
    best = min(series[:-1], key=lambda p: abs((p[0] - target).total_seconds()))
    if abs((best[0] - target).total_seconds()) > tolerance_min * 60:
        return None
    return v_end - best[1]


def system_status(distance_m: float | None, rate_cmh: float | None) -> str:
    cfg = engine_config()["water"]
    if distance_m is None:
        return "UNKNOWN"
    rising = rate_cmh if rate_cmh is not None else 0.0
    if distance_m <= cfg["critical_distance_m"]:
        return "CRITICAL"
    if distance_m <= cfg["warning_distance_m"] or (
            distance_m <= cfg["warning_distance_if_rising_m"] and rising >= cfg["warning_rise_cmh"]):
        return "WARNING"
    if distance_m <= cfg["watch_distance_m"] or rising >= cfg["watch_rise_cmh"]:
        return "WATCH"
    return "NORMAL"


def _worst(*statuses: str) -> str:
    return min(statuses, key=lambda s: STATUS_RANK[s])


def station_state(series: list[tuple[datetime, float]], bank_m: float | None,
                  warning_m: float | None = None, critical_m: float | None = None) -> dict:
    """series: ascending (observed_at, level_m). Returns the computed state.

    Status = worst of (a) our bank-distance/rate rule and (b) the station's own
    warning / critical levels published by the source, when it has them.
    """
    cfg = engine_config()["water"]
    if not series:
        return {"current_m": None, "observed_at": None, "status": "UNKNOWN", "trend": None}
    t_now, level = series[-1]
    rate = rate_of_rise_m_per_h(series, cfg["rate_window_hours"])
    rate_cmh = None if rate is None else rate * 100
    if rate_cmh is None:
        trend = None
    elif rate_cmh >= cfg["trend_steady_cmh"]:
        trend = "rising"
    elif rate_cmh <= -cfg["trend_steady_cmh"]:
        trend = "falling"
    else:
        trend = "steady"
    distance = None if bank_m is None else bank_m - level
    status = system_status(distance, rate_cmh)
    if critical_m is not None and level >= critical_m:
        status = _worst(status, "CRITICAL") if status != "UNKNOWN" else "CRITICAL"
    elif warning_m is not None and level >= warning_m:
        status = _worst(status, "WATCH") if status != "UNKNOWN" else "WATCH"
    return {
        "current_m": round(level, 3),
        "observed_at": t_now,
        "bank_m": bank_m,
        "distance_to_bank_m": None if distance is None else round(distance, 3),
        "warning_level_m": warning_m,
        "distance_to_warning_m": None if warning_m is None else round(warning_m - level, 3),
        "critical_level_m": critical_m,
        "change_1h_m": None if (c := change_over(series, 1.0)) is None else round(c, 3),
        "rate_cm_per_h": None if rate_cmh is None else round(rate_cmh, 2),
        "trend": trend,
        "trend_label_th": TREND_LABEL_TH[trend],
        "points_used": len(series),
        "status": status,
        "status_label_th": STATUS_LABEL_TH[status],
        "status_basis": "system_computed_v0.1",
    }
