from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, aliased

from api.rate_limit import RateLimiter, client_key
from config.settings import get_settings
from database import get_db
from mappings.atc import AtcAdapter
from mappings.base import AdapterNotConfiguredError, BiomedicalAdapter
from mappings.icd11 import ICD11Adapter
from mappings.loinc import LoincAdapter
from mappings.mesh import MeshAdapter
from mappings.rxnorm import RxNormAdapter
from mappings.snomed import SnomedAdapter
from models import Concept, ConceptName, ConceptRelationship, DeduplicationCandidate, Source, SourceRecord
from schemas.terminology import (
    BiomedicalLookupResultResponse,
    BiomedicalSearchResponse,
    ConceptNameResponse,
    ConceptRelationshipResponse,
    ConceptResponse,
    DeduplicationCandidateResponse,
    DeduplicationReviewRequest,
    HealthResponse,
    ResolveMatch,
    ResolveRequest,
    ResolveResponse,
    SearchMatchResponse,
    SearchResponse,
    SourceRecordResponse,
    SourceResponse,
    StatsResponse,
)
from services.deduplication_review import (
    CandidateAlreadyReviewedError,
    CandidateNotFoundError,
    accept_candidate,
    reject_candidate,
)
from terminology.search import search_terms

# Every adapter this endpoint can route to — see docs/LICENSE_MATRIX.md
# for which of these actually work without extra setup (rxnorm/mesh, real
# public APIs) vs. correctly raise AdapterNotConfiguredError (icd11/loinc
# need real credentials this deployment doesn't have; snomed is disabled
# by policy until a licensed terminology server is configured; atc has no
# automated lookup path at all, ever, per its source's own terms).
_BIOMEDICAL_ADAPTERS: dict[str, type[BiomedicalAdapter]] = {
    "rxnorm": RxNormAdapter,
    "mesh": MeshAdapter,
    "icd11": ICD11Adapter,
    "loinc": LoincAdapter,
    "snomed": SnomedAdapter,
    "atc": AtcAdapter,
}

router = APIRouter()
_settings = get_settings()
_rate_limiter = RateLimiter(_settings.rate_limit_per_minute)


def _enforce_rate_limit(request: Request) -> None:
    _rate_limiter.check(client_key(request))


def _validate_query_length(q: str) -> str:
    if len(q) > _settings.max_query_length:
        raise HTTPException(status_code=422, detail=f"query too long (max {_settings.max_query_length} characters)")
    return q


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unavailable"
    return HealthResponse(status="ok" if db_status == "ok" else "degraded", database=db_status)


@router.get("/v1/terminology/search", response_model=SearchResponse)
def search(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> SearchResponse:
    _enforce_rate_limit(request)
    q = _validate_query_length(q)
    matches = search_terms(db, q, limit=limit)
    return SearchResponse(
        query=q,
        matches=[SearchMatchResponse(**m.__dict__) for m in matches],
    )


@router.post("/v1/terminology/resolve", response_model=ResolveResponse)
def resolve(request: Request, body: ResolveRequest, db: Session = Depends(get_db)) -> ResolveResponse:
    _enforce_rate_limit(request)
    matches = search_terms(db, body.text, limit=10)
    return ResolveResponse(
        query=body.text,
        matches=[ResolveMatch(concept_id=m.concept_id, canonical_name=m.canonical_name, category=m.category, match_type=m.match_type, confidence=m.confidence) for m in matches],
    )


@router.get("/v1/biomedical/{system}/search", response_model=BiomedicalSearchResponse)
def biomedical_search(request: Request, system: str, q: str = Query(..., min_length=1)) -> BiomedicalSearchResponse:
    """Live lookup only — spec section 18: never a bulk local copy. `system`
    is one of rxnorm/mesh (genuinely work today, real public APIs, no
    credentials needed) or icd11/loinc/snomed/atc (correctly return 503:
    real credentials/licensing this deployment doesn't have, or — for atc
    — a permanent, by-design absence of any automated lookup path at all).
    See docs/LICENSE_MATRIX.md for exactly why each one is in which state.
    """
    _enforce_rate_limit(request)
    q = _validate_query_length(q)
    adapter_cls = _BIOMEDICAL_ADAPTERS.get(system)
    if adapter_cls is None:
        raise HTTPException(status_code=404, detail=f"unknown biomedical system {system!r}; available: {sorted(_BIOMEDICAL_ADAPTERS)}")

    adapter = adapter_cls()
    try:
        results = adapter.lookup(q)
    except AdapterNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"upstream {system} service error: {e}") from e

    return BiomedicalSearchResponse(
        system=system, query=q,
        results=[BiomedicalLookupResultResponse(code=r.code, display=r.display, source=r.source, source_url=r.source_url) for r in results],
    )


