"""Pure-function tests for ingestion/bhaishajya/ingest.py's ingredient-name
parsing — no database required. See tests/integration/test_bhaishajya_ingestion.py
for the full ingest() behavior against a real database.
"""

from __future__ import annotations

from ingestion.bhaishajya.ingest import _split_parenthetical


def test_no_parens_returns_the_name_unchanged():
    assert _split_parenthetical("Bhringaraja") == ["Bhringaraja"]


def test_primary_and_gloss_are_split_in_source_order():
    assert _split_parenthetical("Dhatri (Amalaki)") == ["Dhatri", "Amalaki"]


def test_extra_whitespace_is_stripped():
    assert _split_parenthetical("  Amrita  (  Guduchi )  ") == ["Amrita", "Guduchi"]


def test_two_parenthetical_groups_takes_the_trailing_one_as_the_gloss():
    # The regex is anchored at both ends, so with more than one
    # parenthetical group it greedily includes everything but the LAST
    # group in the "primary" candidate — normalize_name() strips
    # parentheses to whitespace regardless, so this is still a safe,
    # deterministic (if imperfect) split, never a fuzzy guess.
    assert _split_parenthetical("Abhraka (Mica) (processed)") == ["Abhraka (Mica)", "processed"]


def test_empty_parenthetical_gloss_is_not_matched_at_all():
    # The regex requires at least one character inside the parens, so an
    # empty gloss falls back to the whole string unchanged rather than
    # producing an empty candidate.
    assert _split_parenthetical("Ghrita ()") == ["Ghrita ()"]
