"""Isolation, health status, raw archive de-duplication and the unverified-source parsers.

Payloads are synthetic test inputs, not real source data.
"""
import json

import httpx
from sqlalchemy import func, select

from app.collectors.base import BaseCollector, CollectResult
from app.collectors.gistda import GistdaFloodPointCollector, GistdaFloodPolygonCollector, interpret_point_check
from app.collectors.rid import RidDamCollector
from app.collectors.tmd import TmdSynopticCollector, TmdWarningCollector
from app.models import (CollectorRun, DataSourceHealth, FloodExtent, OfficialWarning, RawPayload, Reservoir,
                        ReservoirStatus, WeatherObservation)
from app.services.database import session_scope
from tests.conftest import mock_fetcher


class Boom(BaseCollector):
    source, job = "test", "test.boom"
    interval_minutes = 10

    def collect(self):
        raise ValueError("unexpected bug")

    def normalize(self, session, raw, text):
        return 0


class Fine(BaseCollector):
    source, job = "test", "test.fine"
    interval_minutes = 10

    def collect(self):
        return CollectResult(records=5)

    def normalize(self, session, raw, text):
        return 0


def test_one_failing_collector_does_not_stop_others(settings):
    outcomes = [c.run() for c in (Boom(settings), Fine(settings))]
    assert [o.status for o in outcomes] == ["ERROR", "OK"]
    with session_scope() as s:
        assert s.get(DataSourceHealth, "test.fine").last_success_at is not None
        assert "unexpected bug" in s.get(DataSourceHealth, "test.boom").last_error


def test_unavailable_after_consecutive_failures(settings):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    statuses = [RidDamCollector(settings, mock_fetcher(down)).run().status for _ in range(3)]
    assert statuses == ["ERROR", "ERROR", "UNAVAILABLE"]
    with session_scope() as s:
        h = s.get(DataSourceHealth, "rid.dam")
        assert h.consecutive_failures == 3 and h.last_success_at is None
        assert s.execute(select(func.count(CollectorRun.id))).scalar_one() == 3


def test_gistda_without_key_reports_no_api_key(settings):
    called = []
    outcome = GistdaFloodPointCollector(settings, mock_fetcher(lambda r: called.append(r))).run()
    assert outcome.status == "NO_API_KEY" and not called


def test_gistda_polygon_without_endpoint_is_not_configured(settings):
    settings.gistda_api_key = "k"
    assert GistdaFloodPolygonCollector(settings).run().status == "NOT_CONFIGURED"


def test_api_key_is_sent_but_never_archived(settings):
    settings.gistda_api_key = "secret-key-123"
    seen = []

    def handler(request):
        seen.append(request.headers.get("API-Key"))
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    outcome = GistdaFloodPointCollector(settings, mock_fetcher(handler)).run()
    assert outcome.status == "OK" and seen and all(k == "secret-key-123" for k in seen)
    with session_scope() as s:
        for raw in s.execute(select(RawPayload)).scalars():
            assert "secret-key-123" not in json.dumps([raw.endpoint, raw.request_params, raw.context])


def test_gistda_polygons_stored_with_geometry(settings):
    settings.gistda_api_key = "k"
    settings.gistda_flood_polygon_url = "https://example.test/flood"
    fc = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": "f1", "properties": {"date": "2026-09-27T06:00:00Z"},
        "geometry": {"type": "Polygon", "coordinates": [[[100.5, 13.7], [100.51, 13.7], [100.51, 13.71],
                                                         [100.5, 13.71], [100.5, 13.7]]]}}]}
    outcome = GistdaFloodPolygonCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=fc))).run()
    assert outcome.status == "OK" and outcome.records == 1
    with session_scope() as s:
        f = s.execute(select(FloodExtent)).scalar_one()
        assert f.source_feature_id == "f1" and 1.0 < f.area_sqkm < 1.5 and f.observed_at is not None


def test_point_check_interpretation():
    assert interpret_point_check({"type": "FeatureCollection", "features": [{}]}) is True
    assert interpret_point_check({"data": {"is_flood": False}}) is False
    assert interpret_point_check({"message": "ok"}) is None


def test_identical_payload_archived_once(settings):
    body = {"data": []}

    def handler(request):
        return httpx.Response(200, json=body)

    c = RidDamCollector(settings, mock_fetcher(handler))
    c.run()
    c.run()
    with session_scope() as s:
        raws = s.execute(select(RawPayload).order_by(RawPayload.id)).scalars().all()
        # 2 days per run -> 4 fetches; bodies only stored for the first fetch of each URL
        assert len(raws) == 4
        assert sum(1 for r in raws if r.payload is not None) == 2
        assert all(r.same_as_id for r in raws if r.payload is None)


