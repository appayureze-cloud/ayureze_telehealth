from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class DeduplicationCandidate(TimestampMixin, Base):
    """The review queue (spec section 13). A fuzzy or otherwise
    non-certain match between two ALREADY-CREATED concepts is recorded
    here, never auto-merged. `status` starts "pending" and is only ever
    changed by an explicit review action (services/deduplication_review.py)
    — nothing in the ingestion pipeline flips it to "accepted"."""

    __tablename__ = "deduplication_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_a: Mapped[str] = mapped_column(ForeignKey("concepts.concept_id"), nullable=False, index=True)
    candidate_b: Mapped[str] = mapped_column(ForeignKey("concepts.concept_id"), nullable=False, index=True)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
