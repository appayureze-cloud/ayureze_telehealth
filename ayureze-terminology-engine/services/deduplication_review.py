"""Human review actions on `deduplication_candidates` (spec section 13).

`deduplication/pipeline.py`'s own docstring anticipated this exact module:
"A human (or a future, explicitly separate review action —
services/deduplication_review.py) is the only thing that can move a
candidate to 'accepted'/'rejected'." Accepting a candidate NEVER merges
the two concepts, deletes a row, or retires a concept_id — it only records
the human decision and creates a human-evidenced `SYNONYM_OF` relationship
between the two concepts, which remain independently addressable. This is
the review-queue outcome the spec's "never auto-merge" rule always
intended a human to eventually reach for; the pipeline itself still never
does this on its own.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import ConceptRelationship, DeduplicationCandidate


class CandidateNotFoundError(Exception):
    pass


class CandidateAlreadyReviewedError(Exception):
    def __init__(self, candidate_id: int, status: str):
        self.candidate_id = candidate_id
        self.status = status
        super().__init__(f"deduplication candidate {candidate_id} was already reviewed (status={status!r})")


def _get_pending_candidate(db: Session, candidate_id: int) -> DeduplicationCandidate:
    candidate = db.get(DeduplicationCandidate, candidate_id)
    if candidate is None:
        raise CandidateNotFoundError(f"deduplication candidate {candidate_id} not found")
    if candidate.status != "pending":
        raise CandidateAlreadyReviewedError(candidate_id, candidate.status)
    return candidate


def accept_candidate(db: Session, candidate_id: int, reviewed_by: str, review_notes: str | None) -> DeduplicationCandidate:
    """Idempotent on the relationship it creates: if that exact SYNONYM_OF
    pair already exists (e.g. the pipeline separately caught the same pair
    under a different reason first), it is not duplicated."""
    candidate = _get_pending_candidate(db, candidate_id)
    evidence = f"Human review accepted deduplication candidate #{candidate.id} (reason={candidate.reason}, similarity={candidate.similarity:.3f}), reviewed_by={reviewed_by!r}"
    existing = db.execute(
        select(ConceptRelationship).where(
            ConceptRelationship.concept_id_a == candidate.candidate_a,
            ConceptRelationship.concept_id_b == candidate.candidate_b,
            ConceptRelationship.relationship_type == "SYNONYM_OF",
        )
    ).first()
    if existing is None:
        db.add(ConceptRelationship(
            concept_id_a=candidate.candidate_a, concept_id_b=candidate.candidate_b,
            relationship_type="SYNONYM_OF", evidence=evidence, confidence=1.0, source_record_id=None,
        ))
    candidate.status = "accepted"
    candidate.reviewed_by = reviewed_by
    candidate.review_notes = review_notes
    db.commit()
    db.refresh(candidate)
    return candidate


def reject_candidate(db: Session, candidate_id: int, reviewed_by: str, review_notes: str | None) -> DeduplicationCandidate:
    """No relationship is created — the two concepts stand as independent,
    non-duplicate entries; only the review decision itself is recorded."""
    candidate = _get_pending_candidate(db, candidate_id)
    candidate.status = "rejected"
    candidate.reviewed_by = reviewed_by
    candidate.review_notes = review_notes
    db.commit()
    db.refresh(candidate)
    return candidate
