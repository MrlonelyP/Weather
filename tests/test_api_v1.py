"""/api/* endpoints over stored data (synthetic payloads through the real collectors)."""
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient

from app.api import cache
from app.collectors.openmeteo import OpenMeteoForecastCollector
from app.collectors.thaiwater import ThaiWaterLevelCollector, ThaiWaterRainCollector
from app.main import app
from app.services.normalizer import BANGKOK, utcnow
from tests.conftest import mock_fetcher
from tests.test_openmeteo import MODEL, make_handler

client = TestClient(app)


def _local(dt):
    return dt.astimezone(BANGKOK).strftime("%Y-%m-%d %H:%M")


def _seed(settings):
    cache.clear()
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    run = now - timedelta(hours=1)
    OpenMeteoForecastCollector(settings, MODEL, mock_fetcher(make_handler(
        {"calls": [], "meta_calls": 0, "runs": [run]}))).run()
    wl = {"waterlevel_data": {"data": [{
        "waterlevel_datetime": _local(now), "waterlevel_msl": "3.72", "waterlevel_msl_previous": "3.64",
        "discharge": "10", "situation_level": 4, "diff_wl_bank": "0.28", "diff_wl_bank_text": "ต่ำกว่าตลิ่ง (ม.)",
        "station": {"id": 1, "tele_station_name": {"th": "สถานีทดสอบ"}, "tele_station_lat": 13.8,
                    "tele_station_long": 100.5, "min_bank": 4.0},
        "geocode": {"province_code": "10", "province_name": {"th": "กรุงเทพมหานคร"}}}]}}
    ThaiWaterLevelCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=wl))).run()
    rain = {"data": [{"rainfall_datetime": _local(now), "rain_24h": 42.0, "rain_1h": 3.5,
                      "station": {"id": 9, "tele_station_name": {"th": "ฝนทดสอบ"}, "tele_station_lat": 13.76,
                                  "tele_station_long": 100.51},
                      "geocode": {"province_code": "10", "province_name": {"th": "กรุงเทพมหานคร"}}}]}
    ThaiWaterRainCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=rain))).run()
    return now


def test_summary_sources_and_freshness(settings):
    _seed(settings)
    s = client.get("/api/dashboard/summary").json()
    assert s["rain_24h"]["value"] == 42.0 and s["rain_24h"]["freshness"]["status"] == "LIVE"
    assert s["critical_water"]["value"] == 0
    assert s["flood_risk"]["available"] is False and s["flood_risk"]["value"] is None
    src = {x["source"]: x for x in client.get("/api/sources/health").json()["sources"]}
    assert src["thaiwater"]["status"] == "LIVE" and src["thaiwater"]["age_minutes"] is not None
    assert src["news"]["status"] == "NOT_CONNECTED"


def test_water_station_computed_and_source_values_separate(settings):
    _seed(settings)
    st = client.get("/api/water/stations").json()["stations"][0]
    assert st["current_m"] == 3.72 and st["distance_to_bank_m"] == 0.28
    assert st["status_basis"].startswith("system_computed")
    assert st["source_assessment"]["situation_level"] == 4
    assert st["source_assessment"]["diff_to_bank_text"] == "ต่ำกว่าตลิ่ง (ม.)"


def test_weather_consensus_and_comparison(settings):
    _seed(settings)
    cur = client.get("/api/weather/current", params={"location": "bangkok"}).json()
    assert cur["forecast_now"]["n_models"] == 1 and cur["forecast_basis"].startswith("Consensus")
    cons = client.get("/api/weather/consensus", params={"location": "bangkok", "hours": 3}).json()
    assert "rain_1h" in cons["windows"] and cons["windows"]["rain_1h"]["n_models"] == 1
    cmp_ = client.get("/api/rainfall/comparison", params={"location": "bangkok"}).json()
    assert "ECMWF" in cmp_["models"] and cmp_["observed"]["stations"] == 1
    assert cmp_["observed"]["series"][0]["mean_mm"] == 3.5


def test_unconnected_blocks_are_explicit(settings):
    cache.clear()
    assert client.get("/api/news").json()["available"] is False
    assert client.get("/api/flood/risk").json()["available"] is False
    ext = client.get("/api/flood/extent").json()
    assert ext["available"] is False and ext["geojson"]["features"] == []
    assert client.get("/api/rainfall", params={"window": "3h"}).json()["points"] == []
