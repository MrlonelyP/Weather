"""RID reservoir collectors (Data Sources RID-01, RID-02).

    RID-01 large dams (35):  https://app.rid.go.th/reservoir/api/dam/public[/{YYYY-MM-DD}]
    RID-02 medium reservoirs: https://app.rid.go.th/reservoir/api/reservoir/public[/{YYYY-MM-DD}]
    documentation:            https://app.rid.go.th/reservoir/api/document/dam

The field names of the JSON have not been verified from this environment, so
records are located by walking the JSON and matching known field-name
variants (see FIELD_ALIASES). Units follow the plan (DB Schema sheet):
volumes in million m3 (MCM), inflow/outflow in MCM/day. A sanity check rejects
payloads whose magnitudes do not look like MCM instead of guessing a conversion.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.collectors.base import AllRequestsFailed, BaseCollector, CollectResult, SchemaMismatch
from app.models import RawPayload, Reservoir, ReservoirStatus
from app.services import normalizer as nz
from app.services.storage import get_or_create, upsert

log = logging.getLogger(__name__)

SOURCE = "rid"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "code": ("id", "damid", "damcode", "code", "rsvid", "rsvcode", "reservoirid", "reservoircode", "stationid"),
    "name": ("name", "damname", "nameth", "rsvname", "reservoirname", "damnameth", "stationname"),
    "name_en": ("nameen", "damnameen", "rsvnameen"),
    "capacity": ("capacity", "damcapacity", "maxcapacity", "storagecapacity", "capacitymcm",
                 "volcapacity", "nhw", "normalhighwater", "maxstorage"),
    "storage": ("volume", "storage", "currentvolume", "watervolume", "damstorage", "vol",
                "currentstorage", "volumemcm", "damvolume", "rsvvolume"),
    "storage_pct": ("percentstorage", "storagepercent", "percent", "percentage", "perstorage",
                    "percentvolume", "volumepercent", "damstoragepercent", "percentcapacity"),
    "usable": ("usablevolume", "activestorage", "volumeusable", "usablestorage", "useablevolume",
               "waterusable", "usablewater", "uses", "usewater", "activevolume"),
    "usable_pct": ("percentusable", "usablepercent", "percentactive", "usablestoragepercent",
                   "percentusablestorage", "usespercent"),
    "inflow": ("inflow", "daminflow", "waterinflow", "inflowvolume", "qin", "inflowmcm"),
    "outflow": ("outflow", "release", "damreleased", "waterrelease", "outflowvolume", "qout",
                "released", "damrelease", "outflowmcm"),
    "dead_storage": ("deadstorage", "minstorage", "deadvolume", "dead", "lowstorage"),
    "date": ("date", "damdate", "datadate", "recorddate", "datetime", "reportdate"),
    "region": ("region", "regionname", "regionth", "zone"),
}

# largest RID reservoir (Bhumibol) is ~13,462 MCM; far larger numbers mean a different unit
MAX_PLAUSIBLE_MCM = 50_000


def _key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", k.lower())


def _pick(item: dict, field: str):
    aliases = FIELD_ALIASES[field]
    for k, v in item.items():
        if _key(k) in aliases and not isinstance(v, (dict, list)):
            return v
    return None


def _is_record(item: dict) -> bool:
    keys = {_key(k) for k in item}
    has_id = any(k in FIELD_ALIASES["code"] for k in keys)
    has_name = any(k in FIELD_ALIASES["name"] for k in keys)
    has_value = any(k in FIELD_ALIASES[f] for f in ("storage", "storage_pct", "inflow", "outflow") for k in keys)
    return has_id and has_name and has_value


def find_records(node, region=None) -> list[tuple[dict, str | None]]:
    """Return (record_dict, region) for reservoir-like dicts anywhere in the document.

    The deepest matches win: a group dict that itself looks like a record (e.g. a
    regional total with a percentage) is only used when it has no nested records,
    so per-dam rows are never hidden behind their group. The group's region
    field (or its name, when the group looks like a record) labels nested rows.
    """
    if isinstance(node, list):
        return [found for value in node for found in find_records(value, region)]
    if not isinstance(node, dict):
        return []
    is_record = _is_record(node)
    group_region = _pick(node, "region") or (_pick(node, "name") if is_record else None) or region
    children = [found for value in node.values() if isinstance(value, (list, dict))
                for found in find_records(value, group_region)]
    if children:
        return children
    return [(node, _pick(node, "region") or region)] if is_record else []


class _RidBase(BaseCollector):
    source = SOURCE
    schema_verified = False
    size_class = "large"
    dataset = "dam"

    @property
    def interval_minutes(self) -> int:
        return self.settings.rid_poll_minutes

    def _base_url(self) -> str:
        raise NotImplementedError

    def url_for(self, day: date) -> str:
        return self.settings.rid_date_path_format.format(url=self._base_url().rstrip("/"), date=day.isoformat())

    def collect(self, days: list[date] | None = None) -> CollectResult:
        result = CollectResult()
        today = nz.bangkok_today()
        days = days or [today - timedelta(days=i) for i in range(self.settings.rid_lookback_days)]
        for day in days:
            try:
                fetched = self.fetch(self.dataset, self.url_for(day), context={"observed_date": day.isoformat()})
                result.records += self.normalize_fetched(fetched)
            except SchemaMismatch as exc:
                result.parse_failures += 1
                result.partial_errors.append(f"{day}: {exc}")
            except Exception as exc:
                result.partial_errors.append(f"{day}: {exc}")
        if days and len(result.partial_errors) == len(days) and not result.parse_failures:
            raise AllRequestsFailed("; ".join(result.partial_errors))
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        ctx = raw.context or {}
        try:
            document = json.loads(text)
        except ValueError as exc:
            raise SchemaMismatch(f"response is not JSON: {exc}") from exc
        requested = date.fromisoformat(ctx["observed_date"]) if ctx.get("observed_date") else None
        records = find_records(document)
        if not records:
            raise SchemaMismatch("no reservoir records (id + name + storage/percent/flow) found")

        rows = []
        for item, region in records:
            code = nz.clean_text(_pick(item, "code"))
            if not code:
                continue
            capacity = nz.to_float(_pick(item, "capacity"))
            storage = nz.to_float(_pick(item, "storage"))
            for value in (capacity, storage):
                if value is not None and value > MAX_PLAUSIBLE_MCM:
                    raise SchemaMismatch(f"reservoir {code}: value {value} does not look like MCM; unit unclear")
            reservoir = get_or_create(
                session, Reservoir, {"source": SOURCE, "reservoir_code": code},
                {"name_th": nz.clean_text(_pick(item, "name")), "name_en": nz.clean_text(_pick(item, "name_en")),
                 "size_class": self.size_class, "region": nz.clean_text(region),
                 "capacity_mcm": capacity, "min_storage_mcm": nz.to_float(_pick(item, "dead_storage"))},
                update=True,
            )
            item_date = nz.parse_datetime(_pick(item, "date"), assume_tz=nz.BANGKOK)
            observed_date = item_date.astimezone(nz.BANGKOK).date() if item_date else requested
            if observed_date is None:
                raise SchemaMismatch("no date in record and no requested date in context")
            inflow, outflow = nz.to_float(_pick(item, "inflow")), nz.to_float(_pick(item, "outflow"))
            rows.append({
                "source": SOURCE,
                "raw_payload_id": raw.id,
                "reservoir_id": reservoir.id,
                "observed_date": observed_date,
                "observed_at": None,
                "storage_mcm": storage,
                "storage_pct": nz.to_float(_pick(item, "storage_pct")),
                "usable_storage_mcm": nz.to_float(_pick(item, "usable")),
                "usable_storage_pct": nz.to_float(_pick(item, "usable_pct")),
                "inflow_mcm_day": inflow,
                "outflow_mcm_day": outflow,
                "inflow_m3s": nz.mcm_per_day_to_m3s(inflow),
                "outflow_m3s": nz.mcm_per_day_to_m3s(outflow),
                "capacity_mcm": capacity,
            })
        if not rows:
            raise SchemaMismatch("reservoir records found but none had an id")
        unique = {(r["reservoir_id"], r["observed_date"]): r for r in rows}
        # RID may revise a day's figures -> latest fetch wins
        return upsert(session, ReservoirStatus, list(unique.values()), constraint="uq_reservoir_status_key",
                      update_columns=["raw_payload_id", "storage_mcm", "storage_pct", "usable_storage_mcm",
                                      "usable_storage_pct", "inflow_mcm_day", "outflow_mcm_day", "inflow_m3s",
                                      "outflow_m3s", "capacity_mcm", "ingested_at"])


class RidDamCollector(_RidBase):
    """RID-01: large dams."""

    job = "rid.dam"
    size_class = "large"
    dataset = "dam"
    dataset_prefixes = ("dam",)

    def configuration_status(self) -> str | None:
        return None if self.settings.rid_enabled else "DISABLED"

    def _base_url(self) -> str:
        return self.settings.rid_dam_url


class RidMediumReservoirCollector(_RidBase):
    """RID-02 (P1): medium reservoirs."""

    job = "rid.medium_reservoir"
    size_class = "medium"
    dataset = "medium_reservoir"
    dataset_prefixes = ("medium_reservoir",)

    def configuration_status(self) -> str | None:
        return None if (self.settings.rid_enabled and self.settings.rid_medium_enabled) else "DISABLED"

    def _base_url(self) -> str:
        return self.settings.rid_medium_url
