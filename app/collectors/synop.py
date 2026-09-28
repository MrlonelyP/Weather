"""Decoder for WMO FM-12 SYNOP (AAXX) land station reports.

Only the groups needed for Phase 0 are decoded; everything else is ignored.
Every decoded report keeps its original text so the value can be traced.

Section 0:  AAXX YYGGiw
Section 1:  IIiii iRiXhVV Nddff (00fff) 1snTTT 2snTdTdTd 3PoPoPoPo 4PPPP 5appp 6RRRtR 7wwW1W2 8NhCLCMCH
Section 3:  333 ... 1snTxTxTx 2snTnTnTn ... 6RRRtR 7R24R24R24R24 ...
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

KNOT_TO_KMH = 1.852
MS_TO_KMH = 3.6

# tR code -> accumulation period in hours
_RAIN_PERIOD = {"1": 6, "2": 12, "3": 18, "4": 24, "5": 1, "6": 2, "7": 3, "8": 9, "9": 15}


@dataclass
class SynopReport:
    station: str  # WMO index IIiii
    observed_at: datetime  # UTC
    text: str
    temperature_c: float | None = None
    dew_point_c: float | None = None
    humidity_pct: float | None = None
    station_pressure_hpa: float | None = None
    pressure_msl_hpa: float | None = None
    visibility_km: float | None = None
    cloud_cover_okta: float | None = None
    wind_direction_deg: float | None = None
    wind_speed_kmh: float | None = None
    rain_mm: float | None = None
    rain_period_hours: float | None = None
    rain_24h_mm: float | None = None
    max_temperature_c: float | None = None
    min_temperature_c: float | None = None
    flags: list[str] = field(default_factory=list)


def _digits(group: str, start: int, end: int) -> int | None:
    part = group[start:end]
    return int(part) if part.isdigit() else None


def _temperature(group: str) -> float | None:
    sign, value = group[1:2], _digits(group, 2, 5)
    if value is None or sign not in ("0", "1"):
        return None
    return round((-value if sign == "1" else value) / 10.0, 1)


def _pressure(group: str) -> float | None:
    value = _digits(group, 1, 5)
    if value is None:
        return None
    hpa = value / 10.0
    if hpa < 100:
        hpa += 1000.0
    return round(hpa, 1) if 850.0 <= hpa <= 1090.0 else None


def _visibility(vv: int | None) -> float | None:
    if vv is None:
        return None
    if vv <= 50:
        return vv / 10.0
    if 56 <= vv <= 80:
        return float(vv - 50)
    if 81 <= vv <= 88:
        return float(30 + (vv - 80) * 5)
    if vv == 89:
        return 70.0  # "> 70 km"; lower bound
    return None  # 51-55 unused, 90-99 non-aeronautical scale


def _rain_amount(rrr: int | None, flags: list[str]) -> float | None:
    if rrr is None:
        return None
    if rrr <= 988:
        return float(rrr)
    if rrr == 989:
        flags.append("rain>=989mm")
        return 989.0
    if rrr == 990:
        flags.append("rain_trace")
        return None  # trace: not measurable, not stored as a number
    return (rrr - 990) / 10.0


def _obs_time(yy: int, gg: int, ref: date) -> datetime | None:
    if not (1 <= yy <= 31 and 0 <= gg <= 23):
        return None
    year, month = ref.year, ref.month
    for _ in range(2):
        try:
            candidate = datetime(year, month, yy, gg, tzinfo=timezone.utc)
        except ValueError:
            candidate = None
        if candidate is not None and candidate.date() <= ref + timedelta(days=1):
            return candidate
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return None


_GROUP = re.compile(r"^[0-9/]{5}$")


def decode_report(tokens: list[str], yy: int, gg: int, iw: str, ref: date) -> SynopReport | None:
    if not tokens or not re.fullmatch(r"\d{5}", tokens[0]):
        return None
    station = tokens[0]
    if len(tokens) > 1 and tokens[1].upper() == "NIL":
        return None
    observed_at = _obs_time(yy, gg, ref)
    if observed_at is None:
        return None
    report = SynopReport(station=station, observed_at=observed_at, text=" ".join(tokens))
    groups = [t for t in tokens[1:] if _GROUP.match(t) or t in ("333", "555", "222")]
    if len(groups) < 2:
        return report

    # iRiXhVV
    i_r = groups[0][0]
    report.visibility_km = _visibility(_digits(groups[0], 3, 5))
    # Nddff
    nddff = groups[1]
    n = _digits(nddff, 0, 1)
    report.cloud_cover_okta = float(n) if n is not None and n <= 8 else None
    dd, ff = _digits(nddff, 1, 3), _digits(nddff, 3, 5)
    idx = 2
    if ff == 99 and idx < len(groups) and groups[idx].startswith("00"):
        ff = _digits(groups[idx], 2, 5)
        idx += 1
    factor = MS_TO_KMH if iw in ("0", "1") else KNOT_TO_KMH if iw in ("3", "4") else None
    if factor is None:
        report.flags.append("wind_unit_unknown")
    else:
        if dd == 0 and ff == 0:
            report.wind_speed_kmh, report.wind_direction_deg = 0.0, None
        elif ff is not None:
            report.wind_speed_kmh = round(ff * factor, 1)
            report.wind_direction_deg = float(dd * 10) if dd is not None and 1 <= dd <= 36 else None

    section, last_indicator = 1, 0
    for group in groups[idx:]:
        if group in ("222", "333", "555"):
            section = int(group[0])
            last_indicator = 0
            continue
        if section == 5:
            break  # national section: not decoded
        if not group[0].isdigit():
            continue
        indicator = int(group[0])
        if section == 1:
            if indicator <= last_indicator:
                continue  # out of order -> not a section 1 group
            last_indicator = indicator
            if indicator == 1:
                report.temperature_c = _temperature(group)
            elif indicator == 2:
                if group[1] == "9":
                    rh = _digits(group, 2, 5)
                    report.humidity_pct = float(rh) if rh is not None and rh <= 100 else None
                else:
                    report.dew_point_c = _temperature(group)
            elif indicator == 3:
                report.station_pressure_hpa = _pressure(group)
            elif indicator == 4:
                report.pressure_msl_hpa = _pressure(group)
            elif indicator == 6 and i_r in ("0", "1"):
                report.rain_mm = _rain_amount(_digits(group, 1, 4), report.flags)
                report.rain_period_hours = _RAIN_PERIOD.get(group[4])
        elif section == 3:
            if indicator == 1:
                report.max_temperature_c = _temperature(group)
            elif indicator == 2:
                report.min_temperature_c = _temperature(group)
            elif indicator == 6 and report.rain_mm is None and i_r in ("0", "2"):
                report.rain_mm = _rain_amount(_digits(group, 1, 4), report.flags)
                report.rain_period_hours = _RAIN_PERIOD.get(group[4])
            elif indicator == 7:
                value = _digits(group, 1, 5)
                if value == 9999:
                    report.flags.append("rain24_trace")
                elif value is not None:
                    report.rain_24h_mm = value / 10.0

    return report


def decode_bulletin(text: str, ref: date) -> list[SynopReport]:
    """Decode every AAXX message in `text`. `ref` = UTC date the bulletin belongs to."""
    reports: list[SynopReport] = []
    normalized = re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " "))
    for chunk in normalized.split("AAXX")[1:]:
        tokens = chunk.strip().split(" ")
        if not tokens or not re.fullmatch(r"[0-9/]{5}", tokens[0]):
            continue
        header = tokens[0]
        yy, gg, iw = _digits(header, 0, 2), _digits(header, 2, 4), header[4]
        if yy is None or gg is None:
            continue
        if yy > 50:  # YY+50 convention: wind in knots
            yy -= 50
        body = " ".join(tokens[1:])
        for station_text in body.split("="):
            station_tokens = station_text.strip().split()
            if not station_tokens:
                continue
            report = decode_report(station_tokens, yy, gg, iw, ref)
            if report is not None:
                reports.append(report)
    return reports
