"""Data freshness: how new is each dataset, judged against per-source expectations.

Every block the API returns carries:
    source        which source
    source_time   time of the data itself (observation / model run / report date)
    fetched_at    when our collector last fetched it successfully
    age_minutes   now - source_time (or fetched_at for event/reference data)
    status        LIVE | DELAYED | STALE | OFFLINE | NO_API_KEY | DISABLED | NOT_CONFIGURED | NO_DATA
"""
from __future__ import annotations

import fnmatch
import json
from datetime import datetime, time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (DataSourceHealth, ForecastRun, OfficialWarning, ReservoirStatus, WaterLevelObservation,
                        WaterStation, WeatherObservation)
from app.services.normalizer import BANGKOK, ensure_utc, utcnow

FRESHNESS_FILE = Path(__file__).resolve().parent.parent / "config" / "freshness.json"
CONFIG_STATES = {"NO_API_KEY", "DISABLED", "NOT_CONFIGURED"}
STATUS_ORDER = ["OFFLINE", "STALE", "DELAYED", "NO_DATA", "NO_API_KEY", "NOT_CONFIGURED", "LIVE", "DISABLED"]


@lru_cache
def freshness_config() -> dict:
    return json.loads(FRESHNESS_FILE.read_text(encoding="utf-8"))


def job_rule(job: str) -> dict:
    for pattern, rule in freshness_config()["jobs"].items():
        if fnmatch.fnmatch(job, pattern):
            return rule
    return {"basis": "fetch", "live": 60, "delayed": 180, "expected": None}


def _data_time(session: Session, job: str) -> datetime | None:
    if job.startswith("openmeteo.forecast."):
        model = job.rsplit(".", 1)[1]
        return session.execute(select(func.max(ForecastRun.model_run_time))
                               .where(ForecastRun.model == model)).scalar_one()
    if job == "tmd.synoptic":
        return session.execute(select(func.max(WeatherObservation.observed_at))
                               .where(WeatherObservation.source == "tmd")).scalar_one()
    if job in ("thaiwater.waterlevel", "thaiwater.rain"):
        value = (WaterLevelObservation.water_level_m if job.endswith("waterlevel")
                 else WaterLevelObservation.rain_mm)
        return session.execute(
            select(func.max(WaterLevelObservation.observed_at))
            .join(WaterStation, WaterStation.id == WaterLevelObservation.station_id)
            .where(WaterStation.source == "thaiwater", value.isnot(None))).scalar_one()
    if job.startswith("rid."):
        d = session.execute(select(func.max(ReservoirStatus.observed_date))
                            .where(ReservoirStatus.source == "rid")).scalar_one()
        return None if d is None else datetime.combine(d, time(0, 0), tzinfo=BANGKOK)
    if job == "tmd.warning":
        return session.execute(select(func.max(OfficialWarning.issued_at))
                               .where(OfficialWarning.source == "tmd")).scalar_one()
    return None


def age_text(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    m = int(round(minutes))
    if m < 60:
        return f"{m} นาที"
    h, mm = divmod(m, 60)
    if h < 48:
        return f"{h} ชม. {mm} นาที" if mm else f"{h} ชม."
    return f"{h // 24} วัน"


def classify(health: DataSourceHealth | None, rule: dict, source_time: datetime | None,
             now: datetime, offline_after: int) -> tuple[str, float | None, str | None]:
    """Return (status, age_minutes, note)."""
    if health is not None and health.status in CONFIG_STATES:
        return health.status, None, None
    fetched = health.last_success_at if health else None
    basis_time = fetched if rule["basis"] == "fetch" else (source_time or None)
    age = None if basis_time is None else (now - ensure_utc(basis_time)).total_seconds() / 60
    note = None
    if health is not None and health.status == "RATE_LIMITED":
        note = "ต้นทางจำกัดจำนวนครั้งเรียก (rate limited)"
    elif health is not None and health.status == "REQUIRES_INVESTIGATION":
        note = "รูปแบบข้อมูลต้นทางต้องตรวจสอบ"
    if health is not None and (health.consecutive_failures or 0) >= offline_after:
        return "OFFLINE", age, note or (health.last_error or "")[:200]
    if age is None:
        return "NO_DATA", None, note
    if age < rule["live"]:
        return "LIVE", age, note
    if age < rule["delayed"]:
        return "DELAYED", age, note
    return "STALE", age, note


def job_freshness(session: Session, health: DataSourceHealth, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rule = job_rule(health.job)
    source_time = _data_time(session, health.job) if rule["basis"] != "fetch" else None
    status, age, note = classify(health, rule, source_time, now, freshness_config()["offline_after_failures"])
    return {
        "job": health.job, "source": health.source, "status": status, "basis": rule["basis"],
        "source_time": source_time, "fetched_at": health.last_success_at, "last_attempt_at": health.last_attempt_at,
        "age_minutes": None if age is None else round(age, 1), "age_text": age_text(age),
        "expected_update": rule.get("expected"), "live_under_min": rule["live"], "delayed_under_min": rule["delayed"],
        "note": note, "collector_status": health.status, "primary": bool(rule.get("primary")),
    }


def worst(statuses: list[str]) -> str:
    active = [s for s in statuses if s != "DISABLED"]
    if not active:
        return "DISABLED"
    return min(active, key=lambda s: STATUS_ORDER.index(s) if s in STATUS_ORDER else 0)


def sources_freshness(session: Session, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    cfg = freshness_config()
    rows = list(session.execute(select(DataSourceHealth).order_by(DataSourceHealth.job)).scalars())
    by_source: dict[str, list[dict]] = {}
    for h in rows:
        by_source.setdefault(h.source, []).append(job_freshness(session, h, now))
    out = []
    for key, meta in cfg["sources"].items():
        jobs = by_source.pop(key, [])
        if meta.get("not_connected"):
            out.append({"source": key, "label": meta["label"], "status": "NOT_CONNECTED", "jobs": [],
                        "source_time": None, "fetched_at": None, "age_minutes": None, "age_text": None})
            continue
        active = [j for j in jobs if j["status"] != "DISABLED"]
        primary = [j for j in active if j["primary"]] or active
        dated = [j for j in primary if j["age_minutes"] is not None]
        oldest = max(dated, key=lambda j: j["age_minutes"], default=None)
        out.append({
            "source": key, "label": meta["label"],
            "status": worst([j["status"] for j in jobs]) if jobs else "NO_DATA",
            "source_time": oldest["source_time"] if oldest else None,
            "fetched_at": max((j["fetched_at"] for j in primary if j["fetched_at"]), default=None),
            "age_minutes": oldest["age_minutes"] if oldest else None,
            "age_text": oldest["age_text"] if oldest else None,
            "age_basis": "ข้อมูลหลักที่เก่าที่สุดของแหล่งนี้",
            "jobs": jobs,
        })
    for key, jobs in by_source.items():  # sources not in the label list
        out.append({"source": key, "label": key, "status": worst([j["status"] for j in jobs]), "jobs": jobs,
                    "source_time": None, "fetched_at": None, "age_minutes": None, "age_text": None})
    return out


def block_freshness(session: Session, job: str, now: datetime | None = None) -> dict | None:
    """Freshness of one job, to attach to an API data block."""
    h = session.get(DataSourceHealth, job)
    if h is None:
        return None
    return job_freshness(session, h, now)
