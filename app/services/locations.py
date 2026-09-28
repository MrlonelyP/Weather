"""Forecast points (configured in app/config/locations.json)."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Location

LOCATIONS_FILE = Path(__file__).resolve().parent.parent / "config" / "locations.json"


def load_location_config(path: Path = LOCATIONS_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["locations"]


def sync_locations(session: Session, path: Path = LOCATIONS_FILE) -> list[Location]:
    """Insert/update the configured locations; returns active locations ordered by id."""
    for item in load_location_config(path):
        loc = session.execute(select(Location).where(Location.code == item["code"])).scalar_one_or_none()
        if loc is None:
            loc = Location(code=item["code"])
            session.add(loc)
        loc.name_en = item["name_en"]
        loc.name_th = item.get("name_th")
        loc.province_code = item.get("province_code")
        loc.lat = float(item["lat"])
        loc.lon = float(item["lon"])
        loc.geom = f"SRID=4326;POINT({loc.lon} {loc.lat})"
        loc.test_area = bool(item.get("test_area", False))
        loc.active = bool(item.get("active", True))
    session.flush()
    return active_locations(session)


def active_locations(session: Session) -> list[Location]:
    return list(session.execute(select(Location).where(Location.active.is_(True)).order_by(Location.id)).scalars())
