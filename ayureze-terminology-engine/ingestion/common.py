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

from models import Concept, ConceptName, Source, SourceRecord
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


def add_name(db: Session, concept: Concept, name: str, language: str, name_type: str, source_record: SourceRecord, script: str | None = None) -> ConceptName | None:
    """Returns None (and adds nothing) for an empty/whitespace-only name
    rather than inserting a useless row — this is a real, counted
    rejection, not a silent skip; callers should track it via
    IngestionStats.reject()."""
    if not name or not name.strip():
        return None
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
    return concept_name


def link_source_record_to_concept(db: Session, source_record: SourceRecord, concept: Concept) -> None:
    source_record.concept_id = concept.concept_id
    db.flush()


def get_or_create_biomedical_stub(db: Session, canonical_name: str) -> Concept:
    """A minimal, UNVERIFIED BIO-DISEASE placeholder concept, created only
    from an Ayurveda/interop source's own stated biomedical correlate
    (e.g. pathology's "correlation" field, NAMASTE's parenthetical
    English gloss) — never from bulk-copying ICD-11/SNOMED (spec section
    18). confidence=0.5 deliberately marks this as source-asserted, not
    independently verified against a real biomedical terminology.
    Idempotent by exact canonical_name match within category=DISEASE, so
    multiple sources citing the same biomedical term share one stub."""
    existing = db.execute(select(Concept).where(Concept.canonical_name == canonical_name, Concept.category == "DISEASE")).scalar_one_or_none()
    if existing is not None:
        return existing
    concept = Concept(
        concept_id=next_concept_id(db, "BIO-DISEASE"),
        domain="BIOMEDICAL", category="DISEASE",
        canonical_name=canonical_name, definition=None,
        status="candidate", confidence=0.5,
    )
    db.add(concept)
    db.flush()
    return concept
