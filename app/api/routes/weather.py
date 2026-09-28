from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.timefmt import times
from app.models import ForecastRun, Location, WeatherForecast, WeatherObservation, WeatherStation
from app.services.database import get_db
from app.services.normalizer import parse_datetime, utcnow

router = APIRouter(prefix="/weather")

FORECAST_VALUES = [
    "temperature_c", "humidity_pct", "precipitation_mm", "rain_mm", "precip_probability_pct",
    "pressure_msl_hpa", "cloud_cover_pct", "wind_speed_kmh", "wind_direction_deg", "wind_gust_kmh",
    "soil_moisture_m3m3", "soil_moisture_layer",
]
OBS_VALUES = [
    "temperature_c", "dew_point_c", "humidity_pct", "pressure_msl_hpa", "station_pressure_hpa",
    "visibility_km", "wind_speed_kmh", "wind_direction_deg", "cloud_cover_okta", "rain_mm",
    "rain_period_hours", "rain_24h_mm", "max_temperature_c", "min_temperature_c",
]


def _location(db: Session, code: str) -> Location:
    loc = db.execute(select(Location).where(Location.code == code)).scalar_one_or_none()
    if loc is None:
        codes = db.execute(select(Location.code).order_by(Location.id)).scalars().all()
        raise HTTPException(404, f"unknown location {code!r}; available: {codes}")
    return loc


def _location_view(loc: Location) -> dict:
    return {"code": loc.code, "name_en": loc.name_en, "name_th": loc.name_th,
            "province_code": loc.province_code, "lat": loc.lat, "lon": loc.lon}


def _forecast_view(f: WeatherForecast) -> dict:
    return {
        "source": f.source, "model": f.model, "product": f.product,
        **times(model_run_time=f.model_run_time, forecast_time=f.forecast_time, ingested_at=f.ingested_at),
        "lead_time_hours": f.lead_time_hours,
        "grid": {"lat": f.grid_lat, "lon": f.grid_lon, "elevation_m": f.grid_elevation_m},
        **{c: getattr(f, c) for c in FORECAST_VALUES},
        "raw_payload_id": f.raw_payload_id,
    }


def _latest_run(db: Session, model: str) -> ForecastRun | None:
    return db.execute(
        select(ForecastRun).where(ForecastRun.model == model)
        .order_by(ForecastRun.model_run_time.desc()).limit(1)
    ).scalar_one_or_none()


def _models(db: Session) -> list[str]:
    return list(db.execute(select(ForecastRun.model).distinct().order_by(ForecastRun.model)).scalars())


@router.get("/current")
def weather_current(
    location: str = Query("bangkok", description="location code (see /weather/locations)"),
    station: str | None = Query(None, description="station code (e.g. WMO id) to restrict observations"),
    max_age_hours: int = Query(6, ge=1, le=72),
    db: Session = Depends(get_db),
):
    """Latest station observations + each model's value for the current hour at the location.

    Observations and model values are reported separately and labelled - a model
    value is never presented as an observation.
    """
    loc = _location(db, location)
    now = utcnow()

    latest = (
        select(WeatherObservation.station_id, func.max(WeatherObservation.observed_at).label("t"))
        .where(WeatherObservation.observed_at >= now - timedelta(hours=max_age_hours))
        .group_by(WeatherObservation.station_id).subquery()
    )
    q = (
        select(WeatherObservation, WeatherStation)
        .join(latest, (WeatherObservation.station_id == latest.c.station_id)
              & (WeatherObservation.observed_at == latest.c.t))
        .join(WeatherStation, WeatherStation.id == WeatherObservation.station_id)
    )
    if station:
        q = q.where(WeatherStation.station_code == station)
    elif loc.province_code:
        # stations whose province is known and matches; stations without province metadata are listed too
        q = q.where((WeatherStation.province_code == loc.province_code) | WeatherStation.province_code.is_(None))
    observations = [{
        "source": o.source, "station_code": s.station_code, "station_name": s.name_en or s.name_th,
        "province_code": s.province_code, "obs_type": o.obs_type,
        **times(observed_at=o.observed_at, ingested_at=o.ingested_at),
        **{c: getattr(o, c) for c in OBS_VALUES},
        "raw_payload_id": o.raw_payload_id,
    } for o, s in db.execute(q.order_by(WeatherStation.station_code)).all()]

    hour = now.replace(minute=0, second=0, microsecond=0)
    model_now = []
    for model in _models(db):
        run = _latest_run(db, model)
        if run is None:
            continue
        f = db.execute(
            select(WeatherForecast).where(WeatherForecast.forecast_run_id == run.id,
                                          WeatherForecast.location_id == loc.id,
                                          WeatherForecast.forecast_time == hour)
        ).scalar_one_or_none()
        if f is not None:
            model_now.append(_forecast_view(f))

    return {
        "location": _location_view(loc),
        **times(generated_at=now),
        "observations": observations,
        "observation_note": None if observations else
        "no observation within max_age_hours (collector may not have run or source unavailable)",
        "model_current_hour": model_now,
    }


@router.get("/forecast")
def weather_forecast(
    location: str = Query("bangkok"),
    model: str | None = Query(None, description="ECMWF | GFS | JMA; default all"),
    run: str = Query("latest", description="'latest' or a model run time (ISO-8601, UTC)"),
    hours: int = Query(72, ge=1, le=384),
    db: Session = Depends(get_db),
):
    """Hourly forecast of the chosen run(s); model_run_time and forecast_time are separate fields."""
    loc = _location(db, location)
    models = [model] if model else _models(db)
    result = []
    for m in models:
        if run == "latest":
            fr = _latest_run(db, m)
        else:
            run_time = parse_datetime(run)
            if run_time is None:
                raise HTTPException(422, "run must be 'latest' or an ISO-8601 datetime")
            fr = db.execute(select(ForecastRun).where(ForecastRun.model == m,
                                                      ForecastRun.model_run_time == run_time)).scalar_one_or_none()
        if fr is None:
            result.append({"model": m, "run": None, "values": [], "note": "no stored run"})
            continue
        rows = db.execute(
            select(WeatherForecast)
            .where(WeatherForecast.forecast_run_id == fr.id, WeatherForecast.location_id == loc.id)
            .order_by(WeatherForecast.forecast_time).limit(hours)
        ).scalars()
        result.append({
            "model": m,
            "run": {"id": fr.id, "source": fr.source,
                    **times(model_run_time=fr.model_run_time, available_at=fr.available_at, fetched_at=fr.fetched_at),
                    "temporal_resolution_seconds": fr.temporal_resolution_seconds},
            "values": [_forecast_view(f) for f in rows],
        })
    return {"location": _location_view(loc), "forecasts": result}


@router.get("/runs")
def forecast_runs(model: str | None = None, limit: int = Query(40, ge=1, le=500), db: Session = Depends(get_db)):
    q = select(ForecastRun).order_by(ForecastRun.model_run_time.desc()).limit(limit)
    if model:
        q = q.where(ForecastRun.model == model)
    return {"runs": [{
        "id": r.id, "source": r.source, "model": r.model,
        **times(model_run_time=r.model_run_time, available_at=r.available_at, fetched_at=r.fetched_at),
        "temporal_resolution_seconds": r.temporal_resolution_seconds,
    } for r in db.execute(q).scalars()]}


@router.get("/locations")
def locations(db: Session = Depends(get_db)):
    return {"locations": [_location_view(l) | {"test_area": l.test_area, "active": l.active}
                          for l in db.execute(select(Location).order_by(Location.id)).scalars()]}
