"""FastAPI entry point:  uvicorn app.main:app

Internal API for Phase 0 (no frontend). All timestamps: `<field>` in UTC,
`<field>_local` in Asia/Bangkok. Every record carries `source` and
`raw_payload_id` so it can be traced to the original response (GET /raw/{id}).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, water, weather
from app.config.logging import setup_logging
from app.config.settings import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    scheduler = None
    if settings.run_scheduler_in_api:
        from app.scheduler.jobs import create_background_scheduler

        scheduler = create_background_scheduler(settings)
        scheduler.start()
        log.info("scheduler started inside API process")
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Thailand Weather & Flood Intelligence - Phase 0 Data API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(health.router, tags=["health"])
app.include_router(weather.router, tags=["weather"])
app.include_router(water.router, tags=["water"])
