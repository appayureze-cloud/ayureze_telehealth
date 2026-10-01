"""Real search behavior against a real Postgres database (spec section 21:
exact search, case normalization, whitespace normalization, synonyms,
scientific names, transliteration, fuzzy matching, false positives).
"""

from __future__ import annotations

from models import Concept, ConceptName
from normalization import normalize_name
from terminology.search import search_terms


def _make_concept(db, concept_id: str, canonical_name: str, category: str = "HERB", domain: str = "AYURVEDA") -> Concept:
    concept = Concept(concept_id=concept_id, domain=domain, category=category, canonical_name=canonical_name, status="candidate", confidence=1.0)
    db.add(concept)
    db.flush()
    return concept


def _add_name(db, concept: Concept, name: str, name_type: str, language: str = "sa", script: str | None = "Latin") -> None:
    db.add(ConceptName(concept_id=concept.concept_id, name=name, normalized_name=normalize_name(name), language=language, script=script, name_type=name_type))
    db.flush()


def test_exact_preferred_name_match(db):
    c = _make_concept(db, "TEST-HERB-000001", "Tulsi")
    _add_name(db, c, "Tulsi", "preferred")

    matches = search_terms(db, "Tulsi")
    assert len(matches) == 1
    assert matches[0].concept_id == "TEST-HERB-000001"
    assert matches[0].match_type == "exact_preferred_name"
    assert matches[0].confidence == 1.0


def test_search_is_case_insensitive(db):
    c = _make_concept(db, "TEST-HERB-000002", "Ashwagandha")
    _add_name(db, c, "Ashwagandha", "preferred")

    for query in ["ashwagandha", "ASHWAGANDHA", "AshWagandha"]:
        matches = search_terms(db, query)
        assert any(m.concept_id == "TEST-HERB-000002" for m in matches), f"failed for query={query!r}"


def test_search_is_whitespace_insensitive(db):
    c = _make_concept(db, "TEST-HERB-000003", "Brahmi Ghrita")
    _add_name(db, c, "Brahmi Ghrita", "preferred")

    matches = search_terms(db, "  Brahmi   Ghrita  ")
    assert any(m.concept_id == "TEST-HERB-000003" for m in matches)


def test_real_guduchi_giloy_resolution(db):
    """The spec's own worked example: 'Guduchi' should resolve to the same
    concept as 'Giloy' when the source explicitly identifies it as a
    synonym — exercised here exactly as the real herb_database source
    itself states it (a preferred name 'Giloy' with a source-listed
    Sanskrit synonym 'Guduchi'), not invented."""
    giloy = _make_concept(db, "TEST-HERB-GILOY", "Giloy")
    _add_name(db, giloy, "Giloy", "preferred")
    _add_name(db, giloy, "Guduchi", "synonym")

    matches = search_terms(db, "Guduchi")
    assert any(m.concept_id == "TEST-HERB-GILOY" and m.match_type == "exact_synonym" for m in matches)


def test_scientific_botanical_name_match(db):
    c = _make_concept(db, "TEST-HERB-000004", "Tulsi")
    _add_name(db, c, "Tulsi", "preferred")
    _add_name(db, c, "Ocimum sanctum", "botanical", language="la")

    matches = search_terms(db, "Ocimum sanctum")
    assert any(m.concept_id == "TEST-HERB-000004" and m.match_type == "scientific_botanical_name" for m in matches)


def test_transliteration_match(db):
    c = _make_concept(db, "TEST-PATH-000001", "Amavata")
    _add_name(db, c, "Amavata", "preferred")
    _add_name(db, c, "आमवात", "transliteration", script="Devanagari")

    matches = search_terms(db, "आमवात")
    assert any(m.concept_id == "TEST-PATH-000001" and m.match_type == "transliteration" for m in matches)


def test_prefix_match(db):
    c = _make_concept(db, "TEST-HERB-000005", "Ashwagandha")
    _add_name(db, c, "Ashwagandha", "preferred")

    matches = search_terms(db, "Ashwa")
    assert any(m.concept_id == "TEST-HERB-000005" and m.match_type == "prefix" for m in matches)


def test_fuzzy_match_for_minor_spelling_variant(db):
    c = _make_concept(db, "TEST-HERB-000006", "Ashwagandha")
    _add_name(db, c, "Ashwagandha", "preferred")

    matches = search_terms(db, "Ashwagandhaa")  # one extra letter
    fuzzy_matches = [m for m in matches if m.match_type == "fuzzy"]
    assert any(m.concept_id == "TEST-HERB-000006" for m in fuzzy_matches)
    assert all(0.0 < m.confidence < 1.0 for m in fuzzy_matches), "fuzzy confidence must be a real similarity score, never 1.0 or 0"


def test_false_positive_unrelated_terms_do_not_match(db):
    """Do NOT create synonym relationships (or search matches) merely
    because strings look similar (spec section 21) — two genuinely
    unrelated herb names must not cross-match."""
    c1 = _make_concept(db, "TEST-HERB-000007", "Tulsi")
    _add_name(db, c1, "Tulsi", "preferred")
    c2 = _make_concept(db, "TEST-HERB-000008", "Shatavari")
    _add_name(db, c2, "Shatavari", "preferred")

    matches = search_terms(db, "Tulsi")
    assert not any(m.concept_id == "TEST-HERB-000008" for m in matches)


def test_no_match_returns_empty_list_not_an_error(db):
    assert search_terms(db, "completely-nonexistent-term-xyz-123") == []


def test_a_concept_is_never_listed_twice_under_a_weaker_match_type(db):
    """A concept matching both exactly (preferred name) and fuzzily (some
    other name) must appear once, under the STRONGEST match_type."""
    c = _make_concept(db, "TEST-HERB-000009", "Amla")
    _add_name(db, c, "Amla", "preferred")
    _add_name(db, c, "Amlaa", "synonym")  # would also fuzzy-match "Amla"

    matches = search_terms(db, "Amla")
    matching_this_concept = [m for m in matches if m.concept_id == "TEST-HERB-000009"]
    assert len(matching_this_concept) == 1
    assert matching_this_concept[0].match_type == "exact_preferred_name"
