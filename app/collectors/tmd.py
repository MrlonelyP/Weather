"""TMD telecom API collectors (Data Sources TMD-01..03).

Endpoints (public, JSON): https://telecom.tmd.go.th/api/ftp/{synoptic|warning|metar}
queried by date / country / utc (https://telecom.tmd.go.th/api-docs).

The responses carry GTS bulletins (text). Because the exact JSON envelope has
not been verified from this environment, bulletin text is located by walking
the JSON (any string containing "AAXX" for synoptic; any bulletin-like text for
warnings). The raw response is always archived; if nothing can be extracted
the job reports REQUIRES_INVESTIGATION and the payload can be re-processed
after the parser is adjusted (`python -m app.cli reprocess --job tmd.synoptic`).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.collectors.base import AllRequestsFailed, BaseCollector, CollectResult, SchemaMismatch
from app.collectors.synop import decode_bulletin
from app.models import OfficialWarning, RawPayload, WeatherObservation, WeatherStation
from app.services import normalizer as nz
from app.services.storage import get_or_create, sha256_text, upsert

log = logging.getLogger(__name__)

SOURCE = "tmd"

# WMO abbreviated heading: TTAAii CCCC YYGGgg [BBB]
WMO_HEADING = re.compile(r"\b([A-Z]{4}\d{2})\s+([A-Z]{4})\s+(\d{2})(\d{2})(\d{2})(?:\s+([A-Z]{3}))?\b")
WARNING_TYPES = {
    "WS": "sigmet", "WC": "tropical_cyclone_sigmet", "WV": "volcanic_ash_sigmet",
    "WT": "tropical_cyclone", "FK": "tropical_cyclone_advisory", "WW": "warning",
    "WO": "warning_other", "WA": "airmet",
}


def _load_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text  # some endpoints may return plain text bulletins


def iter_strings(node):
    """Yield every string in a JSON document (depth first)."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from iter_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_strings(value)


def iter_bulletin_items(node):
    """Yield (text, item) for bulletin-like entries: strings or dicts holding a long text field."""
    if isinstance(node, str):
        if len(node.strip()) >= 20:
            yield node, None
    elif isinstance(node, list):
        for value in node:
            yield from iter_bulletin_items(value)
    elif isinstance(node, dict):
        texts = [v for v in node.values() if isinstance(v, str) and len(v.strip()) >= 20]
        if texts:
            yield max(texts, key=len), node
        for value in node.values():
            if isinstance(value, (list, dict)):
                yield from iter_bulletin_items(value)


def _heading_time(day: int, hour: int, minute: int, ref: date) -> datetime | None:
    year, month = ref.year, ref.month
    for _ in range(2):
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            if candidate.date() <= ref + timedelta(days=1):
                return candidate
        except ValueError:
            pass
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return None


class _TmdBase(BaseCollector):
    source = SOURCE
    schema_verified = False

    def _enabled_flag(self) -> bool:
        raise NotImplementedError

    def configuration_status(self) -> str | None:
        if not self.settings.tmd_enabled or not self._enabled_flag():
            return "DISABLED"
        return None

    def _params(self, day: date, hour: int | None = None) -> dict:
        s = self.settings
        params = {s.tmd_param_date: day.strftime(s.tmd_date_format), s.tmd_param_country: s.tmd_country}
        if hour is not None:
            params[s.tmd_param_utc] = f"{hour:02d}"
        return params

    def _url(self, product: str) -> str:
        return f"{self.settings.tmd_base_url.rstrip('/')}/{product}"


