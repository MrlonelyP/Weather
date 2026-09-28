"""ThaiWater / HII national water data (Data Sources TW-01 rainfall, TW-02 runoff/water level).

Public JSON API (no key): https://api-v3.thaiwater.net/api/v1/thaiwater30/public
    waterlevel_load -> telemetered river/canal water level + discharge
    rain_24h        -> rain gauge 24h / 1h accumulation

Water level is reported in metres above MSL (waterlevel_msl). Rain is mm.
Both feed the water tables so the Flood Engine inputs (water level + trend,
discharge, short-term rainfall) have real data.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectResult, SchemaMismatch
from app.models import RawPayload, WaterLevelObservation, WaterStation
from app.services import normalizer as nz
from app.services.storage import upsert

log = logging.getLogger(__name__)

SOURCE = "thaiwater"
DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def _localized(node, lang="th"):
    """ThaiWater wraps names as {"th": ..., "en": ...}; return the preferred language."""
    if isinstance(node, dict):
        return node.get(lang) or node.get("en") or next((v for v in node.values() if v), None)
    return node


def _station_fields(item: dict, kind: str) -> tuple[str, dict] | None:
    station = item.get("station") or {}
    code = station.get("id") or station.get("tele_station_oldcode")
    if code is None:
        return None
    geo = item.get("geocode") or {}
    basin = item.get("basin") or {}
    agency = item.get("agency") or {}
    defaults = {
        "station_kind": kind,
        "name_th": nz.clean_text(_localized(station.get("tele_station_name"))),
        "name_en": nz.clean_text(_localized(station.get("tele_station_name"), "en")),
        "river_basin": nz.clean_text(_localized(basin.get("basin_name"))),
        "province_code": nz.clean_text(geo.get("province_code")),
        "lat": nz.to_float(station.get("tele_station_lat")),
        "lon": nz.to_float(station.get("tele_station_long")),
        "ground_level_m": nz.to_float(station.get("ground_level")),
        "bank_level_m": nz.to_float(station.get("min_bank") or station.get("left_bank")),
        "warning_level_m": nz.to_float(station.get("warning_level_m")),
        "critical_level_m": nz.to_float(station.get("critical_level_m") or station.get("critical_level_msl")),
        "datum": "MSL",
        "extra": {
            "oldcode": station.get("tele_station_oldcode"),
            "agency": nz.clean_text(_localized((agency.get("agency_shortname") or {}))),
            "amphoe": nz.clean_text(_localized(geo.get("amphoe_name"))),
            "tumbon": nz.clean_text(_localized(geo.get("tumbon_name"))),
            "province_name": nz.clean_text(_localized(geo.get("province_name"))),
            "is_key_station": station.get("is_key_station"),
            "situation_level": item.get("situation_level"),
        },
    }
    return str(code), defaults


class _ThaiWaterBase(BaseCollector):
    source = SOURCE
    schema_verified = False
    station_kind = "river"

    @property
    def interval_minutes(self) -> int:
        return self.settings.thaiwater_poll_minutes

    def _endpoint(self) -> str:
        raise NotImplementedError

    def _dataset(self) -> str:
        raise NotImplementedError

    def configuration_status(self) -> str | None:
        return None if self.settings.thaiwater_enabled else "DISABLED"

    def _url(self) -> str:
        return f"{self.settings.thaiwater_base_url.rstrip('/')}/{self._endpoint()}"

    def _station_cache(self, session: Session) -> dict[str, int]:
        rows = session.execute(
            select(WaterStation.station_code, WaterStation.id).where(WaterStation.source == SOURCE)
        ).all()
        return {code: sid for code, sid in rows}

    def _ensure_station(self, session: Session, cache: dict, code: str, defaults: dict) -> int:
        if code in cache:
            return cache[code]
        station = WaterStation(source=SOURCE, station_code=code,
                               **{k: v for k, v in defaults.items() if k != "extra"}, extra=defaults["extra"])
        # geom for spatial queries
        if defaults["lat"] is not None and defaults["lon"] is not None:
            station.geom = f"SRID=4326;POINT({defaults['lon']} {defaults['lat']})"
        session.add(station)
        session.flush()
        cache[code] = station.id
        return station.id

    def collect(self) -> CollectResult:
        result = CollectResult()
        fetched = self.fetch(self._dataset(), self._url())
        result.records = self.normalize_fetched(fetched, force=True)
        return result


class ThaiWaterLevelCollector(_ThaiWaterBase):
    """TW-02: telemetered river/canal water level and discharge."""

    job = "thaiwater.waterlevel"
    dataset_prefixes = ("waterlevel",)
    station_kind = "river"

    def configuration_status(self) -> str | None:
        if not (self.settings.thaiwater_enabled and self.settings.thaiwater_waterlevel_enabled):
            return "DISABLED"
        return None

    def _endpoint(self) -> str:
        return "waterlevel_load"

    def _dataset(self) -> str:
        return "waterlevel"

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise SchemaMismatch(f"response is not JSON: {exc}") from exc
        data = (doc.get("waterlevel_data") or {}).get("data")
        if not isinstance(data, list):
            raise SchemaMismatch("waterlevel_data.data is not a list")
        cache = self._station_cache(session)
        rows = []
        for item in data:
            sf = _station_fields(item, self.station_kind)
            if sf is None:
                continue
            code, defaults = sf
            observed = nz.parse_datetime(item.get("waterlevel_datetime"), assume_tz=nz.BANGKOK, formats=DT_FORMATS)
            if observed is None:
                continue
            station_id = self._ensure_station(session, cache, code, defaults)
            level = nz.to_float(item.get("waterlevel_msl"))
            if level is None:
                level = nz.to_float(item.get("waterlevel_m"))
            rows.append({
                "source": SOURCE, "raw_payload_id": raw.id, "station_id": station_id, "observed_at": observed,
                "water_level_m": level,
                "discharge_m3s": nz.to_float(item.get("discharge") or item.get("flow_rate")),
            })
        if not rows:
            raise SchemaMismatch("no usable water level records")
        unique = {(r["station_id"], r["observed_at"]): r for r in rows}
        return upsert(session, WaterLevelObservation, list(unique.values()),
                      constraint="uq_water_level_observation_key",
                      update_columns=["water_level_m", "discharge_m3s", "raw_payload_id", "ingested_at"])


class ThaiWaterRainCollector(_ThaiWaterBase):
    """TW-01: rain gauge 24h accumulation (stored as rain_gauge water stations)."""

    job = "thaiwater.rain"
    dataset_prefixes = ("rain24h",)
    station_kind = "rain_gauge"

    def configuration_status(self) -> str | None:
        if not (self.settings.thaiwater_enabled and self.settings.thaiwater_rain_enabled):
            return "DISABLED"
        return None

    def _endpoint(self) -> str:
        return "rain_24h"

    def _dataset(self) -> str:
        return "rain24h"

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise SchemaMismatch(f"response is not JSON: {exc}") from exc
        data = doc.get("data")
        if not isinstance(data, list):
            raise SchemaMismatch("data is not a list")
        cache = self._station_cache(session)
        rows = []
        for item in data:
            sf = _station_fields(item, self.station_kind)
            if sf is None:
                continue
            code, defaults = sf
            observed = nz.parse_datetime(item.get("rainfall_datetime"), assume_tz=nz.BANGKOK, formats=DT_FORMATS)
            rain = nz.to_float(item.get("rain_24h"))
            if observed is None or rain is None:
                continue
            station_id = self._ensure_station(session, cache, code, defaults)
            rows.append({
                "source": SOURCE, "raw_payload_id": raw.id, "station_id": station_id, "observed_at": observed,
                "rain_mm": rain, "rain_period_hours": 24.0,
            })
        if not rows:
            raise SchemaMismatch("no usable rain records")
        unique = {(r["station_id"], r["observed_at"]): r for r in rows}
        return upsert(session, WaterLevelObservation, list(unique.values()),
                      constraint="uq_water_level_observation_key",
                      update_columns=["rain_mm", "rain_period_hours", "raw_payload_id", "ingested_at"])
