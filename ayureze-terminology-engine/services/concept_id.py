"""Concept ID minting (spec section 8): AYU-HERB-000001, BIO-DRUG-000001,
etc. Never a source's own ID. Atomic under concurrent ingestion via a
single `UPDATE ... RETURNING` against models.IdCounter — no read-then-write
race window.
"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from models import IdCounter

_WIDTH = 6


def next_concept_id(db: Session, prefix: str) -> str:
    """prefix is e.g. "AYU-HERB", "BIO-DRUG", "NAMASTE" — the full
    concept_id returned is f"{prefix}-{n:06d}"."""
    row = db.execute(
        update(IdCounter).where(IdCounter.prefix == prefix).values(next_value=IdCounter.next_value + 1).returning(IdCounter.next_value)
    ).first()
    if row is None:
        db.execute(insert(IdCounter).values(prefix=prefix, next_value=2))
        n = 1
    else:
        n = row[0] - 1
    return f"{prefix}-{n:0{_WIDTH}d}"


def peek_next_value(db: Session, prefix: str) -> int:
    """Read-only — for tests/reporting, never for minting an ID."""
    value = db.execute(select(IdCounter.next_value).where(IdCounter.prefix == prefix)).scalar()
    return value if value is not None else 1
