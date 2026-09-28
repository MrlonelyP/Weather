from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient

from app.collectors.openmeteo import OpenMeteoForecastCollector
from app.collectors.registry import build_collectors
from app.main import app
from app.scheduler.jobs import configure
from app.services.normalizer import utcnow
from tests.conftest import mock_fetcher
from tests.test_openmeteo import MODEL, make_handler

client = TestClient(app)


def _seed_forecast(settings):
    run = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    state = {"calls": [], "meta_calls": 0, "runs": [run]}
    OpenMeteoForecastCollector(settings, MODEL, mock_fetcher(make_handler(state))).run()
    return run


def test_scheduler_registers_each_enabled_job_separately(settings):
    scheduler = BackgroundScheduler(timezone="UTC")
    collectors = configure(scheduler, settings, build_collectors(settings), run_immediately=False)
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "openmeteo.forecast.ECMWF" in job_ids and "tmd.synoptic" in job_ids and "rid.dam" in job_ids
    assert "tmd.metar" not in job_ids  # disabled by default (P1)
    assert all(j.max_instances == 1 and j.coalesce for j in scheduler.get_jobs())
    assert len(collectors) == 11


def test_health_and_sources(settings):
    _seed_forecast(settings)
    body = client.get("/health").json()
    assert body["database"] == "OK"
    om = next(s for s in body["sources"] if s["source"] == "openmeteo")
    assert om["jobs"]["openmeteo.forecast.ECMWF"] == "OK" and om["last_success_local"].endswith("+07:00")

    sources = client.get("/sources").json()["sources"]
    assert len(sources) == 18
    by_id = {s["id"]: s for s in sources}
    assert by_id["WX-01"]["status"] == "OK"
    assert by_id["BMA-01"]["status"] == "NOT_IMPLEMENTED"
    assert client.get("/sources/openmeteo.forecast.ECMWF/runs").json()["runs"][0]["status"] == "OK"


def test_weather_forecast_and_current(settings):
    run = _seed_forecast(settings)
    fc = client.get("/weather/forecast", params={"location": "bangkok", "model": "ECMWF", "hours": 3}).json()
    block = fc["forecasts"][0]
    assert block["run"]["model_run_time"] == run.isoformat().replace("+00:00", "Z")
    v = block["values"][0]
    assert v["model_run_time"] != v["forecast_time"] or v["lead_time_hours"] == 0
    assert v["forecast_time_local"].endswith("+07:00") and v["raw_payload_id"]

    raw = client.get(f"/raw/{v['raw_payload_id']}", params={"include_payload": True}).json()
    assert raw["source"] == "openmeteo" and raw["payload"]

    cur = client.get("/weather/current", params={"location": "bangkok"}).json()
    assert cur["observations"] == [] and cur["observation_note"]
    assert cur["model_current_hour"][0]["model"] == "ECMWF"

    assert client.get("/weather/forecast", params={"location": "nowhere"}).status_code == 404


def test_reservoirs_and_warnings_empty_is_honest(settings):
    assert client.get("/reservoirs").json() == {"reservoirs": []}
    assert client.get("/warnings").json() == {"warnings": []}