class TmdSynopticCollector(_TmdBase):
    """TMD-01: surface synoptic (AAXX) bulletins -> weather_observation."""

    job = "tmd.synoptic"
    dataset_prefixes = ("synoptic",)
    schema_verified = True  # verified against live TMD SYNOP bulletins 2026-09-28

    def _enabled_flag(self) -> bool:
        return self.settings.tmd_synoptic_enabled

    @property
    def interval_minutes(self) -> int:
        return self.settings.tmd_synoptic_poll_minutes

    def collect(self) -> CollectResult:
        result = CollectResult()
        now = nz.utcnow()
        # main synoptic hours 00,03,...,21 UTC inside the look-back window
        hours = []
        t = now.replace(minute=0, second=0, microsecond=0)
        while now - t <= timedelta(hours=self.settings.tmd_synoptic_lookback_hours):
            if t.hour % 3 == 0:
                hours.append(t)
            t -= timedelta(hours=1)
        for slot in hours:
            context = {"ref_date": slot.date().isoformat(), "utc_hour": slot.hour}
            try:
                fetched = self.fetch("synoptic", self._url("synoptic"),
                                     self._params(slot.date(), slot.hour), context=context)
                result.records += self.normalize_fetched(fetched)
            except SchemaMismatch as exc:
                result.parse_failures += 1
                result.partial_errors.append(f"{slot:%Y-%m-%d %H}Z: {exc}")
            except Exception as exc:
                result.partial_errors.append(f"{slot:%Y-%m-%d %H}Z: {exc}")
        if hours and len(result.partial_errors) == len(hours) and not result.parse_failures:
            raise AllRequestsFailed("; ".join(result.partial_errors))
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        ctx = raw.context or {}
        ref = date.fromisoformat(ctx["ref_date"]) if ctx.get("ref_date") else raw.fetched_at.date()
        document = _load_json(text)
        bulletins = [s for s in iter_strings(document) if "AAXX" in s]
        if not bulletins:
            if _looks_empty(document):
                return 0  # valid but empty answer (no bulletins for that hour yet)
            raise SchemaMismatch("no AAXX synoptic text found in response")
        prefixes = tuple(self.settings.tmd_wmo_prefix_list)
        rows, stations = [], {}
        for bulletin in bulletins:
            for rep in decode_bulletin(bulletin, ref):
                if prefixes and not rep.station.startswith(prefixes):
                    continue
                if rep.station not in stations:
                    station = get_or_create(
                        session, WeatherStation, {"source": SOURCE, "station_code": rep.station},
                        {"wmo_id": rep.station, "first_seen_at": raw.fetched_at},
                    )
                    station.last_seen_at = raw.fetched_at
                    stations[rep.station] = station.id
                rows.append({
                    "source": SOURCE,
                    "raw_payload_id": raw.id,
                    "station_id": stations[rep.station],
                    "observed_at": rep.observed_at,
                    "obs_type": "synop",
                    "temperature_c": rep.temperature_c,
                    "dew_point_c": rep.dew_point_c,
                    "humidity_pct": rep.humidity_pct,
                    "pressure_msl_hpa": rep.pressure_msl_hpa,
                    "station_pressure_hpa": rep.station_pressure_hpa,
                    "visibility_km": rep.visibility_km,
                    "wind_speed_kmh": rep.wind_speed_kmh,
                    "wind_direction_deg": rep.wind_direction_deg,
                    "cloud_cover_okta": rep.cloud_cover_okta,
                    "rain_mm": rep.rain_mm,
                    "rain_period_hours": rep.rain_period_hours,
                    "rain_24h_mm": rep.rain_24h_mm,
                    "max_temperature_c": rep.max_temperature_c,
                    "min_temperature_c": rep.min_temperature_c,
                    "report_text": rep.text,
                })
        # the same report can appear in several bulletins (corrections: first wins)
        unique = {(r["station_id"], r["observed_at"]): r for r in reversed(rows)}
        return upsert(session, WeatherObservation, list(unique.values()), constraint="uq_weather_observation_key")


class TmdWarningCollector(_TmdBase):
    """TMD-03: weather warnings / tropical cyclone / SIGMET bulletins -> official_warning."""

    job = "tmd.warning"
    dataset_prefixes = ("warning",)
    schema_verified = True  # verified against live TMD SIGMET bulletins 2026-09-28

    def _enabled_flag(self) -> bool:
        return self.settings.tmd_warning_enabled

    @property
    def interval_minutes(self) -> int:
        return self.settings.tmd_warning_poll_minutes

    def collect(self) -> CollectResult:
        result = CollectResult()
        today = nz.utcnow().date()
        for day in (today - timedelta(days=1), today):
            try:
                fetched = self.fetch("warning", self._url("warning"), self._params(day),
                                     context={"ref_date": day.isoformat()})
                result.records += self.normalize_fetched(fetched)
            except SchemaMismatch as exc:
                result.parse_failures += 1
                result.partial_errors.append(f"{day}: {exc}")
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        ctx = raw.context or {}
        ref = date.fromisoformat(ctx["ref_date"]) if ctx.get("ref_date") else raw.fetched_at.date()
        document = _load_json(text)
        rows = []
        for body, item in iter_bulletin_items(document):
            body = body.strip()
            # Only bulletin-like entries count: a WMO heading must be present in the
            # text or in a sibling field. This keeps API status/error messages out
            # of official_warning.
            heading_source = body
            if isinstance(item, dict):
                heading_source = " ".join(str(v) for v in item.values() if isinstance(v, str))
            heading = WMO_HEADING.search(heading_source)
            if heading is None:
                continue
            header = issued_at = None
            wtype = None
            if heading:
                header = " ".join(g for g in heading.groups()[:2] if g) + " " + "".join(heading.groups()[2:5])
                if heading.group(6):
                    header += " " + heading.group(6)
                issued_at = _heading_time(int(heading.group(3)), int(heading.group(4)), int(heading.group(5)), ref)
                wtype = WARNING_TYPES.get(heading.group(1)[:2])
            if issued_at is None and isinstance(item, dict):
                for key in ("issued_at", "issue_time", "datetime", "date_time", "time", "date"):
                    if key in item:
                        issued_at = nz.parse_datetime(item[key])
                        if issued_at:
                            break
            rows.append({
                "source": SOURCE,
                "raw_payload_id": raw.id,
                "agency": "TMD",
                "source_warning_id": (header or "bulletin") + ":" + sha256_text(body)[:16],
                "bulletin_header": header,
                "warning_type": wtype,
                "issued_at": issued_at,
                "title": body.splitlines()[0][:500] if body else None,
                "body": body,
                "extra": {k: v for k, v in item.items() if not isinstance(v, (list, dict))} if item else None,
            })
        if not rows:
            if _looks_empty(document):
                return 0
            raise SchemaMismatch("no bulletin text found in warning response")
        unique = {r["source_warning_id"]: r for r in rows}
        return upsert(session, OfficialWarning, list(unique.values()), constraint="uq_official_warning_key")