RID_DOC = {"status": "ok", "data": [{"region": "ภาคเหนือ", "dam": [
    {"id": "100101", "name": "เขื่อนตัวอย่าง", "capacity": 1000.0, "volume": 800.0, "percent_storage": 80.0,
     "usable_volume": 700.0, "inflow": 8.64, "outflow": 4.32}]}]}


def test_rid_parser_and_revision_upsert(settings):
    c = RidDamCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=RID_DOC)))
    outcome = c.run()
    assert outcome.status == "OK"
    with session_scope() as s:
        res = s.execute(select(Reservoir)).scalar_one()
        assert res.reservoir_code == "100101" and res.region == "ภาคเหนือ" and res.capacity_mcm == 1000.0
        st = s.execute(select(ReservoirStatus).order_by(ReservoirStatus.observed_date)).scalars().all()
        assert len(st) == 2  # today + yesterday requested
        assert st[0].storage_pct == 80.0 and st[0].inflow_m3s == 100.0 and st[0].outflow_mcm_day == 4.32


def test_rid_implausible_units_require_investigation(settings):
    doc = {"data": [{"id": "1", "name": "x", "volume": 800_000_000}]}
    outcome = RidDamCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=doc))).run()
    assert outcome.status == "REQUIRES_INVESTIGATION" and outcome.records == 0


def test_unknown_payload_shape_requires_investigation(settings):
    doc = {"unexpected": {"structure": [1, 2, 3]}}
    outcome = RidDamCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=doc))).run()
    assert outcome.status == "REQUIRES_INVESTIGATION"
    with session_scope() as s:
        assert all(r.parse_status in ("failed", "duplicate") for r in s.execute(select(RawPayload)).scalars())


def test_tmd_synoptic_bulletin_to_observations(settings):
    from app.services.normalizer import utcnow

    day = utcnow().day
    doc = {"data": [{"header": "SMTH01 VTBB", "message": f"AAXX {day:02d}001 48455 11560 72304 10275 60031="}]}

    def handler(request):
        return httpx.Response(200, json=doc)

    settings.tmd_synoptic_lookback_hours = 3  # always covers >= 1 synoptic slot
    outcome = TmdSynopticCollector(settings, mock_fetcher(handler)).run()
    assert outcome.status == "OK"
    with session_scope() as s:
        obs = s.execute(select(WeatherObservation)).scalars().all()
        assert len(obs) == 1 and obs[0].rain_mm == 3.0 and obs[0].report_text.startswith("48455")


def test_tmd_warning_requires_wmo_heading(settings):
    doc = {"data": [
        {"header": "WSTH31 VTBB 280300", "text": "VTBB SIGMET 1 VALID 280300/280700 VTBB- EMBD TS OBS"},
        {"message": "Request processed successfully, no additional info"},
    ]}
    outcome = TmdWarningCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=doc))).run()
    assert outcome.status == "OK"
    with session_scope() as s:
        w = s.execute(select(OfficialWarning)).scalars().all()
        assert len(w) == 1 and w[0].warning_type == "sigmet" and w[0].issued_at.hour == 3


def test_rid_group_summary_does_not_hide_nested_dams(settings):
    doc = {"data": [{"id": "N", "name": "ภาคเหนือ", "percent_storage": 70.0, "dam": [
        {"id": "100101", "name": "A", "volume": 10.0}, {"id": "100102", "name": "B", "volume": 20.0}]}]}
    outcome = RidDamCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=doc))).run()
    assert outcome.status == "OK"
    with session_scope() as s:
        codes = sorted(r.reservoir_code for r in s.execute(select(Reservoir)).scalars())
        regions = {r.region for r in s.execute(select(Reservoir)).scalars()}
        assert codes == ["100101", "100102"] and regions == {"ภาคเหนือ"}


def test_rid_real_shape_volume_is_current_water_not_storage(settings):
    # RID reports "storage" == capacity (normal high water) and "volume" == current water.
    # Regression: the current-water column must come from "volume", not "storage".
    doc = {"data": [{"id": "200101", "name": "เขื่อนภูมิพล", "capacity": 13462, "storage": 13462,
                     "active_storage": 9662, "dead_storage": 3800, "volume": 8470.24,
                     "percent_storage": 62.92, "inflow": 36.16, "outflow": 3}]}
    outcome = RidDamCollector(settings, mock_fetcher(lambda r: httpx.Response(200, json=doc))).run()
    assert outcome.status == "OK"
    with session_scope() as s:
        st = s.execute(select(ReservoirStatus).limit(1)).scalar_one()
        assert st.capacity_mcm == 13462
        assert st.storage_mcm == 8470.24            # current water, from "volume"
        assert st.usable_storage_mcm == 9662        # from "active_storage"
        assert st.storage_pct == 62.92
