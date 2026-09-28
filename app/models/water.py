"""River / canal / tide gauge stations.

No collector writes here yet in Phase 0 (rain gauge, river level and sea level
sources are scheduled for exploration after the core collectors work), but the
tables exist so the Flood Engine inputs (water level, trend, discharge, tide)
have a defined home.
"""
from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProvenanceMixin


class WaterStation(Base):
    __tablename__ = "water_station"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    station_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # river | canal | tide | reservoir_gauge | ...
    station_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="river")
    name_th: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    river_basin: Mapped[str | None] = mapped_column(String(128))
    province_code: Mapped[str | None] = mapped_column(String(8), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    # reference levels, all in metres above MSL
    ground_level_m: Mapped[float | None] = mapped_column(Float)
    bank_level_m: Mapped[float | None] = mapped_column(Float)
    warning_level_m: Mapped[float | None] = mapped_column(Float)
    critical_level_m: Mapped[float | None] = mapped_column(Float)
    datum: Mapped[str | None] = mapped_column(String(32))  # e.g. "MSL"
    extra: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("source", "station_code", name="uq_water_station_source_code"),)


class WaterLevelObservation(ProvenanceMixin, Base):
    __tablename__ = "water_level_observation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("water_station.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    water_level_m: Mapped[float | None] = mapped_column(Float)  # metres (datum on station)
    discharge_m3s: Mapped[float | None] = mapped_column(Float)
    rain_mm: Mapped[float | None] = mapped_column(Float)
    rain_period_hours: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("source", "station_id", "observed_at", name="uq_water_level_observation_key"),
        Index("ix_water_level_observation_station_time", "station_id", "observed_at"),
    )
