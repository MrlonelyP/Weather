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
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectResult, SchemaMismatch
from app.models import RawPayload, WaterLevelObservation, WaterStation
from app.services import normalizer as nz
from app.services.database import session_scope
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
            "river_name": nz.clean_text(_localized(item.get("river_name"))),
        },
    }
    return str(code), defaults


class _ThaiWaterBase(BaseCollector):
    source = SOURCE
    schema_verified = False
    measure = "water_level"
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

    def _station_cache(self, session: Session) -> dict[str, WaterStation]:
        rows = session.execute(select(WaterStation).where(WaterStation.source == SOURCE)).scalars()
        return {st.station_code: st for st in rows}

    def _ensure_station(self, session: Session, cache: dict, code: str, defaults: dict) -> int:
        """Create the station, or refresh its metadata from the latest payload (once per run)."""
        station = cache.get(code)
        if station is None:
            station = WaterStation(source=SOURCE, station_code=code)
            session.add(station)
            cache[code] = station
        elif getattr(station, "_refreshed", False):
            return station.id
        # ThaiWater telemetry stations often report BOTH water level and rain under one station id.
        # The station stays "river" once it reports a level (a rain payload must not downgrade it),
        # and extra["measures"] records every quantity it reports.
        measures = sorted(set((station.extra or {}).get("measures", [])) | {self.measure})
        for key, value in defaults.items():
            if key == "extra":
                station.extra = {**(station.extra or {}), **{k: v for k, v in value.items() if v is not None},
                                 "measures": measures}
            elif key == "station_kind":
                if station.station_kind is None or value == "river":
                    station.station_kind = value
            elif value is not None:
                setattr(station, key, value)
        if station.lat is not None and station.lon is not None:
            station.geom = f"SRID=4326;POINT({station.lon} {station.lat})"
        session.flush()
        station._refreshed = True
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
            situation = item.get("situation_level")
            rows.append({
                "source": SOURCE, "raw_payload_id": raw.id, "station_id": station_id, "observed_at": observed,
                "water_level_m": level,
                "discharge_m3s": nz.to_float(item.get("discharge") or item.get("flow_rate")),
                # as given by ThaiWater - never mixed with values our system computes
                "source_prev_level_m": nz.to_float(item.get("waterlevel_msl_previous")),
                "source_diff_to_bank_m": nz.to_float(item.get("diff_wl_bank")),
                "source_diff_to_bank_text": nz.clean_text(item.get("diff_wl_bank_text")),
                "source_situation_level": int(situation) if isinstance(situation, (int, float)) else None,
            })
        if not rows:
            raise SchemaMismatch("no usable water level records")
        unique = {(r["station_id"], r["observed_at"]): r for r in rows}
        return upsert(session, WaterLevelObservation, list(unique.values()),
                      constraint="uq_water_level_observation_key",
                      update_columns=["water_level_m", "discharge_m3s", "source_prev_level_m",
                                      "source_diff_to_bank_m", "source_diff_to_bank_text",
                                      "source_situation_level", "raw_payload_id", "ingested_at"])


class ThaiWaterRainCollector(_ThaiWaterBase):
    """TW-01: rain gauge 24h accumulation (stored as rain_gauge water stations)."""

    job = "thaiwater.rain"
    dataset_prefixes = ("rain24h",)
    station_kind = "rain_gauge"
    measure = "rain"

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
                "rain_1h_mm": nz.to_float(item.get("rain_1h")),
            })
        if not rows:
            raise SchemaMismatch("no usable rain records")
        unique = {(r["station_id"], r["observed_at"]): r for r in rows}
        return upsert(session, WaterLevelObservation, list(unique.values()),
                      constraint="uq_water_level_observation_key",
                      update_columns=["rain_mm", "rain_period_hours", "rain_1h_mm", "raw_payload_id",
                                      "ingested_at"])


