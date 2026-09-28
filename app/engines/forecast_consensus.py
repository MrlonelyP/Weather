"""Forecast Consensus Engine v0.1 - "our forecast" built from ECMWF, GFS and JMA.

Method (no machine learning yet):
  consensus   weighted mean of the models (weights default 1:1:1; later from backtest skill)
  spread      max - min;  std = weighted population standard deviation
  agreement   1 / (1 + (std / tau)^2),  tau = max(abs_tol, rel_tol * |consensus|)   (per variable)
  coverage    models available / models expected
  confidence  coverage * agreement
              rain adds occurrence agreement: 0.5*amount_agreement + 0.5*|2p - 1|,
              p = share of models forecasting at least the rain threshold
  wind dir    circular (vector) mean; agreement = mean resultant length R

Rain windows (next 1/3/6/12/24/48 h) sum each model's hourly precipitation first
and then build the consensus. Open-Meteo hourly precipitation at time T is the
amount of the preceding hour (T-1h, T], so "next N hours" from the current hour
H0 = values at H0+1h .. H0+Nh. A model only enters a window when it has every
hour of that window.

Input values are the collected model forecasts; nothing is invented. If no
model has a value, the output is None.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from app.engines import engine_config
from app.engines.weather_derived import apparent_temperature_c, weather_condition

SCALAR_VARIABLES = [
    "temperature_c", "humidity_pct", "precipitation_mm", "precip_probability_pct", "pressure_msl_hpa",
    "cloud_cover_pct", "wind_speed_kmh", "wind_gust_kmh", "soil_moisture_m3m3",
]
# prepared: summarized when a model provides them
OPTIONAL_VARIABLES = ["cape_jkg", "visibility_m", "runoff_mm"]
NON_NEGATIVE = {"precipitation_mm", "precip_probability_pct", "wind_speed_kmh", "wind_gust_kmh", "cloud_cover_pct",
                "humidity_pct", "soil_moisture_m3m3", "cape_jkg", "visibility_m", "runoff_mm"}


@dataclass
class ModelSeries:
    model: str
    model_run_time: datetime
    # forecast_time (UTC, on the hour) -> {variable: value}
    points: dict[datetime, dict[str, float | None]] = field(default_factory=dict)


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def _agreement(std: float, tau: float) -> float:
    if tau <= 0:
        return 1.0 if std == 0 else 0.0
    return 1.0 / (1.0 + (std / tau) ** 2)


def summarize(values: dict[str, float], weights: dict[str, float], expected_models: int,
              tol_abs: float, tol_rel: float, non_negative: bool = False, nd: int = 2) -> dict:
    """Consensus statistics for one quantity across models (values already non-null)."""
    out: dict = {m.lower(): _r(v, nd) for m, v in values.items()}
    n = len(values)
    if n == 0:
        out.update(consensus=None, median=None, min=None, max=None, spread=None, std=None,
                   likely_range=None, n_models=0, confidence=None)
        return out
    w = {m: max(weights.get(m, 1.0), 0.0) for m in values}
    total = sum(w.values()) or float(n)
    if total == 0:
        w = {m: 1.0 for m in values}
        total = float(n)
    mean = sum(w[m] * v for m, v in values.items()) / total
    std = math.sqrt(sum(w[m] * (v - mean) ** 2 for m, v in values.items()) / total)
    tau = max(tol_abs, tol_rel * abs(mean))
    agreement = _agreement(std, tau)
    coverage = n / max(expected_models, 1)
    low, high = mean - std / 2, mean + std / 2
    if non_negative:
        low = max(low, 0.0)
    out.update(
        consensus=_r(mean, nd), median=_r(median(values.values()), nd), min=_r(min(values.values()), nd),
        max=_r(max(values.values()), nd), spread=_r(max(values.values()) - min(values.values()), nd),
        std=_r(std, nd), likely_range=[_r(low, nd), _r(high, nd)], n_models=n,
        agreement=_r(agreement, 3), coverage=_r(coverage, 3), confidence=_r(coverage * agreement, 3),
    )
    return out


def summarize_rain(values: dict[str, float], weights: dict[str, float], expected_models: int,
                   tol_abs: float, tol_rel: float, threshold_mm: float) -> dict:
    out = summarize(values, weights, expected_models, tol_abs, tol_rel, non_negative=True, nd=1)
    if not values:
        out.update(probability_model_agreement=None, occurrence_agreement=None)
        return out
    p = sum(1 for v in values.values() if v >= threshold_mm) / len(values)
    occurrence = abs(2 * p - 1)
    amount = out["agreement"]
    out.update(
        probability_model_agreement=_r(p, 3), threshold_mm=threshold_mm,
        occurrence_agreement=_r(occurrence, 3),
        confidence=_r(out["coverage"] * (0.5 * amount + 0.5 * occurrence), 3),
    )
    return out


def summarize_direction(values: dict[str, float], weights: dict[str, float], expected_models: int) -> dict:
    out: dict = {m.lower(): _r(v, 0) for m, v in values.items()}
    n = len(values)
    if n == 0:
        out.update(consensus=None, n_models=0, confidence=None)
        return out
    w = {m: weights.get(m, 1.0) for m in values}
    total = sum(w.values()) or float(n)
    s = sum(w[m] * math.sin(math.radians(v)) for m, v in values.items()) / total
    c = sum(w[m] * math.cos(math.radians(v)) for m, v in values.items()) / total
    resultant = math.hypot(s, c)
    direction = (math.degrees(math.atan2(s, c)) + 360) % 360 if resultant > 1e-9 else None
    coverage = n / max(expected_models, 1)
    out.update(consensus=_r(direction, 0), n_models=n, agreement=_r(resultant, 3), coverage=_r(coverage, 3),
               confidence=_r(coverage * resultant, 3))
    return out


def build_consensus(series: list[ModelSeries], now: datetime, horizon_hours: int = 48,
                    weights: dict[str, float] | None = None, expected_models: int | None = None) -> dict:
    """Hourly consensus timeline + rain windows for one location."""
    cfg = engine_config()["consensus"]
    tol = cfg["tolerance"]
    weights = weights or cfg["default_model_weights"]
    expected = expected_models or len(cfg["default_model_weights"])
    hour0 = now.replace(minute=0, second=0, microsecond=0)

    hourly = []
    for h in range(0, horizon_hours + 1):
        t = hour0 + timedelta(hours=h)
        row: dict = {"forecast_time": t, "lead_from_now_h": h}
        for var in SCALAR_VARIABLES + OPTIONAL_VARIABLES:
            vals = {s.model: s.points[t][var] for s in series
                    if t in s.points and s.points[t].get(var) is not None}
            if var in OPTIONAL_VARIABLES and not vals:
                continue
            t_cfg = tol.get(var, {"abs": 1.0, "rel": 0.0})
            if var == "precipitation_mm":
                row[var] = summarize_rain(vals, weights, expected, t_cfg["abs"], t_cfg["rel"],
                                          cfg["rain_occurrence_threshold_mm"]["1"])
            else:
                row[var] = summarize(vals, weights, expected, t_cfg["abs"], t_cfg["rel"],
                                     non_negative=var in NON_NEGATIVE)
        dirs = {s.model: s.points[t]["wind_direction_deg"] for s in series
                if t in s.points and s.points[t].get("wind_direction_deg") is not None}
        row["wind_direction_deg"] = summarize_direction(dirs, weights, expected)
        temp = row["temperature_c"]["consensus"]
        rh = row["humidity_pct"]["consensus"]
        wind = row["wind_speed_kmh"]["consensus"]
        row["feels_like_c"] = apparent_temperature_c(temp, rh, wind)
        row["condition"] = weather_condition(row["precipitation_mm"]["consensus"],
                                             row["cloud_cover_pct"]["consensus"])
        # displayed rain probability: model-provided where available, else model agreement
        prob = row["precip_probability_pct"]["consensus"]
        agree = row["precipitation_mm"].get("probability_model_agreement")
        row["rain_probability"] = (
            {"value_pct": prob, "basis": "model_provided"} if prob is not None else
            {"value_pct": _r(agree * 100, 0), "basis": "model_agreement"} if agree is not None else
            {"value_pct": None, "basis": None})
        hourly.append(row)

    windows = {}
    for n in cfg["rain_windows_hours"]:
        hours = [hour0 + timedelta(hours=k) for k in range(1, n + 1)]
        sums = {}
        for s in series:
            vals = [s.points.get(t, {}).get("precipitation_mm") for t in hours]
            if all(v is not None for v in vals):
                sums[s.model] = sum(vals)
        windows[f"rain_{n}h"] = summarize_rain(
            sums, weights, expected, tol["rain_window"]["abs"][str(n)], tol["rain_window"]["rel"],
            cfg["rain_occurrence_threshold_mm"][str(n)])
        windows[f"rain_{n}h"].update(window_start=hour0, window_end=hours[-1], hours=n)

    return {
        "hour0": hour0,
        "models": [{"model": s.model, "model_run_time": s.model_run_time,
                    "hours_available": len(s.points)} for s in series],
        "weights": {m: weights.get(m, 1.0) for m in [s.model for s in series]},
        "weights_basis": "equal (default v0.1)" if weights == cfg["default_model_weights"] else "backtest",
        "hourly": hourly,
        "windows": windows,
    }
