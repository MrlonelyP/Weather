"""Load the latest stored model runs for a location and build our consensus forecast."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines import engine_config
from app.engines.forecast_consensus import ModelSeries, build_consensus
from app.models import ForecastRun, Location, WeatherForecast
from app.services.normalizer import utcnow

VALUE_COLUMNS = [
    "temperature_c", "humidity_pct", "precipitation_mm", "rain_mm", "precip_probability_pct", "pressure_msl_hpa",
    "cloud_cover_pct", "wind_speed_kmh", "wind_direction_deg", "wind_gust_kmh", "soil_moisture_m3m3",
    "cape_jkg", "visibility_m", "runoff_mm",
]


def get_location(session: Session, code: str) -> Location | None:
    return session.execute(select(Location).where(Location.code == code)).scalar_one_or_none()


def latest_runs(session: Session, now: datetime | None = None) -> list[ForecastRun]:
    """Newest run per model, if not older than max_run_age_hours."""
    now = now or utcnow()
    max_age = timedelta(hours=engine_config()["consensus"]["max_run_age_hours"])
    runs = []
    for (model,) in session.execute(select(ForecastRun.model).distinct().order_by(ForecastRun.model)):
        run = session.execute(select(ForecastRun).where(ForecastRun.model == model)
                              .order_by(ForecastRun.model_run_time.desc()).limit(1)).scalar_one()
        if now - run.model_run_time <= max_age:
            runs.append(run)
    return runs


def model_series(session: Session, location: Location, runs: list[ForecastRun], start: datetime,
                 end: datetime) -> list[ModelSeries]:
    series = []
    for run in runs:
        rows = session.execute(
            select(WeatherForecast).where(WeatherForecast.forecast_run_id == run.id,
                                          WeatherForecast.location_id == location.id,
                                          WeatherForecast.forecast_time >= start,
                                          WeatherForecast.forecast_time <= end)
            .order_by(WeatherForecast.forecast_time)).scalars()
        s = ModelSeries(model=run.model, model_run_time=run.model_run_time)
        for r in rows:
            s.points[r.forecast_time] = {c: getattr(r, c) for c in VALUE_COLUMNS}
        if s.points:
            series.append(s)
    return series


def consensus_for_location(session: Session, location: Location, horizon_hours: int = 48,
                           now: datetime | None = None) -> dict:
    now = now or utcnow()
    runs = latest_runs(session, now)
    hour0 = now.replace(minute=0, second=0, microsecond=0)
    series = model_series(session, location, runs, hour0, hour0 + timedelta(hours=horizon_hours))
    result = build_consensus(series, now, horizon_hours)
    result["runs"] = [{"model": r.model, "model_run_time": r.model_run_time, "fetched_at": r.fetched_at,
                       "available_at": r.available_at} for r in runs]
    return result
