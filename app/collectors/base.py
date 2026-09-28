"""Base class shared by every collector.

Each collector job:
  * fetches with timeout / retry / exponential backoff   (HttpFetcher)
  * archives every response as raw_payload (own transaction, committed first)
  * normalizes the payload into the canonical tables     (`normalize`)
  * records a collector_run row and updates data_source_health
  * never raises out of `run()` - one failing source cannot stop another
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.collectors.http import FetchError, HttpFetcher
from app.config.settings import Settings
from app.models import RawPayload
from app.services import health, storage
from app.services.database import session_scope
from app.services.normalizer import utcnow

log = logging.getLogger(__name__)


class SourceNotConfigured(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status  # NO_API_KEY | NOT_CONFIGURED | DISABLED


class SchemaMismatch(Exception):
    """The source answered but the payload does not have the structure we expect."""


class AllRequestsFailed(Exception):
    """Every request of a multi-request run failed (each failure already archived/logged)."""


class HttpStatusError(Exception):
    def __init__(self, status_code: int, url: str, raw_payload_id: int | None):
        super().__init__(f"HTTP {status_code} from {url} (raw_payload_id={raw_payload_id})")
        self.status_code = status_code
        self.raw_payload_id = raw_payload_id


@dataclass
class Fetched:
    raw_payload_id: int
    status_code: int
    text: str
    fetched_at: datetime
    latency_ms: int
    is_duplicate: bool
    url: str


@dataclass
class CollectResult:
    records: int = 0
    partial_errors: list[str] = field(default_factory=list)
    parse_failures: int = 0
    details: dict = field(default_factory=dict)


@dataclass
class RunOutcome:
    job: str
    status: str
    records: int
    error: str | None
    latency_ms: int | None


class BaseCollector(ABC):
    source: str = ""
    job: str = ""
    # Has the parser been validated against a real captured payload?
    schema_verified: bool = False
    # keys whose values must never be written to the database/logs
    secret_params: tuple[str, ...] = ()
    # raw_payload.dataset values this collector can (re-)normalize
    dataset_prefixes: tuple[str, ...] = ()

    def handles_dataset(self, dataset: str) -> bool:
        return any(dataset == p or dataset.startswith(p + ".") for p in self.dataset_prefixes)

    def __init__(self, settings: Settings, fetcher: HttpFetcher | None = None):
        self.settings = settings
        self.fetcher = fetcher or HttpFetcher.from_settings(settings)
        self._requests = 0
        self._latencies: list[int] = []
        self._last_status_code: int | None = None

    # ----------------------------------------------------------------- config
    @property
    @abstractmethod
    def interval_minutes(self) -> int: ...

    def configuration_status(self) -> str | None:
        """Return DISABLED / NO_API_KEY / NOT_CONFIGURED, or None when runnable."""
        return None

    # ----------------------------------------------------------------- work
    @abstractmethod
    def collect(self) -> CollectResult: ...

    @abstractmethod
    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        """Parse one archived payload into canonical tables. Must be idempotent.

        Used both right after fetching and by `app.cli reprocess`.
        Raise SchemaMismatch when the payload is not understood.
        """

    # ----------------------------------------------------------------- helpers
    def fetch(
        self,
        dataset: str,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        context: dict | None = None,
    ) -> Fetched:
        """GET + archive. Raises FetchError (no response) or HttpStatusError (non-2xx, archived)."""
        fetched_at = utcnow()
        self._requests += 1
        result = self.fetcher.get(url, params=params, headers=headers)
        response = result.response
        self._latencies.append(result.latency_ms)
        self._last_status_code = response.status_code
        with session_scope() as session:
            raw = storage.save_raw(
                session,
                source=self.source,
                dataset=dataset,
                url=url,
                params=params,
                fetched_at=fetched_at,
                status_code=response.status_code,
                body=response.text,
                content_type=response.headers.get("content-type"),
                latency_ms=result.latency_ms,
                context=context,
                secret_keys=self.secret_params,
            )
            raw_id, duplicate = raw.id, raw.same_as_id is not None
        log.info("%s %s -> HTTP %d in %d ms (raw_payload_id=%d%s)", self.job, dataset,
                 response.status_code, result.latency_ms, raw_id, ", unchanged" if duplicate else "")
        if not response.is_success:
            raise HttpStatusError(response.status_code, url, raw_id)
        return Fetched(raw_id, response.status_code, response.text, fetched_at,
                       result.latency_ms, duplicate, url)

    def normalize_fetched(self, fetched: Fetched, force: bool = False) -> int:
        """Normalize a just-fetched payload in its own transaction; bookkeeping on raw row.

        Unchanged payloads (same checksum as the previous fetch) are skipped
        unless `force` - their content was already normalized.
        """
        if fetched.is_duplicate and not force:
            return 0
        return normalize_raw(self, fetched.raw_payload_id, fetched.text)

    # ----------------------------------------------------------------- lifecycle
    def run(self) -> RunOutcome:
        started = utcnow()
        t0 = time.perf_counter()
        self._requests, self._latencies, self._last_status_code = 0, [], None
        status, error, result = "OK", None, CollectResult()

        inactive = self.configuration_status()
        if inactive:
            status, error = inactive, _inactive_message(inactive, self)
            log.info("%s skipped: %s", self.job, error)
        else:
            try:
                result = self.collect()
                if result.records == 0 and result.parse_failures:
                    status = "REQUIRES_INVESTIGATION"
                    error = "; ".join(result.partial_errors) or "payload not understood"
                elif result.partial_errors:
                    status = "DEGRADED"
                    error = "; ".join(result.partial_errors)[:4000]
            except SchemaMismatch as exc:
                status, error = "REQUIRES_INVESTIGATION", str(exc)
                log.warning("%s: schema mismatch: %s", self.job, exc)
            except (FetchError, HttpStatusError, AllRequestsFailed) as exc:
                status, error = "ERROR", str(exc)
                log.error("%s: fetch failed: %s", self.job, exc)
            except Exception as exc:  # noqa: BLE001 - isolation boundary
                status, error = "ERROR", f"{type(exc).__name__}: {exc}"
                log.exception("%s: unexpected error", self.job)

        finished = utcnow()
        latency = int(sum(self._latencies) / len(self._latencies)) if self._latencies else None
        try:
            with session_scope() as session:
                status = health.record_run(
                    session,
                    job=self.job,
                    source=self.source,
                    status=status,
                    started_at=started,
                    finished_at=finished,
                    interval_minutes=self.interval_minutes,
                    schema_verified=self.schema_verified,
                    unavailable_after=self.settings.health_unavailable_after_failures,
                    latency_ms=latency,
                    status_code=self._last_status_code,
                    error=error,
                    records=result.records,
                    http_requests=self._requests,
                    details=result.details or None,
                )
        except Exception:  # noqa: BLE001 - health bookkeeping must not crash the scheduler
            log.exception("%s: could not record health", self.job)
        log.info("%s finished: %s, %d records, %d requests, %.1fs", self.job, status,
                 result.records, self._requests, time.perf_counter() - t0)
        return RunOutcome(self.job, status, result.records, error, latency)


def normalize_raw(collector: BaseCollector, raw_payload_id: int, text: str) -> int:
    """Run collector.normalize for one raw row and record the parse outcome on it."""
    try:
        with session_scope() as session:
            raw = session.get(RawPayload, raw_payload_id)
            count = collector.normalize(session, raw, text)
            raw.parse_status, raw.parse_error, raw.records_parsed = "parsed", None, count
            return count
    except SchemaMismatch as exc:
        with session_scope() as session:
            raw = session.get(RawPayload, raw_payload_id)
            raw.parse_status, raw.parse_error, raw.records_parsed = "failed", str(exc)[:4000], 0
        raise
    except Exception as exc:
        with session_scope() as session:
            raw = session.get(RawPayload, raw_payload_id)
            raw.parse_status, raw.parse_error = "failed", f"{type(exc).__name__}: {exc}"[:4000]
        raise


def _inactive_message(status: str, collector: BaseCollector) -> str:
    return {
        "DISABLED": f"{collector.job} disabled in .env",
        "NO_API_KEY": f"{collector.job} requires an API key (not set in .env)",
        "NOT_CONFIGURED": f"{collector.job} endpoint not configured in .env",
    }.get(status, status)
