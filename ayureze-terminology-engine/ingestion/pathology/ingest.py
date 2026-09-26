"""Ingests data/raw/pathology/Encyclopedia-of-Ayurvedic-Pathology.json (203
real records, CC-BY-4.0) as AYU-PATHOLOGY concepts.

The "correlation" field (e.g. Amavata -> "Rheumatoid Arthritis") is a REAL
finding worth being explicit about: it is the SOURCE's own claimed
biomedical correlate, not a verified ICD-11/SNOMED lookup. This ingester
creates a minimal BIO-DISEASE STUB concept for each unique correlation
string encountered (domain=BIOMEDICAL, category=DISEASE, confidence=0.5 —
deliberately lower than a directly-sourced concept's default 1.0, since
this is unverified against any real biomedical terminology, just recorded
verbatim from what this Ayurveda source asserts) and links it via
RELATED_TO (never EXACT_MATCH — spec section 11 explicitly forbids
auto-assigning EXACT_MATCH between an Ayurvedic and biomedical concept).
Verifying these stub concepts against a real biomedical terminology
(ICD-11 TM2 is the obvious candidate, since this is precisely what it
exists to standardize) is future adapter work, not done here — this
codebase does NOT bulk-copy ICD-11 content, per spec section 18.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from ingestion.common import IngestionStats, add_name, add_relationship_if_new, get_or_create_biomedical_stub, get_or_create_record_and_concept, get_or_create_source

RAW_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "pathology" / "Encyclopedia-of-Ayurvedic-Pathology.json"
MANIFEST_SOURCE_NAME = "encyclopedia_of_ayurvedic_pathology"

_LIST_FIELDS = ["nidana", "purvarupa", "rupa", "upashaya", "anupashaya", "bheda", "keyFormulations"]


def load_manifest_entry() -> dict:
    manifest = json.loads((Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json").read_text())
    return next(s for s in manifest["sources"] if s["source_name"] == MANIFEST_SOURCE_NAME)


def ingest(db: Session) -> IngestionStats:
    stats = IngestionStats(source_name=MANIFEST_SOURCE_NAME)
    source = get_or_create_source(db, load_manifest_entry())
    records = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    biomedical_stubs_created = 0

    for idx, entry in enumerate(records):
        stats.read_count += 1
        name = (entry.get("transliteratedName") or "").strip()
        if not name:
            stats.reject(f"record[{idx}]: missing required 'transliteratedName' field")
            continue

        definition_parts = [
            f"System: {entry['system']}" if entry.get("system") else None,
            f"Sadhya-Asadhyata (prognosis): {entry['sadhyaAsadhyata']}" if entry.get("sadhyaAsadhyata") else None,
            f"Samprapti (pathogenesis): {entry['samprapti']}" if entry.get("samprapti") else None,
            f"Chikitsa (treatment): {entry['chikitsa']}" if entry.get("chikitsa") else None,
            f"Reference: {entry['reference']}" if entry.get("reference") else None,
        ]
        for field in _LIST_FIELDS:
            values = entry.get(field) or []
            if values:
                definition_parts.append(f"{field}: {'; '.join(values)}")
        definition = " | ".join(p for p in definition_parts if p) or None

        source_record, concept, _is_new = get_or_create_record_and_concept(
            db, stats, source, source_record_id=str(idx), original_payload=entry,
            source_url="https://github.com/sciencewithsaucee-sudo/Encyclopedia-of-Ayurvedic-Pathology",
            prefix="AYU-PATHOLOGY", domain="AYURVEDA", category="PATHOLOGY_TERM",
            canonical_name=name, definition=definition,
        )

        add_name(db, stats, concept, name, language="sa", name_type="preferred", source_record=source_record, script="Latin")
        sanskrit = (entry.get("sanskritName") or "").strip()
        add_name(db, stats, concept, sanskrit, language="sa", name_type="synonym", source_record=source_record, script="Devanagari")

        correlation = (entry.get("correlation") or "").strip()
        if correlation:
            stub, stub_is_new = get_or_create_biomedical_stub(db, correlation)
            if stub_is_new:
                biomedical_stubs_created += 1
            add_relationship_if_new(
                db, concept.concept_id, stub.concept_id, "RELATED_TO",
                evidence=f"Encyclopedia of Ayurvedic Pathology's own 'correlation' field for '{name}': '{correlation}' (source-asserted, NOT independently verified against ICD-11/SNOMED)",
                source_record=source_record, confidence=0.5,
            )

        stats.imported_count += 1

    db.commit()
    if biomedical_stubs_created:
        stats.rejected_reasons.append(f"informational: created {biomedical_stubs_created} unverified BIO-DISEASE stub concepts from source-asserted correlations")
    return stats


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = ingest(db)
        print(result)
    finally:
        db.close()
