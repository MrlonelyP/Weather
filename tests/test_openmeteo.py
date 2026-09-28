"""Open-Meteo collector. Responses are synthetic, shaped per the public API docs."""
import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from app.collectors.openmeteo import OpenMeteoForecastCollector, OpenMeteoHistoricalCollector
from app.config.settings import OpenMeteoModel
from app.models import ForecastRun, RawPayload, WeatherForecast
from app.services.database import session_scope
from app.services.locations import load_location_config
from tests.conftest import mock_fetcher

RUN = datetime(2026, 9, 28, 0, tzinfo=timezone.utc)
MODEL = OpenMeteoModel(name="ECMWF", endpoint="ecmwf", param="ecmwf_ifs", meta_id="ecmwf_ifs",
                       extra_hourly=["soil_moisture_0_to_7cm"])


def meta(run=RUN):
    return {"last_run_initialisation_time": int(run.timestamp()),
            "last_run_availability_time": int((run + timedelta(hours=7)).timestamp()),
            "temporal_resolution_seconds": 3600, "update_interval_seconds": 21600}


def forecast_payload(n_locations, hours=6, start=RUN - timedelta(hours=2), with_soil=True):
    times = [int((start + timedelta(hours=h)).timestamp()) for h in range(hours)]
    items = []
    for i in range(n_locations):
        hourly = {"time": times,
                  "temperature_2m": [25.0 + h for h in range(hours)],
                  "precipitation": [0.1 * h for h in range(hours)],
                  "rain": [0.1 * h for h in range(hours)],
                  "wind_speed_10m": [10.0] * hours,
                  "relative_humidity_2m": [80] * hours,
                  "precipitation_probability": [None] * hours}
        units = {"temperature_2m": "°C", "precipitation": "mm", "rain": "mm", "wind_speed_10m": "km/h",
                 "relative_humidity_2m": "%"}
        if with_soil:
            hourly["soil_moisture_0_to_7cm"] = [0.3] * hours
            units["soil_moisture_0_to_7cm"] = "m³/m³"
        items.append({"latitude": 13.75 + i * 0.01, "longitude": 100.5, "elevation": 2.0,
                      "hourly_units": units, "hourly": hourly})
    return items


def make_handler(state):
    def handler(request: httpx.Request):
        state["calls"].append(str(request.url))
        if "meta.json" in request.url.path:
            state["meta_calls"] += 1
            run = state["runs"][min(state["meta_calls"] - 1, len(state["runs"]) - 1)]
            return httpx.Response(200, json=meta(run))
        hourly = request.url.params.get("hourly", "")
        if state.get("reject_soil") and "soil_moisture" in hourly:
            return httpx.Response(400, json={"error": True, "reason": "Cannot initialize variable"})
        n = len(request.url.params["latitude"].split(","))
        start = state["runs"][0] - timedelta(hours=2)
        return httpx.Response(200, json=forecast_payload(n, start=start, with_soil="soil_moisture" in hourly))
    return handler


def collector(settings, state):
    return OpenMeteoForecastCollector(settings, MODEL, mock_fetcher(make_handler(state)))


def test_forecast_stores_run_time_separately_and_is_idempotent(settings):
    state = {"calls": [], "meta_calls": 0, "runs": [RUN]}
    outcome = collector(settings, state).run()
    n_loc = len(load_location_config())
    assert outcome.status == "OK"
    # 6 hours returned starting 2 h before the run -> only the 4 hours >= run time are kept
    assert outcome.records == n_loc * 4

    with session_scope() as s:
        run = s.execute(select(ForecastRun)).scalar_one()
        assert run.model == "ECMWF" and run.model_run_time == RUN
        assert run.available_at == RUN + timedelta(hours=7)
        rows = s.execute(select(WeatherForecast).order_by(WeatherForecast.forecast_time)).scalars().all()
        first = rows[0]
        assert first.model_run_time == RUN and first.forecast_time == RUN and first.lead_time_hours == 0
        assert first.temperature_c == 27.0 and first.soil_moisture_m3m3 == 0.3
        assert first.soil_moisture_layer == "0-7cm" and first.wind_speed_kmh == 10.0
        assert first.raw_payload_id is not None and first.source == "openmeteo"
        raw = s.get(RawPayload, first.raw_payload_id)
        assert raw.parse_status == "parsed" and raw.context["model_run_time"] == RUN.isoformat()

    # second run with the same model run: nothing new fetched, nothing duplicated
    outcome2 = collector(settings, state).run()
    assert outcome2.status == "OK" and outcome2.records == 0
    with session_scope() as s:
        assert s.execute(select(func.count(WeatherForecast.id))).scalar_one() == n_loc * 4


def test_run_changing_during_fetch_is_not_normalized(settings):
    state = {"calls": [], "meta_calls": 0, "runs": [RUN, RUN + timedelta(hours=6)]}
    outcome = collector(settings, state).run()
    assert outcome.status == "DEGRADED" and outcome.records == 0
    with session_scope() as s:
        assert s.execute(select(func.count(WeatherForecast.id))).scalar_one() == 0
        raw = s.execute(select(RawPayload).where(RawPayload.dataset == "forecast.ECMWF")).scalar_one()
        assert raw.parse_status == "skipped" and raw.payload  # raw kept for audit


def test_rejected_extra_variable_falls_back(settings):
    state = {"calls": [], "meta_calls": 0, "runs": [RUN], "reject_soil": True}
    outcome = collector(settings, state).run()
    assert outcome.status == "DEGRADED" and outcome.records > 0
    with session_scope() as s:
        assert s.execute(select(func.count(RawPayload.id)).where(RawPayload.status_code == 400)).scalar_one() == 1


def test_historical_forecast_has_no_run_time_and_upserts(settings):
    def handler(request):
        n = len(request.url.params["latitude"].split(","))
        return httpx.Response(200, json=forecast_payload(n, with_soil=False))

    c = OpenMeteoHistoricalCollector(settings, mock_fetcher(handler))
    first = c.run()
    assert first.status == "OK" and first.records > 0
    again = OpenMeteoHistoricalCollector(settings, mock_fetcher(handler)).run()
    assert again.status == "OK"
    with session_scope() as s:
        rows = s.execute(select(WeatherForecast)).scalars().all()
        assert all(r.product == "historical_forecast" and r.model_run_time is None for r in rows)
        # 3 models x 6 locations x 6 hours; re-fetch updated rows, no duplicates
        assert len(rows) == 3 * len(load_location_config()) * 6


def test_forecast_payload_request_uses_canonical_units(settings):
    state = {"calls": [], "meta_calls": 0, "runs": [RUN]}
    collector(settings, state).run()
    forecast_url = next(u for u in state["calls"] if "/v1/ecmwf" in u)
    params = httpx.URL(forecast_url).params
    assert params["timezone"] == "GMT" and params["wind_speed_unit"] == "kmh"
    assert params["precipitation_unit"] == "mm" and params["models"] == "ecmwf_ifs"
    assert json.loads(json.dumps(params["latitude"].split(",")))[0] == "13.7563"
