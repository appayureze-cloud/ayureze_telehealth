"""Staged deduplication (spec section 13). Every stage only ever WRITES to
deduplication_candidates (status="pending") — nothing in this module ever
merges, deletes, or mutates a Concept. A human (or a future, explicitly
separate review action — services/deduplication_review.py) is the only
thing that can move a candidate to "accepted"/"rejected", and even
"accepted" in Phase 1 means "flagged as a real duplicate for a human to
resolve," not an automatic merge — this codebase does not implement
automatic concept merging in Phase 1.

Stages, in order (weakest evidence requirement to strongest):
  1. exact_normalized_match: two DIFFERENT concepts whose canonical
     (preferred) names normalize identically.
  2. known_synonym_match: a name of one concept (any type) exactly matches
     a name of a different concept (any type), where stage 1 didn't
     already catch it — this is the spec's own worked example ("Guduchi"
     should resolve to the same concept as "Giloy" if the source
     identifies it as a synonym) when both terms happen to be indexed as
     names of two DIFFERENT concept rows rather than one.
  3. scientific_name_match: two different concepts share an identical
     normalized BOTANICAL or SCIENTIFIC name — real Latin binomials are
     about as strong a duplicate signal as data gets (see the real
     Giloy/Amrita finding in this build's own ingested data, both
     Tinospora cordifolia).
  4. high_confidence_fuzzy_match: pg_trgm similarity >= FUZZY_THRESHOLD
     between two different concepts' preferred names, catching near-misses
     (transliteration variants, minor spelling differences) that exact
     matching won't. Deliberately the LAST, weakest-evidence stage, and
     the only one where similarity < 1.0 is expected/normal.

Every stage only ever compares concepts that already exist — dedup runs
AFTER canonicalization, on the same concept registry every other stage
also sees, per spec section 4's layering.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import DeduplicationCandidate

FUZZY_THRESHOLD = 0.6


@dataclass
class DeduplicationStats:
    candidates_found: dict[str, int] = field(default_factory=dict)
    candidates_inserted: int = 0
    candidates_already_pending: int = 0


def _insert_candidates(db: Session, stats: DeduplicationStats, reason: str, pairs: list[tuple[str, str, float]]) -> None:
    stats.candidates_found[reason] = len(pairs)
    for a, b, similarity in pairs:
        candidate_a, candidate_b = sorted((a, b))
        exists = db.execute(
            text("SELECT 1 FROM deduplication_candidates WHERE candidate_a = :a AND candidate_b = :b"),
            {"a": candidate_a, "b": candidate_b},
        ).first()
        if exists:
            stats.candidates_already_pending += 1
            continue
        db.add(DeduplicationCandidate(
            candidate_a=candidate_a, candidate_b=candidate_b,
            similarity=similarity, reason=reason, status="pending",
        ))
        stats.candidates_inserted += 1
    db.flush()


def _stage_exact_normalized_match(db: Session) -> list[tuple[str, str, float]]:
    rows = db.execute(text("""
        SELECT n1.concept_id, n2.concept_id
        FROM concept_names n1
        JOIN concept_names n2
          ON n1.normalized_name = n2.normalized_name
         AND n1.concept_id < n2.concept_id
        WHERE n1.name_type = 'preferred' AND n2.name_type = 'preferred'
        GROUP BY n1.concept_id, n2.concept_id
    """)).fetchall()
    return [(a, b, 1.0) for a, b in rows]


def _stage_known_synonym_match(db: Session) -> list[tuple[str, str, float]]:
    # Excludes botanical/scientific-name pairs on BOTH sides deliberately:
    # that specific combination belongs to _stage_scientific_name_match
    # (stronger, more specific evidence) even though it would otherwise
    # also satisfy this broader "any non-preferred-pair name match"
    # condition — found via a real test failure (Giloy/Amrita's shared
    # botanical name was being attributed to this stage instead).
    rows = db.execute(text("""
        SELECT n1.concept_id, n2.concept_id
        FROM concept_names n1
        JOIN concept_names n2
          ON n1.normalized_name = n2.normalized_name
         AND n1.concept_id < n2.concept_id
        WHERE NOT (n1.name_type = 'preferred' AND n2.name_type = 'preferred')
          AND NOT (n1.name_type IN ('botanical', 'scientific') AND n2.name_type IN ('botanical', 'scientific'))
        GROUP BY n1.concept_id, n2.concept_id
    """)).fetchall()
    return [(a, b, 1.0) for a, b in rows]


def _stage_scientific_name_match(db: Session) -> list[tuple[str, str, float]]:
    rows = db.execute(text("""
        SELECT n1.concept_id, n2.concept_id
        FROM concept_names n1
        JOIN concept_names n2
          ON n1.normalized_name = n2.normalized_name
         AND n1.concept_id < n2.concept_id
        WHERE n1.name_type IN ('botanical', 'scientific')
          AND n2.name_type IN ('botanical', 'scientific')
        GROUP BY n1.concept_id, n2.concept_id
    """)).fetchall()
    return [(a, b, 1.0) for a, b in rows]


def _stage_high_confidence_fuzzy_match(db: Session, threshold: float = FUZZY_THRESHOLD) -> list[tuple[str, str, float]]:
    rows = db.execute(text("""
        SELECT n1.concept_id, n2.concept_id, similarity(n1.normalized_name, n2.normalized_name) AS sim
        FROM concept_names n1
        JOIN concept_names n2
          ON n1.concept_id < n2.concept_id
         AND n1.normalized_name % n2.normalized_name
        WHERE n1.name_type = 'preferred' AND n2.name_type = 'preferred'
          AND n1.normalized_name != n2.normalized_name
          AND similarity(n1.normalized_name, n2.normalized_name) >= :threshold
        GROUP BY n1.concept_id, n2.concept_id, sim
    """), {"threshold": threshold}).fetchall()
    return [(a, b, float(sim)) for a, b, sim in rows]


def run_deduplication(db: Session) -> DeduplicationStats:
    stats = DeduplicationStats()
    already_matched: set[tuple[str, str]] = set()

    for reason, stage_fn in [
        ("exact_normalized_match", _stage_exact_normalized_match),
        ("known_synonym_match", _stage_known_synonym_match),
        ("scientific_name_match", _stage_scientific_name_match),
        ("high_confidence_fuzzy_match", _stage_high_confidence_fuzzy_match),
    ]:
        pairs = stage_fn(db)
        # A pair already flagged by an earlier (stronger-evidence) stage is
        # not re-flagged by a later, weaker stage under a different reason
        # — one candidate row per pair, with the strongest evidence that
        # actually applies.
        new_pairs = [(a, b, sim) for a, b, sim in pairs if tuple(sorted((a, b))) not in already_matched]
        already_matched.update(tuple(sorted((a, b))) for a, b, _ in pairs)
        _insert_candidates(db, stats, reason, new_pairs)

    db.commit()
    return stats
