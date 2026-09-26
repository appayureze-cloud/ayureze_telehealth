from __future__ import annotations

from pydantic import BaseModel, Field


class SearchMatchResponse(BaseModel):
    concept_id: str
    canonical_name: str
    category: str
    domain: str
    match_type: str
    confidence: float
    matched_name: str


class SearchResponse(BaseModel):
    query: str
    matches: list[SearchMatchResponse]


class ResolveRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)


class ResolveMatch(BaseModel):
    concept_id: str
    canonical_name: str
    category: str
    match_type: str
    confidence: float


class ResolveResponse(BaseModel):
    query: str
    matches: list[ResolveMatch]


class ConceptResponse(BaseModel):
    concept_id: str
    domain: str
    category: str
    canonical_name: str
    definition: str | None
    status: str
    confidence: float


class ConceptNameResponse(BaseModel):
    name: str
    normalized_name: str
    language: str
    script: str | None
    name_type: str


class SourceRecordResponse(BaseModel):
    source_name: str
    source_record_id: str
    source_url: str
    source_version: str
    ingestion_timestamp: str


class ConceptRelationshipResponse(BaseModel):
    concept_id_a: str
    concept_id_b: str
    relationship_type: str
    evidence: str
    confidence: float


class SourceResponse(BaseModel):
    source_name: str
    repository_url: str
    version_or_commit: str
    license: str
    retrieved_at: str
    record_count: int
    commercial_use_status: str
    notes: str | None


class StatsResponse(BaseModel):
    total_concepts: int
    concepts_by_domain: dict[str, int]
    concepts_by_category: dict[str, int]
    total_names: int
    total_relationships: int
    total_source_records: int
    total_sources: int
    deduplication_candidates_pending: int
    deduplication_candidates_accepted: int
    deduplication_candidates_rejected: int


class HealthResponse(BaseModel):
    status: str
    database: str


class BiomedicalLookupResultResponse(BaseModel):
    code: str
    display: str
    source: str
    source_url: str


class BiomedicalSearchResponse(BaseModel):
    system: str
    query: str
    results: list[BiomedicalLookupResultResponse]
