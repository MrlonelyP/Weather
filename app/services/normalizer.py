"""Unit / time / number normalization shared by all collectors.

Canonical units (stored in the database):
    time            UTC (timestamptz); displayed as Asia/Bangkok
    rain            mm
    temperature     degC
    wind speed      km/h   (DB Schema sheet: wind_kph)
    pressure        hPa
    water level     m
    discharge       m3/s
    reservoir vol.  million m3 (MCM); reservoir flow also MCM/day

Rule: if a unit cannot be identified we return None rather than guess.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

UTC = timezone.utc
BANGKOK = ZoneInfo("Asia/Bangkok")

_MISSING_TOKENS = {"", "-", "--", "n/a", "na", "null", "none", "nan", "missing", "///", "////"}


class UnknownUnitError(ValueError):
    pass


# --------------------------------------------------------------------------- numbers
def to_float(value) -> float | None:
    """Parse numbers from APIs: handles '1,234.5', ' 12 ', '-', None, NaN. Never invents a value."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)
    if isinstance(value, dict):  # {"Value": "27.4", "Unit": "..."} style
        for key in ("value", "Value", "val", "#text"):
            if key in value:
                return to_float(value[key])
        return None
    text = str(value).strip()
    if text.lower() in _MISSING_TOKENS:
        return None
    text = text.replace(",", "").replace(" ", "")
    try:
        result = float(text)
    except ValueError:
        return None
    return None if math.isnan(result) else result


# --------------------------------------------------------------------------- time
def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime, assume_tz=UTC) -> datetime:
    """Return an aware UTC datetime. Naive input is interpreted in `assume_tz`."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt.astimezone(UTC)


def from_unix(ts) -> datetime | None:
    value = to_float(ts)
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def parse_datetime(value, assume_tz=UTC, formats: tuple[str, ...] = ()) -> datetime | None:
    """Parse ISO-8601 or any of `formats`. Naive results are interpreted in `assume_tz`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, assume_tz)
    text = str(value).strip()
    if not text:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")), assume_tz)
    except ValueError:
        pass
    for fmt in formats:
        try:
            return ensure_utc(datetime.strptime(text, fmt), assume_tz)
        except ValueError:
            continue
    return None


def to_local(dt: datetime | None, tz: ZoneInfo = BANGKOK) -> datetime | None:
    return None if dt is None else ensure_utc(dt).astimezone(tz)


def bangkok_today() -> date:
    return datetime.now(BANGKOK).date()


# --------------------------------------------------------------------------- units
def _norm_unit(unit: str | None) -> str:
    if unit is None:
        return ""
    u = unit.strip().lower().replace(" ", "").replace("°", "").replace("³", "3")
    return u


_TEMPERATURE = {
    "c": lambda v: v, "degc": lambda v: v, "celsius": lambda v: v, "celcius": lambda v: v,
    "f": lambda v: (v - 32) * 5 / 9, "degf": lambda v: (v - 32) * 5 / 9, "fahrenheit": lambda v: (v - 32) * 5 / 9,
    "k": lambda v: v - 273.15, "kelvin": lambda v: v - 273.15,
}
_LENGTH_TO_MM = {"mm": 1.0, "millimeter": 1.0, "millimetre": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4, "in": 25.4}
_LENGTH_TO_M = {"m": 1.0, "meter": 1.0, "metre": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "feet": 0.3048}
_SPEED_TO_KMH = {
    "km/h": 1.0, "kmh": 1.0, "kph": 1.0, "kilometer/hour": 1.0,
    "m/s": 3.6, "ms": 3.6, "mps": 3.6, "meter/second": 3.6,
    "kn": 1.852, "kt": 1.852, "kts": 1.852, "knot": 1.852, "knots": 1.852,
    "mph": 1.609344,
}
_PRESSURE_TO_HPA = {"hpa": 1.0, "mb": 1.0, "mbar": 1.0, "millibar": 1.0, "pa": 0.01, "kpa": 10.0, "inhg": 33.8639}
_VOLUME_TO_MCM = {
    "mcm": 1.0, "millionm3": 1.0, "mm3": 1.0, "ล้านลบ.ม.": 1.0, "ล้านลูกบาศก์เมตร": 1.0,
    "m3": 1e-6, "cubicmeter": 1e-6, "cubicmetre": 1e-6,
}


def _convert(value, unit: str | None, table: dict, kind: str):
    v = to_float(value)
    if v is None:
        return None
    key = _norm_unit(unit)
    if key not in table:
        raise UnknownUnitError(f"unknown {kind} unit: {unit!r}")
    factor = table[key]
    return factor(v) if callable(factor) else v * factor


def temperature_c(value, unit: str | None = "c") -> float | None:
    return _convert(value, unit, _TEMPERATURE, "temperature")


def rain_mm(value, unit: str | None = "mm") -> float | None:
    return _convert(value, unit, _LENGTH_TO_MM, "precipitation")


def level_m(value, unit: str | None = "m") -> float | None:
    return _convert(value, unit, _LENGTH_TO_M, "water level")


def speed_kmh(value, unit: str | None = "km/h") -> float | None:
    return _convert(value, unit, _SPEED_TO_KMH, "speed")


def pressure_hpa(value, unit: str | None = "hpa") -> float | None:
    return _convert(value, unit, _PRESSURE_TO_HPA, "pressure")


def volume_mcm(value, unit: str | None = "mcm") -> float | None:
    return _convert(value, unit, _VOLUME_TO_MCM, "volume")


def mcm_per_day_to_m3s(value) -> float | None:
    v = to_float(value)
    return None if v is None else v * 1_000_000 / 86_400


def m3s_to_mcm_per_day(value) -> float | None:
    v = to_float(value)
    return None if v is None else v * 86_400 / 1_000_000


def safe(fn, *args, **kwargs):
    """Call a converter; on an unknown unit log it and return None (never guess)."""
    try:
        return fn(*args, **kwargs)
    except UnknownUnitError as exc:
        log.warning("normalization skipped: %s", exc)
        return None


# --------------------------------------------------------------------------- text
_WS = re.compile(r"\s+")


def clean_text(value) -> str | None:
    if value is None:
        return None
    text = _WS.sub(" ", str(value)).strip()
    return text or None
