from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProvenanceMixin


class OfficialWarning(ProvenanceMixin, Base):
    """Official alerts (TMD weather warnings, later DDPM).

    `source_warning_id` is the id at the source, or a sha256 of the bulletin
    text when the source provides none - it is the de-duplication key.
    """

    __tablename__ = "official_warning"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agency: Mapped[str] = mapped_column(String(32), nullable=False)  # TMD | DDPM ...
    source_warning_id: Mapped[str] = mapped_column(String(128), nullable=False)
    bulletin_header: Mapped[str | None] = mapped_column(String(128))  # e.g. WMO abbreviated heading
    warning_type: Mapped[str | None] = mapped_column(String(64))  # weather | tropical_cyclone | sigmet ...
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severity: Mapped[str | None] = mapped_column(String(32))  # only when stated by the source
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    area_text: Mapped[str | None] = mapped_column(Text)
    province_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(8)))
    url: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("source", "source_warning_id", name="uq_official_warning_key"),
        Index("ix_official_warning_issued", "issued_at"),
    )
