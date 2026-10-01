from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IdCounter(Base):
    """Backs deterministic, gap-tolerant concept_id minting (AYU-HERB-000001,
    BIO-DRUG-000001, ...) — one row per prefix, incremented atomically via
    an `UPDATE ... RETURNING` in services/concept_id.py so concurrent
    ingestion runs never collide. A plain counter table rather than
    per-prefix Postgres SEQUENCE objects: new prefixes (a new Ayurvedic
    category, a new biomedical domain) don't require a schema migration to
    add, only a new row."""

    __tablename__ = "id_counters"

    prefix: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_value: Mapped[int] = mapped_column(nullable=False, default=1)
