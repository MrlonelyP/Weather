"""Command line tools.

    python -m app.cli init-db                      # alembic upgrade head + seed locations/health rows
    python -m app.cli jobs                         # list collector jobs and their configuration state
    python -m app.cli collect <job>|all            # run collector(s) once, now
    python -m app.cli backfill-openmeteo --start 2026-09-01 --end 2026-09-27
    python -m app.cli backfill-rid --start 2026-09-01 --end 2026-09-27 [--medium]
    python -m app.cli reprocess --job tmd.synoptic [--since 2026-09-01] [--failed-only]
    python -m app.cli health                       # source health report
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
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
