from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.timefmt import times
from app.config.settings import get_settings
from app.models import CollectorRun, DataSourceHealth, RawPayload
from app.services import health as health_service
from app.services.database import get_db
from app.services.storage import raw_body

router = APIRouter()

CATALOG_FILE = Path(__file__).resolve().parents[2] / "config" / "source_catalog.json"


def _catalog() -> list[dict]:
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))["sources"]


def _job_view(h: DataSourceHealth, stale_factor: float) -> dict:
    return {
        "job": h.job,
        "source": h.source,
        "status": health_service.effective_status(h, stale_factor),
        "stored_status": h.status,
        "schema_verified": h.schema_verified,
        **times(last_success=h.last_success_at, last_attempt=h.last_attempt_at, last_failure=h.last_failure_at),
        "latency_ms": h.last_latency_ms,
        "last_status_code": h.last_status_code,
        "consecutive_failures": h.consecutive_failures,
        "records_last_run": h.records_last_run,
        "expected_interval_minutes": h.expected_interval_minutes,
        "last_error": h.last_error,
        "details": h.details,
    }


@router.get("/health")
def get_health(db: Session = Depends(get_db)):
    """Service + database status and a one-line status per source."""
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "OK"
    except Exception as exc:  # pragma: no cover - reported, not raised
        return {"status": "ERROR", "database": f"ERROR: {exc}", "sources": []}

    jobs = [_job_view(h, settings.health_stale_factor) for h in health_service.all_health(db)]
    by_source: dict[str, list[dict]] = {}
    for job in jobs:
        by_source.setdefault(job["source"], []).append(job)
    sources = []
    for source, items in sorted(by_source.items()):
        successes = [j for j in items if j["last_success"]]
        latest = max(successes, key=lambda j: j["last_success"]) if successes else None
        latencies = [j["latency_ms"] for j in items if j["latency_ms"] is not None]
        sources.append({
            "source": source,
            "status": health_service.aggregate_source_status([j["status"] for j in items]),
            "last_success": latest["last_success"] if latest else None,
            "last_success_local": latest["last_success_local"] if latest else None,
            "latency_ms": int(sum(latencies) / len(latencies)) if latencies else None,
            "jobs": {j["job"]: j["status"] for j in items},
        })
    return {"status": "OK", "database": database, "sources": sources}


@router.get("/sources")
def get_sources(db: Session = Depends(get_db)):
    """All 18 planned sources (Data Sources sheet) with the live health of their collector jobs."""
    settings = get_settings()
    health_rows = {h.job: h for h in health_service.all_health(db)}
    catalog = []
    for entry in _catalog():
        jobs = [_job_view(health_rows[j], settings.health_stale_factor) for j in entry["jobs"] if j in health_rows]
        if not entry["jobs"]:
            status = "NOT_IMPLEMENTED"  # planned; endpoint discovery pending (see plan_status)
        else:
            status = health_service.aggregate_source_status([j["status"] for j in jobs]) if jobs else "NEVER_RUN"
        catalog.append({
            "id": entry["id"],
            "name": entry["name"],
            "group": entry["group"],
            "priority": entry["priority"],
            "plan_status": entry["plan_status"],
            "auth": entry["auth"],
            "endpoint": entry["endpoint"],
            "doc_url": entry["doc_url"],
            "status": status,
            "jobs": jobs,
        })
    return {"sources": catalog}


@router.get("/sources/{job}/runs")
def get_job_runs(job: str, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    runs = db.execute(
        select(CollectorRun).where(CollectorRun.job == job).order_by(CollectorRun.started_at.desc()).limit(limit)
    ).scalars()
    return {"job": job, "runs": [{
        "id": r.id, "status": r.status, **times(started_at=r.started_at, finished_at=r.finished_at),
        "http_requests": r.http_requests, "records_inserted": r.records_inserted,
        "latency_ms": r.latency_ms, "error": r.error, "details": r.details,
    } for r in runs]}


@router.get("/raw/{raw_id}")
def get_raw(raw_id: int, include_payload: bool = False, db: Session = Depends(get_db)):
    """Trace any normalized record back to the exact response it came from."""
    raw = db.get(RawPayload, raw_id)
    if raw is None:
        raise HTTPException(404, "raw payload not found")
    out = {
        "id": raw.id, "source": raw.source, "dataset": raw.dataset, "endpoint": raw.endpoint,
        **times(fetched_at=raw.fetched_at), "status_code": raw.status_code,
        "content_type": raw.content_type, "latency_ms": raw.latency_ms, "size_bytes": raw.size_bytes,
        "checksum": raw.checksum, "same_as_id": raw.same_as_id, "context": raw.context,
        "parse_status": raw.parse_status, "parse_error": raw.parse_error, "records_parsed": raw.records_parsed,
    }
    if include_payload:
        out["payload"] = raw_body(db, raw)
    return out
