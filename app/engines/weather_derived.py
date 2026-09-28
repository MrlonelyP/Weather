"""Derived weather quantities computed from consensus values (documented formulas)."""
from __future__ import annotations

import math

from app.engines import engine_config


def apparent_temperature_c(temp_c: float | None, rh_pct: float | None, wind_kmh: float | None) -> float | None:
    """Feels-like temperature, Steadman apparent temperature (Australian BoM form, no radiation).

    AT = Ta + 0.33*e - 0.70*ws - 4.00, e = RH/100 * 6.105 * exp(17.27*Ta / (237.7 + Ta)) [hPa], ws [m/s]
    """
    if temp_c is None or rh_pct is None:
        return None
    ws = (wind_kmh or 0.0) / 3.6
    e = rh_pct / 100.0 * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    return round(temp_c + 0.33 * e - 0.70 * ws - 4.00, 1)


CONDITIONS = {
    "heavy_rain": "ฝนตกหนัก",
    "moderate_rain": "ฝนปานกลาง",
    "light_rain": "ฝนเล็กน้อย",
    "overcast": "มีเมฆมาก",
    "partly_cloudy": "มีเมฆบางส่วน",
    "clear": "ท้องฟ้าแจ่มใส",
}


def weather_condition(rain_mmh: float | None, cloud_pct: float | None) -> dict | None:
    """Condition from hourly rain rate (WMO/AMS classes) and cloud cover. None if no inputs."""
    cfg = engine_config()["weather_condition"]
    if rain_mmh is None and cloud_pct is None:
        return None
    if rain_mmh is not None and rain_mmh >= cfg["heavy_rain_mmh"]:
        code = "heavy_rain"
    elif rain_mmh is not None and rain_mmh >= cfg["moderate_rain_mmh"]:
        code = "moderate_rain"
    elif rain_mmh is not None and rain_mmh >= cfg["light_rain_mmh"]:
        code = "light_rain"
    elif cloud_pct is None:
        return None
    elif cloud_pct >= cfg["overcast_pct"]:
        code = "overcast"
    elif cloud_pct >= cfg["partly_cloudy_pct"]:
        code = "partly_cloudy"
    else:
        code = "clear"
    return {"code": code, "label_th": CONDITIONS[code]}