class ThaiWaterLevelHistoryCollector(_ThaiWaterBase):
    """Hourly/10-min water level history for selected stations (waterlevel_graph).

    Used to backfill trend history (rate of rise) instead of waiting for hourly
    polls to accumulate. A station is skipped when the graph value at our latest
    stored time differs from the stored level (guards against a datum mismatch).
    """

    job = "thaiwater.waterlevel_history"
    dataset_prefixes = ("waterlevel_graph",)
    DATUM_TOLERANCE_M = 0.05

    @property
    def interval_minutes(self) -> int:
        return self.settings.thaiwater_history_poll_minutes

    def configuration_status(self) -> str | None:
        return None if self.settings.thaiwater_enabled else "DISABLED"

    def _endpoint(self) -> str:
        return "waterlevel_graph"

    def _dataset(self) -> str:
        return "waterlevel_graph"

    def collect(self, station_codes: list[str] | None = None, hours: int | None = None) -> CollectResult:
        hours = hours or self.settings.thaiwater_history_hours
        result = CollectResult()
        with session_scope() as session:
            q = select(WaterStation.station_code).where(WaterStation.source == SOURCE,
                                                        WaterStation.station_kind == "river")
            if station_codes:
                q = q.where(WaterStation.station_code.in_(station_codes))
            else:
                q = q.where(WaterStation.province_code.in_(self.settings.thaiwater_history_provinces_list))
            codes = [c for (c,) in session.execute(q)]
        today = nz.bangkok_today()
        start = today - timedelta(days=max(1, (hours + 23) // 24))
        for code in codes:
            params = {"station_type": "tele_waterlevel", "station_id": code,
                      "start_date": start.isoformat(), "end_date": today.isoformat()}
            try:
                fetched = self.fetch(self._dataset(), self._url(), params, context={"station_code": code})
                result.records += self.normalize_fetched(fetched, force=True)
            except SchemaMismatch as exc:
                result.parse_failures += 1
                result.partial_errors.append(f"{code}: {exc}")
            except Exception as exc:  # one station must not stop the rest
                result.partial_errors.append(f"{code}: {exc}")
        result.details = {"stations": len(codes), "start_date": start.isoformat()}
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        code = (raw.context or {}).get("station_code")
        try:
            doc = json.loads(text)
            points = doc["data"]["graph_data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SchemaMismatch(f"waterlevel_graph not understood: {exc}") from exc
        station = session.execute(select(WaterStation).where(
            WaterStation.source == SOURCE, WaterStation.station_code == str(code))).scalar_one_or_none()
        if station is None:
            raise SchemaMismatch(f"unknown station {code}")
        # reference levels published with the graph (source values, metres MSL)
        for key, attr in (("min_bank", "bank_level_m"), ("warning_level", "warning_level_m"),
                          ("critical_level", "critical_level_m"), ("ground_level", "ground_level_m")):
            value = nz.to_float(doc["data"].get(key))
            if value is not None:
                setattr(station, attr, value)
        series = []
        for p in points:
            t = nz.parse_datetime(p.get("datetime"), assume_tz=nz.BANGKOK, formats=DT_FORMATS)
            v = nz.to_float(p.get("value"))
            if t is not None and v is not None:
                series.append((t, v, nz.to_float(p.get("discharge"))))
        if not series:
            return 0
        latest = session.execute(
            select(WaterLevelObservation.observed_at, WaterLevelObservation.water_level_m)
            .where(WaterLevelObservation.station_id == station.id,
                   WaterLevelObservation.water_level_m.isnot(None))
            .order_by(WaterLevelObservation.observed_at.desc()).limit(1)).first()
        if latest is not None:
            same_time = [v for t, v, _ in series if t == latest.observed_at]
            if same_time and abs(same_time[0] - latest.water_level_m) > self.DATUM_TOLERANCE_M:
                raise SchemaMismatch(
                    f"station {code}: graph {same_time[0]} vs stored {latest.water_level_m} at "
                    f"{latest.observed_at.isoformat()} - datum mismatch, skipped")
        rows = [{"source": SOURCE, "raw_payload_id": raw.id, "station_id": station.id, "observed_at": t,
                 "water_level_m": v, "discharge_m3s": q} for t, v, q in series]
        unique = {r["observed_at"]: r for r in rows}
        # do not overwrite rows from waterlevel_load (they also carry source situation fields)
        return upsert(session, WaterLevelObservation, list(unique.values()),
                      constraint="uq_water_level_observation_key")