class TmdMetarCollector(_TmdBase):
    """TMD-02 (P1): METAR/SPECI archived as raw payload only for now."""

    job = "tmd.metar"
    dataset_prefixes = ("metar",)

    def _enabled_flag(self) -> bool:
        return self.settings.tmd_metar_enabled

    @property
    def interval_minutes(self) -> int:
        return self.settings.tmd_metar_poll_minutes

    def collect(self) -> CollectResult:
        now = nz.utcnow()
        fetched = self.fetch("metar", self._url("metar"), self._params(now.date(), now.hour),
                             context={"ref_date": now.date().isoformat(), "utc_hour": now.hour})
        self.normalize_fetched(fetched)
        return CollectResult(details={"note": "raw archive only (METAR parsing is P1)"})

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        return 0


def _looks_empty(document) -> bool:
    if document in (None, "", [], {}):
        return True
    if isinstance(document, dict):
        values = [v for v in document.values() if v not in (None, "", [], {})]
        return all(not isinstance(v, (list, dict)) for v in values) and not any(
            isinstance(v, str) and len(v) > 200 for v in values)
    return False


class TmdStationCollector(_TmdBase):
    """TMD station metadata (names, province, coordinates) -> weather_station.

    SYNOP reports carry only the WMO index; this fills in where each station is.
    Endpoint: data.tmd.go.th Station/v1 (uid/ukey in .env; defaults are TMD's
    published example credentials).
    """

    job = "tmd.stations"
    dataset_prefixes = ("stations",)
    secret_params = ("uid", "ukey")
    schema_verified = True  # checked against the live response 2026-09-28

    def _enabled_flag(self) -> bool:
        return self.settings.tmd_stations_enabled

    def configuration_status(self) -> str | None:
        status = super().configuration_status()
        if status:
            return status
        if not (self.settings.tmd_station_uid and self.settings.tmd_station_ukey):
            return "NO_API_KEY"
        return None

    @property
    def interval_minutes(self) -> int:
        return 24 * 60

    def collect(self) -> CollectResult:
        s = self.settings
        fetched = self.fetch("stations", s.tmd_station_url,
                             {"uid": s.tmd_station_uid, "ukey": s.tmd_station_ukey, "format": "json"})
        return CollectResult(records=self.normalize_fetched(fetched, force=True))

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        from sqlalchemy import select as _select

        from app.models import WaterStation

        document = _load_json(text)
        stations = None
        if isinstance(document, dict):
            node = document.get("Station") or document.get("Stations")
            stations = node if isinstance(node, list) else None
        if not stations:
            raise SchemaMismatch("no Station list in response")
        # province name -> TIS-1099 code, learned from ThaiWater geocodes (source data, not typed by hand)
        province_codes = {}
        for extra, code in session.execute(
                _select(WaterStation.extra, WaterStation.province_code).where(WaterStation.province_code.isnot(None))):
            name = (extra or {}).get("province_name")
            if name:
                province_codes[name] = code
        count = 0
        for st in stations:
            wmo = nz.clean_text(st.get("WmoCode"))
            if not wmo:
                continue
            lat, lon = nz.to_float(st.get("Latitude")), nz.to_float(st.get("Longitude"))
            province = nz.clean_text(st.get("Province"))
            station = get_or_create(session, WeatherStation, {"source": SOURCE, "station_code": wmo},
                                    {"wmo_id": wmo, "first_seen_at": raw.fetched_at})
            station.name_th = nz.clean_text(st.get("StationNameThai"))
            station.name_en = nz.clean_text(st.get("StationNameEnglish"))
            station.province_name = province
            station.province_code = province_codes.get(province) if province else None
            station.lat, station.lon = lat, lon
            station.elevation_m = nz.to_float(st.get("HeightAboveMSL"))
            if lat is not None and lon is not None:
                station.geom = f"SRID=4326;POINT({lon} {lat})"
            station.extra = {"station_id": st.get("StationID"), "station_type": st.get("StationType")}
            count += 1
        return count
