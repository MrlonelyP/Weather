from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10, future=True)

    @event.listens_for(engine, "connect")
    def _set_utc(dbapi_conn, _record):  # every session works in UTC
        with dbapi_conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

    return engine


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def configure_engine(url: str) -> Engine:
    """Point the app at a specific database (used by tests / CLI)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = _make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
