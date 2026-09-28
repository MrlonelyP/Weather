"""Test setup.

Tests run against a separate PostgreSQL + PostGIS database (TEST_DATABASE_URL,
default postgresql+psycopg://flood:flood@localhost:5432/flood_intel_test).

IMPORTANT: payloads used in tests are synthetic structures shaped after the
public API documentation. They exist only to test parsing/storage logic and
are never written to the real database.
"""
from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy import text

from app.collectors.http import HttpFetcher
from app.config.settings import Settings, get_settings
from app.models import Base
from app.services import database

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://flood:flood@localhost:5432/flood_intel_test")


@pytest.fixture(scope="session")
def engine():
    eng = database.configure_engine(TEST_DB)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture(autouse=True)
def clean_db(request, engine):
    if "nodb" in request.keywords:
        yield
        return
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(_env_file=None, database_url=TEST_DB, http_max_retries=2, http_backoff_base_seconds=0.0)


def mock_fetcher(handler) -> HttpFetcher:
    """HttpFetcher whose requests are answered by `handler(request) -> httpx.Response`."""
    return HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None,
                       max_retries=2, backoff_base_seconds=0.0)