@router.get("/v1/terminology/concepts/{concept_id}", response_model=ConceptResponse)
def get_concept(concept_id: str, db: Session = Depends(get_db)) -> ConceptResponse:
    concept = db.execute(select(Concept).where(Concept.concept_id == concept_id)).scalar_one_or_none()
    if concept is None:
        raise HTTPException(status_code=404, detail=f"concept {concept_id!r} not found")
    return ConceptResponse(
        concept_id=concept.concept_id, domain=concept.domain, category=concept.category,
        canonical_name=concept.canonical_name, definition=concept.definition,
        status=concept.status, confidence=concept.confidence,
    )


@router.get("/v1/terminology/concepts/{concept_id}/names", response_model=list[ConceptNameResponse])
def get_concept_names(concept_id: str, db: Session = Depends(get_db)) -> list[ConceptNameResponse]:
    if db.execute(select(Concept.id).where(Concept.concept_id == concept_id)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"concept {concept_id!r} not found")
    names = db.execute(select(ConceptName).where(ConceptName.concept_id == concept_id)).scalars().all()
    return [ConceptNameResponse(name=n.name, normalized_name=n.normalized_name, language=n.language, script=n.script, name_type=n.name_type) for n in names]


@router.get("/v1/terminology/concepts/{concept_id}/sources", response_model=list[SourceRecordResponse])
def get_concept_sources(concept_id: str, db: Session = Depends(get_db)) -> list[SourceRecordResponse]:
    if db.execute(select(Concept.id).where(Concept.concept_id == concept_id)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"concept {concept_id!r} not found")
    rows = db.execute(
        select(SourceRecord, Source.source_name)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(SourceRecord.concept_id == concept_id)
    ).all()
    return [
        SourceRecordResponse(
            source_name=source_name, source_record_id=record.source_record_id,
            source_url=record.source_url, source_version=record.source_version,
            ingestion_timestamp=record.ingestion_timestamp,
        )
        for record, source_name in rows
    ]


@router.get("/v1/terminology/concepts/{concept_id}/relationships", response_model=list[ConceptRelationshipResponse])
def get_concept_relationships(concept_id: str, db: Session = Depends(get_db)) -> list[ConceptRelationshipResponse]:
    if db.execute(select(Concept.id).where(Concept.concept_id == concept_id)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"concept {concept_id!r} not found")
    rows = db.execute(
        select(ConceptRelationship).where(
            (ConceptRelationship.concept_id_a == concept_id) | (ConceptRelationship.concept_id_b == concept_id)
        )
    ).scalars().all()
    return [
        ConceptRelationshipResponse(
            concept_id_a=r.concept_id_a, concept_id_b=r.concept_id_b,
            relationship_type=r.relationship_type, evidence=r.evidence, confidence=r.confidence,
        )
        for r in rows
    ]


@router.get("/v1/sources", response_model=list[SourceResponse])
def list_sources(db: Session = Depends(get_db)) -> list[SourceResponse]:
    sources = db.execute(select(Source)).scalars().all()
    return [
        SourceResponse(
            source_name=s.source_name, repository_url=s.repository_url, version_or_commit=s.version_or_commit,
            license=s.license, retrieved_at=s.retrieved_at, record_count=s.record_count,
            commercial_use_status=s.commercial_use_status, notes=s.notes,
        )
        for s in sources
    ]


