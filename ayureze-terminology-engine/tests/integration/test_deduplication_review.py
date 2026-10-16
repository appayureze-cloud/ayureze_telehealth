"""services/deduplication_review.py against a real Postgres database (spec
section 13: a human review action, never an automated merge). Every test
here asserts the two concepts stay independently addressable — accepting
a candidate must never delete a row, retire a concept_id, or change either
concept's own fields.
"""

from __future__ import annotations

import pytest

from models import Concept, ConceptRelationship, DeduplicationCandidate
from services.deduplication_review import (
    CandidateAlreadyReviewedError,
    CandidateNotFoundError,
    accept_candidate,
    reject_candidate,
)


def _concept(db, concept_id: str, canonical_name: str) -> Concept:
    c = Concept(concept_id=concept_id, domain="AYURVEDA", category="HERB", canonical_name=canonical_name, status="candidate", confidence=1.0)
    db.add(c)
    db.flush()
    return c


def _candidate(db, a: str, b: str, reason: str = "known_synonym_match", similarity: float = 1.0) -> DeduplicationCandidate:
    candidate = DeduplicationCandidate(candidate_a=a, candidate_b=b, similarity=similarity, reason=reason, status="pending")
    db.add(candidate)
    db.flush()
    return candidate


def test_accepting_a_candidate_creates_a_synonym_of_relationship_and_marks_it_accepted(db):
    a = _concept(db, "TEST-REVIEW-A1", "Giloy")
    b = _concept(db, "TEST-REVIEW-A2", "Amrita")
    candidate = _candidate(db, a.concept_id, b.concept_id)

    result = accept_candidate(db, candidate.id, reviewed_by="dr.sharma@example.test", review_notes="confirmed same plant")

    assert result.status == "accepted"
    assert result.reviewed_by == "dr.sharma@example.test"
    assert result.review_notes == "confirmed same plant"

    rel = db.query(ConceptRelationship).filter_by(concept_id_a=a.concept_id, concept_id_b=b.concept_id, relationship_type="SYNONYM_OF").one_or_none()
    assert rel is not None
    assert "dr.sharma@example.test" in rel.evidence
    assert rel.confidence == 1.0

    # Neither concept was merged, deleted, or otherwise mutated.
    refreshed_a = db.query(Concept).filter_by(concept_id=a.concept_id).one()
    refreshed_b = db.query(Concept).filter_by(concept_id=b.concept_id).one()
    assert refreshed_a.status == "candidate"
    assert refreshed_b.status == "candidate"
    assert refreshed_a.canonical_name == "Giloy"
    assert refreshed_b.canonical_name == "Amrita"


def test_rejecting_a_candidate_creates_no_relationship(db):
    a = _concept(db, "TEST-REVIEW-B1", "Kutaj")
    b = _concept(db, "TEST-REVIEW-B2", "Indrayava")
    candidate = _candidate(db, a.concept_id, b.concept_id, reason="scientific_name_match")

    result = reject_candidate(db, candidate.id, reviewed_by="dr.sharma@example.test", review_notes="different Sanskrit synonyms, not a duplicate")

    assert result.status == "rejected"
    assert result.reviewed_by == "dr.sharma@example.test"
    rel = db.query(ConceptRelationship).filter_by(concept_id_a=a.concept_id, concept_id_b=b.concept_id).one_or_none()
    assert rel is None


def test_accepting_an_already_reviewed_candidate_raises(db):
    a = _concept(db, "TEST-REVIEW-C1", "X")
    b = _concept(db, "TEST-REVIEW-C2", "Y")
    candidate = _candidate(db, a.concept_id, b.concept_id)
    reject_candidate(db, candidate.id, reviewed_by="reviewer1", review_notes=None)

    with pytest.raises(CandidateAlreadyReviewedError):
        accept_candidate(db, candidate.id, reviewed_by="reviewer2", review_notes=None)


def test_reviewing_an_unknown_candidate_id_raises_not_found(db):
    with pytest.raises(CandidateNotFoundError):
        accept_candidate(db, 999_999_999, reviewed_by="reviewer1", review_notes=None)


def test_accepting_twice_does_not_duplicate_the_relationship(db):
    """Defensive idempotency: even though the endpoint itself blocks a
    second review via CandidateAlreadyReviewedError, the underlying
    relationship-creation step is independently idempotent too."""
    a = _concept(db, "TEST-REVIEW-D1", "X")
    b = _concept(db, "TEST-REVIEW-D2", "Y")
    candidate = _candidate(db, a.concept_id, b.concept_id)
    accept_candidate(db, candidate.id, reviewed_by="reviewer1", review_notes=None)

    # Reset status directly (bypassing the endpoint's own guard) purely to
    # exercise accept_candidate's own idempotent relationship insert.
    candidate.status = "pending"
    db.commit()
    accept_candidate(db, candidate.id, reviewed_by="reviewer1", review_notes=None)

    rels = db.query(ConceptRelationship).filter_by(concept_id_a=a.concept_id, concept_id_b=b.concept_id, relationship_type="SYNONYM_OF").all()
    assert len(rels) == 1
