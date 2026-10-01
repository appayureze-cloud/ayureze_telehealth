"""Ingestion idempotency — a real, previously-documented gap
(docs/INGESTION.md's "known limitation": re-running an ingester without
truncating first used to create duplicate concepts). Fixed via
get_or_create_record_and_concept/add_name/add_relationship_if_new; these
tests lock the fix in so it can't silently regress.
"""

from __future__ import annotations

from ingestion.common import add_name, add_relationship_if_new, get_or_create_record_and_concept, get_or_create_source, IngestionStats
from models import Concept, ConceptName, ConceptRelationship, SourceRecord


def _manifest_entry(name: str) -> dict:
    return {
        "source_name": name, "repository_url": "https://example.test/repo",
        "version_or_commit": "v1", "license": "CC-BY-4.0", "retrieved_at": "2026-09-26",
        "record_count": 1, "commercial_use_status": "verified", "notes": None,
    }


def test_re_ingesting_the_same_record_does_not_create_a_second_concept(db):
    source = get_or_create_source(db, _manifest_entry("idempotency_test_source"))
    stats = IngestionStats(source_name="idempotency_test_source")

    _, concept1, is_new1 = get_or_create_record_and_concept(
        db, stats, source, source_record_id="0", original_payload={"name": "Tulsi"},
        source_url="https://example.test/repo", prefix="TEST-IDEMP", domain="AYURVEDA",
        category="HERB", canonical_name="Tulsi", definition="A holy herb.",
    )
    _, concept2, is_new2 = get_or_create_record_and_concept(
        db, stats, source, source_record_id="0", original_payload={"name": "Tulsi"},
        source_url="https://example.test/repo", prefix="TEST-IDEMP", domain="AYURVEDA",
        category="HERB", canonical_name="Tulsi", definition="A holy herb.",
    )

    assert is_new1 is True
    assert is_new2 is False
    assert concept1.concept_id == concept2.concept_id
    assert db.query(Concept).filter_by(concept_id=concept1.concept_id).count() == 1
    assert db.query(SourceRecord).filter_by(source_id=source.id, source_record_id="0").count() == 1


def test_re_ingesting_updates_a_changed_payload_without_minting_a_new_concept(db):
    source = get_or_create_source(db, _manifest_entry("idempotency_test_source_2"))
    stats = IngestionStats(source_name="idempotency_test_source_2")

    _, concept1, _ = get_or_create_record_and_concept(
        db, stats, source, source_record_id="0", original_payload={"name": "Tulsi", "v": 1},
        source_url="https://example.test/repo", prefix="TEST-IDEMP2", domain="AYURVEDA",
        category="HERB", canonical_name="Tulsi", definition="A holy herb.",
    )
    record2, concept2, is_new2 = get_or_create_record_and_concept(
        db, stats, source, source_record_id="0", original_payload={"name": "Tulsi", "v": 2},
        source_url="https://example.test/repo", prefix="TEST-IDEMP2", domain="AYURVEDA",
        category="HERB", canonical_name="Tulsi", definition="A holy herb.",
    )

    assert is_new2 is False
    assert concept1.concept_id == concept2.concept_id
    assert record2.original_payload == {"name": "Tulsi", "v": 2}
    assert stats.payload_updated_on_rerun == 1
    assert stats.skipped_unchanged == 0


def test_re_ingesting_an_unchanged_payload_counts_as_skipped_not_updated(db):
    source = get_or_create_source(db, _manifest_entry("idempotency_test_source_3"))
    stats = IngestionStats(source_name="idempotency_test_source_3")
    payload = {"name": "Tulsi"}

    get_or_create_record_and_concept(
        db, stats, source, source_record_id="0", original_payload=payload,
        source_url="https://example.test/repo", prefix="TEST-IDEMP3", domain="AYURVEDA",
        category="HERB", canonical_name="Tulsi", definition=None,
    )
    get_or_create_record_and_concept(
        db, stats, source, source_record_id="0", original_payload=dict(payload),
        source_url="https://example.test/repo", prefix="TEST-IDEMP3", domain="AYURVEDA",
        category="HERB", canonical_name="Tulsi", definition=None,
    )

    assert stats.skipped_unchanged == 1
    assert stats.payload_updated_on_rerun == 0


def test_re_adding_the_same_name_does_not_duplicate_it(db):
    source = get_or_create_source(db, _manifest_entry("idempotency_test_source_4"))
    stats = IngestionStats(source_name="idempotency_test_source_4")
    source_record, concept, _ = get_or_create_record_and_concept(
        db, stats, source, source_record_id="0", original_payload={"name": "Tulsi"},
        source_url="https://example.test/repo", prefix="TEST-IDEMP4", domain="AYURVEDA",
        category="HERB", canonical_name="Tulsi", definition=None,
    )

    add_name(db, stats, concept, "Tulsi", language="sa", name_type="preferred", source_record=source_record)
    add_name(db, stats, concept, "Tulsi", language="sa", name_type="preferred", source_record=source_record)

    assert stats.names_created == 1
    assert db.query(ConceptName).filter_by(concept_id=concept.concept_id, name="Tulsi", name_type="preferred").count() == 1


def test_re_adding_the_same_relationship_does_not_duplicate_it(db):
    source = get_or_create_source(db, _manifest_entry("idempotency_test_source_5"))
    stats = IngestionStats(source_name="idempotency_test_source_5")
    source_record, herb, _ = get_or_create_record_and_concept(
        db, stats, source, source_record_id="herb", original_payload={"name": "Haritaki"},
        source_url="https://example.test/repo", prefix="TEST-IDEMP5-HERB", domain="AYURVEDA",
        category="HERB", canonical_name="Haritaki", definition=None,
    )
    _, formulation, _ = get_or_create_record_and_concept(
        db, stats, source, source_record_id="formulation", original_payload={"name": "Triphala"},
        source_url="https://example.test/repo", prefix="TEST-IDEMP5-FORM", domain="AYURVEDA",
        category="FORMULATION", definition=None, canonical_name="Triphala",
    )

    first = add_relationship_if_new(db, formulation.concept_id, herb.concept_id, "HAS_INGREDIENT", "evidence text", source_record)
    second = add_relationship_if_new(db, formulation.concept_id, herb.concept_id, "HAS_INGREDIENT", "evidence text", source_record)

    assert first is True
    assert second is False
    assert db.query(ConceptRelationship).filter_by(
        concept_id_a=formulation.concept_id, concept_id_b=herb.concept_id, relationship_type="HAS_INGREDIENT"
    ).count() == 1