@router.get("/v1/deduplication/candidates", response_model=list[DeduplicationCandidateResponse])
def list_deduplication_candidates(
    request: Request,
    status: str = Query("pending", pattern="^(pending|accepted|rejected)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[DeduplicationCandidateResponse]:
    """The review queue itself (spec section 13) — every row here is a
    flagged, NOT auto-merged pair. Defaults to `status=pending` since
    that's the actionable set; pass `status=accepted`/`rejected` to see
    past decisions. Ordered by similarity descending so the strongest,
    most obviously-correct candidates (e.g. exact_normalized_match at
    1.0) surface first for a reviewer."""
    _enforce_rate_limit(request)
    concept_a = aliased(Concept)
    concept_b = aliased(Concept)
    rows = db.execute(
        select(DeduplicationCandidate, concept_a.canonical_name, concept_b.canonical_name)
        .join(concept_a, concept_a.concept_id == DeduplicationCandidate.candidate_a)
        .join(concept_b, concept_b.concept_id == DeduplicationCandidate.candidate_b)
        .where(DeduplicationCandidate.status == status)
        .order_by(DeduplicationCandidate.similarity.desc(), DeduplicationCandidate.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        DeduplicationCandidateResponse(
            id=c.id, candidate_a=c.candidate_a, candidate_a_name=name_a,
            candidate_b=c.candidate_b, candidate_b_name=name_b,
            similarity=c.similarity, reason=c.reason, status=c.status,
            reviewed_by=c.reviewed_by, review_notes=c.review_notes,
        )
        for c, name_a, name_b in rows
    ]


def _candidate_response(db: Session, candidate: DeduplicationCandidate) -> DeduplicationCandidateResponse:
    name_a = db.execute(select(Concept.canonical_name).where(Concept.concept_id == candidate.candidate_a)).scalar_one()
    name_b = db.execute(select(Concept.canonical_name).where(Concept.concept_id == candidate.candidate_b)).scalar_one()
    return DeduplicationCandidateResponse(
        id=candidate.id, candidate_a=candidate.candidate_a, candidate_a_name=name_a,
        candidate_b=candidate.candidate_b, candidate_b_name=name_b,
        similarity=candidate.similarity, reason=candidate.reason, status=candidate.status,
        reviewed_by=candidate.reviewed_by, review_notes=candidate.review_notes,
    )


@router.post("/v1/deduplication/candidates/{candidate_id}/accept", response_model=DeduplicationCandidateResponse)
def accept_deduplication_candidate(candidate_id: int, body: DeduplicationReviewRequest, request: Request, db: Session = Depends(get_db)) -> DeduplicationCandidateResponse:
    """Accepting NEVER merges the two concepts (spec section 13) — it
    records the human decision and creates a human-evidenced SYNONYM_OF
    relationship between them; both concept_ids remain independently
    addressable and unchanged. See services/deduplication_review.py."""
    _enforce_rate_limit(request)
    try:
        candidate = accept_candidate(db, candidate_id, body.reviewed_by, body.review_notes)
    except CandidateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CandidateAlreadyReviewedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _candidate_response(db, candidate)


@router.post("/v1/deduplication/candidates/{candidate_id}/reject", response_model=DeduplicationCandidateResponse)
def reject_deduplication_candidate(candidate_id: int, body: DeduplicationReviewRequest, request: Request, db: Session = Depends(get_db)) -> DeduplicationCandidateResponse:
    """Rejecting records the decision only — no relationship is created,
    and both concepts stand as independent, non-duplicate entries."""
    _enforce_rate_limit(request)
    try:
        candidate = reject_candidate(db, candidate_id, body.reviewed_by, body.review_notes)
    except CandidateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CandidateAlreadyReviewedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _candidate_response(db, candidate)


@router.get("/v1/stats", response_model=StatsResponse)
def stats(db: Session = Depends(get_db)) -> StatsResponse:
    total_concepts = db.execute(select(func.count()).select_from(Concept)).scalar_one()
    by_domain = dict(db.execute(select(Concept.domain, func.count()).group_by(Concept.domain)).all())
    by_category = dict(db.execute(select(Concept.category, func.count()).group_by(Concept.category)).all())
    total_names = db.execute(select(func.count()).select_from(ConceptName)).scalar_one()
    total_relationships = db.execute(select(func.count()).select_from(ConceptRelationship)).scalar_one()
    total_source_records = db.execute(select(func.count()).select_from(SourceRecord)).scalar_one()
    total_sources = db.execute(select(func.count()).select_from(Source)).scalar_one()
    dedup_by_status = dict(db.execute(select(DeduplicationCandidate.status, func.count()).group_by(DeduplicationCandidate.status)).all())

    return StatsResponse(
        total_concepts=total_concepts,
        concepts_by_domain=by_domain,
        concepts_by_category=by_category,
        total_names=total_names,
        total_relationships=total_relationships,
        total_source_records=total_source_records,
        total_sources=total_sources,
        deduplication_candidates_pending=dedup_by_status.get("pending", 0),
        deduplication_candidates_accepted=dedup_by_status.get("accepted", 0),
        deduplication_candidates_rejected=dedup_by_status.get("rejected", 0),
    )
