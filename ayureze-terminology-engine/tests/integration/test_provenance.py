"""Every canonical concept must be traceable back to its source records
(spec section 10) — and source filtering must work (spec section 21).
"""

from __future__ import annotations

from models import Concept, Source, SourceRecord


def test_concept_is_traceable_to_its_source_record(db):
    source = Source(
        source_name="test_source", repository_url="https://example.test/repo",
        version_or_commit="abc123", license="CC-BY-4.0", retrieved_at="2026-09-26",
        record_count=1, commercial_use_status="verified",
    )
    db.add(source)
    db.flush()

    concept = Concept(concept_id="TEST-HERB-000010", domain="AYURVEDA", category="HERB", canonical_name="Test Herb", status="candidate", confidence=1.0)
    db.add(concept)
    db.flush()

    record = SourceRecord(
        source_id=source.id, source_record_id="0", concept_id=concept.concept_id,
        original_payload={"name": "Test Herb"}, source_version="abc123",
        source_url="https://example.test/repo", ingestion_timestamp="2026-09-26T00:00:00+00:00",
    )
    db.add(record)
    db.flush()

    fetched = db.query(SourceRecord).filter_by(concept_id=concept.concept_id).all()
    assert len(fetched) == 1
    assert fetched[0].original_payload == {"name": "Test Herb"}
    assert fetched[0].source_url == "https://example.test/repo"


def test_original_payload_is_never_mutated(db):
    """Raw provenance is immutable (spec section 7) — storing then
    re-reading a record must return byte-for-byte the same structure,
    including a value the normalization layer WOULD have changed if this
    were a ConceptName instead."""
    source = Source(
        source_name="test_source_2", repository_url="https://example.test/repo2",
        version_or_commit="def456", license="CC-BY-4.0", retrieved_at="2026-09-26",
        record_count=1, commercial_use_status="verified",
    )
    db.add(source)
    db.flush()

    original = {"name": "  MiXeD Case Name!  ", "nested": {"a": [1, 2, 3]}}
    record = SourceRecord(
        source_id=source.id, source_record_id="0", concept_id=None,
        original_payload=original, source_version="def456",
        source_url="https://example.test/repo2", ingestion_timestamp="2026-09-26T00:00:00+00:00",
    )
    db.add(record)
    db.flush()
    db.expire_all()

    fetched = db.get(SourceRecord, record.id)
    assert fetched.original_payload == original


def test_source_filtering_by_name(db):
    for name in ("source_a", "source_b"):
        db.add(Source(
            source_name=name, repository_url=f"https://example.test/{name}",
            version_or_commit="v1", license="CC-BY-4.0", retrieved_at="2026-09-26",
            record_count=0, commercial_use_status="verified",
        ))
    db.flush()

    only_a = db.query(Source).filter_by(source_name="source_a").all()
    assert len(only_a) == 1
    assert only_a[0].source_name == "source_a"
