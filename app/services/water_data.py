"""Water stations with computed state (level, distance to bank, rate of rise, trend, status)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.engines import engine_config
from app.engines.water_calc import STATUS_RANK, station_state
from app.models import WaterLevelObservation, WaterStation
from app.models.water import reports_rain
from app.services.normalizer import utcnow



# A reference level (bank / warning / critical) from the source is not used when it is 0
# (placeholder seen for some dam gauges) or more than this far from the observed level
# (different datum). We never replace it with a guess - it is reported as missing.
MAX_REF_GAP_M = 30.0


def sane_ref(ref: float | None, level: float | None) -> float | None:
    if ref is None or ref == 0:
        return None
    if level is not None and abs(level - ref) > MAX_REF_GAP_M:
        return None
    return ref


def _ref_note(raw: dict, level: float | None) -> str | None:
    dropped = [k for k, v in raw.items() if v is not None and sane_ref(v, level) is None]
    if not dropped:
        return None
    names = {"bank": "ตลิ่ง", "warning": "เฝ้าระวัง", "critical": "วิกฤต"}
    return ("ไม่ใช้ระดับ" + "/".join(names[k] for k in dropped)
            + " จากต้นทาง เพราะเป็น 0 หรือห่างจากระดับน้ำเกิน 30 ม. (น่าจะคนละระดับอ้างอิง)")


def _station_filter(q, scope: str, provinces: list[str]):
    if scope == "key":
        return q.where(WaterStation.extra["is_key_station"].as_boolean().is_(True))
    if scope == "area":
        return q.where(WaterStation.province_code.in_(provinces))
    return q


def stations_state(session: Session, scope: str = "all", provinces: list[str] | None = None,
                   now: datetime | None = None, at: datetime | None = None) -> list[dict]:
    """State of every river station with a recent reading.

    `at` evaluates the state as of an earlier time (used for "change vs 24 h ago").
    """
    now = now or utcnow()
    ref = at or now
    cfg = engine_config()["water"]
    window = timedelta(hours=cfg["rate_window_hours"] + 1)
    max_age = timedelta(hours=cfg["max_obs_age_hours"])
    q = (select(WaterStation, WaterLevelObservation)
         .join(WaterLevelObservation, WaterLevelObservation.station_id == WaterStation.id)
         .where(WaterStation.source == "thaiwater", WaterStation.station_kind == "river",
                WaterLevelObservation.water_level_m.isnot(None),
                WaterLevelObservation.observed_at > ref - window,
                WaterLevelObservation.observed_at <= ref)
         .order_by(WaterStation.id, WaterLevelObservation.observed_at))
    q = _station_filter(q, scope, provinces or [])
    grouped: dict[int, list] = defaultdict(list)
    stations = {}
    for st, obs in session.execute(q).all():
        grouped[st.id].append(obs)
        stations[st.id] = st
    out = []
    for sid, obs in grouped.items():
        if ref - obs[-1].observed_at > max_age:
            continue
        st = stations[sid]
        level = obs[-1].water_level_m
        refs = {"bank": st.bank_level_m, "warning": st.warning_level_m, "critical": st.critical_level_m}
        state = station_state([(o.observed_at, o.water_level_m) for o in obs], sane_ref(refs["bank"], level),
                              sane_ref(refs["warning"], level), sane_ref(refs["critical"], level))
        state["reference_note"] = _ref_note(refs, level)
        # newest reading that carries the source's own assessment
        src = next((o for o in reversed(obs) if o.source_situation_level is not None
                    or o.source_diff_to_bank_m is not None), None)
        extra = st.extra or {}
        out.append({
            "station_id": sid, "station_code": st.station_code, "name": st.name_th,
            "river": extra.get("river_name"), "basin": st.river_basin,
            "province": extra.get("province_name"), "province_code": st.province_code,
            "amphoe": extra.get("amphoe"), "agency": extra.get("agency"),
            "is_key_station": bool(extra.get("is_key_station")),
            "lat": st.lat, "lon": st.lon,
            "discharge_m3s": obs[-1].discharge_m3s,
            **state,
            "source_assessment": {
                "situation_level": src.source_situation_level if src else None,
                "diff_to_bank_m": src.source_diff_to_bank_m if src else None,
                "diff_to_bank_text": src.source_diff_to_bank_text if src else None,
                "note": "ค่าที่ ThaiWater กำหนด (ไม่ใช่ค่าที่ระบบคำนวณ)",
            },
            "raw_payload_id": obs[-1].raw_payload_id,
            "source": "thaiwater",
        })
    return out


def sort_stations(items: list[dict], by: str = "risk") -> list[dict]:
    if by == "level":
        return sorted(items, key=lambda x: -(x["current_m"] or -999))
    if by == "trend":
        return sorted(items, key=lambda x: -(x["rate_cm_per_h"] if x["rate_cm_per_h"] is not None else -999))
    return sorted(items, key=lambda x: (STATUS_RANK[x["status"]],
                                        x["distance_to_bank_m"] if x["distance_to_bank_m"] is not None else 999))


def station_series(session: Session, station_code: str, hours: int = 48) -> dict | None:
    st = session.execute(select(WaterStation).where(WaterStation.source == "thaiwater",
                                                    WaterStation.station_code == station_code)).scalar_one_or_none()
    if st is None:
        return None
    since = utcnow() - timedelta(hours=hours)
    rows = session.execute(select(WaterLevelObservation.observed_at, WaterLevelObservation.water_level_m,
                                  WaterLevelObservation.discharge_m3s)
                           .where(WaterLevelObservation.station_id == st.id,
                                  WaterLevelObservation.observed_at >= since,
                                  WaterLevelObservation.water_level_m.isnot(None))
                           .order_by(WaterLevelObservation.observed_at)).all()
    level = rows[-1][1] if rows else None
    state = station_state([(t, v) for t, v, _ in rows], sane_ref(st.bank_level_m, level),
                          sane_ref(st.warning_level_m, level), sane_ref(st.critical_level_m, level))
    return {"station_code": st.station_code, "name": st.name_th, "bank_m": st.bank_level_m,
            "series": [{"time": t, "level_m": v, "discharge_m3s": q} for t, v, q in rows], "state": state}


def latest_observation_time(session: Session) -> datetime | None:
    return session.execute(
        select(func.max(WaterLevelObservation.observed_at))
        .join(WaterStation, WaterStation.id == WaterLevelObservation.station_id)
        .where(WaterStation.station_kind == "river")).scalar_one()


# ---------------------------------------------------------------- filters / detail / nearby
def filter_stations(items: list[dict], province: str | None = None, basin: str | None = None,
                    river: str | None = None, status: str | None = None, q: str | None = None) -> list[dict]:
    def ok(s: dict) -> bool:
        if province and s["province_code"] != province:
            return False
        if basin and s["basin"] != basin:
            return False
        if river and s["river"] != river:
            return False
        if status and s["status"] not in status.upper().split(","):
            return False
        if q:
            hay = " ".join(str(s.get(k) or "") for k in ("name", "river", "basin", "province", "amphoe"))
            if q.lower() not in hay.lower():
                return False
        return True
    return [s for s in items if ok(s)]


def filter_options(items: list[dict]) -> dict:
    def count(key, label_key=None):
        c: dict = {}
        for s in items:
            k = s.get(key)
            if k:
                lab = s.get(label_key) if label_key else k
                c.setdefault(k, {"value": k, "label": lab, "count": 0})["count"] += 1
        return sorted(c.values(), key=lambda x: -x["count"])
    return {"provinces": count("province_code", "province"), "basins": count("basin"), "rivers": count("river"),
            "statuses": [{"value": k, "count": sum(1 for s in items if s["status"] == k)}
                         for k in ("CRITICAL", "WARNING", "WATCH", "NORMAL", "UNKNOWN")]}


RANGES = {"6h": 6, "24h": 24, "3d": 72, "7d": 168}


def station_detail(session: Session, station_code: str, range_key: str = "24h") -> dict | None:
    st = session.execute(select(WaterStation).where(WaterStation.source == "thaiwater",
                                                    WaterStation.station_code == station_code)).scalar_one_or_none()
    if st is None:
        return None
    now = utcnow()
    hours = RANGES[range_key]
    since = now - timedelta(hours=max(hours, 24))
    rows = session.execute(
        select(WaterLevelObservation).where(WaterLevelObservation.station_id == st.id,
                                            WaterLevelObservation.observed_at >= since,
                                            WaterLevelObservation.water_level_m.isnot(None))
        .order_by(WaterLevelObservation.observed_at)).scalars().all()
    rate_window = [(o.observed_at, o.water_level_m) for o in rows
                   if o.observed_at >= now - timedelta(hours=engine_config()["water"]["rate_window_hours"] + 1)]
    level = rows[-1].water_level_m if rows else None
    refs = {"bank": st.bank_level_m, "warning": st.warning_level_m, "critical": st.critical_level_m}
    bank, warning, critical = (sane_ref(refs[k], level) for k in ("bank", "warning", "critical"))
    state = station_state(rate_window or [(o.observed_at, o.water_level_m) for o in rows[-1:]],
                          bank, warning, critical)
    state["reference_note"] = _ref_note(refs, level)
    last24 = [o for o in rows if o.observed_at >= now - timedelta(hours=24)]
    mx = max(last24, key=lambda o: o.water_level_m, default=None)
    mn = min(last24, key=lambda o: o.water_level_m, default=None)
    first = session.execute(select(func.min(WaterLevelObservation.observed_at))
                            .where(WaterLevelObservation.station_id == st.id)).scalar_one()
    in_range = [o for o in rows if o.observed_at >= now - timedelta(hours=hours)]
    src = next((o for o in reversed(rows) if o.source_situation_level is not None
                or o.source_diff_to_bank_m is not None), None)
    extra = st.extra or {}
    return {
        "station_code": st.station_code, "name": st.name_th, "river": extra.get("river_name"),
        "basin": st.river_basin, "province": extra.get("province_name"), "province_code": st.province_code,
        "amphoe": extra.get("amphoe"), "tumbon": extra.get("tumbon"), "agency": extra.get("agency"),
        "lat": st.lat, "lon": st.lon, "source": "thaiwater", "datum": st.datum,
        "levels": {"bank_m": bank, "warning_m": warning, "critical_m": critical,
                   "ground_m": st.ground_level_m, "basis": "ระดับอ้างอิงที่ต้นทาง (ThaiWater) กำหนด, ม.รทก.",
                   "note": state["reference_note"]},
        "state": {**state, "discharge_m3s": rows[-1].discharge_m3s if rows else None},
        "stats_24h": {"max_m": mx.water_level_m if mx else None, "max_at": mx.observed_at if mx else None,
                      "min_m": mn.water_level_m if mn else None, "min_at": mn.observed_at if mn else None},
        "source_assessment": {"situation_level": src.source_situation_level if src else None,
                              "diff_to_bank_m": src.source_diff_to_bank_m if src else None,
                              "diff_to_bank_text": src.source_diff_to_bank_text if src else None},
        "range": range_key, "series": [{"time": o.observed_at, "level_m": o.water_level_m,
                                        "discharge_m3s": o.discharge_m3s} for o in in_range],
        "history_available_since": first,
        "history_note": None if first and first <= now - timedelta(hours=hours)
        else "ระบบยังเก็บประวัติของสถานีนี้ไม่ครบช่วงที่เลือก",
        "forecast": None, "forecast_note": "ยังไม่มีแบบจำลองพยากรณ์ระดับน้ำ (แสดงเฉพาะค่าตรวจวัด)",
    }


def nearest_stations(session: Session, lat: float, lon: float, radius_km: float, kind: str = "river",
                     limit: int = 10) -> list[tuple[WaterStation, float]]:
    point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    dist = func.ST_Distance(cast(WaterStation.geom, Geography), cast(point, Geography))
    kind_filter = reports_rain() if kind == "rain_gauge" else WaterStation.station_kind == kind
    return list(session.execute(
        select(WaterStation, dist).where(WaterStation.source == "thaiwater", kind_filter,
                                         func.ST_DWithin(cast(WaterStation.geom, Geography),
                                                         cast(point, Geography), radius_km * 1000))
        .order_by(dist).limit(limit)).all())


def observed_rain_24h_max(session: Session, lat: float, lon: float, radius_km: float = 10) -> float | None:
    ids = [st.id for st, _ in nearest_stations(session, lat, lon, radius_km, "rain_gauge", 80)]
    if not ids:
        return None
    return session.execute(select(func.max(WaterLevelObservation.rain_mm))
                           .where(WaterLevelObservation.station_id.in_(ids),
                                  WaterLevelObservation.observed_at >= utcnow() - timedelta(minutes=90))).scalar_one()
