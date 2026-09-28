"""Observed rainfall (gauges) - kept strictly apart from forecast rain.

Sources:
  ThaiWater rain gauges: rain_24h (24 h) and rain_1h (last hour) each hourly poll.
      3 h / 6 h = sum of rain_1h over consecutive hourly readings we have stored;
      reported only when every hour of the window is present.
  TMD synoptic: rain with its own accumulation period (3/6/12/24 h).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.models import Location, WaterLevelObservation, WaterStation, WeatherObservation, WeatherStation
from app.services.normalizer import utcnow

WINDOWS = {"1h": 1, "3h": 3, "6h": 6, "24h": 24}
MAX_AGE = timedelta(minutes=90)


def _hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def gauge_windows(session: Session, window: str, now: datetime | None = None) -> dict:
    """Observed rain per gauge for a window ending at the latest hourly reading."""
    now = now or utcnow()
    n = WINDOWS[window]
    since = now - timedelta(hours=max(n, 1) + 2)
    rows = session.execute(
        select(WaterStation.id, WaterStation.station_code, WaterStation.name_th, WaterStation.lat,
               WaterStation.lon, WaterStation.province_code, WaterStation.extra,
               WaterLevelObservation.observed_at, WaterLevelObservation.rain_mm, WaterLevelObservation.rain_1h_mm)
        .join(WaterLevelObservation, WaterLevelObservation.station_id == WaterStation.id)
        .where(WaterStation.source == "thaiwater", WaterStation.station_kind == "rain_gauge",
               WaterLevelObservation.observed_at >= since, WaterLevelObservation.observed_at <= now)
        .order_by(WaterStation.id, WaterLevelObservation.observed_at)).all()
    per_station: dict[int, list] = defaultdict(list)
    meta = {}
    for r in rows:
        per_station[r.id].append(r)
        meta[r.id] = r
    points, incomplete = [], 0
    for sid, obs in per_station.items():
        last = obs[-1]
        if now - last.observed_at > MAX_AGE:
            continue
        value = None
        if window == "24h":
            value = last.rain_mm
        elif window == "1h":
            value = last.rain_1h_mm
        else:
            by_hour = {_hour(o.observed_at): o.rain_1h_mm for o in obs if o.rain_1h_mm is not None}
            needed = [_hour(last.observed_at) - timedelta(hours=k) for k in range(n)]
            if all(h in by_hour for h in needed):
                value = sum(by_hour[h] for h in needed)
            else:
                incomplete += 1
                continue
        if value is None:
            continue
        m = meta[sid]
        points.append({"station_id": sid, "station_code": m.station_code, "name": m.name_th,
                       "province": (m.extra or {}).get("province_name"), "province_code": m.province_code,
                       "lat": m.lat, "lon": m.lon, "value_mm": round(value, 1), "window": window,
                       "observed_at": last.observed_at, "source": "thaiwater", "kind": "observed"})
    note = None
    if window in ("3h", "6h"):
        note = (f"สะสมจากฝนรายชั่วโมงที่ระบบเก็บไว้ ต้องมีครบทุกชั่วโมง; สถานีที่ข้อมูลยังไม่ครบ {incomplete} แห่ง"
                if incomplete else "สะสมจากฝนรายชั่วโมงที่ระบบเก็บไว้")
    return {"window": window, "kind": "observed", "points": points, "stations": len(points),
            "incomplete_stations": incomplete, "note": note}


def synoptic_rain(session: Session, window_hours: int, now: datetime | None = None) -> list[dict]:
    """TMD synoptic rain with exactly this accumulation period, newest per station (last 6 h)."""
    now = now or utcnow()
    rows = session.execute(
        select(WeatherStation, WeatherObservation)
        .join(WeatherObservation, WeatherObservation.station_id == WeatherStation.id)
        .where(WeatherObservation.observed_at >= now - timedelta(hours=6),
               WeatherObservation.rain_period_hours == window_hours,
               WeatherObservation.rain_mm.isnot(None))
        .order_by(WeatherObservation.observed_at.desc())).all()
    seen, out = set(), []
    for st, o in rows:
        if st.id in seen:
            continue
        seen.add(st.id)
        out.append({"station_code": st.station_code, "name": st.name_th, "lat": st.lat, "lon": st.lon,
                    "value_mm": o.rain_mm, "window": f"{window_hours}h", "observed_at": o.observed_at,
                    "source": "tmd", "kind": "observed"})
    return out


def observed_hourly_near(session: Session, location: Location, hours: int, radius_km: float,
                         now: datetime | None = None) -> dict:
    """Hourly observed rain around a location: mean/max of rain_1h over gauges within radius."""
    now = now or utcnow()
    point = func.ST_SetSRID(func.ST_MakePoint(location.lon, location.lat), 4326)
    rows = session.execute(
        select(WaterLevelObservation.observed_at, WaterLevelObservation.rain_1h_mm, WaterStation.id)
        .join(WaterStation, WaterStation.id == WaterLevelObservation.station_id)
        .where(WaterStation.source == "thaiwater", WaterStation.station_kind == "rain_gauge",
               WaterLevelObservation.rain_1h_mm.isnot(None),
               WaterLevelObservation.observed_at >= now - timedelta(hours=hours),
               func.ST_DWithin(cast(WaterStation.geom, Geography), cast(point, Geography), radius_km * 1000))
    ).all()
    buckets: dict[datetime, list[float]] = defaultdict(list)
    stations = set()
    for t, v, sid in rows:
        buckets[_hour(t)].append(v)
        stations.add(sid)
    series = [{"time": t, "mean_mm": round(sum(v) / len(v), 2), "max_mm": round(max(v), 1), "n_stations": len(v)}
              for t, v in sorted(buckets.items())]
    return {"radius_km": radius_km, "stations": len(stations), "series": series,
            "note": "ฝนรายชั่วโมงที่ตรวจวัดได้ เฉพาะชั่วโมงที่ระบบดึงข้อมูลไว้แล้ว"}
