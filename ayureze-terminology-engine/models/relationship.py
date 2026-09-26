from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ConceptRelationship(TimestampMixin, Base):
    """Relationships and cross-system mappings (spec section 11).

    `evidence` is REQUIRED and must cite what in the source justified this
    relationship (e.g. "Encyclopedia of Ayurvedic Pathology 'correlation'
    field" or "NAMASTE icd_biomedicine_code mapping") — this table must
    never be populated by string-similarity guessing. EXACT_MATCH between
    an AYURVEDA-domain and BIOMEDICAL-domain concept is never created
    automatically by this codebase; see mappings/ for the only code paths
    allowed to write one, and NEVER TO write one without a source citation.
    """

    __tablename__ = "concept_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id_a: Mapped[str] = mapped_column(ForeignKey("concepts.concept_id"), nullable=False, index=True)
    concept_id_b: Mapped[str] = mapped_column(ForeignKey("concepts.concept_id"), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)

    __table_args__ = (
        Index("ix_concept_relationships_a_b", "concept_id_a", "concept_id_b"),
    )
