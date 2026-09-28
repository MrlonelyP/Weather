"""APScheduler setup.

* every collector job is scheduled independently (its own interval / cron)
* max_instances=1: a slow run of a job is never overlapped by the same job
* coalesce=True: missed runs (e.g. after downtime) collapse into one run
* jobs run in a thread pool, so one hung source does not delay the others
* collector.run() never raises - a failing source cannot stop the scheduler
* start times are staggered so sources are not all hit at the same second
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.collectors.base import BaseCollector
from app.collectors.openmeteo import OpenMeteoHistoricalCollector
from app.collectors.registry import build_collectors
from app.config.settings import Settings
from app.services import health
from app.services.database import session_scope
from app.services.locations import sync_locations
from app.services.normalizer import utcnow

log = logging.getLogger(__name__)


def register_health_rows(collectors: list[BaseCollector]) -> None:
    with session_scope() as session:
        sync_locations(session)
        for c in collectors:
            health.register_job(session, job=c.job, source=c.source, interval_minutes=c.interval_minutes,
                                schema_verified=c.schema_verified, inactive_status=c.configuration_status())


def _trigger(collector: BaseCollector, settings: Settings):
    if isinstance(collector, OpenMeteoHistoricalCollector):
        return CronTrigger(hour=settings.openmeteo_historical_hour_utc, minute=15, timezone="UTC")
    return IntervalTrigger(minutes=collector.interval_minutes, timezone="UTC")


def configure(scheduler, settings: Settings, collectors: list[BaseCollector] | None = None,
              run_immediately: bool = True) -> list[BaseCollector]:
    collectors = collectors if collectors is not None else build_collectors(settings)
    register_health_rows(collectors)
    now = utcnow()
    for index, collector in enumerate(collectors):
        if collector.configuration_status() == "DISABLED":
            log.info("job %s disabled - not scheduled", collector.job)
            continue
        first_run = now + timedelta(seconds=5 + index * 7) if run_immediately else None
        kwargs = {"next_run_time": first_run} if first_run else {}
        scheduler.add_job(
            collector.run,
            trigger=_trigger(collector, settings),
            id=collector.job,
            name=collector.job,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(60, collector.interval_minutes * 30),
            replace_existing=True,
            **kwargs,
        )
        log.info("scheduled %s every %s", collector.job,
                 "day" if isinstance(collector, OpenMeteoHistoricalCollector) else f"{collector.interval_minutes} min")
    if settings.features_snapshot_enabled:
        from app.services.water_features import run_hourly

        scheduler.add_job(run_hourly, trigger=CronTrigger(minute=settings.features_snapshot_minute, timezone="UTC"),
                          id="features.snapshot", name="features.snapshot", max_instances=1, coalesce=True,
                          misfire_grace_time=1800, replace_existing=True)
        log.info("scheduled features.snapshot hourly at minute %d", settings.features_snapshot_minute)
    return collectors


def _executors() -> dict:
    return {"default": ThreadPoolExecutor(max_workers=8)}


def create_background_scheduler(settings: Settings) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(executors=_executors(), timezone="UTC")
    configure(scheduler, settings)
    return scheduler


def create_blocking_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler(executors=_executors(), timezone="UTC")
    configure(scheduler, settings)
    return scheduler
