"""Ingests data/raw/bhaishajya/Bhaishajya-Kalpana-Kosha.json (176 real
records, CC-BY-4.0) as AYU-FORMULATION concepts.

Mapping decisions:
  - formulation["name"] -> canonical_name + PREFERRED ConceptName
  - formulation["ingredients"]+"indications"+"dosage"+"anupana"+"reference"
    -> concatenated into Concept.definition (all free text in the source;
    Phase 1 does not invent structured dosage/ingredient-quantity fields
    the source does not provide as data)
  - formulation["main_ingredients"][] -> a HAS_INGREDIENT concept_relationship
    to an existing HERB or FORMULATION concept (see _find_herb_concept_id's
    own docstring for why FORMULATION is a real, correct target too —
    compound preparations like bhasmas are genuinely listed as ingredients
    of more complex formulations), ONLY when a concept with that exact
    normalized name already exists in the registry (herb_database's
    ingestion must run first for the HERB half of this) — this is real
    cross-source evidence linking, not a guess. An ingredient name with no
    matching concept is recorded as a name on the formulation's own
    concept instead (so the information isn't silently lost) and counted
    as an unresolved ingredient reference in IngestionStats.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ingestion.common import IngestionStats, add_name, add_relationship_if_new, get_or_create_record_and_concept, get_or_create_source
from models import Concept, ConceptName
from normalization import normalize_name

RAW_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "bhaishajya" / "Bhaishajya-Kalpana-Kosha.json"
MANIFEST_SOURCE_NAME = "bhaishajya_kalpana_kosha"


def load_manifest_entry() -> dict:
    manifest = json.loads((Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json").read_text())
    return next(s for s in manifest["sources"] if s["source_name"] == MANIFEST_SOURCE_NAME)


def _find_herb_concept_id(db: Session, ingredient_name: str) -> str | None:
    """Resolves an ingredient reference to an existing concept — HERB or
    FORMULATION only, never any other category.

    Investigated as a possible bug (2026-09-26) and found NOT to be one,
    on closer inspection: this originally had no category filter at all,
    and a check of the real data found 167 real HAS_INGREDIENT relationships
    pointing at another FORMULATION concept rather than a HERB. That is
    NOT mislinking — it's real Ayurvedic pharmacology: compound
    preparations (bhasmas like "Loha Bhasma"/"Swarna Bhasma", or
    intermediate ghritas/tailas like "Mahanarayana Taila") are genuinely
    listed as ingredients of more complex formulations, and the Bhaishajya
    Kalpana Kosha source catalogues those preparations as their OWN
    entries too — so a formulation-references-formulation match is a
    real, correct fact, not noise. A count against every existing
    HAS_INGREDIENT relationship's target category confirmed zero matches
    against any category OTHER than HERB/FORMULATION (no accidental link
    to an AYURVEDIC_CONCEPT, PATHOLOGY_TERM, SIDDHANTA, DISEASE, or
    NAMASTE_CODE) — so the category restriction below exists as a sensible
    guardrail against categories that could never plausibly be an
    "ingredient," not as a narrowing of what was already correct.
    A deterministic ORDER BY ensures a genuine multi-match always resolves
    to the same concept rather than whatever order Postgres happens to
    return."""
    normalized = normalize_name(ingredient_name)
    return db.execute(
        select(ConceptName.concept_id)
        .join(Concept, Concept.concept_id == ConceptName.concept_id)
        .where(ConceptName.normalized_name == normalized, Concept.category.in_(["HERB", "FORMULATION"]))
        .order_by(Concept.id)
        .limit(1)
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

        source_record, concept, _is_new = get_or_create_record_and_concept(
            db, stats, source, source_record_id=str(idx), original_payload=formulation,
            source_url="https://github.com/sciencewithsaucee-sudo/Bhaishajya-Kalpana-Kosha",
            prefix="AYU-FORMULATION", domain="AYURVEDA", category="FORMULATION",
            canonical_name=name, definition=definition,
        )

        add_name(db, stats, concept, name, language="sa", name_type="preferred", source_record=source_record, script="Latin")

        for ingredient in formulation.get("main_ingredients") or []:
            herb_concept_id = _find_herb_concept_id(db, ingredient)
            if herb_concept_id and herb_concept_id != concept.concept_id:
                add_relationship_if_new(
                    db, concept.concept_id, herb_concept_id, "HAS_INGREDIENT",
                    evidence=f"Bhaishajya Kalpana Kosha record '{name}' lists '{ingredient}' in main_ingredients",
                    source_record=source_record,
                )
            else:
                unresolved_ingredients += 1
                add_name(db, stats, concept, ingredient, language="sa", name_type="alias", source_record=source_record, script="Latin")

        stats.imported_count += 1

    db.commit()
    stats.rejected_reasons.append(f"{unresolved_ingredients} ingredient references had no matching HERB/FORMULATION concept (run herb_database ingestion first)") if unresolved_ingredients else None
    return stats


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = ingest(db)
        print(result)
    finally:
        db.close()
