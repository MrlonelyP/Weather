"""Water-first endpoints over stored data (synthetic payloads through the real collectors)."""
import urllib.parse

from fastapi.testclient import TestClient

from app.api import cache
from app.engines.water_impact import assess
from app.main import app
from tests.test_api_v1 import _seed

client = TestClient(app)


def test_station_detail_filters_and_search(settings):
    _seed(settings)
    d = client.get("/api/water/stations/1", params={"range": "6h"}).json()
    assert d["levels"]["bank_m"] == 4.0 and d["state"]["distance_to_bank_m"] == 0.28
    assert d["stats_24h"]["max_m"] == 3.72 and d["forecast"] is None and d["forecast_note"]
    assert d["impact"]["outlook"] in ("likely_rise", "possible_rise", "no_signal", "insufficient_data")
    assert "ไม่ใช่ประกาศทางราชการ" in d["impact"]["disclaimer"]
    f = client.get("/api/water/filters").json()
    assert f["provinces"][0]["value"] == "10"
    assert client.get("/api/water/stations", params={"status": "CRITICAL"}).json()["stations"] == []
    assert len(client.get("/api/water/stations", params={"province": "10"}).json()["stations"]) == 1
    s = client.get("/api/search?q=" + urllib.parse.quote("ทดสอบ")).json()
    assert s["stations"][0]["station_code"] == "1"
    assert client.get("/api/water/stations/999").status_code == 404


def test_nearby_and_tide(settings):
    _seed(settings)
    n = client.get("/api/water/nearby", params={"lat": 13.8, "lon": 100.5, "radius_km": 5}).json()
    assert n["stations"][0]["station_code"] == "1" and n["rain_gauges"][0]["rain_24h_mm"] == 42.0
    cache.clear()
    t = client.get("/api/tide").json()
    assert t["available"] is False and t["stations"] == []


def test_impact_never_invents_a_level():
    state = {"trend": "rising", "rate_cm_per_h": 4.0, "distance_to_bank_m": 0.28, "trend_label_th": "สูงขึ้น"}
    rain6 = {"consensus": 12.0, "confidence": 0.8}
    out = assess(state, rain6, {"consensus": 30.0}, None, {"code": "bangkok"})
    assert out["outlook"] == "likely_rise" and "level" not in str(out["inputs"]).lower().replace("level_", "")
    none = assess(state, None, None, None, None)
    assert none["outlook"] == "insufficient_data" and none["label_th"].startswith("ข้อมูลยังไม่เพียงพอ")
    calm = assess({"trend": "falling", "distance_to_bank_m": 3.0, "trend_label_th": "ลดลง"},
                  {"consensus": 0.2, "confidence": 0.9}, {"consensus": 0.5}, 0.0, {"code": "x"})
    assert calm["outlook"] == "no_signal"
