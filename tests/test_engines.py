"""Engines are pure functions; inputs here are synthetic test vectors."""
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.forecast_consensus import ModelSeries, build_consensus, summarize, summarize_direction, summarize_rain
from app.engines.water_calc import rate_of_rise_m_per_h, station_state, system_status
from app.engines.weather_derived import apparent_temperature_c, weather_condition

pytestmark = pytest.mark.nodb
W = {"ECMWF": 1.0, "GFS": 1.0, "JMA": 1.0}


def test_consensus_example_from_spec():
    out = summarize_rain({"ECMWF": 34.0, "GFS": 21.0, "JMA": 39.0}, W, 3, tol_abs=2.0, tol_rel=0.5, threshold_mm=1.0)
    assert out["consensus"] == pytest.approx(31.3, abs=0.05)
    assert out["min"] == 21.0 and out["max"] == 39.0 and out["median"] == 34.0
    assert out["agreement"] == pytest.approx(0.81, abs=0.01)
    assert out["probability_model_agreement"] == 1.0
    assert out["ecmwf"] == 34.0 and out["n_models"] == 3


def test_confidence_drops_with_disagreement_and_missing_models():
    close = summarize({"ECMWF": 30.0, "GFS": 30.5, "JMA": 29.8}, W, 3, 1.5, 0.0)
    far = summarize({"ECMWF": 25.0, "GFS": 31.0, "JMA": 35.0}, W, 3, 1.5, 0.0)
    two = summarize({"ECMWF": 30.0, "GFS": 30.5}, W, 3, 1.5, 0.0)
    assert close["confidence"] > far["confidence"]
    assert two["confidence"] < close["confidence"]
    assert summarize({}, W, 3, 1.5, 0.0)["consensus"] is None


def test_split_rain_occurrence_lowers_confidence():
    agree_dry = summarize_rain({"ECMWF": 0.0, "GFS": 0.0, "JMA": 0.0}, W, 3, 2.0, 0.5, 1.0)
    split = summarize_rain({"ECMWF": 0.0, "GFS": 6.0, "JMA": 0.2}, W, 3, 2.0, 0.5, 1.0)
    assert agree_dry["confidence"] == 1.0
    assert split["confidence"] < 0.6


def test_wind_direction_is_circular():
    out = summarize_direction({"ECMWF": 350.0, "GFS": 10.0}, W, 2)
    assert out["consensus"] in (0.0, 360.0)
    assert out["confidence"] > 0.95


def test_rain_windows_require_every_hour():
    t0 = datetime(2026, 9, 28, 5, tzinfo=timezone.utc)
    full = ModelSeries("ECMWF", t0, {t0 + timedelta(hours=h): {"precipitation_mm": 1.0} for h in range(0, 8)})
    gap = ModelSeries("GFS", t0, {t0 + timedelta(hours=h): {"precipitation_mm": 2.0} for h in (0, 1, 2)})
    out = build_consensus([full, gap], t0 + timedelta(minutes=20), horizon_hours=6, weights=W, expected_models=3)
    w6 = out["windows"]["rain_6h"]
    assert w6["ecmwf"] == 6.0 and "gfs" not in w6 and w6["n_models"] == 1
    w1 = out["windows"]["rain_1h"]
    assert w1["ecmwf"] == 1.0 and w1["gfs"] == 2.0


def test_derived_weather():
    assert apparent_temperature_c(30.0, 75.0, 10.0) == pytest.approx(34.5, abs=0.1)  # hand-computed
    assert apparent_temperature_c(None, 70, 5) is None
    assert weather_condition(8.0, 90)["code"] == "heavy_rain"
    assert weather_condition(0.0, 50)["code"] == "partly_cloudy"
    assert weather_condition(None, None) is None


def test_water_rate_trend_and_status():
    t = datetime(2026, 9, 28, 0, tzinfo=timezone.utc)
    series = [(t + timedelta(hours=h), 3.48 + 0.08 * h) for h in range(4)]  # +8 cm/h, ends 3.72
    rate = rate_of_rise_m_per_h(series, 3)
    assert rate == pytest.approx(0.08, abs=1e-6)
    st = station_state(series, bank_m=4.0)
    assert st["current_m"] == pytest.approx(3.72) and st["distance_to_bank_m"] == pytest.approx(0.28)
    assert st["trend"] == "rising" and st["rate_cm_per_h"] == pytest.approx(8.0)
    assert st["status"] == "WARNING" and st["status_basis"].startswith("system")
    assert station_state(series, bank_m=None)["status"] == "UNKNOWN"
    assert system_status(-0.1, 0) == "CRITICAL"
    assert system_status(2.0, 0.0) == "NORMAL"
    assert system_status(0.7, 0.0) == "WATCH"
