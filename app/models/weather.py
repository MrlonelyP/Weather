from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProvenanceMixin


class Location(Base):
    """Named points we request model forecasts for (configured, not measured)."""

    __tablename__ = "location"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name_en: Mapped[str] = mapped_column(String(128), nullable=False)
    name_th: Mapped[str | None] = mapped_column(String(128))
    province_code: Mapped[str | None] = mapped_column(String(8), index=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    test_area: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WeatherStation(Base):
    """Observation stations (e.g. TMD synoptic stations, identified by WMO number)."""

    __tablename__ = "weather_station"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    station_code: Mapped[str] = mapped_column(String(64), nullable=False)  # id at the source
    wmo_id: Mapped[str | None] = mapped_column(String(16))
    name_th: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    province_name: Mapped[str | None] = mapped_column(String(128))
    province_code: Mapped[str | None] = mapped_column(String(8), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    extra: Mapped[dict | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("source", "station_code", name="uq_weather_station_source_code"),)


class ForecastRun(Base):
    """One model run (initialisation) of one NWP model, as published by a source.

    `model_run_time` is the model initialisation time (e.g. 2026-09-28T00:00Z),
    **not** the time we fetched it and **not** the valid time of a forecast value.
    """

    __tablename__ = "forecast_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    model_run_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # when the source says the run became available
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temporal_resolution_seconds: Mapped[int | None] = mapped_column(Integer)
    meta_raw_payload_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_payload.id", ondelete="SET NULL")
    )
    meta: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("source", "model", "model_run_time", name="uq_forecast_run_key"),)


class WeatherForecast(ProvenanceMixin, Base):
    """Hourly forecast values, one row per (model run, valid time, location).

    product:
      - "forecast"            live forecast; `model_run_time` is known exactly
                              (from the source's model metadata) and never changes.
      - "historical_forecast" Open-Meteo Historical Forecast API: a continuous
                              series stitched from successive runs; the individual
                              run time is not provided so `model_run_time` is NULL.
    """

    __tablename__ = "weather_forecast"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[str] = mapped_column(String(32), nullable=False, default="forecast")
    forecast_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("forecast_run.id", ondelete="CASCADE"), index=True
    )
    model_run_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    forecast_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lead_time_hours: Mapped[int | None] = mapped_column(Integer)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("location.id"), nullable=False)
    # grid cell actually used by the model (returned by the API)
    grid_lat: Mapped[float | None] = mapped_column(Float)
    grid_lon: Mapped[float | None] = mapped_column(Float)
    grid_elevation_m: Mapped[float | None] = mapped_column(Float)

    # requested point (= location.lat/lon), kept on the row as in the DB Schema sheet
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    temperature_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    precipitation_mm: Mapped[float | None] = mapped_column(Float)  # rain + showers + snow
    rain_mm: Mapped[float | None] = mapped_column(Float)  # liquid rain only
    precip_probability_pct: Mapped[float | None] = mapped_column(Float)
    pressure_msl_hpa: Mapped[float | None] = mapped_column(Float)
    cloud_cover_pct: Mapped[float | None] = mapped_column(Float)
    wind_speed_kmh: Mapped[float | None] = mapped_column(Float)
    wind_direction_deg: Mapped[float | None] = mapped_column(Float)
    wind_gust_kmh: Mapped[float | None] = mapped_column(Float)
    # volumetric soil moisture (m3/m3); layer differs per model, e.g. "0-7cm"
    soil_moisture_m3m3: Mapped[float | None] = mapped_column(Float)
    soil_moisture_layer: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        UniqueConstraint(
            "source",
            "model",
            "product",
            "model_run_time",
            "forecast_time",
            "location_id",
            name="uq_weather_forecast_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_weather_forecast_lookup", "location_id", "model", "forecast_time"),
    )


class WeatherObservation(ProvenanceMixin, Base):
    """Measured weather at a station at `observed_at` (UTC)."""

    __tablename__ = "weather_observation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("weather_station.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    obs_type: Mapped[str] = mapped_column(String(32), nullable=False, default="synoptic")

    temperature_c: Mapped[float | None] = mapped_column(Float)
    dew_point_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    pressure_msl_hpa: Mapped[float | None] = mapped_column(Float)
    station_pressure_hpa: Mapped[float | None] = mapped_column(Float)
    visibility_km: Mapped[float | None] = mapped_column(Float)
    wind_speed_kmh: Mapped[float | None] = mapped_column(Float)
    wind_direction_deg: Mapped[float | None] = mapped_column(Float)
    cloud_cover_okta: Mapped[float | None] = mapped_column(Float)
    # rainfall is only meaningful with its accumulation period
    rain_mm: Mapped[float | None] = mapped_column(Float)
    rain_period_hours: Mapped[float | None] = mapped_column(Float)
    rain_24h_mm: Mapped[float | None] = mapped_column(Float)
    max_temperature_c: Mapped[float | None] = mapped_column(Float)
    min_temperature_c: Mapped[float | None] = mapped_column(Float)
    # the undecoded report (e.g. one SYNOP station report) for traceability
    report_text: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("source", "station_id", "observed_at", "obs_type", name="uq_weather_observation_key"),
        Index("ix_weather_observation_station_time", "station_id", "observed_at"),
    )
