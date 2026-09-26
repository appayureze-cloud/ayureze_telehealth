"""NAMASTE <-> canonical registry interface (spec section 19).

Three things are kept deliberately SEPARATE here, per the spec's explicit
instruction not to "treat the FHIR service itself as the canonical
medical truth":
  1. FHIR interoperability — this module's job: a deterministic, read-only
     transform from this engine's OWN canonical concepts (domain=INTEROP,
     category=NAMASTE_CODE — ingested by ingestion/namaste/ingest.py from
     the real 14-row sample CSV, see docs/DATA_QUALITY_REPORT.md for why
     it's 14 rows, not the full 7,363) into a FHIR R4 CodeSystem resource.
  2. Terminology concepts — the canonical registry itself (models.Concept),
     never mutated by this module.
  3. Mappings — the tm2_code/icd_biomedicine_code correlations, which (per
     ingestion/namaste/ingest.py) are stored as ConceptRelationship rows
     with relationship_type=RELATED_TO and explicit evidence, never
     EXACT_MATCH, never invented here.

This is a PURE FUNCTION over data already in this engine's own database —
it does not call the live NAMASTE portal, the demo repo's MongoDB backend,
or WHO's ICD-11 API. Building the FHIR ConceptMap (NAMASTE->ICD-11)
equivalent would require real tm2_code/icd_biomedicine_code data this
14-row sample doesn't actually populate (verified: every row's
tm2_code/icd_biomedicine_code field is empty in the source CSV) — so only
CodeSystem generation is implemented here; ConceptMap generation is
correctly left as a documented gap, not faked with empty codes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Concept


def generate_namaste_codesystem(db: Session) -> dict:
    """Builds a FHIR R4 CodeSystem resource from this engine's own
    NAMASTE_CODE concepts — verified against the real FHIR CodeSystem
    shape used by the approved NAMASTE repository's own
    backend/app/fhir/codesystem.py (see data/raw/namaste/fhir_reference/),
    but generated fresh from OUR canonical registry, not copied from
    theirs."""
    concepts = db.execute(select(Concept).where(Concept.category == "NAMASTE_CODE")).scalars().all()
    return {
        "resourceType": "CodeSystem",
        "id": "ayureze-namaste-codesystem",
        "url": "https://ayureze.example/fhir/CodeSystem/namaste",
        "version": "0.1.0",
        "name": "AyurEzeNamasteCodeSystem",
        "title": "NAMASTE codes represented in the AyurEze Terminology Engine",
        "status": "draft",
        "publisher": "AyurEze Terminology Engine (Phase 1) — derived from the approved NAMASTE sample dataset, not an official Ministry of AYUSH publication",
        "description": "Generated from this engine's own canonical concept registry — see mappings/namaste_fhir.py. NOT the canonical NAMASTE source; that authority remains with the Ministry of AYUSH's own portal.",
        "count": len(concepts),
        "concept": [
            {"code": c.concept_id, "display": c.canonical_name, "definition": c.definition or ""}
            for c in concepts
        ],
    }
