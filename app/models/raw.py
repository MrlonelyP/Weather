from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawPayload(Base):
    """Layer 1: the original response body, byte-for-byte as text.

    Stored for every HTTP response we receive (including non-2xx) so that data
    can be audited and re-processed later with an improved parser.

    When a response is identical (same checksum) to the latest stored payload
    for the same `request_key`, the body is not stored again: `payload` is NULL
    and `same_as_id` points at the row that holds the body. The fetch itself is
    still recorded so we know *when* the source was checked.
    """

    __tablename__ = "raw_payload"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)  # URL without secrets
    request_params: Mapped[dict | None] = mapped_column(JSONB)  # secrets redacted
    # stable key for "the same request" (endpoint + params minus secrets)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 of body
    payload: Mapped[str | None] = mapped_column(Text)
    same_as_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_payload.id", ondelete="SET NULL"))
    # collector context needed to re-process the payload later without
    # calling the API again (e.g. verified model run time, location codes)
    context: Mapped[dict | None] = mapped_column(JSONB)
    # normalization bookkeeping
    parse_status: Mapped[str | None] = mapped_column(String(32))  # parsed | failed | skipped | pending
    parse_error: Mapped[str | None] = mapped_column(Text)
    records_parsed: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_raw_payload_source_dataset_fetched", "source", "dataset", "fetched_at"),
        Index("ix_raw_payload_request_key_fetched", "request_key", "fetched_at"),
        Index("ix_raw_payload_checksum", "checksum"),
    )
