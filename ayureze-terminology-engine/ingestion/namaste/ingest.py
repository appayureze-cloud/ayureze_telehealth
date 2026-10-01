"""Ingests data/raw/namaste/namaste_sample.csv — 14 REAL data rows.

HONEST LIMITATION, restated from the manifest: the NAMASTE repository's own
README advertises "7,363 codes", but the actual git repository content is
this 13-row sample only — the full dataset lives in a live external
MongoDB behind that project's own backend, which is NOT part of the
approved source list and was not accessed. This ingester processes
exactly what is actually present, no more.

term_english embeds a source-provided biomedical gloss in parentheses,
e.g. "Amavata (Rheumatoid Arthritis)" — split the same way as
Siddhanta's "Latin (Devanagari)" pattern, and (like pathology's
"correlation" field) linked via RELATED_TO to an unverified BIO-DISEASE
stub, never EXACT_MATCH.

Concepts are minted in the INTEROP domain (category NAMASTE_CODE, prefix
"NAMASTE") — spec section 19: "Do not treat the FHIR service itself as
the canonical medical truth." These are deliberately NOT merged into the
AYURVEDA-domain concepts from the other four sources even when a NAMASTE
term superficially resembles one (e.g. NAMASTE's "Amavata" vs. the
Encyclopedia of Ayurvedic Pathology's own "Amavata" record) — that
would be exactly the kind of unevidenced auto-merge deduplication must
never do; a human-reviewed deduplication_candidates entry is the correct
path if this is later confirmed, not silent identity.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ingestion.common import IngestionStats, add_name, add_relationship_if_new, get_or_create_biomedical_stub, get_or_create_record_and_concept, get_or_create_source

RAW_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "namaste" / "namaste_sample.csv"
MANIFEST_SOURCE_NAME = "namaste"
REPO_URL = "https://github.com/siddhanthsain/NAMASTE/tree/main/namaste-fhir-service"

_GLOSS_PATTERN = re.compile(r"^(?P<term>.+?)\s*\((?P<gloss>[^)]+)\)\s*$")


def load_manifest_entry() -> dict:
    manifest = json.loads((Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json").read_text())
    return next(s for s in manifest["sources"] if s["source_name"] == MANIFEST_SOURCE_NAME)


def ingest(db: Session) -> IngestionStats:
    stats = IngestionStats(source_name=MANIFEST_SOURCE_NAME)
    source = get_or_create_source(db, load_manifest_entry())

    with RAW_FILE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for idx, row in enumerate(rows):
        stats.read_count += 1
        namaste_code = (row.get("namaste_code") or "").strip()
        term_original = (row.get("term_original") or "").strip()
        if not namaste_code or not term_original:
            stats.reject(f"row[{idx}]: missing namaste_code or term_original")
            continue

        term_english = (row.get("term_english") or "").strip()
        gloss_match = _GLOSS_PATTERN.match(term_english) if term_english else None
        biomedical_gloss = gloss_match.group("gloss").strip() if gloss_match else None

        definition_parts = [
            f"NAMASTE code: {namaste_code}",
            f"System: {row['system']}" if row.get("system") else None,
            f"Category: {row['category']}" if row.get("category") else None,
        ]
        definition = " | ".join(p for p in definition_parts if p)

        source_record, concept, _is_new = get_or_create_record_and_concept(
            db, stats, source, source_record_id=namaste_code, original_payload=row, source_url=REPO_URL,
            prefix="NAMASTE", domain="INTEROP", category="NAMASTE_CODE",
            canonical_name=term_original, definition=definition,
        )

        add_name(db, stats, concept, term_original, language="unspecified", name_type="preferred", source_record=source_record, script="Latin")
        if term_english:
            add_name(db, stats, concept, term_english, language="en", name_type="synonym", source_record=source_record, script="Latin")

        if biomedical_gloss:
            stub, _stub_is_new = get_or_create_biomedical_stub(db, biomedical_gloss)
            add_relationship_if_new(
                db, concept.concept_id, stub.concept_id, "RELATED_TO",
                evidence=f"NAMASTE sample data's own term_english field for '{namaste_code}': '{term_english}' (source-asserted parenthetical gloss, NOT independently verified against ICD-11/SNOMED)",
                source_record=source_record, confidence=0.5,
            )

        stats.imported_count += 1

    db.commit()
    return stats


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = ingest(db)
        print(result)
    finally:
        db.close()
