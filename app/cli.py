"""Command line tools.

    python -m app.cli init-db                      # alembic upgrade head + seed locations/health rows
    python -m app.cli jobs                         # list collector jobs and their configuration state
    python -m app.cli collect <job>|all            # run collector(s) once, now
    python -m app.cli backfill-openmeteo --start 2026-09-01 --end 2026-09-27
    python -m app.cli backfill-rid --start 2026-09-01 --end 2026-09-27 [--medium]
    python -m app.cli reprocess --job tmd.synoptic [--since 2026-09-01] [--failed-only]
    python -m app.cli health                       # source health report
    python -m app.cli terrain-download [--dataset copernicus_glo30] [--tile N13E100]
    python -m app.cli terrain-status               # DEM tiles on disk / at source
    python -m app.cli waterways-import [--refresh]  # OSM waterways (HOT export, ODbL) into PostGIS
    python -m app.cli terrain-precompute            # terrain attributes for stations / forecast points
    python -m app.cli hydro-import [--skip-download] # HydroSHEDS basins, rivers, 15" rasters (region only)
    python -m app.cli hydro-link                    # station -> river reach, upstream/downstream relations
    python -m app.cli features-snapshot [--as-of 2026-09-28T05:00] [--no-forecast]
    python -m app.cli features-backfill --hours 48  # past hours from stored observations (as-of, no look-ahead)
    python -m app.cli features-label                # fill actual levels for rows whose target time has passed
    python -m app.cli run-due                       # one pass of every due job (cron / GitHub Actions)
    python -m app.cli prune                         # apply RETENTION_* settings
    python -m app.cli features-export --before 2026-09-28T00:00 --out training.jsonl.gz
    python -m app.cli features-delete --before 2026-09-28T00:00   # after the export is stored safely
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config.logging import setup_logging
from app.config.settings import get_settings

log = logging.getLogger("app.cli")
ROOT = Path(__file__).resolve().parent.parent


def cmd_init_db(_args) -> int:
    from alembic import command
    from alembic.config import Config

    from app.collectors.registry import build_collectors
    from app.scheduler.jobs import register_health_rows

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    register_health_rows(build_collectors(get_settings()))
    print("database ready")
    return 0


def cmd_jobs(_args) -> int:
    from app.collectors.registry import build_collectors

    for c in build_collectors(get_settings()):
        state = c.configuration_status() or "ENABLED"
        print(f"{c.job:32s} {state:15s} every {c.interval_minutes} min  schema_verified={c.schema_verified}")
    return 0


def cmd_collect(args) -> int:
    from app.collectors.registry import build_collectors, get_collector
    from app.scheduler.jobs import register_health_rows

    settings = get_settings()
    collectors = build_collectors(settings) if args.job == "all" else [get_collector(settings, args.job)]
    register_health_rows(collectors)
    worst = 0
    for c in collectors:
        outcome = c.run()
        print(f"{outcome.job:32s} {outcome.status:24s} records={outcome.records}"
              + (f"  error={outcome.error}" if outcome.error else ""))
        if outcome.status in ("ERROR", "UNAVAILABLE", "REQUIRES_INVESTIGATION"):
            worst = 1
    return worst


def cmd_backfill_openmeteo(args) -> int:
    from app.collectors.openmeteo import OpenMeteoHistoricalCollector

    collector = OpenMeteoHistoricalCollector(get_settings())
    result = collector.collect(start_date=args.start, end_date=args.end)
    print(f"historical forecast rows: {result.records}; errors: {result.partial_errors or 'none'}")
    return 1 if result.partial_errors else 0


def cmd_backfill_rid(args) -> int:
    from app.collectors.rid import RidDamCollector, RidMediumReservoirCollector

    settings = get_settings()
    collector = RidMediumReservoirCollector(settings) if args.medium else RidDamCollector(settings)
    days, d = [], args.start
    while d <= args.end:
        days.append(d)
        d += timedelta(days=1)
    result = collector.collect(days=days)
    print(f"reservoir rows: {result.records}; errors: {result.partial_errors or 'none'}")
    return 1 if result.partial_errors else 0


def cmd_reprocess(args) -> int:
    """Re-run normalization from archived raw payloads (no API call)."""
    from app.collectors.base import SchemaMismatch, normalize_raw
    from app.collectors.registry import get_collector
    from app.models import RawPayload
    from app.services.database import session_scope
    from app.services.storage import raw_body

    collector = get_collector(get_settings(), args.job)
    with session_scope() as session:
        q = select(RawPayload.id).where(RawPayload.source == collector.source,
                                        RawPayload.status_code >= 200, RawPayload.status_code < 300,
                                        RawPayload.payload.is_not(None))
        if args.since:
            q = q.where(RawPayload.fetched_at >= args.since)
        if args.failed_only:
            q = q.where(RawPayload.parse_status == "failed")
        ids = [i for (i,) in session.execute(q.order_by(RawPayload.fetched_at))]
    done = failed = records = 0
    for raw_id in ids:
        with session_scope() as session:
            raw = session.get(RawPayload, raw_id)
            if not collector.handles_dataset(raw.dataset):
                continue
            text = raw_body(session, raw)
        try:
            records += normalize_raw(collector, raw_id, text)
            done += 1
        except SchemaMismatch as exc:
            failed += 1
            log.warning("raw %d: %s", raw_id, exc)
    print(f"reprocessed {done} payload(s), {failed} failed, {records} rows inserted/updated")
    return 1 if failed else 0


def cmd_health(_args) -> int:
    from app.services import health
    from app.services.database import session_scope
    from app.services.normalizer import to_local

    settings = get_settings()
    with session_scope() as session:
        rows = health.all_health(session)
        if not rows:
            print("no jobs registered yet - run `python -m app.cli init-db`")
            return 0
        for h in rows:
            status = health.effective_status(h, settings.health_stale_factor)
            last = to_local(h.last_success_at)
            print(h.job)
            print(f"  STATUS: {status}" + ("" if h.schema_verified else "   (parser not yet verified on real data)"))
            print(f"  Last Success: {last:%Y-%m-%d %H:%M} (Asia/Bangkok)" if last else "  Last Success: -")
            print(f"  Latency: {h.last_latency_ms} ms" if h.last_latency_ms is not None else "  Latency: -")
            if h.last_error and status != "OK":
                print(f"  Last error: {h.last_error[:300]}")
    return 0


def _parse_tile(t: str) -> tuple[int, int]:
    lat = int(t[1:3]) * (1 if t[0] == "N" else -1)
    lon = int(t[4:7]) * (1 if t[3] == "E" else -1)
    return lat, lon


def cmd_terrain_download(args) -> int:
    from app.services.database import session_scope
    from app.services.dem_download import download_dataset

    settings = get_settings()
    datasets = [args.dataset] if args.dataset else settings.terrain_dataset_list
    tiles = [_parse_tile(t) for t in args.tile] if args.tile else None
    failed = 0
    for ds in datasets:
        with session_scope() as session:
            result = download_dataset(session, ds, settings, tiles=tiles)
        print(result)
        failed += result.get("failed", 0)
    return 1 if failed else 0


def cmd_terrain_status(_args) -> int:
    from sqlalchemy import func

    from app.models import DemTile
    from app.services.database import session_scope

    with session_scope() as session:
        rows = session.execute(select(DemTile.dataset, DemTile.status, func.count(), func.sum(DemTile.bytes))
                               .group_by(DemTile.dataset, DemTile.status).order_by(DemTile.dataset)).all()
    for ds, status, n, size in rows:
        print(f"{ds:18} {status:14} {n:4} tiles {float(size or 0) / 1e9:7.2f} GB")
    return 0


def cmd_waterways_import(args) -> int:
    from app.services.database import session_scope
    from app.services.waterways import download_extract, import_extract

    path = download_extract(get_settings(), force=args.refresh)
    with session_scope() as session:
        print(import_extract(session, path))
    return 0


def cmd_terrain_precompute(_args) -> int:
    from app.services.database import session_scope
    from app.services.terrain_data import precompute

    with session_scope() as session:
        print(precompute(session))
    return 0


def cmd_hydro_import(args) -> int:
    from app.services import hydro_import
    from app.services.database import session_scope

    datasets = ["hydrobasins_v1c", "hydrorivers_v10"] + ([] if args.no_rasters else
                                                       ["hydrosheds_dir_15s", "hydrosheds_acc_15s"])
    with session_scope() as session:
        if not args.skip_download:
            print("download", hydro_import.download(session, datasets))
        print("basins", hydro_import.import_basins(session))
        print("rivers", hydro_import.import_rivers(session))
    if not args.no_rasters:
        print("rasters", hydro_import.clip_rasters())
    return 0


def cmd_hydro_link(_args) -> int:
    from app.services.database import session_scope
    from app.services.station_network import build_relations, link_all

    with session_scope() as session:
        print("links", link_all(session))
        print("relations", build_relations(session))
    return 0


def _as_of(value: str | None):
    from datetime import datetime, timezone

    if not value:
        return None
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def cmd_features_snapshot(args) -> int:
    from app.services.database import session_scope
    from app.services.water_features import snapshot

    with session_scope() as session:
        print(snapshot(session, _as_of(args.as_of), with_forecast=not args.no_forecast))
    return 0


def cmd_features_backfill(args) -> int:
    from datetime import timedelta

    from app.services.database import session_scope
    from app.services.normalizer import utcnow
    from app.services.water_features import label_due, snapshot

    end = utcnow().replace(minute=0, second=0, microsecond=0)
    with session_scope() as session:
        for h in range(args.hours, 0, -1):
            print(snapshot(session, end - timedelta(hours=h), with_forecast=not args.no_forecast))
        print("label", label_due(session))
    return 0


def cmd_features_label(_args) -> int:
    from app.services.database import session_scope
    from app.services.water_features import label_due

    with session_scope() as session:
        print(label_due(session))
    return 0


def cmd_run_due(_args) -> int:
    import json

    from app.services.maintenance import run_due

    report = run_due()
    print(json.dumps(report, ensure_ascii=False, default=str, indent=1))
    return 0


def cmd_prune(_args) -> int:
    from app.services.database import session_scope
    from app.services.maintenance import prune

    with session_scope() as session:
        print(prune(session))
    return 0


def cmd_features_export(args) -> int:
    from app.services.database import session_scope
    from app.services.maintenance import export_training

    before = _as_of(args.before)
    with session_scope() as session:
        n = export_training(session, Path(args.out), before)
    print({"exported": n, "file": args.out, "before": before.isoformat()})
    return 0


def cmd_features_delete(args) -> int:
    from sqlalchemy import delete

    from app.models import WaterForecastTraining
    from app.services.database import session_scope

    before = _as_of(args.before)
    with session_scope() as session:
        n = session.execute(delete(WaterForecastTraining).where(WaterForecastTraining.prediction_time < before)).rowcount
        session.commit()
    print({"deleted": n, "before": before.isoformat()})
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    sub.add_parser("jobs").set_defaults(func=cmd_jobs)
    p = sub.add_parser("collect")
    p.add_argument("job")
    p.set_defaults(func=cmd_collect)
    p = sub.add_parser("backfill-openmeteo")
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.set_defaults(func=cmd_backfill_openmeteo)
    p = sub.add_parser("backfill-rid")
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--medium", action="store_true")
    p.set_defaults(func=cmd_backfill_rid)
    p = sub.add_parser("reprocess")
    p.add_argument("--job", required=True)
    p.add_argument("--since", type=date.fromisoformat)
    p.add_argument("--failed-only", action="store_true")
    p.set_defaults(func=cmd_reprocess)
    sub.add_parser("health").set_defaults(func=cmd_health)
    p = sub.add_parser("terrain-download")
    p.add_argument("--dataset")
    p.add_argument("--tile", action="append", help="e.g. N13E100 (repeatable); default: all tiles covering Thailand")
    p.set_defaults(func=cmd_terrain_download)
    sub.add_parser("terrain-status").set_defaults(func=cmd_terrain_status)
    sub.add_parser("terrain-precompute").set_defaults(func=cmd_terrain_precompute)
    sub.add_parser("hydro-link").set_defaults(func=cmd_hydro_link)
    p = sub.add_parser("features-snapshot")
    p.add_argument("--as-of")
    p.add_argument("--no-forecast", action="store_true")
    p.set_defaults(func=cmd_features_snapshot)
    p = sub.add_parser("features-backfill")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--no-forecast", action="store_true")
    p.set_defaults(func=cmd_features_backfill)
    sub.add_parser("features-label").set_defaults(func=cmd_features_label)
    sub.add_parser("run-due").set_defaults(func=cmd_run_due)
    sub.add_parser("prune").set_defaults(func=cmd_prune)
    p = sub.add_parser("features-export")
    p.add_argument("--before", required=True, help="export rows with prediction_time before this UTC time")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_features_export)
    p = sub.add_parser("features-delete")
    p.add_argument("--before", required=True, help="delete rows with prediction_time before this UTC time")
    p.set_defaults(func=cmd_features_delete)
    p = sub.add_parser("hydro-import")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--no-rasters", action="store_true", help="skip the 15\" rasters (hosts without a data disk)")
    p.set_defaults(func=cmd_hydro_import)
    p = sub.add_parser("waterways-import")
    p.add_argument("--refresh", action="store_true", help="download the extract again")
    p.set_defaults(func=cmd_waterways_import)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
