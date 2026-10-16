"""ingestion/bhaishajya/ingest.py against a real Postgres database, using a
small synthetic main_ingredients dataset (monkeypatching RAW_FILE) so the
two specific behaviors under test are unambiguous:

1. A "Primary (Gloss)" ingredient reference resolves via either literal
   name candidate, exactly like siddhanta/namaste's own parenthetical
   splitting elsewhere in this codebase — never a fuzzy guess.
2. An ingredient reference with NO matching concept is no longer recorded
   as an alias of the REFERENCING formulation — the real bug found
   2026-09-28 (see ingest.py's own module docstring) that caused later,
   unrelated formulations referencing the same unresolved name to
   mis-link onto whichever formulation happened to mention it first.
"""

from __future__ import annotations

import json

import ingestion.bhaishajya.ingest as bhaishajya_ingest
from models import Concept, ConceptName, ConceptRelationship
from normalization import normalize_name


def _herb(db, concept_id: str, canonical_name: str) -> Concept:
    c = Concept(concept_id=concept_id, domain="AYURVEDA", category="HERB", canonical_name=canonical_name, status="candidate", confidence=1.0)
    db.add(c)
    db.flush()
    db.add(ConceptName(concept_id=c.concept_id, name=canonical_name, normalized_name=normalize_name(canonical_name), language="sa", script="Latin", name_type="preferred"))
    db.flush()
    return c


def _write_records(tmp_path, records):
    path = tmp_path / "synthetic_bhaishajya.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def test_parenthetical_gloss_resolves_to_an_existing_herb(db, tmp_path, monkeypatch):
    _herb(db, "TEST-BHAI-HERB-1", "Amalaki")
    records = [{"name": "Test Formulation One", "main_ingredients": ["Dhatri (Amalaki)"]}]
    monkeypatch.setattr(bhaishajya_ingest, "RAW_FILE", _write_records(tmp_path, records))

    bhaishajya_ingest.ingest(db)

    formulation = db.query(Concept).filter_by(canonical_name="Test Formulation One").one()
    rel = db.query(ConceptRelationship).filter_by(concept_id_a=formulation.concept_id, concept_id_b="TEST-BHAI-HERB-1", relationship_type="HAS_INGREDIENT").one_or_none()
    assert rel is not None
    assert "Dhatri (Amalaki)" in rel.evidence
    assert "matched via 'Amalaki'" in rel.evidence


def test_unresolved_ingredient_is_not_added_as_an_alias_of_the_referencing_formulation(db, tmp_path, monkeypatch):
    records = [{"name": "Test Formulation Two", "main_ingredients": ["Nonexistent Herb XYZ"]}]
    monkeypatch.setattr(bhaishajya_ingest, "RAW_FILE", _write_records(tmp_path, records))

    stats = bhaishajya_ingest.ingest(db)

    formulation = db.query(Concept).filter_by(canonical_name="Test Formulation Two").one()
    names = db.query(ConceptName).filter_by(concept_id=formulation.concept_id).all()
    assert all(n.name != "Nonexistent Herb XYZ" for n in names), "an unresolved ingredient must never become a name of the formulation that merely mentions it"
    assert "1 ingredient references had no matching HERB/FORMULATION concept" in " ".join(stats.rejected_reasons)


def test_two_formulations_referencing_the_same_unresolved_ingredient_do_not_cross_link(db, tmp_path, monkeypatch):
    """The real bug (2026-09-28): before the fix, the SECOND formulation
    below would have exact-matched onto the FIRST one, because the first
    unresolved reference got wrongly indexed as an alias of Formulation A."""
    records = [
        {"name": "Formulation A", "main_ingredients": ["Ghostroot"]},
        {"name": "Formulation B", "main_ingredients": ["Ghostroot"]},
    ]
    monkeypatch.setattr(bhaishajya_ingest, "RAW_FILE", _write_records(tmp_path, records))

    bhaishajya_ingest.ingest(db)

    a = db.query(Concept).filter_by(canonical_name="Formulation A").one()
    b = db.query(Concept).filter_by(canonical_name="Formulation B").one()
    rel = db.query(ConceptRelationship).filter(
        ConceptRelationship.relationship_type == "HAS_INGREDIENT",
        ((ConceptRelationship.concept_id_a == b.concept_id) & (ConceptRelationship.concept_id_b == a.concept_id))
        | ((ConceptRelationship.concept_id_a == a.concept_id) & (ConceptRelationship.concept_id_b == b.concept_id)),
    ).one_or_none()
    assert rel is None, "Formulation B must not be linked to Formulation A just because both mention the same unresolved ingredient name"
