"""Source health monitor.

Stored status (written after every run) is combined with staleness at read time.

Statuses:
    OK                      last run succeeded
    DEGRADED                last run stored data but part of it failed (e.g. 2 of 3 models)
    ERROR                   last run failed (fewer than N consecutive failures)
    UNAVAILABLE             N or more consecutive failed runs
    REQUIRES_INVESTIGATION  source answered but the response could not be interpreted
                            (schema unknown/changed) - raw payload is kept for re-processing
    NO_API_KEY              job needs a key that is not configured in .env
    NOT_CONFIGURED          endpoint not known yet (must be set in .env)
    DISABLED                switched off in .env
    STALE                   last success older than expected interval x factor (read time)
    NEVER_RUN               registered but has not run yet
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import CollectorRun, DataSourceHealth
from app.services.normalizer import utcnow

log = logging.getLogger(__name__)

SUCCESS = {"OK", "DEGRADED"}
FAILURE = {"ERROR", "UNAVAILABLE"}
INACTIVE = {"NO_API_KEY", "NOT_CONFIGURED", "DISABLED"}


def register_job(session: Session, *, job: str, source: str, interval_minutes: int | None,
                 schema_verified: bool, inactive_status: str | None = None) -> None:
    """Make sure a health row exists; reflect configuration state (disabled / no key)."""
    values = dict(job=job, source=source, status=inactive_status or "NEVER_RUN",
                  expected_interval_minutes=interval_minutes, schema_verified=schema_verified,
                  consecutive_failures=0)
    stmt = insert(DataSourceHealth).values(**values)
    update = {"expected_interval_minutes": interval_minutes, "source": source}
    if inactive_status:
        update["status"] = inactive_status
    stmt = stmt.on_conflict_do_update(index_elements=[DataSourceHealth.job], set_=update)
    session.execute(stmt)


def record_run(
    session: Session,
    *,
    job: str,
    source: str,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    interval_minutes: int | None,
    schema_verified: bool,
    unavailable_after: int,
    latency_ms: int | None = None,
    status_code: int | None = None,
    error: str | None = None,
    records: int = 0,
    http_requests: int = 0,
    details: dict | None = None,
) -> str:
    """Persist the outcome of one run; returns the stored status."""
    health = session.get(DataSourceHealth, job, with_for_update=True)
    if health is None:
        health = DataSourceHealth(job=job, source=source, consecutive_failures=0)
        session.add(health)

    health.source = source
    health.expected_interval_minutes = interval_minutes
    health.schema_verified = schema_verified
    health.last_attempt_at = finished_at
    health.last_status_code = status_code
    health.details = details
    if latency_ms is not None:
        health.last_latency_ms = latency_ms

    if status in SUCCESS:
        health.last_success_at = finished_at
        health.consecutive_failures = 0
        health.records_last_run = records
        health.last_error = error  # DEGRADED keeps the partial error message
    elif status in FAILURE:
        health.consecutive_failures = (health.consecutive_failures or 0) + 1
        health.last_failure_at = finished_at
        health.last_error = error
        health.records_last_run = records
        if health.consecutive_failures >= unavailable_after:
            status = "UNAVAILABLE"
    else:  # REQUIRES_INVESTIGATION / inactive states
        health.last_error = error
        health.records_last_run = records
        if status == "REQUIRES_INVESTIGATION":
            health.last_failure_at = finished_at
    health.status = status

    session.add(CollectorRun(
        job=job, source=source, started_at=started_at, finished_at=finished_at, status=status,
        http_requests=http_requests, records_inserted=records, latency_ms=latency_ms,
        error=error, details=details,
    ))
    session.flush()
    return status


def effective_status(health: DataSourceHealth, stale_factor: float, now: datetime | None = None) -> str:
    now = now or utcnow()
    if (
        health.status in SUCCESS
        and health.last_success_at is not None
        and health.expected_interval_minutes
        and now - health.last_success_at > timedelta(minutes=health.expected_interval_minutes * stale_factor)
    ):
        return "STALE"
    return health.status


def all_health(session: Session) -> list[DataSourceHealth]:
    return list(session.execute(select(DataSourceHealth).order_by(DataSourceHealth.job)).scalars())


def aggregate_source_status(statuses: list[str]) -> str:
    """Roll job statuses up to one source-level status for the summary view."""
    if not statuses:
        return "NEVER_RUN"
    order = ["UNAVAILABLE", "ERROR", "REQUIRES_INVESTIGATION", "STALE", "DEGRADED",
             "NO_API_KEY", "NOT_CONFIGURED", "NEVER_RUN", "OK", "DISABLED"]
    active = [s for s in statuses if s != "DISABLED"] or statuses
    if all(s == "OK" for s in active):
        return "OK"
    for status in order:
        if status in active:
            return status if status != "OK" else "DEGRADED"
    return active[0]
