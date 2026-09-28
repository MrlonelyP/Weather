"""Hydrography: HydroSHEDS basins/rivers, station links, station relations, training rows.

- static_source_file: provenance of every static file we downloaded (URL, zip member, sha256, fetch time)
- hydro_basin:  HydroBASINS units (several Pfafstetter levels) with their downstream topology
- hydro_river:  HydroRIVERS reaches with NEXT_DOWN topology and upstream area
- station_hydro_link: which reach / catchment a water station belongs to, how it was chosen, confidence
- station_relation:   upstream / downstream station pairs along the river network (lag not estimated yet)
- water_forecast_training: feature snapshots at prediction time + the actual level observed later
"""
from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (BigInteger, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StaticSourceFile(Base):
    __tablename__ = "static_source_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_member: Mapped[str | None] = mapped_column(String(256))
    path: Mapped[str | None] = mapped_column(String(512))
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # downloaded | failed
    error: Mapped[str | None] = mapped_column(String(1000))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("dataset", "name", name="uq_static_source_file_dataset_name"),)


class HydroBasin(Base):
    __tablename__ = "hydro_basin"

    hybas_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    next_down: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 0 = outlet (sea / sink)
    next_sink: Mapped[int | None] = mapped_column(BigInteger)
    main_bas: Mapped[int | None] = mapped_column(BigInteger)
    pfaf_id: Mapped[int | None] = mapped_column(BigInteger)
    sub_area_km2: Mapped[float | None] = mapped_column(Float)
    up_area_km2: Mapped[float | None] = mapped_column(Float)
    dist_main_km: Mapped[float | None] = mapped_column(Float)
    coast: Mapped[int | None] = mapped_column(SmallInteger)
    endo: Mapped[int | None] = mapped_column(SmallInteger)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False)
    source_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (Index("ix_hydro_basin_level_next_down", "level", "next_down"),)


class HydroRiver(Base):
    __tablename__ = "hydro_river"

    hyriv_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    next_down: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)  # 0 = outlet
    main_riv: Mapped[int | None] = mapped_column(BigInteger, index=True)
    length_km: Mapped[float | None] = mapped_column(Float)
    dist_dn_km: Mapped[float | None] = mapped_column(Float)
    dist_up_km: Mapped[float | None] = mapped_column(Float)
    catch_km2: Mapped[float | None] = mapped_column(Float)
    upland_km2: Mapped[float | None] = mapped_column(Float)
    dis_av_cms: Mapped[float | None] = mapped_column(Float)  # modelled long-term mean discharge (HydroRIVERS)
    ord_stra: Mapped[int | None] = mapped_column(SmallInteger)
    ord_clas: Mapped[int | None] = mapped_column(SmallInteger)
    hybas_l12: Mapped[int | None] = mapped_column(BigInteger, index=True)
    geom = mapped_column(Geometry("MULTILINESTRING", srid=4326, spatial_index=True), nullable=False)
    source_version: Mapped[str] = mapped_column(String(32), nullable=False)


class StationHydroLink(Base):
    __tablename__ = "station_hydro_link"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("water_station.id", ondelete="CASCADE"), nullable=False)
    method_version: Mapped[str] = mapped_column(String(16), nullable=False)
    hyriv_id: Mapped[int | None] = mapped_column(BigInteger)
    reach_distance_m: Mapped[float | None] = mapped_column(Float)
    reach_upland_km2: Mapped[float | None] = mapped_column(Float)
    # name_and_distance | distance_only | none
    reach_method: Mapped[str] = mapped_column(String(24), nullable=False)
    hybas_l12: Mapped[int | None] = mapped_column(BigInteger)
    osm_waterway_name: Mapped[str | None] = mapped_column(String(255))  # OSM line near the station with the same name
    osm_waterway_distance_m: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("station_id", "method_version", name="uq_station_hydro_link_station"),)


class StationRelation(Base):
    __tablename__ = "station_relation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("water_station.id", ondelete="CASCADE"), nullable=False)
    other_station_id: Mapped[int] = mapped_column(Integer, ForeignKey("water_station.id", ondelete="CASCADE"),
                                                  nullable=False)
    relation: Mapped[str] = mapped_column(String(16), nullable=False)  # upstream | downstream (other relative to station)
    network: Mapped[str] = mapped_column(String(32), nullable=False)  # hydrorivers_v10
    river_distance_km: Mapped[float | None] = mapped_column(Float)
    hops: Mapped[int | None] = mapped_column(Integer)
    same_river_name: Mapped[bool | None] = mapped_column()
    # travel time is not estimated until there is historical support
    lag_hours: Mapped[float | None] = mapped_column(Float)
    lag_basis: Mapped[str] = mapped_column(String(32), nullable=False, default="not_estimated")
    confidence: Mapped[float | None] = mapped_column(Float)
    method_version: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("station_id", "other_station_id", "network", name="uq_station_relation_pair"),
        Index("ix_station_relation_station", "station_id", "relation"),
    )


class WaterForecastTraining(Base):
    """One station, one prediction time, one horizon: features known then + what actually happened."""

    __tablename__ = "water_forecast_training"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("water_station.id", ondelete="CASCADE"), nullable=False)
    prediction_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(16), nullable=False)
    current_level_m: Mapped[float | None] = mapped_column(Float)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)  # water-level features
    rain_features: Mapped[dict | None] = mapped_column(JSONB)
    upstream_features: Mapped[dict | None] = mapped_column(JSONB)
    terrain_features: Mapped[dict | None] = mapped_column(JSONB)
    source_versions: Mapped[dict | None] = mapped_column(JSONB)
    actual_water_level_m: Mapped[float | None] = mapped_column(Float)
    actual_change_m: Mapped[float | None] = mapped_column(Float)
    actual_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    labelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("station_id", "prediction_time", "horizon_hours", name="uq_water_forecast_training_key"),
        Index("ix_water_forecast_training_target_unlabelled", "target_time", "labelled_at"),
    )
