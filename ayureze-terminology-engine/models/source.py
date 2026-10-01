from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Source(Base):
    """One row per approved data source (spec section 6) — the DB-queryable
    mirror of data/manifests/source_manifest.json, so GET /v1/sources can
    answer from Postgres instead of re-reading a file at request time.
    The manifest JSON file remains the source of truth for the full audit
    record (schema_summary, files list, notes); this table holds what the
    API actually needs to serve."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    version_or_commit: Mapped[str] = mapped_column(String(128), nullable=False)
    license: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[str] = mapped_column(String(32), nullable=False)
    record_count: Mapped[int] = mapped_column(nullable=False, default=0)
    commercial_use_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    records: Mapped[list["SourceRecord"]] = relationship(back_populates="source")


class SourceRecord(TimestampMixin, Base):
    """Provenance for every canonical concept (spec section 10): the exact
    original payload a concept/name/relationship was derived from, never
    mutated. concept_id is nullable because ingestion is staged — a raw
    record can exist before canonicalization assigns it a concept (see
    docs/INGESTION.md's pipeline stages)."""

    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(256), nullable=False)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.concept_id"), nullable=True, index=True)
    original_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    ingestion_timestamp: Mapped[str] = mapped_column(String(32), nullable=False)

    source: Mapped["Source"] = relationship(back_populates="records")
