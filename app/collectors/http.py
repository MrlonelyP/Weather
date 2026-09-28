"""HTTP GET with timeout, retry and exponential backoff (+ jitter).

Retries on network errors / timeouts and on transient HTTP statuses
(408, 425, 429, 5xx gateway errors). `Retry-After` is honoured (capped).
Other 4xx responses are returned immediately - retrying will not help.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(Exception):
    """All attempts failed without any HTTP response (DNS, connect, timeout...)."""

    def __init__(self, url: str, attempts: int, cause: Exception):
        super().__init__(f"{type(cause).__name__} after {attempts} attempt(s): {cause} [{url}]")
        self.url = url
        self.attempts = attempts
        self.cause = cause


@dataclass
class HttpResult:
    response: httpx.Response
    latency_ms: int
    attempts: int


class HttpFetcher:
    def __init__(
        self,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 2.0,
        backoff_max_seconds: float = 60.0,
        user_agent: str = "ThailandWeatherFloodIntel-Phase0/0.1",
        sleep: Callable[[float], None] = time.sleep,
        client: httpx.Client | None = None,
    ):
        self.max_retries = max_retries
        self.backoff_base = backoff_base_seconds
        self.backoff_max = backoff_max_seconds
        self._sleep = sleep
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json, text/plain, */*"},
        )

    @classmethod
    def from_settings(cls, settings) -> HttpFetcher:
        return cls(
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            backoff_base_seconds=settings.http_backoff_base_seconds,
            backoff_max_seconds=settings.http_backoff_max_seconds,
            user_agent=settings.http_user_agent,
        )

    def backoff_delay(self, attempt: int) -> float:
        """Exponential backoff for retry number `attempt` (1-based) with jitter."""
        delay = self.backoff_base * (2 ** (attempt - 1))
        delay += random.uniform(0, self.backoff_base)
        return min(delay, self.backoff_max)

    def _retry_after(self, response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return min(max(float(value), 0.0), self.backoff_max)
        except ValueError:
            return None

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> HttpResult:
        attempt = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                response = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:  # includes timeouts and connect errors
                if attempt > self.max_retries:
                    raise FetchError(url, attempt, exc) from exc
                delay = self.backoff_delay(attempt)
                log.warning("GET %s failed (%s: %s); retry %d/%d in %.1fs",
                            url, type(exc).__name__, exc, attempt, self.max_retries, delay)
                self._sleep(delay)
                continue
            latency_ms = int((time.perf_counter() - started) * 1000)
            retry_after = self._retry_after(response)
            # 429 without Retry-After is usually a daily quota ("try again tomorrow"):
            # retrying only burns more quota, so hand it back immediately.
            quota_exhausted = response.status_code == 429 and retry_after is None
            if response.status_code in RETRY_STATUS and attempt <= self.max_retries and not quota_exhausted:
                delay = retry_after or self.backoff_delay(attempt)
                log.warning("GET %s -> HTTP %d; retry %d/%d in %.1fs",
                            url, response.status_code, attempt, self.max_retries, delay)
                self._sleep(delay)
                continue
            return HttpResult(response=response, latency_ms=latency_ms, attempts=attempt)

    def close(self) -> None:
        self._client.close()
