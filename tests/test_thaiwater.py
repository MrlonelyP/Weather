"""ThaiWater collector. Payloads are synthetic, shaped after the public API."""
import httpx
from sqlalchemy import select

from app.collectors.thaiwater import ThaiWaterLevelCollector, ThaiWaterRainCollector
from app.models import WaterLevelObservation, WaterStation
from app.services.database import session_scope
from tests.conftest import mock_fetcher

WL = {"waterlevel_data": {"result": "OK", "data": [
    {"waterlevel_datetime": "2026-09-28 11:00", "waterlevel_msl": "1.83", "discharge": "12.50",
     "situation_level": 4,
     "station": {"id": 700100, "tele_station_name": {"th": "คลองเปรมประชากร"}, "tele_station_lat": 13.9,
                 "tele_station_long": 100.5, "min_bank": 1.29, "ground_level": 0.5, "critical_level_msl": 2.0,
                 "is_key_station": True, "tele_station_oldcode": "X01"},
     "basin": {"basin_name": {"th": "เจ้าพระยา"}},
     "geocode": {"province_code": "13", "province_name": {"th": "ปทุมธานี"}, "amphoe_name": {"th": "เมือง"}},
     "agency": {"agency_shortname": {"th": "สทนช."}}},
]}}
RAIN = {"result": "OK", "data": [
    {"rainfall_datetime": "2026-09-28 12:00", "rain_24h": 239, "rain_1h": 1.8,
     "station": {"id": 800200, "tele_station_name": {"th": "ปิล๊อก"}, "tele_station_lat": 14.6,
                 "tele_station_long": 98.3, "tele_station_oldcode": "R01"},
     "geocode": {"province_code": "71", "province_name": {"th": "กาญจนบุรี"}}},
]}


def test_waterlevel_creates_station_and_observation(settings):
    c = ThaiWaterLevelCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=WL)))
    out = c.run()
    assert out.status == "OK" and out.records == 1
    with session_scope() as s:
        st = s.execute(select(WaterStation)).scalar_one()
        assert st.station_kind == "river" and st.name_th == "คลองเปรมประชากร"
        assert st.bank_level_m == 1.29 and st.province_code == "13" and st.datum == "MSL"
        assert st.extra["agency"] == "สทนช."
        o = s.execute(select(WaterLevelObservation)).scalar_one()
        assert o.water_level_m == 1.83 and o.discharge_m3s == 12.5
    # idempotent
    assert ThaiWaterLevelCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=WL))).run().records == 1
    with session_scope() as s:
        assert s.execute(select(WaterStation)).scalars().all().__len__() == 1


def test_rain_gauge_stored_as_water_station(settings):
    c = ThaiWaterRainCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=RAIN)))
    out = c.run()
    assert out.status == "OK" and out.records == 1
    with session_scope() as s:
        st = s.execute(select(WaterStation)).scalar_one()
        assert st.station_kind == "rain_gauge"
        o = s.execute(select(WaterLevelObservation)).scalar_one()
        assert o.rain_mm == 239 and o.rain_period_hours == 24.0


def test_disabled_when_flag_off(settings):
    settings.thaiwater_rain_enabled = False
    assert ThaiWaterRainCollector(settings).run().status == "DISABLED"
