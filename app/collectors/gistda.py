"""GISTDA flood collectors (Data Sources GIS-01, GIS-02). API key required.

GIS-01  flood-extent-1day point check (api-gateway.gistda.or.th):
        "is this lat/lon inside a satellite-detected flood extent?" per location.
GIS-02  flood polygons from the GISTDA Disaster Platform open API
        (https://disaster.gistda.or.th/services/open-api). The concrete endpoint is
        issued with the key, so it must be set in .env (GISTDA_FLOOD_POLYGON_URL);
        until then the job reports NOT_CONFIGURED.

The API key is read from GISTDA_API_KEY and sent as a header; it is never
written to raw_payload (headers are not archived).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import func, text as sql_text, update
from sqlalchemy.orm import Session

from app.collectors.base import AllRequestsFailed, BaseCollector, CollectResult, SchemaMismatch
from app.models import FloodExtent, FloodPointCheck, RawPayload
from app.services import normalizer as nz
from app.services.database import session_scope
from app.services.locations import active_locations, sync_locations
from app.services.storage import sha256_text, upsert

log = logging.getLogger(__name__)

SOURCE = "gistda"

FLOOD_FLAG_KEYS = ("is_flood", "isflood", "flood", "flooded", "is_flooded", "in_flood", "inflood", "result")
TIME_KEYS = ("observed_at", "acquisition_date", "acq_date", "date", "datetime", "detected_date",
             "flood_date", "_createdAt", "created_at", "updated_at", "time")


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SchemaMismatch(f"response is not JSON: {exc}") from exc


def _find_time(node) -> str | None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k.lower() in {t.lower() for t in TIME_KEYS} and isinstance(v, str):
                return v
        for v in node.values():
            found = _find_time(v)
            if found:
                return found
    return None


def interpret_point_check(document) -> bool | None:
    """True/False when the answer is explicit, None when it cannot be interpreted."""
    if isinstance(document, dict):
        if document.get("type") == "FeatureCollection" and isinstance(document.get("features"), list):
            return len(document["features"]) > 0
        for k, v in document.items():
            if k.lower() in FLOOD_FLAG_KEYS and isinstance(v, bool):
                return v
        for key in ("data", "result", "results", "features", "items"):
            if key in document and isinstance(document[key], (dict, list)):
                inner = interpret_point_check(document[key])
                if inner is not None:
                    return inner
    if isinstance(document, list):
        # list of matching flood features/records for the point
        return len(document) > 0 if all(isinstance(x, dict) for x in document) else None
    return None


class _GistdaBase(BaseCollector):
    source = SOURCE
    schema_verified = False

    @property
    def interval_minutes(self) -> int:
        return self.settings.gistda_poll_minutes

    def configuration_status(self) -> str | None:
        if not self.settings.gistda_enabled:
            return "DISABLED"
        if not self.settings.gistda_api_key:
            return "NO_API_KEY"
        return None

    def _headers(self) -> dict:
        return {self.settings.gistda_api_key_header: self.settings.gistda_api_key or ""}


class GistdaFloodPointCollector(_GistdaBase):
    """GIS-01: point-in-flood-extent check for each configured location."""

    job = "gistda.flood_point_check"
    dataset_prefixes = ("flood_point_check",)

    def collect(self) -> CollectResult:
        result = CollectResult()
        with session_scope() as session:
            sync_locations(session)
            locations = [{"id": l.id, "code": l.code, "lat": l.lat, "lon": l.lon} for l in active_locations(session)]
        s = self.settings
        for loc in locations:
            params = {s.gistda_point_param_lat: loc["lat"], s.gistda_point_param_lon: loc["lon"]}
            try:
                fetched = self.fetch("flood_point_check", s.gistda_point_check_url, params,
                                     headers=self._headers(), context={"location": loc})
                result.records += self.normalize_fetched(fetched, force=True)
            except SchemaMismatch as exc:
                result.parse_failures += 1
                result.partial_errors.append(f"{loc['code']}: {exc}")
            except Exception as exc:
                result.partial_errors.append(f"{loc['code']}: {exc}")
        if locations and len(result.partial_errors) == len(locations) and not result.parse_failures:
            raise AllRequestsFailed("; ".join(result.partial_errors))
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        loc = (raw.context or {}).get("location")
        if not loc:
            raise SchemaMismatch("raw payload has no location in context")
        document = _json(text)
        flooded = interpret_point_check(document)
        if flooded is None:
            raise SchemaMismatch("could not interpret point-check answer")
        row = {
            "source": SOURCE,
            "raw_payload_id": raw.id,
            "location_id": loc["id"],
            "checked_at": raw.fetched_at.replace(microsecond=0),
            "lat": loc["lat"],
            "lon": loc["lon"],
            "is_flooded": flooded,
            "observed_at": nz.parse_datetime(_find_time(document)),
            "details": None,
        }
        return upsert(session, FloodPointCheck, [row], constraint="uq_flood_point_check_key")


class GistdaFloodPolygonCollector(_GistdaBase):
    """GIS-02: flood extent polygons (GeoJSON FeatureCollection, paged with limit/offset)."""

    job = "gistda.flood_polygon"
    dataset_prefixes = ("flood_polygon",)

    def configuration_status(self) -> str | None:
        status = super().configuration_status()
        if status:
            return status
        return None if self.settings.gistda_flood_polygon_url else "NOT_CONFIGURED"

    def collect(self) -> CollectResult:
        result = CollectResult()
        s = self.settings
        for page in range(s.gistda_max_pages):
            params = {"limit": s.gistda_page_limit, "offset": page * s.gistda_page_limit}
            fetched = self.fetch("flood_polygon", s.gistda_flood_polygon_url, params,
                                 headers=self._headers(), context={"page": page})
            result.records += self.normalize_fetched(fetched, force=True)
            features = _json(fetched.text).get("features") or []
            if len(features) < s.gistda_page_limit:
                break
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        document = _json(text)
        if not isinstance(document, dict) or not isinstance(document.get("features"), list):
            raise SchemaMismatch("expected a GeoJSON FeatureCollection")
        rows = []
        for feature in document["features"]:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if not geometry:
                continue
            props = feature.get("properties") or {}
            geo_json = json.dumps(geometry, sort_keys=True)
            feature_id = feature.get("id") or props.get("id") or props.get("_id") or props.get("gid")
            rows.append({
                "source": SOURCE,
                "raw_payload_id": raw.id,
                "source_feature_id": str(feature_id) if feature_id is not None else "sha256:" + sha256_text(geo_json),
                "product": props.get("product"),
                "observed_at": nz.parse_datetime(_find_time(props)),
                "province_code": nz.clean_text(props.get("pv_idn") or props.get("province_code")),
                "province_name": nz.clean_text(props.get("pv_tn") or props.get("province")),
                "geometry": func.ST_SetSRID(func.ST_GeomFromGeoJSON(geo_json), 4326),
                "properties": props,
            })
        count = upsert(session, FloodExtent, rows, constraint="uq_flood_extent_key", chunk_size=200)
        session.execute(
            update(FloodExtent)
            .where(FloodExtent.raw_payload_id == raw.id, FloodExtent.area_sqkm.is_(None))
            .values(area_sqkm=func.ST_Area(sql_text("geometry::geography")) / 1_000_000)
        )
        return count
