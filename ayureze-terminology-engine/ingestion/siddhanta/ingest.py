"""Ingests data/raw/siddhanta/Siddhanta-Kosha.json (162 real records,
CC-BY-4.0) as AYU-SIDDHANTA concepts (fundamental Ayurvedic concepts —
spec's SIDDHANTA domain type).

The source's "name" field is formatted "Latin (Devanagari)", e.g.
"Ama (आम)" — split into two separate ConceptNames (verified by inspecting
every record's actual format, not assumed for all 162: see
_split_name()'s fallback for the few records that don't match this
pattern, counted rather than silently mis-parsed).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ingestion.common import IngestionStats, add_name, get_or_create_record_and_concept, get_or_create_source

RAW_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "siddhanta" / "Siddhanta-Kosha.json"
MANIFEST_SOURCE_NAME = "siddhanta_kosha"

_NAME_PATTERN = re.compile(r"^(?P<latin>.+?)\s*\((?P<devanagari>[ऀ-ॿ\s]+)\)\s*$")


def load_manifest_entry() -> dict:
    manifest = json.loads((Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json").read_text())
    return next(s for s in manifest["sources"] if s["source_name"] == MANIFEST_SOURCE_NAME)


def _split_name(raw_name: str) -> tuple[str, str | None]:
    """Returns (latin_name, devanagari_name_or_None). Falls back to the
    raw string as-is (no Devanagari split) when the "Latin (Devanagari)"
    pattern isn't matched — never raises, never guesses a split."""
    match = _NAME_PATTERN.match(raw_name.strip())
    if match:
        return match.group("latin").strip(), match.group("devanagari").strip()
    return raw_name.strip(), None


def ingest(db: Session) -> IngestionStats:
    stats = IngestionStats(source_name=MANIFEST_SOURCE_NAME)
    source = get_or_create_source(db, load_manifest_entry())
    records = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    unparsed_name_format = 0

    for idx, entry in enumerate(records):
        stats.read_count += 1
        raw_name = (entry.get("name") or "").strip()
        if not raw_name:
            stats.reject(f"record[{idx}]: missing required 'name' field")
            continue

        latin_name, devanagari_name = _split_name(raw_name)
        if devanagari_name is None:
            unparsed_name_format += 1

        definition_parts = [
            entry.get("explanation"),
            f"Shloka: {entry['shloka']} {entry.get('shloka_ref', '')}".strip() if entry.get("shloka") else None,
            f"Clinical importance: {entry['clinical_importance']}" if entry.get("clinical_importance") else None,
        ]
        definition = " | ".join(p for p in definition_parts if p) or None

        source_record, concept, _is_new = get_or_create_record_and_concept(
            db, stats, source, source_record_id=str(idx), original_payload=entry,
            source_url="https://github.com/sciencewithsaucee-sudo/Siddhanta-Kosha",
            prefix="AYU-SIDDHANTA", domain="AYURVEDA", category="SIDDHANTA",
            canonical_name=latin_name, definition=definition,
        )

        add_name(db, stats, concept, latin_name, language="sa", name_type="preferred", source_record=source_record, script="Latin")
        if devanagari_name:
            add_name(db, stats, concept, devanagari_name, language="sa", name_type="synonym", source_record=source_record, script="Devanagari")

        stats.imported_count += 1

    db.commit()
    if unparsed_name_format:
        stats.rejected_reasons.append(f"informational: {unparsed_name_format} records' name field didn't match the 'Latin (Devanagari)' pattern — used verbatim as the single name")
    return stats


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = ingest(db)
        print(result)
    finally:
        db.close()
