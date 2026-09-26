from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Concept(TimestampMixin, Base):
    """The canonical, language-independent concept registry (spec section
    8). concept_id is a newly-minted internal identifier (AYU-HERB-000001,
    BIO-DRUG-000001, ...) — NEVER a source's own ID; that traceability
    lives in SourceRecord instead (spec section 10)."""

    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    # How confident the ingestion pipeline is that this concept's fields
    # are correctly extracted/canonicalized — NOT a claim about the
    # underlying Ayurvedic/medical knowledge's own certainty. 1.0 for a
    # directly-sourced, well-formed record; lower for records assembled
    # from partial/malformed source data. See docs/DATA_QUALITY_REPORT.md.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    names: Mapped[list["ConceptName"]] = relationship(back_populates="concept", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_concepts_domain_category", "domain", "category"),
    )


class ConceptName(Base):
    """Every name a concept is known by (spec section 9) — preferred,
    synonym, alias, scientific/botanical, transliteration, abbreviation.
    Original spelling is preserved verbatim in `name`; `normalized_name`
    is a deterministic, non-destructive derivative used for matching
    (see normalization/)."""

    __tablename__ = "concept_names"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.concept_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    script: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)

    concept: Mapped["Concept"] = relationship(back_populates="names")

    __table_args__ = (
        Index("ix_concept_names_concept_id_name_type", "concept_id", "name_type"),
    )
