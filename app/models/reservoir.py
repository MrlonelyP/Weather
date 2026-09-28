from __future__ import annotations

from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProvenanceMixin


class Reservoir(Base):
    __tablename__ = "reservoir"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reservoir_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name_th: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    size_class: Mapped[str | None] = mapped_column(String(16))  # large | medium
    region: Mapped[str | None] = mapped_column(String(64))
    province_code: Mapped[str | None] = mapped_column(String(8))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    # million cubic metres, as reported by the source
    capacity_mcm: Mapped[float | None] = mapped_column(Float)
    normal_high_storage_mcm: Mapped[float | None] = mapped_column(Float)
    min_storage_mcm: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("source", "reservoir_code", name="uq_reservoir_source_code"),)


class ReservoirStatus(ProvenanceMixin, Base):
    """Daily reservoir status.

    Volumes in million cubic metres (MCM). Inflow/outflow are stored both as
    reported daily volume (MCM/day) and as mean discharge (m3/s) derived from it.
    `observed_date` is the reporting date in Asia/Bangkok (RID reports daily).
    """

    __tablename__ = "reservoir_status"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reservoir_id: Mapped[int] = mapped_column(Integer, ForeignKey("reservoir.id"), nullable=False)
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_mcm: Mapped[float | None] = mapped_column(Float)
    storage_pct: Mapped[float | None] = mapped_column(Float)  # % as reported by the source (RID: of normal storage)
    usable_storage_mcm: Mapped[float | None] = mapped_column(Float)  # current usable water (volume - dead storage)
    usable_storage_pct: Mapped[float | None] = mapped_column(Float)
    inflow_mcm_day: Mapped[float | None] = mapped_column(Float)
    outflow_mcm_day: Mapped[float | None] = mapped_column(Float)
    inflow_m3s: Mapped[float | None] = mapped_column(Float)
    outflow_m3s: Mapped[float | None] = mapped_column(Float)
    capacity_mcm: Mapped[float | None] = mapped_column(Float)  # max capacity as reported that day
    # RID "storage" = ปริมาณน้ำเก็บกัก (normal retention volume); percent_storage is relative to it
    normal_storage_mcm: Mapped[float | None] = mapped_column(Float)
    dead_storage_mcm: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("source", "reservoir_id", "observed_date", name="uq_reservoir_status_key"),
        Index("ix_reservoir_status_res_date", "reservoir_id", "observed_date"),
    )
