"""Free deployment helpers: dual level+rain stations, retention, run-due selection, URL handling.

Payloads are synthetic structures shaped after the ThaiWater public API.
"""
from __future__ import annotations

from datetime import timedelta

import httpx
from sqlalchemy import select

from app.collectors.thaiwater import ThaiWaterLevelCollector, ThaiWaterRainCollector
from app.config.settings import Settings
from app.models import DataSourceHealth, WaterLevelObservation, WaterStation
from app.services.database import session_scope
from app.services.maintenance import due_jobs, prune
from app.services.normalizer import utcnow
from app.services.rainfall import gauge_windows
from app.services.water_data import nearest_stations
from tests.conftest import mock_fetcher
from tests.test_api_v1 import _local


def _level(now, code=5):
    return {"waterlevel_data": {"data": [{
        "waterlevel_datetime": _local(now), "waterlevel_msl": "2.10",
        "station": {"id": code, "tele_station_name": {"th": "สถานีคู่"}, "tele_station_lat": 13.9,
                    "tele_station_long": 100.6, "min_bank": 3.0},
        "geocode": {"province_code": "10", "province_name": {"th": "กรุงเทพมหานคร"}}}]}}


def _rain(now, code=5):
    return {"data": [{"rainfall_datetime": _local(now), "rain_24h": 12.5, "rain_1h": 2.0,
                      "station": {"id": code, "tele_station_name": {"th": "สถานีคู่"}, "tele_station_lat": 13.9,
                                  "tele_station_long": 100.6},
                      "geocode": {"province_code": "10", "province_name": {"th": "กรุงเทพมหานคร"}}}]}


def test_station_reporting_level_and_rain_stays_a_river_station(settings):
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    ThaiWaterLevelCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=_level(now)))).run()
    ThaiWaterRainCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=_rain(now)))).run()
    with session_scope() as s:
        st = s.execute(select(WaterStation).where(WaterStation.station_code == "5")).scalar_one()
        assert st.station_kind == "river"  # the rain payload did not downgrade it
        assert st.extra["measures"] == ["rain", "water_level"]
        obs = s.execute(select(WaterLevelObservation).where(WaterLevelObservation.station_id == st.id)).scalar_one()
        assert obs.water_level_m == 2.10 and obs.rain_mm == 12.5  # one row, both values
        # rain queries include it even though it is a river station
        assert [p["value_mm"] for p in gauge_windows(s, "24h", now)["points"]] == [12.5]
        assert [x.station_code for x, _ in nearest_stations(s, 13.9, 100.6, 5, "rain_gauge")] == ["5"]
        assert [x.station_code for x, _ in nearest_stations(s, 13.9, 100.6, 5, "river")] == ["5"]


def test_prune_follows_retention_and_row_content(settings, monkeypatch):
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    ThaiWaterLevelCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=_level(now)))).run()
    with session_scope() as s:
        st = s.execute(select(WaterStation)).scalar_one()
        s.add_all([
            WaterLevelObservation(station_id=st.id, observed_at=now - timedelta(days=3), rain_mm=5.0, source="thaiwater"),
            WaterLevelObservation(station_id=st.id, observed_at=now - timedelta(days=3, hours=1), water_level_m=1.9,
                                  source="thaiwater"),
            WaterLevelObservation(station_id=st.id, observed_at=now - timedelta(days=10), water_level_m=1.5,
                                  source="thaiwater"),
        ])
        s.commit()
        assert prune(s, Settings(_env_file=None), now) == {}  # nothing configured -> nothing deleted
        res = prune(s, Settings(_env_file=None, retention_rain_gauge_days=2, retention_water_level_days=8), now)
        assert res["rain_only_rows"] == 1 and res["water_level_observation"] == 1
        left = s.execute(select(WaterLevelObservation.observed_at).order_by(WaterLevelObservation.observed_at)).scalars().all()
        assert left == [now - timedelta(days=3, hours=1), now]


def test_due_jobs_respects_intervals(settings):
    from app.collectors.registry import build_collectors

    now = utcnow()
    collectors = [c for c in build_collectors(settings) if c.job in ("thaiwater.waterlevel", "rid.dam")]
    with session_scope() as s:
        assert {c.job for c in due_jobs(s, collectors, now)} == {"thaiwater.waterlevel", "rid.dam"}  # never run
        s.add(DataSourceHealth(job="thaiwater.waterlevel", source="thaiwater", status="OK", last_attempt_at=now - timedelta(minutes=55)))
        s.add(DataSourceHealth(job="rid.dam", source="rid", status="OK", last_attempt_at=now - timedelta(minutes=55)))
        s.commit()
        # hourly job is due within the slack; the 3-hourly one is not
        assert [c.job for c in due_jobs(s, collectors, now)] == ["thaiwater.waterlevel"]


def test_cloud_database_url_is_normalised():
    assert Settings(_env_file=None, database_url="postgres://u:p@h:5432/db").database_url.startswith("postgresql+psycopg://")
    assert Settings(_env_file=None, retention_raw_payload_days="").retention_raw_payload_days is None
