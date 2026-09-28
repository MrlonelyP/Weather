"""Jobs for deployments without a long-running scheduler (e.g. GitHub Actions on a free plan).

run_due()        one pass of "whatever is due": every collector whose last attempt is older than its
                 interval, the hourly feature snapshot + labelling, then retention.
prune()          delete rows older than the retention settings (nothing is deleted when unset).
export_training() write labelled training rows to gzip JSON lines before they are pruned.
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.models import DataSourceHealth, WaterForecastTraining
from app.services.normalizer import utcnow

log = logging.getLogger(__name__)
SLACK = timedelta(minutes=10)  # an hourly runner may start a few minutes early or late


def due_jobs(session: Session, collectors: list, now: datetime) -> list:
    last = {h.job: h.last_attempt_at for h in session.execute(select(DataSourceHealth)).scalars()}
    out = []
    for c in collectors:
        if c.configuration_status() == "DISABLED":
            continue
        t = last.get(c.job)
        if t is None or now - t >= timedelta(minutes=c.interval_minutes) - SLACK:
            out.append(c)
    return out


def run_due(settings: Settings | None = None, now: datetime | None = None) -> dict:
    from app.collectors.registry import build_collectors
    from app.scheduler.jobs import register_health_rows
    from app.services.database import session_scope
    from app.services.water_features import label_due, snapshot

    settings = settings or get_settings()
    now = now or utcnow()
    collectors = build_collectors(settings)
    register_health_rows(collectors)
    with session_scope() as session:
        due = due_jobs(session, collectors, now)
    report: dict = {"collectors": {}}
    for c in due:
        outcome = c.run()  # never raises
        report["collectors"][c.job] = outcome.status
    try:
        from app.services.station_network import link_missing

        with session_scope() as session:
            report["station_links"] = link_missing(session)
    except Exception as exc:  # noqa: BLE001
        log.exception("station linking failed")
        report["station_links"] = {"error": str(exc)[:300]}
    if settings.features_snapshot_enabled:
        try:
            with session_scope() as session:
                report["features"] = snapshot(session)
                report["labels"] = label_due(session)
        except Exception as exc:  # noqa: BLE001 - one failing step must not stop the others
            log.exception("feature snapshot failed")
            report["features"] = {"error": str(exc)[:300]}
    with session_scope() as session:
        report["pruned"] = prune(session, settings)
    return report


def _delete(session: Session, sql: str, days: int | None, now: datetime) -> int | None:
    if days is None:
        return None
    n = session.execute(text(sql), {"cutoff": now - timedelta(days=days)}).rowcount
    session.commit()
    return n


def prune(session: Session, settings: Settings | None = None, now: datetime | None = None) -> dict:
    s = settings or get_settings()
    now = now or utcnow()
    return {k: v for k, v in {
        # rows are judged by what they hold: a telemetry station can report both level and rain
        "rain_only_rows": _delete(session, """
            DELETE FROM water_level_observation WHERE water_level_m IS NULL AND observed_at < :cutoff""",
            s.retention_rain_gauge_days, now),
        "water_level_observation": _delete(session, """
            DELETE FROM water_level_observation WHERE observed_at < :cutoff""",
            s.retention_water_level_days, now),
        "forecast_run": _delete(session, "DELETE FROM forecast_run WHERE model_run_time < :cutoff",
                                s.retention_forecast_days, now),
        "weather_forecast_historical": _delete(session, """
            DELETE FROM weather_forecast WHERE forecast_run_id IS NULL AND forecast_time < :cutoff""",
            s.retention_forecast_days, now),
        "weather_observation": _delete(session, "DELETE FROM weather_observation WHERE observed_at < :cutoff",
                                       s.retention_observation_days, now),
        "reservoir_status": _delete(session, "DELETE FROM reservoir_status WHERE ingested_at < :cutoff",
                                    s.retention_observation_days, now),
        "collector_run": _delete(session, "DELETE FROM collector_run WHERE started_at < :cutoff",
                                 s.retention_log_days, now),
        "raw_payload": _delete(session, "DELETE FROM raw_payload WHERE fetched_at < :cutoff",
                               s.retention_raw_payload_days, now),
        "water_forecast_training": _delete(session, """
            DELETE FROM water_forecast_training WHERE prediction_time < :cutoff""",
            s.retention_training_days, now),
    }.items() if v is not None}


def export_training(session: Session, out: Path, before: datetime) -> int:
    """Write every training row with prediction_time before `before` to gzip JSON lines."""
    cutoff = before
    rows = session.execute(select(WaterForecastTraining).where(WaterForecastTraining.prediction_time < cutoff)
                           .order_by(WaterForecastTraining.prediction_time)).scalars()
    n = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for r in rows:
            rec = {c.name: getattr(r, c.name) for c in WaterForecastTraining.__table__.columns}
            f.write(json.dumps(rec, ensure_ascii=False, default=lambda o: o.isoformat()) + "\n")
            n += 1
    return n
