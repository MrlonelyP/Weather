"""Flow engine, catchments, station network, relevance, catchment rain and training rows.

Grids, basin polygons and river lines here are synthetic shapes built for the test.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import cache
from app.engines.flow import NOT_RELIABLE_TH, accumulate, analyze_flow, route
from app.main import app
from app.models import HydroBasin, HydroRiver, WaterForecastTraining, WaterLevelObservation, WaterStation
from app.services import catchment_rain, drainage, station_network
from app.services.database import session_scope
from app.services.relevance import relevant_station
from app.services.water_features import label_due, snapshot
from tests.test_api_v1 import _seed

D = 30.0
client = TestClient(app)


@pytest.mark.nodb
def test_plane_flows_downhill_with_confidence():
    _, cols = np.indices((101, 101))
    grid = (100 - 0.02 * cols * D).astype(np.float32)  # 20 m per km towards the east
    out = analyze_flow(grid, 50, 50, D, D, None, noise_m=1.5)
    assert out["reliable"] and out["flow_direction"] == "E" and out["confidence"] >= 0.5
    assert out["reached"]["type"] == "window_edge" and out["path_length_m"] > 1000
    assert out["kind"] == "terrain_derived_flow"


@pytest.mark.nodb
def test_flat_terrain_withholds_direction():
    rng = np.random.default_rng(3)
    grid = (2 + rng.uniform(-0.3, 0.3, (101, 101))).astype(np.float32)
    out = analyze_flow(grid, 50, 50, D, D, None, noise_m=1.5)
    assert out["reliable"] is False and out["flow_direction"] is None
    assert out["message_th"] == NOT_RELIABLE_TH


@pytest.mark.nodb
def test_waterway_is_an_outlet_and_pit_is_an_accumulation_zone():
    _, cols = np.indices((81, 81))
    grid = (50 - 0.03 * cols * D).astype(np.float32)
    labels = np.zeros(grid.shape, dtype=np.int32)
    labels[:, 60] = 7  # a mapped canal running north-south, east of the point
    out = analyze_flow(grid, 40, 40, D, D, labels, noise_m=1.0)
    assert out["reached"] == {"type": "waterway", "label": 7}
    assert out["path_length_m"] == pytest.approx(20 * D, abs=1)
    bowl = (5 + 10 * np.hypot(*(np.indices((81, 81)) - 40)) * D / 1000).astype(np.float32)
    pit = analyze_flow(bowl, 40, 30, D, D, None, noise_m=1.0)
    assert pit["accumulation_zone"] is not None and pit["accumulation_zone"]["max_depth_m"] > 1


@pytest.mark.nodb
def test_route_and_accumulate_cover_every_cell():
    _, cols = np.indices((10, 10))
    z = (10 - cols).astype(np.float32)
    filled, receiver, order = route(z, np.zeros(z.shape, dtype=bool))
    acc = accumulate(receiver, order).reshape(10, 10)
    assert acc.sum() >= 100 and np.allclose(filled, z)  # a plane has nothing to fill
    assert acc[5, 9] > acc[5, 1]  # more cells drain through the downhill edge


@pytest.mark.nodb
def test_catchment_rain_does_not_fill_units_without_gauges(monkeypatch):
    maps = {"at": 1e18, "gauge": {1: 10, 2: 10, 3: 20}, "area": {10: 100.0, 20: 300.0, 30: 600.0}, "points": {}}
    monkeypatch.setattr(catchment_rain, "_UNITS", maps)
    windows = {"1h": {1: {"value_mm": 2.0}, 2: {"value_mm": 4.0}, 3: {"value_mm": 10.0}},
               "3h": {}, "6h": {}, "24h": {1: {"value_mm": 20.0}}}
    out = catchment_rain.observed(None, {10, 20, 30}, windows)
    w = out["windows"]["1h"]
    assert w["gauges"] == 3 and w["gauge_max_mm"] == 10.0 and w["gauge_mean_mm"] == 5.3
    assert w["area_weighted_mm"] == pytest.approx((3.0 * 100 + 10.0 * 300) / 400, abs=0.06)  # 8.25 rounded
    assert w["coverage"] == 0.4  # unit 30 has no gauge and is not filled
    assert out["windows"]["3h"]["gauge_mean_mm"] is None


def _box(w, s, e, n):
    return f"SRID=4326;MULTIPOLYGON((({w} {s},{e} {s},{e} {n},{w} {n},{w} {s})))"


def _hydro(session):
    for lv in (5, 7):
        session.add(HydroBasin(hybas_id=lv * 1000, level=lv, next_down=0, sub_area_km2=500, up_area_km2=500,
                               geom=_box(100.4, 13.7, 100.7, 13.9), source_version="test"))
    session.add(HydroBasin(hybas_id=12001, level=12, next_down=0, sub_area_km2=100, up_area_km2=200,
                           geom=_box(100.45, 13.75, 100.55, 13.85), source_version="test"))
    session.add(HydroBasin(hybas_id=12002, level=12, next_down=12001, sub_area_km2=100, up_area_km2=100,
                           geom=_box(100.55, 13.75, 100.65, 13.85), source_version="test"))
    session.add(HydroRiver(hyriv_id=2, next_down=0, length_km=9, upland_km2=200, hybas_l12=12001,
                           geom="SRID=4326;MULTILINESTRING((100.46 13.8,100.55 13.8))", source_version="test"))
    session.add(HydroRiver(hyriv_id=1, next_down=2, length_km=9, upland_km2=100, hybas_l12=12002,
                           geom="SRID=4326;MULTILINESTRING((100.64 13.8,100.55 13.8))", source_version="test"))
    session.commit()


def test_station_network_relevance_rain_and_training(settings):
    now = _seed(settings)
    drainage.reset_caches()
    station_network._REACH_GRAPH.clear()
    catchment_rain.reset_cache()
    with session_scope() as s:
        _hydro(s)
        assert station_network.link_all(s) == {"distance_only": 1}
        st = s.execute(select(WaterStation).where(WaterStation.station_code == "1",
                                                  WaterStation.station_kind == "river")).scalar_one()
        catch = station_network.station_catchment(s, station_network.link_for(s, st.id))
        assert catch["method"] == "reach_network" and catch["units"] == {12001, 12002}

        # a point in the upstream unit drains to the station -> same_catchment (names unknown)
        dr = {"catchment": {"available": True, "local_catchment": {"hybas_id": 12002}}}
        cand = [{"station_id": st.id, "station_code": "1", "name": "สถานีทดสอบ", "river": None,
                 "distance_km": 12.0, "current_m": 3.72}]
        rel = relevant_station(s, dr, {"selected": None}, cand)
        assert rel["selection_method"] == "same_catchment" and rel["selected"]["station_code"] == "1"
        # same name on the chosen waterway and same catchment -> tier 1
        cand[0]["river"] = "คลองทดสอบ"
        rel = relevant_station(s, dr, {"selected": {"name": "คลองทดสอบ", "confidence": 0.5}}, cand)
        assert rel["selection_method"] == "same_waterway_and_catchment"
        # a point outside every catchment of the station -> only "nearby"
        rel = relevant_station(s, {"catchment": {"available": True, "local_catchment": {"hybas_id": 99}}},
                               {"selected": None}, cand)
        assert rel["selection_method"] == "nearby" and "ใกล้เคียง" in rel["reason_th"]
        assert relevant_station(s, dr, {"selected": None}, [])["selection_method"] == "none"

        obs = catchment_rain.observed(s, catch["units"], catchment_rain.observed_windows(s, now))
        assert obs["windows"]["24h"]["gauges"] == 1 and obs["windows"]["24h"]["gauge_max_mm"] == 42.0

        res = snapshot(s, now, with_forecast=False)
        assert res["rows"] == 5
        row = s.execute(select(WaterForecastTraining).where(WaterForecastTraining.horizon_hours == 1)).scalar_one()
        assert row.current_level_m == 3.72 and row.features["distance_to_bank_m"] == 0.28
        assert row.rain_features["catchment_rain_24h"]["gauge_max_mm"] == 42.0
        assert row.features["reservoir_release"] is None and row.source_versions["feature_version"]
        s.add(WaterLevelObservation(station_id=st.id, observed_at=now + timedelta(hours=1, minutes=10),
                                    water_level_m=3.80, source="thaiwater"))
        s.commit()
        assert label_due(s, now + timedelta(hours=2))["labelled"] == 1
        s.refresh(row)
        assert row.actual_water_level_m == 3.80 and row.actual_change_m == 0.08
        assert snapshot(s, now, with_forecast=False)["rows"] == 0  # idempotent

    cache.clear()
    d = client.get("/api/water/stations/1").json()
    assert d["network"]["catchment_method"] == "reach_network"
    assert d["network"]["relations_note"] and d["network"]["relations"] == {"upstream": [], "downstream": []}
