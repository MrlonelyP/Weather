"""Water forecast feature set + historical training rows (no model is trained here).

`station_features(station, as_of)` uses only data stored at or before `as_of`
(observations with observed_at <= as_of, forecast runs fetched by as_of), so a
snapshot built later for a past hour has no look-ahead. Missing inputs stay
null with a reason; nothing is interpolated or invented.

`snapshot()` writes one row per station x horizon into water_forecast_training.
`label_due()` fills actual_water_level_m / actual_change_m once the target time
has an observation within the tolerance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.engines import engine_config
from app.engines.water_calc import change_over, rate_of_rise_m_per_h
from app.models import StationRelation, TerrainProfile, WaterForecastTraining, WaterLevelObservation, WaterStation
from app.services import catchment_rain
from app.services.normalizer import utcnow
from app.services.station_network import link_for, station_catchment
from app.services.water_data import sane_ref

log = logging.getLogger(__name__)
NOT_AVAILABLE = {
    "reservoir_release": "RID ไม่ให้พิกัดเขื่อน จึงยังระบุไม่ได้ว่าเขื่อนใดอยู่ต้นน้ำของสถานี",
    "tide": "ยังไม่มีแหล่งข้อมูลระดับน้ำทะเลแบบใกล้เวลาจริง",
}


def _cfg() -> dict:
    return engine_config()["features"]


def _series(session: Session, station_id: int, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    return [(t, v) for t, v in session.execute(
        select(WaterLevelObservation.observed_at, WaterLevelObservation.water_level_m).where(
            WaterLevelObservation.station_id == station_id, WaterLevelObservation.water_level_m.isnot(None),
            WaterLevelObservation.observed_at > start, WaterLevelObservation.observed_at <= end)
        .order_by(WaterLevelObservation.observed_at))]


def water_block(session: Session, st: WaterStation, as_of: datetime) -> dict | None:
    cfg_w = engine_config()["water"]
    series = _series(session, st.id, as_of - timedelta(hours=4), as_of)
    if not series or as_of - series[-1][0] > timedelta(hours=cfg_w["max_obs_age_hours"]):
        return None
    t, level = series[-1]
    ago1 = change_over(series, 1.0)
    ago3 = change_over(series, 3.0)
    rate = rate_of_rise_m_per_h(series, cfg_w["rate_window_hours"])
    bank = sane_ref(st.bank_level_m, level)
    return {"current_water_level_m": round(level, 3), "observed_at": t.isoformat(),
            "water_level_1h_ago_m": None if ago1 is None else round(level - ago1, 3),
            "water_level_3h_ago_m": None if ago3 is None else round(level - ago3, 3),
            "rate_of_rise_cm_per_h": None if rate is None else round(rate * 100, 2),
            "distance_to_bank_m": None if bank is None else round(bank - level, 3),
            "points_4h": len(series)}


def station_features(session: Session, st: WaterStation, as_of: datetime, rain_windows: dict | None = None,
                     with_forecast: bool = True) -> dict | None:
    water = water_block(session, st, as_of)
    if water is None:
        return None
    link = link_for(session, st.id)
    catch = station_catchment(session, link)
    units = catch["units"]
    rain: dict = {"catchment_units": len(units), "catchment_method": catch["method"], "catchment_note": catch["note"]}
    if units:
        rain_windows = rain_windows if rain_windows is not None else catchment_rain.observed_windows(session, as_of)
        obs = catchment_rain.observed(session, units, rain_windows)
        rain |= {f"catchment_rain_{w}": v for w, v in obs["windows"].items()}
        rain["catchment_area_km2"] = catch["area_km2"] or obs["catchment_area_km2"]
        if with_forecast:
            fc = catchment_rain.forecast(session, units, (st.lat, st.lon), as_of)
            rain["forecast_method"] = fc.get("method")
            for k in catchment_rain.FORECAST_WINDOWS:
                rain[f"forecast_catchment_{k}"] = (fc.get("windows") or {}).get(k)
            if not fc.get("available"):
                rain["forecast_reason"] = fc.get("reason")
        else:
            rain["forecast_reason"] = "ไม่ได้คำนวณในโหมดนี้"
    else:
        rain["reason"] = "สถานียังไม่ถูกผูกกับพื้นที่รับน้ำ (HydroBASINS)"

    upstream = []
    rels = session.execute(select(StationRelation).where(
        StationRelation.station_id == st.id, StationRelation.relation == "upstream")
        .order_by(StationRelation.same_river_name.desc(), StationRelation.river_distance_km)
        .limit(_cfg()["upstream_max_stations"])).scalars().all()
    for rel in rels:
        other = session.get(WaterStation, rel.other_station_id)
        block = water_block(session, other, as_of) if other else None
        upstream.append({"station_code": other.station_code if other else None, "river_distance_km": rel.river_distance_km,
                         "same_river_name": rel.same_river_name, "confidence": rel.confidence,
                         "upstream_water_level_m": block["current_water_level_m"] if block else None,
                         "upstream_rate_of_rise_cm_per_h": block["rate_of_rise_cm_per_h"] if block else None,
                         "upstream_distance_to_bank_m": block["distance_to_bank_m"] if block else None})

    terrain = {}
    tp = session.execute(select(TerrainProfile).where(
        TerrainProfile.subject_type == "water_station", TerrainProfile.subject_code == f"{st.source}:{st.station_code}",
        TerrainProfile.dataset == "copernicus_glo30")).scalar_one_or_none()
    if tp:
        terrain = {"relative_elevation_500_m": tp.rel_elev_500_m, "local_depression": tp.possible_local_depression,
                   "terrain_position": tp.terrain_position, "dataset": tp.dataset, "method_version": tp.method_version}
    return {"water": {**water, "reservoir_release": None, "tide": None, "not_available": NOT_AVAILABLE},
            "rain": rain, "upstream": upstream, "terrain": terrain,
            "hydro_link": {"reach_method": link.reach_method if link else None,
                           "hyriv_id": link.hyriv_id if link else None,
                           "hybas_l12": link.hybas_l12 if link else None,
                           "confidence": link.confidence if link else None}}


def source_versions() -> dict:
    e = engine_config()
    return {"feature_version": _cfg()["feature_version"], "catchment": e["catchment"]["method_version"],
            "flow": e["flow"]["method_version"], "terrain": e["terrain"]["method_version"],
            "hydrobasins": "v1c", "hydrorivers": "v1.0", "dem": "copernicus_glo30",
            "water_calc": "system_computed_v0.1"}


def snapshot(session: Session, as_of: datetime | None = None, with_forecast: bool = True) -> dict:
    from app.config.settings import get_settings

    settings = get_settings()
    as_of = (as_of or utcnow()).replace(minute=0, second=0, microsecond=0)
    q = select(WaterStation).where(WaterStation.source == "thaiwater", WaterStation.station_kind == "river")
    if settings.features_station_scope == "key":
        q = q.where(WaterStation.extra["is_key_station"].as_boolean().is_(True))
    elif settings.features_station_scope == "provinces":
        q = q.where(WaterStation.province_code.in_(settings.thaiwater_history_provinces_list))
    stations = session.execute(q).scalars().all()
    horizons = settings.features_horizons_list or _cfg()["horizons_hours"]
    rain_windows = catchment_rain.observed_windows(session, as_of)
    versions = source_versions()
    rows, skipped = 0, 0
    for st in stations:
        f = station_features(session, st, as_of, rain_windows, with_forecast)
        if f is None:
            skipped += 1
            continue
        for h in horizons:
            stmt = insert(WaterForecastTraining).values(
                station_id=st.id, prediction_time=as_of, horizon_hours=h, target_time=as_of + timedelta(hours=h),
                feature_version=versions["feature_version"], current_level_m=f["water"]["current_water_level_m"],
                features=f["water"] | {"hydro_link": f["hydro_link"]}, rain_features=f["rain"],
                upstream_features={"stations": f["upstream"]}, terrain_features=f["terrain"],
                source_versions=versions).on_conflict_do_nothing(
                constraint="uq_water_forecast_training_key").returning(WaterForecastTraining.id)
            rows += len(session.execute(stmt).all())
        session.commit()
    log.info("feature snapshot %s: %d rows, %d stations without a current reading", as_of, rows, skipped)
    return {"as_of": as_of.isoformat(), "rows": rows, "stations_without_reading": skipped}


def label_due(session: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    tol = timedelta(minutes=_cfg()["label_tolerance_minutes"])
    due = session.execute(select(WaterForecastTraining).where(
        WaterForecastTraining.labelled_at.is_(None), WaterForecastTraining.target_time <= now - tol)
        .limit(20000)).scalars().all()
    labelled = 0
    for row in due:
        obs = session.execute(text("""
            SELECT observed_at, water_level_m FROM water_level_observation
            WHERE station_id = :s AND water_level_m IS NOT NULL AND observed_at BETWEEN :a AND :b
            ORDER BY abs(extract(epoch FROM observed_at - :t)) LIMIT 1"""),
            {"s": row.station_id, "a": row.target_time - tol, "b": row.target_time + tol, "t": row.target_time}).one_or_none()
        if obs is None:
            continue
        row.actual_water_level_m = obs.water_level_m
        row.actual_observed_at = obs.observed_at
        row.actual_change_m = None if row.current_level_m is None else round(obs.water_level_m - row.current_level_m, 3)
        row.labelled_at = now
        labelled += 1
    session.commit()
    return {"due": len(due), "labelled": labelled}


def run_hourly() -> None:
    """Scheduler entry point: snapshot this hour, then label rows whose target time has passed."""
    from app.services.database import session_scope

    try:
        with session_scope() as session:
            snapshot(session)
            label_due(session)
    except Exception:  # noqa: BLE001 - must never stop the scheduler
        log.exception("feature snapshot failed")
