"""Builds the list of collector jobs from settings."""
from __future__ import annotations

from app.collectors.base import BaseCollector
from app.collectors.gistda import GistdaFloodPointCollector, GistdaFloodPolygonCollector
from app.collectors.http import HttpFetcher
from app.collectors.openmeteo import OpenMeteoForecastCollector, OpenMeteoHistoricalCollector
from app.collectors.rid import RidDamCollector, RidMediumReservoirCollector
from app.collectors.tmd import TmdMetarCollector, TmdSynopticCollector, TmdWarningCollector
from app.config.settings import Settings


def build_collectors(settings: Settings) -> list[BaseCollector]:
    """One instance per job. Each job gets its own HTTP client so a hung
    connection pool of one source cannot block another."""

    def fetcher() -> HttpFetcher:
        return HttpFetcher.from_settings(settings)

    collectors: list[BaseCollector] = [
        OpenMeteoForecastCollector(settings, model, fetcher()) for model in settings.openmeteo_models
    ]
    collectors += [
        OpenMeteoHistoricalCollector(settings, fetcher()),
        TmdSynopticCollector(settings, fetcher()),
        TmdWarningCollector(settings, fetcher()),
        TmdMetarCollector(settings, fetcher()),
        RidDamCollector(settings, fetcher()),
        RidMediumReservoirCollector(settings, fetcher()),
        GistdaFloodPointCollector(settings, fetcher()),
        GistdaFloodPolygonCollector(settings, fetcher()),
    ]
    return collectors


def get_collector(settings: Settings, job: str) -> BaseCollector:
    for collector in build_collectors(settings):
        if collector.job == job:
            return collector
    raise KeyError(f"unknown job {job!r}; known: {[c.job for c in build_collectors(settings)]}")
