"""Persistence helpers: raw payload archive and idempotent upserts."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import RawPayload

REDACTED = "***"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact(params: dict | None, secret_keys: Iterable[str] = ()) -> dict | None:
    if params is None:
        return None
    secrets = {k.lower() for k in secret_keys}
    return {k: (REDACTED if k.lower() in secrets else v) for k, v in params.items()}


def build_endpoint(url: str, params: dict | None) -> str:
    return f"{url}?{urlencode(params, doseq=True)}" if params else url


def request_key(dataset: str, url: str, params: dict | None) -> str:
    material = json.dumps([dataset, url, sorted((params or {}).items())], default=str, ensure_ascii=False)
    return sha256_text(material)


def save_raw(
    session: Session,
    *,
    source: str,
    dataset: str,
    url: str,
    params: dict | None,
    fetched_at: datetime,
    status_code: int,
    body: str,
    content_type: str | None,
    latency_ms: int | None,
    context: dict | None = None,
    secret_keys: Iterable[str] = (),
) -> RawPayload:
    """Archive one HTTP response.

    If the body is identical to the latest archived body of the same request,
    only the fetch is recorded (payload NULL, same_as_id -> row holding the body).
    """
    safe_params = redact(params, secret_keys)
    key = request_key(dataset, url, safe_params)
    checksum = sha256_text(body)

    previous = session.execute(
        select(RawPayload.id, RawPayload.checksum, RawPayload.same_as_id)
        .where(RawPayload.request_key == key, RawPayload.status_code == status_code)
        .order_by(RawPayload.fetched_at.desc(), RawPayload.id.desc())
        .limit(1)
    ).first()
    duplicate_of = None
    if previous is not None and previous.checksum == checksum:
        duplicate_of = previous.same_as_id or previous.id

    raw = RawPayload(
        source=source,
        dataset=dataset,
        endpoint=build_endpoint(url, safe_params),
        request_params=safe_params,
        request_key=key,
        fetched_at=fetched_at,
        status_code=status_code,
        content_type=content_type,
        latency_ms=latency_ms,
        size_bytes=len(body.encode("utf-8")),
        checksum=checksum,
        payload=None if duplicate_of else body,
        same_as_id=duplicate_of,
        context=context,
        parse_status="duplicate" if duplicate_of else "pending",
    )
    session.add(raw)
    session.flush()
    return raw


def raw_body(session: Session, raw: RawPayload) -> str | None:
    """Return the body of a raw row, following `same_as_id` for de-duplicated fetches."""
    if raw.payload is not None:
        return raw.payload
    if raw.same_as_id is None:
        return None
    target = session.get(RawPayload, raw.same_as_id)
    return None if target is None else target.payload


def upsert(
    session: Session,
    model,
    rows: Sequence[dict],
    *,
    constraint: str,
    update_columns: Sequence[str] | None = None,
    chunk_size: int = 1000,
) -> int:
    """INSERT ... ON CONFLICT on a named unique constraint.

    update_columns=None  -> DO NOTHING (immutable facts, e.g. a model run's values)
    update_columns=[...] -> DO UPDATE those columns (sources that revise values)
    Returns the number of rows inserted or updated.
    """
    if not rows:
        return 0
    affected = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        stmt = insert(model).values(list(chunk))
        if update_columns:
            stmt = stmt.on_conflict_do_update(
                constraint=constraint, set_={c: stmt.excluded[c] for c in update_columns}
            )
        else:
            stmt = stmt.on_conflict_do_nothing(constraint=constraint)
        # RETURNING gives exactly the inserted/updated rows (rowcount is unreliable
        # for multi-row VALUES containing SQL expressions such as geometries)
        affected += len(session.execute(stmt.returning(model.__table__.c.id)).all())
    return affected


def get_or_create(session: Session, model, lookup: dict, defaults: dict | None = None, update: bool = False):
    """Fetch a registry row (station, reservoir...) by its natural key, creating it if needed.

    With update=True non-None `defaults` overwrite stored values (metadata refresh).
    """
    obj = session.execute(select(model).filter_by(**lookup)).scalar_one_or_none()
    if obj is None:
        obj = model(**lookup, **(defaults or {}))
        session.add(obj)
        session.flush()
    elif update and defaults:
        for key, value in defaults.items():
            if value is not None:
                setattr(obj, key, value)
    return obj
