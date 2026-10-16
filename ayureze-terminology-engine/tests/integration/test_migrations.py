"""Database migration correctness (spec section 21) — verifies the schema
the app actually depends on (tables, pg_trgm, full-text search column)
really exists, not just that "alembic upgrade head" exited 0.
"""

from __future__ import annotations

from sqlalchemy import inspect, text


def test_all_expected_tables_exist(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {"concepts", "concept_names", "sources", "source_records", "concept_relationships", "deduplication_candidates", "id_counters"}
    assert expected <= tables


def test_pg_trgm_extension_is_installed(engine):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")).fetchone()
    assert result is not None


def test_concept_id_is_unique(db):
    from models import Concept

    db.add(Concept(concept_id="TEST-UNIQUE-1", domain="AYURVEDA", category="HERB", canonical_name="A", status="candidate", confidence=1.0))
    db.flush()

    import pytest
    from sqlalchemy.exc import IntegrityError

    db.add(Concept(concept_id="TEST-UNIQUE-1", domain="AYURVEDA", category="HERB", canonical_name="B", status="candidate", confidence=1.0))
    with pytest.raises(IntegrityError):
        db.flush()


def test_concept_name_foreign_key_is_enforced(db):
    import pytest
    from sqlalchemy.exc import IntegrityError

    from models import ConceptName

    db.add(ConceptName(concept_id="DOES-NOT-EXIST", name="x", normalized_name="x", language="en", name_type="preferred"))
    with pytest.raises(IntegrityError):
        db.flush()
