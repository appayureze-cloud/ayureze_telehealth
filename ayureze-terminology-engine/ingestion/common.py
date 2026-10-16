"""Shared plumbing every per-source ingester uses — kept here once instead
of repeated seven times, per this project's own "don't over-engineer, but
don't duplicate either" standard. Handles the layers spec section 4 asks
to be kept separate: registering the Source row, writing an immutable
SourceRecord per raw record, minting a Concept, and attaching
ConceptNames — normalization is applied here but nothing here ever
mutates the original raw value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Concept, ConceptName, ConceptRelationship, Source, SourceRecord
from normalization import normalize_name
from services.concept_id import next_concept_id


@dataclass
class IngestionStats:
    """Real counts for docs/DATA_QUALITY_REPORT.md — never silently
    dropped (spec section 22: "Do not silently discard conflicts")."""

    source_name: str
    read_count: int = 0
    imported_count: int = 0
    rejected_count: int = 0
    rejected_reasons: list[str] = field(default_factory=list)
    concepts_created: int = 0
    names_created: int = 0
    skipped_unchanged: int = 0
    payload_updated_on_rerun: int = 0

    def reject(self, reason: str) -> None:
        self.rejected_count += 1
        self.rejected_reasons.append(reason)


def get_or_create_source(db: Session, manifest_entry: dict) -> Source:
    existing = db.execute(select(Source).where(Source.source_name == manifest_entry["source_name"])).scalar_one_or_none()
    if existing is not None:
        return existing
    source = Source(
        source_name=manifest_entry["source_name"],
        repository_url=manifest_entry["repository_url"],
        version_or_commit=manifest_entry["version_or_commit"],
        license=manifest_entry["license"],
        retrieved_at=manifest_entry["retrieved_at"],
        record_count=manifest_entry["record_count"],
        commercial_use_status=manifest_entry["commercial_use_status"],
        notes=manifest_entry.get("notes"),
    )
    db.add(source)
    db.flush()
    return source


def find_existing_source_record(db: Session, source: Source, source_record_id: str) -> SourceRecord | None:
    """The natural key ingestion idempotency is built on: (source_id,
    source_record_id). Most of this project's sources have no ID field of
    their own (verified per-source in data/manifests/source_manifest.json)
    — the array index or file path each ingester already uses as
    source_record_id IS that record's stable identity across runs, as
    long as the underlying source file's ordering/paths don't change
    between re-ingestions (a real, documented assumption, not a hidden
    one — see docs/INGESTION.md)."""
    return db.execute(
        select(SourceRecord).where(SourceRecord.source_id == source.id, SourceRecord.source_record_id == source_record_id)
    ).scalar_one_or_none()


def create_source_record(db: Session, source: Source, source_record_id: str, original_payload: dict, source_url: str) -> SourceRecord:
    """original_payload is stored EXACTLY as read from the raw file —
    never post-normalization, never post-parsing-cleanup. json-round-trips
    to guarantee it is JSON-serializable as-is (spec section 10: "Every
    canonical concept must be traceable back to its source records")."""
    record = SourceRecord(
        source_id=source.id,
        source_record_id=source_record_id,
        concept_id=None,
        original_payload=json.loads(json.dumps(original_payload, ensure_ascii=False, default=str)),
        source_version=source.version_or_commit,
        source_url=source_url,
        ingestion_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    db.add(record)
    db.flush()
    return record


def create_concept(db: Session, prefix: str, domain: str, category: str, canonical_name: str, definition: str | None, confidence: float = 1.0) -> Concept:
    concept_id = next_concept_id(db, prefix)
    concept = Concept(
        concept_id=concept_id,
        domain=domain,
        category=category,
        canonical_name=canonical_name,
        definition=definition,
        status="candidate",
        confidence=confidence,
    )
    db.add(concept)
    db.flush()
    return concept


def get_or_create_record_and_concept(
    db: Session, stats: IngestionStats, source: Source, source_record_id: str, original_payload: dict, source_url: str,
    prefix: str, domain: str, category: str, canonical_name: str, definition: str | None, confidence: float = 1.0,
) -> tuple[SourceRecord, Concept, bool]:
    """The idempotent entry point every ingester should use instead of
    calling create_source_record/create_concept/link_source_record_to_concept
    separately. Re-running an ingester against the SAME source file no
    longer mints a second concept for a record already seen — the real
    gap flagged in docs/INGESTION.md's "known limitation" until now.

    Returns (source_record, concept, is_new). When is_new is False, the
    payload is refreshed in place if it changed (a source file CAN change
    upstream between runs; we don't want a stale copy silently kept
    forever), but the concept itself, its concept_id, and its names are
    left untouched — re-ingestion never re-mints an ID for something that
    already has one."""
    existing = find_existing_source_record(db, source, source_record_id)
    normalized_payload = json.loads(json.dumps(original_payload, ensure_ascii=False, default=str))

    if existing is not None:
        concept = (
            db.execute(select(Concept).where(Concept.concept_id == existing.concept_id)).scalar_one_or_none()
            if existing.concept_id else None
        )
        if concept is None:
            # A source_record exists but was never linked to a concept
            # (e.g. a prior run was interrupted) — treat as new.
            concept = create_concept(db, prefix, domain, category, canonical_name, definition, confidence)
            link_source_record_to_concept(db, existing, concept)
            stats.concepts_created += 1
            return existing, concept, True
        if existing.original_payload != normalized_payload:
            existing.original_payload = normalized_payload
            existing.ingestion_timestamp = datetime.now(timezone.utc).isoformat()
            db.flush()
            stats.payload_updated_on_rerun += 1
        else:
            stats.skipped_unchanged += 1
        return existing, concept, False

    source_record = create_source_record(db, source, source_record_id, original_payload, source_url)
    concept = create_concept(db, prefix, domain, category, canonical_name, definition, confidence)
    link_source_record_to_concept(db, source_record, concept)
    stats.concepts_created += 1
    return source_record, concept, True


def add_name(db: Session, stats: IngestionStats, concept: Concept, name: str, language: str, name_type: str, source_record: SourceRecord, script: str | None = None) -> ConceptName | None:
    """Returns None (and adds nothing) for an empty/whitespace-only name —
    callers that need to track that as a rejection call stats.reject()
    themselves; this function only manages names_created, so re-running an
    ingester never double-counts a name that already existed.

    Idempotent: re-running an ingester over a record that already has this
    exact (concept_id, name, name_type) combination finds and returns the
    existing row (stats untouched) instead of inserting a duplicate — the
    other half of making ingestion safe to re-run (see
    get_or_create_record_and_concept)."""
    if not name or not name.strip():
        return None
    existing = db.execute(
        select(ConceptName).where(
            ConceptName.concept_id == concept.concept_id,
            ConceptName.name == name,
            ConceptName.name_type == name_type,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    concept_name = ConceptName(
        concept_id=concept.concept_id,
        name=name,
        normalized_name=normalize_name(name),
        language=language,
        script=script,
        name_type=name_type,
        source_record_id=source_record.id,
    )
    db.add(concept_name)
    db.flush()
    stats.names_created += 1
    return concept_name


def link_source_record_to_concept(db: Session, source_record: SourceRecord, concept: Concept) -> None:
    source_record.concept_id = concept.concept_id
    db.flush()


def add_relationship_if_new(
    db: Session, concept_id_a: str, concept_id_b: str, relationship_type: str,
    evidence: str, source_record: SourceRecord, confidence: float = 1.0,
) -> bool:
    """Idempotent relationship creation — the third piece of making
    ingestion safe to re-run (concepts and names were the other two). A
    re-run must not insert a second identical HAS_INGREDIENT/RELATED_TO
    row for a pair already linked. Returns True if a new row was
    inserted, False if one already existed."""
    # .first(), not .scalar_one_or_none(): this build's very first
    # (pre-idempotent) ingestion runs could insert more than one identical
    # row for a pair when a source record listed the same ingredient
    # twice (a real, confirmed case in the Bhaishajya data) — any match at
    # all means "already linked," so tolerate more than one existing row
    # rather than erroring on it.
    existing = db.execute(
        select(ConceptRelationship).where(
            ConceptRelationship.concept_id_a == concept_id_a,
            ConceptRelationship.concept_id_b == concept_id_b,
            ConceptRelationship.relationship_type == relationship_type,
        )
    ).first()
    if existing is not None:
        return False
    db.add(ConceptRelationship(
        concept_id_a=concept_id_a, concept_id_b=concept_id_b, relationship_type=relationship_type,
        evidence=evidence, confidence=confidence, source_record_id=source_record.id,
    ))
    db.flush()
    return True


def get_or_create_biomedical_stub(db: Session, canonical_name: str) -> tuple[Concept, bool]:
    """A minimal, UNVERIFIED BIO-DISEASE placeholder concept, created only
    from an Ayurveda/interop source's own stated biomedical correlate
    (e.g. pathology's "correlation" field, NAMASTE's parenthetical
    English gloss) — never from bulk-copying ICD-11/SNOMED (spec section
    18). confidence=0.5 deliberately marks this as source-asserted, not
    independently verified against a real biomedical terminology.
    Idempotent by exact canonical_name match within category=DISEASE, so
    multiple sources citing the same biomedical term share one stub.
    Returns (concept, is_new) so callers can keep an honest count of how
    many stubs were actually newly minted vs. reused."""
    existing = db.execute(select(Concept).where(Concept.canonical_name == canonical_name, Concept.category == "DISEASE")).scalar_one_or_none()
    if existing is not None:
        return existing, False
    concept = Concept(
        concept_id=next_concept_id(db, "BIO-DISEASE"),
        domain="BIOMEDICAL", category="DISEASE",
        canonical_name=canonical_name, definition=None,
        status="candidate", confidence=0.5,
    )
    db.add(concept)
    db.flush()
    return concept, True
