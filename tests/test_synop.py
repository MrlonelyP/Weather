"""SYNOP decoding follows WMO FM-12. The report strings below are hand-built
test vectors (not real observations) exercising each decoded group."""
from datetime import date, datetime, timezone

import pytest

from app.collectors.synop import decode_bulletin

pytestmark = pytest.mark.nodb

BULLETIN = """SMTH01 VTBB 280000
AAXX 28001
48455 11560 72304 10275 20241 30072 40085 57012 60031 70522 83530
333 10330 20248 70125=
48456 NIL=
48900 32970 00000 11012 29085 40123=
"""


def test_decode_section1_and_section3():
    reports = decode_bulletin(BULLETIN, date(2026, 9, 28))
    assert [r.station for r in reports] == ["48455", "48900"]
    r = reports[0]
    assert r.observed_at == datetime(2026, 9, 28, 0, tzinfo=timezone.utc)
    assert r.visibility_km == 10.0             # VV=60 -> 10 km
    assert r.cloud_cover_okta == 7.0           # N=7
    assert r.wind_direction_deg == 230.0       # dd=23
    assert r.wind_speed_kmh == pytest.approx(14.4)  # ff=04 m/s (iw=1)
    assert r.temperature_c == 27.5
    assert r.dew_point_c == 24.1
    assert r.station_pressure_hpa == 1007.2
    assert r.pressure_msl_hpa == 1008.5
    assert r.rain_mm == 3.0 and r.rain_period_hours == 6   # 6 003 1
    assert r.max_temperature_c == 33.0 and r.min_temperature_c == 24.8
    assert r.rain_24h_mm == 12.5
    assert "48455 11560" in r.text


def test_calm_negative_temp_humidity_group_and_no_rain_group():
    r = decode_bulletin(BULLETIN, date(2026, 9, 28))[1]
    assert r.wind_speed_kmh == 0.0 and r.wind_direction_deg is None   # 00000 calm
    assert r.temperature_c == -1.2                                  # 1 1 012
    assert r.humidity_pct == 85.0 and r.dew_point_c is None         # 29UUU
    assert r.rain_mm is None                                        # iR=3: group omitted
    assert r.pressure_msl_hpa == 1012.3
    assert r.visibility_km == 20.0                                  # VV=70


def test_knots_trace_and_month_rollover():
    text = "AAXX 30124 48327 12965 81010 10301 69907 333 79999="
    r = decode_bulletin(text, date(2026, 10, 1))[0]
    assert r.observed_at == datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    assert r.wind_speed_kmh == pytest.approx(18.5, abs=0.1)  # 10 kt
    assert r.rain_mm is None and "rain_trace" in r.flags
    assert r.rain_24h_mm is None and "rain24_trace" in r.flags
