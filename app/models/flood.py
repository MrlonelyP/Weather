from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProvenanceMixin


class FloodExtent(ProvenanceMixin, Base):
    """Satellite-detected flood polygons (GISTDA GIS-02)."""

    __tablename__ = "flood_extent"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # id at the source, or sha256 of the geometry when none is given
    source_feature_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product: Mapped[str | None] = mapped_column(String(32))  # 1day | 3days | 7days | 30days
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # satellite acquisition
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sensor: Mapped[str | None] = mapped_column(String(64))
    province_code: Mapped[str | None] = mapped_column(String(8), index=True)
    province_name: Mapped[str | None] = mapped_column(String(128))
    area_sqkm: Mapped[float | None] = mapped_column(Float)  # computed from geometry (geography)
    geometry = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=False)
    properties: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("source", "source_feature_id", name="uq_flood_extent_key"),
        Index("ix_flood_extent_observed", "observed_at"),
    )


class FloodPointCheck(ProvenanceMixin, Base):
    """Result of asking the source "is this point inside a detected flood extent?" (GIS-01)."""

    __tablename__ = "flood_point_check"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("location.id"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    is_flooded: Mapped[bool | None] = mapped_column(Boolean)  # NULL = could not interpret
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # data time if given
    details: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("source", "location_id", "checked_at", name="uq_flood_point_check_key"),
    )
