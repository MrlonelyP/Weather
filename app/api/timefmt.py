"""Timestamps in API responses: `<name>` is UTC ISO-8601, `<name>_local` is Asia/Bangkok."""
from __future__ import annotations

from datetime import date, datetime

from app.services.normalizer import ensure_utc, to_local


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else ensure_utc(dt).isoformat().replace("+00:00", "Z")


def iso_local(dt: datetime | None) -> str | None:
    return None if dt is None else to_local(dt).isoformat()


def times(**fields: datetime | None) -> dict:
    out: dict = {}
    for name, value in fields.items():
        out[name] = iso(value)
        out[f"{name}_local"] = iso_local(value)
    return out


def iso_date(d: date | None) -> str | None:
    return None if d is None else d.isoformat()
