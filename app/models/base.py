from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ProvenanceMixin:
    """Columns every normalized record carries so it can be traced to its source.

    - source:         which agency / API (e.g. "openmeteo", "tmd", "rid", "gistda")
    - raw_payload_id: the exact raw response the value was parsed from
    - ingested_at:    when *we* stored it (fetch time lives on raw_payload.fetched_at)
    The *data* time (observed_at / forecast_time / issued_at ...) is defined per table.
    """

    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    raw_payload_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_payload.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
