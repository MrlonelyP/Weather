"""Terrain / elevation: DEM tile registry, computed terrain attributes, waterways.

The DEM rasters themselves stay on disk as GeoTIFF (COG) files; the database
only records WHICH file was fetched from WHERE and WHEN (dem_tile), the
attributes our terrain engine computed from them (terrain_profile) and the
OSM waterway lines used for distance-to-waterway (waterway).
"""
from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DemTile(Base):
    """One 1x1 degree DEM tile of one dataset (e.g. copernicus_glo30 N13E100)."""

    __tablename__ = "dem_tile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    tile_id: Mapped[str] = mapped_column(String(16), nullable=False)  # N13E100 (south-west corner)
    # downloaded | not_at_source | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_member: Mapped[str | None] = mapped_column(String(128))  # file inside a zip archive
    path: Mapped[str | None] = mapped_column(String(512))  # relative to settings.dem_data_dir
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    nodata: Mapped[float | None] = mapped_column(Float)
    source_metadata: Mapped[dict | None] = mapped_column(JSONB)  # GeoTIFF tags as published
    error: Mapped[str | None] = mapped_column(String(1000))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("dataset", "tile_id", name="uq_dem_tile_dataset_tile"),)


class TerrainProfile(Base):
    """Terrain attributes computed by our engine for one point and one DEM dataset.

    subject_type/subject_code say what the point is (water_station, location,
    weather_station). Values are computed, not observed: method_version and
    params make every number reproducible from the same DEM tiles.
    """

    __tablename__ = "terrain_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_code: Mapped[str] = mapped_column(String(96), nullable=False)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    method_version: Mapped[str] = mapped_column(String(16), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    elevation_m: Mapped[float | None] = mapped_column(Float)
    rel_elev_250_m: Mapped[float | None] = mapped_column(Float)
    rel_elev_500_m: Mapped[float | None] = mapped_column(Float)
    rel_elev_1000_m: Mapped[float | None] = mapped_column(Float)
    slope_deg: Mapped[float | None] = mapped_column(Float)
    terrain_position: Mapped[str | None] = mapped_column(String(16))  # LOW_AREA | NORMAL | HIGH_AREA | MIXED
    possible_local_depression: Mapped[bool | None] = mapped_column(Boolean)
    depression_depth_m: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict | None] = mapped_column(JSONB)  # full engine output incl. stats, params, tiles, limits
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_code", "dataset", "method_version", name="uq_terrain_profile_key"),
    )


class Waterway(Base):
    """OSM waterway line (river / canal / stream / drain ...)."""

    __tablename__ = "waterway"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    osm_type: Mapped[str] = mapped_column(String(16), nullable=False)  # ways_line | relations_line
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    waterway_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    geom = mapped_column(Geometry("MULTILINESTRING", srid=4326, spatial_index=True), nullable=False)
    source_snapshot: Mapped[str | None] = mapped_column(String(64))  # export time of the OSM extract (UTC)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "osm_type", "osm_id", name="uq_waterway_source_osm"),
        Index("ix_waterway_type", "waterway_type"),
    )
