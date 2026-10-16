"""Ingests data/raw/herb_database/herb.json (360 real records, CC-BY-4.0 —
see data/manifests/source_manifest.json) into raw SourceRecord rows, then
canonicalizes each into an AYU-HERB concept with names.

Field-to-schema mapping decisions (documented, not silently assumed):
  - herb["name"]           -> canonical_name + a PREFERRED ConceptName
  - herb["botanical_name"] -> a BOTANICAL ConceptName (Latin binomial)
  - herb["english_name"]   -> a SYNONYM ConceptName, language="en"
  - herb["sanskrit_synonyms"][] -> SYNONYM ConceptNames, language="sa",
    script="Latin" (the source stores these as Latin-script transliteration,
    e.g. "Surasa" — NOT Devanagari Unicode; verified by inspecting the raw
    file directly, not assumed)
  - herb["preview"]        -> Concept.definition (verbatim source prose)
  - herb has no stable ID field (verified: no "id"/"code" key exists) — the
    array index is used as source_record_id, which is why REPRODUCIBILITY
    depends on this exact file/commit, tracked in the manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from ingestion.common import IngestionStats, add_name, get_or_create_record_and_concept, get_or_create_source

RAW_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "herb_database" / "herb.json"
MANIFEST_SOURCE_NAME = "herb_database"


def load_manifest_entry() -> dict:
    manifest = json.loads((Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json").read_text())
    return next(s for s in manifest["sources"] if s["source_name"] == MANIFEST_SOURCE_NAME)


def ingest(db: Session) -> IngestionStats:
    stats = IngestionStats(source_name=MANIFEST_SOURCE_NAME)
    source = get_or_create_source(db, load_manifest_entry())
    records = json.loads(RAW_FILE.read_text(encoding="utf-8"))

    for idx, herb in enumerate(records):
        stats.read_count += 1
        name = (herb.get("name") or "").strip()
        if not name:
            stats.reject(f"record[{idx}]: missing required 'name' field")
            continue

        source_record, concept, _is_new = get_or_create_record_and_concept(
            db, stats, source, source_record_id=str(idx), original_payload=herb,
            source_url="https://github.com/sciencewithsaucee-sudo/herb-database",
            prefix="AYU-HERB", domain="AYURVEDA", category="HERB",
            canonical_name=name, definition=herb.get("preview") or None,
        )

        add_name(db, stats, concept, name, language="sa", name_type="preferred", source_record=source_record, script="Latin")

        botanical = (herb.get("botanical_name") or "").strip()
        if not add_name(db, stats, concept, botanical, language="la", name_type="botanical", source_record=source_record, script="Latin") and botanical == "":
            stats.reject(f"record[{idx}] ({name}): missing botanical_name")

        english = (herb.get("english_name") or "").strip()
        add_name(db, stats, concept, english, language="en", name_type="synonym", source_record=source_record, script="Latin")

        for synonym in herb.get("sanskrit_synonyms") or []:
            add_name(db, stats, concept, synonym, language="sa", name_type="synonym", source_record=source_record, script="Latin")

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
