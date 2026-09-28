"""Reservoir status for display: per dam with day-over-day change, and the national total.

National % = sum(current volume) / sum(normal storage) - the same basis RID uses for
percent_storage (ปริมาณน้ำเก็บกัก), so it is comparable with the per-dam figures.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Reservoir, ReservoirStatus


def _by_date(session: Session, day) -> dict[int, ReservoirStatus]:
    rows = session.execute(select(ReservoirStatus).where(ReservoirStatus.observed_date == day)).scalars()
    return {r.reservoir_id: r for r in rows}


def _total_pct(statuses) -> float | None:
    pairs = [(s.storage_mcm, s.normal_storage_mcm) for s in statuses
             if s.storage_mcm is not None and s.normal_storage_mcm]
    if not pairs:
        return None
    return round(sum(v for v, _ in pairs) / sum(n for _, n in pairs) * 100, 2)


def reservoirs_overview(session: Session, size_class: str | None = "large") -> dict:
    dates = [d for (d,) in session.execute(
        select(ReservoirStatus.observed_date).distinct().order_by(ReservoirStatus.observed_date.desc()).limit(2))]
    if not dates:
        return {"observed_date": None, "previous_date": None, "total_pct": None, "total_pct_change": None,
                "reservoirs": []}
    latest = _by_date(session, dates[0])
    prev = _by_date(session, dates[1]) if len(dates) > 1 else {}
    regs = {r.id: r for r in session.execute(select(Reservoir)).scalars()}
    items = []
    for rid, s in latest.items():
        r = regs[rid]
        if size_class and r.size_class != size_class:
            continue
        p = prev.get(rid)
        items.append({
            "reservoir_code": r.reservoir_code, "name": r.name_th, "region": r.region, "size_class": r.size_class,
            "lat": r.lat, "lon": r.lon,
            "volume_mcm": s.storage_mcm, "normal_storage_mcm": s.normal_storage_mcm, "capacity_mcm": s.capacity_mcm,
            "pct": s.storage_pct, "pct_change": None if (p is None or p.storage_pct is None or s.storage_pct is None)
            else round(s.storage_pct - p.storage_pct, 2),
            "usable_mcm": s.usable_storage_mcm, "usable_pct": s.usable_storage_pct,
            "inflow_mcm_day": s.inflow_mcm_day, "outflow_mcm_day": s.outflow_mcm_day,
            "inflow_m3s": s.inflow_m3s, "outflow_m3s": s.outflow_m3s,
            "outflow_change_mcm_day": None if (p is None or p.outflow_mcm_day is None or s.outflow_mcm_day is None)
            else round(s.outflow_mcm_day - p.outflow_mcm_day, 2),
            "observed_date": s.observed_date, "raw_payload_id": s.raw_payload_id, "source": s.source,
        })
    items.sort(key=lambda x: -(x["pct"] or 0))
    total = _total_pct([latest[k] for k in latest if regs[k].size_class == size_class or not size_class])
    total_prev = _total_pct([prev[k] for k in prev if regs[k].size_class == size_class or not size_class])
    return {
        "observed_date": dates[0], "previous_date": dates[1] if len(dates) > 1 else None,
        "total_pct": total, "total_pct_change": None if total is None or total_prev is None
        else round(total - total_prev, 2),
        "total_basis": "sum(volume) / sum(normal storage), RID",
        "coordinates_note": "RID API ไม่มีพิกัดเขื่อน จึงยังแสดงบนแผนที่ไม่ได้",
        "reservoirs": items,
    }


def reservoir_count(session: Session) -> int:
    return session.execute(select(func.count(Reservoir.id))).scalar_one()
