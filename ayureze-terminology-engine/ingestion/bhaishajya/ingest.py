"""Ingests data/raw/bhaishajya/Bhaishajya-Kalpana-Kosha.json (176 real
records, CC-BY-4.0) as AYU-FORMULATION concepts.

Mapping decisions:
  - formulation["name"] -> canonical_name + PREFERRED ConceptName
  - formulation["ingredients"]+"indications"+"dosage"+"anupana"+"reference"
    -> concatenated into Concept.definition (all free text in the source;
    Phase 1 does not invent structured dosage/ingredient-quantity fields
    the source does not provide as data)
  - formulation["main_ingredients"][] -> a HAS_INGREDIENT concept_relationship
    to an existing HERB concept, ONLY when a herb with that exact
    normalized name already exists in the registry (from herb_database's
    ingestion, which must run first) — this is real cross-source evidence
    linking, not a guess. An ingredient name with no matching herb concept
    is recorded as a name on the formulation's own concept instead (so the
    information isn't silently lost) and counted as an unresolved
    ingredient reference in IngestionStats.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ingestion.common import IngestionStats, add_name, create_concept, create_source_record, get_or_create_source, link_source_record_to_concept
from models import ConceptName, ConceptRelationship
from normalization import normalize_name

RAW_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "bhaishajya" / "Bhaishajya-Kalpana-Kosha.json"
MANIFEST_SOURCE_NAME = "bhaishajya_kalpana_kosha"


def load_manifest_entry() -> dict:
    manifest = json.loads((Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json").read_text())
    return next(s for s in manifest["sources"] if s["source_name"] == MANIFEST_SOURCE_NAME)


def _find_herb_concept_id(db: Session, ingredient_name: str) -> str | None:
    normalized = normalize_name(ingredient_name)
    return db.execute(
        select(ConceptName.concept_id).where(ConceptName.normalized_name == normalized).limit(1)
    ).scalar_one_or_none()


def ingest(db: Session) -> IngestionStats:
    stats = IngestionStats(source_name=MANIFEST_SOURCE_NAME)
    source = get_or_create_source(db, load_manifest_entry())
    records = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    unresolved_ingredients = 0

    for idx, formulation in enumerate(records):
        stats.read_count += 1
        name = (formulation.get("name") or "").strip()
        if not name:
            stats.reject(f"record[{idx}]: missing required 'name' field")
            continue

        source_record = create_source_record(
            db, source, source_record_id=str(idx), original_payload=formulation,
            source_url="https://github.com/sciencewithsaucee-sudo/Bhaishajya-Kalpana-Kosha",
        )

        definition_parts = [
            f"Type: {formulation['type']}" if formulation.get("type") else None,
            f"Category: {formulation['category']}" if formulation.get("category") else None,
            f"Ingredients: {formulation['ingredients']}" if formulation.get("ingredients") else None,
            f"Indications: {formulation['indications']}" if formulation.get("indications") else None,
            f"Dosage: {formulation['dosage']}" if formulation.get("dosage") else None,
            f"Anupana: {formulation['anupana']}" if formulation.get("anupana") else None,
            f"Reference: {formulation['reference']}" if formulation.get("reference") else None,
        ]
        definition = " | ".join(p for p in definition_parts if p) or None

        concept = create_concept(
            db, prefix="AYU-FORMULATION", domain="AYURVEDA", category="FORMULATION",
            canonical_name=name, definition=definition,
        )
        link_source_record_to_concept(db, source_record, concept)
        stats.concepts_created += 1

        if add_name(db, concept, name, language="sa", name_type="preferred", source_record=source_record, script="Latin"):
            stats.names_created += 1

        for ingredient in formulation.get("main_ingredients") or []:
            herb_concept_id = _find_herb_concept_id(db, ingredient)
            if herb_concept_id and herb_concept_id != concept.concept_id:
                db.add(ConceptRelationship(
                    concept_id_a=concept.concept_id,
                    concept_id_b=herb_concept_id,
                    relationship_type="HAS_INGREDIENT",
                    evidence=f"Bhaishajya Kalpana Kosha record '{name}' lists '{ingredient}' in main_ingredients",
                    confidence=1.0,
                    source_record_id=source_record.id,
                ))
            else:
                unresolved_ingredients += 1
                if add_name(db, concept, ingredient, language="sa", name_type="alias", source_record=source_record, script="Latin"):
                    stats.names_created += 1

        stats.imported_count += 1

    db.commit()
    stats.rejected_reasons.append(f"{unresolved_ingredients} ingredient references had no matching HERB concept (run herb_database ingestion first)") if unresolved_ingredients else None
    return stats


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = ingest(db)
        print(result)
    finally:
        db.close()
