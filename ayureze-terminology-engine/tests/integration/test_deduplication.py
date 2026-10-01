"""Staged deduplication against a real Postgres database (spec section 21:
"duplicate detection"). Every stage is exercised with synthetic data
whose expected outcome is unambiguous, plus a false-positive check:
fuzzy matching must never silently merge — only ever queue a candidate.
"""

from __future__ import annotations

from deduplication.pipeline import run_deduplication
from models import Concept, ConceptName, DeduplicationCandidate
from normalization import normalize_name


def _concept(db, concept_id: str, canonical_name: str) -> Concept:
    c = Concept(concept_id=concept_id, domain="AYURVEDA", category="HERB", canonical_name=canonical_name, status="candidate", confidence=1.0)
    db.add(c)
    db.flush()
    return c


def _name(db, concept: Concept, name: str, name_type: str) -> None:
    db.add(ConceptName(concept_id=concept.concept_id, name=name, normalized_name=normalize_name(name), language="sa", script="Latin", name_type=name_type))
    db.flush()


def test_exact_normalized_match_is_flagged(db):
    a = _concept(db, "TEST-DUP-A1", "Tulsi")
    _name(db, a, "Tulsi", "preferred")
    b = _concept(db, "TEST-DUP-A2", "tulsi")  # same name, different case
    _name(db, b, "tulsi", "preferred")

    stats = run_deduplication(db)
    assert stats.candidates_found["exact_normalized_match"] >= 1
    pair = db.query(DeduplicationCandidate).filter_by(candidate_a="TEST-DUP-A1", candidate_b="TEST-DUP-A2").one_or_none()
    assert pair is not None
    assert pair.status == "pending"
    assert pair.similarity == 1.0


def test_synonym_dedup_matches_a_different_concepts_synonym(db):
    """The real, observed case from this build's own ingested data: two
    DIFFERENT concepts (Giloy, Amrita) share a synonym (Guduchi) — flagged
    for human review, never silently merged."""
    giloy = _concept(db, "TEST-DUP-GILOY", "Giloy")
    _name(db, giloy, "Giloy", "preferred")
    _name(db, giloy, "Guduchi", "synonym")

    amrita = _concept(db, "TEST-DUP-AMRITA", "Amrita")
    _name(db, amrita, "Amrita", "preferred")
    _name(db, amrita, "Guduchi", "synonym")

    stats = run_deduplication(db)
    assert stats.candidates_found["known_synonym_match"] >= 1
    pair = db.query(DeduplicationCandidate).filter_by(candidate_a="TEST-DUP-AMRITA", candidate_b="TEST-DUP-GILOY").one_or_none()
    assert pair is not None
    assert pair.reason == "known_synonym_match"
    assert pair.status == "pending", "must be queued for review, never auto-accepted"


def test_scientific_name_match_is_flagged(db):
    a = _concept(db, "TEST-DUP-SCI-A", "Giloy")
    _name(db, a, "Giloy", "preferred")
    _name(db, a, "Tinospora cordifolia", "botanical")

    b = _concept(db, "TEST-DUP-SCI-B", "Amrita")
    _name(db, b, "Amrita", "preferred")
    _name(db, b, "Tinospora cordifolia", "botanical")

    run_deduplication(db)
    # Either scientific_name_match OR an earlier stage (both concepts also
    # differ in preferred/synonym names here, so scientific IS the first
    # stage that applies) must have caught this real pair.
    pair = db.query(DeduplicationCandidate).filter_by(candidate_a="TEST-DUP-SCI-A", candidate_b="TEST-DUP-SCI-B").one_or_none()
    assert pair is not None
    assert pair.reason == "scientific_name_match"


def test_high_confidence_fuzzy_match_is_flagged_with_real_similarity_score(db):
    a = _concept(db, "TEST-DUP-FUZZY-A", "Ashwagandha")
    _name(db, a, "Ashwagandha", "preferred")
    b = _concept(db, "TEST-DUP-FUZZY-B", "Ashwagandhaa")
    _name(db, b, "Ashwagandhaa", "preferred")

    stats = run_deduplication(db)
    assert stats.candidates_found["high_confidence_fuzzy_match"] >= 1
    pair = db.query(DeduplicationCandidate).filter_by(candidate_a="TEST-DUP-FUZZY-A", candidate_b="TEST-DUP-FUZZY-B").one_or_none()
    assert pair is not None
    assert 0.0 < pair.similarity < 1.0, "fuzzy similarity must be the real score, never 1.0 (that would be an exact match, a different stage)"


def test_unrelated_concepts_are_never_flagged_as_duplicates(db):
    """False-positive avoidance (spec section 21: 'Do NOT create synonym
    relationships merely because strings look similar')."""
    a = _concept(db, "TEST-DUP-UNRELATED-A", "Tulsi")
    _name(db, a, "Tulsi", "preferred")
    b = _concept(db, "TEST-DUP-UNRELATED-B", "Shatavari")
    _name(db, b, "Shatavari", "preferred")

    run_deduplication(db)
    pair = db.query(DeduplicationCandidate).filter(
        DeduplicationCandidate.candidate_a.in_(["TEST-DUP-UNRELATED-A", "TEST-DUP-UNRELATED-B"]),
        DeduplicationCandidate.candidate_b.in_(["TEST-DUP-UNRELATED-A", "TEST-DUP-UNRELATED-B"]),
    ).one_or_none()
    assert pair is None


def test_deduplication_never_merges_or_deletes_concepts(db):
    """Fuzzy matches must NOT automatically merge records (spec section
    13) — running dedup must never change concept count or mutate an
    existing Concept row."""
    a = _concept(db, "TEST-DUP-NOMERGE-A", "Brahmi")
    _name(db, a, "Brahmi", "preferred")
    b = _concept(db, "TEST-DUP-NOMERGE-B", "brahmi")
    _name(db, b, "brahmi", "preferred")

    count_before = db.query(Concept).count()
    run_deduplication(db)
    count_after = db.query(Concept).count()
    assert count_before == count_after

    assert db.get(Concept, a.id) is not None
    assert db.get(Concept, b.id) is not None


def test_a_pair_is_never_duplicated_across_stages(db):
    """A pair caught by a stronger-evidence stage is not ALSO inserted
    under a weaker stage's reason — one row per pair."""
    a = _concept(db, "TEST-DUP-ONCE-A", "Giloy")
    _name(db, a, "Giloy", "preferred")
    _name(db, a, "Guduchi", "synonym")
    b = _concept(db, "TEST-DUP-ONCE-B", "Amrita")
    _name(db, b, "Amrita", "preferred")
    _name(db, b, "Guduchi", "synonym")

    run_deduplication(db)
    rows = db.query(DeduplicationCandidate).filter_by(candidate_a="TEST-DUP-ONCE-A", candidate_b="TEST-DUP-ONCE-B").all()
    assert len(rows) == 1
