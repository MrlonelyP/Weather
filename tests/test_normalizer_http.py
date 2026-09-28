from datetime import datetime, timezone

import httpx
import pytest

from app.collectors.http import FetchError, HttpFetcher
from app.services import normalizer as nz

pytestmark = pytest.mark.nodb


def test_to_float_handles_api_noise():
    assert nz.to_float("1,234.5") == 1234.5
    assert nz.to_float(" 12 ") == 12.0
    assert nz.to_float("-") is None
    assert nz.to_float("") is None
    assert nz.to_float(None) is None
    assert nz.to_float(float("nan")) is None
    assert nz.to_float({"Value": "27.4", "Unit": "celcius"}) == 27.4
    assert nz.to_float(True) is None


def test_unit_conversions():
    assert nz.temperature_c(32, "°F") == pytest.approx(0.0)
    assert nz.temperature_c(300, "K") == pytest.approx(26.85)
    assert nz.speed_kmh(10, "m/s") == pytest.approx(36.0)
    assert nz.speed_kmh(10, "kn") == pytest.approx(18.52)
    assert nz.rain_mm(1, "inch") == pytest.approx(25.4)
    assert nz.level_m(150, "cm") == pytest.approx(1.5)
    assert nz.volume_mcm(2_000_000, "m3") == pytest.approx(2.0)
    assert nz.mcm_per_day_to_m3s(8.64) == pytest.approx(100.0)
    assert nz.m3s_to_mcm_per_day(100) == pytest.approx(8.64)


def test_unknown_unit_is_never_guessed():
    with pytest.raises(nz.UnknownUnitError):
        nz.rain_mm(3, "bucket")
    assert nz.safe(nz.rain_mm, 3, "bucket") is None


def test_time_handling_utc_and_bangkok():
    local = nz.parse_datetime("2026-09-28 07:00:00", assume_tz=nz.BANGKOK, formats=("%Y-%m-%d %H:%M:%S",))
    assert local == datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)
    assert nz.parse_datetime("2026-09-28T00:00:00Z") == datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert nz.from_unix(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert nz.to_local(datetime(2026, 9, 28, tzinfo=timezone.utc)).hour == 7


def _fetcher(handler, sleeps):
    return HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)),
                       sleep=sleeps.append, max_retries=3, backoff_base_seconds=1.0, backoff_max_seconds=30)


def test_retry_with_exponential_backoff_then_success():
    calls, sleeps = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    result = _fetcher(handler, sleeps).get("https://example.test/x")
    assert result.response.status_code == 200
    assert result.attempts == 3
    assert len(sleeps) == 2
    assert 1.0 <= sleeps[0] <= 2.0 and 2.0 <= sleeps[1] <= 3.0  # base*2^(n-1) + jitter(0..base)


def test_retry_after_header_is_respected():
    calls, sleeps = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "7"}) if len(calls) == 1 else httpx.Response(200)

    _fetcher(handler, sleeps).get("https://example.test/x")
    assert sleeps == [7.0]


def test_client_errors_are_not_retried():
    calls, sleeps = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    result = _fetcher(handler, sleeps).get("https://example.test/x")
    assert result.response.status_code == 404 and len(calls) == 1 and sleeps == []


def test_network_errors_exhaust_retries():
    sleeps = []

    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(FetchError) as info:
        _fetcher(handler, sleeps).get("https://example.test/x")
    assert info.value.attempts == 4 and len(sleeps) == 3
