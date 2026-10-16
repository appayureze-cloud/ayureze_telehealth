"""Deterministic, language-aware negation detection.

Per docs/ai/README.md's safety-validator design: "Do not take this
medicine" translated as "Take this medicine" is a complete meaning
inversion that a numbers-only check cannot catch (no number is involved
at all). This module answers one question — "does this text, in this
language, contain a clinical negation marker?" — using each language's
own vocabulary, never by searching the *source* language's negation
words inside *translated* text (which would just never match and give a
false sense of safety).

Deliberately covers only English and Tamil (the two languages this
build's safety validator is graded against — see the "Language coverage"
note below and docs/ai/README.md's Known limitations). Malayalam is a
supported pipeline language (lid.py) but has no negation table here;
`has_negation()` returns None (unknown) for it rather than guessing.
"""

from __future__ import annotations

import re

# Ordered roughly most-specific-first; matching is boundary-anchored so
# order doesn't affect correctness, only readability.
_NEGATION_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "en": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"\bdo\s+not\b",
            r"\bdon['’]t\b",
            r"\bdoes\s+not\b",
            r"\bdoesn['’]t\b",
            r"\bdid\s+not\b",
            r"\bdidn['’]t\b",
            r"\bshould\s+not\b",
            r"\bshouldn['’]t\b",
            r"\bmust\s+not\b",
            r"\bmustn['’]t\b",
            r"\bcannot\b",
            r"\bcan['’]t\b",
            r"\bnever\b",
            r"\bavoid\b",
            r"\bwithout\b",
            r"\bno\s+longer\b",
            # Bare "not" last and narrowest — still a real English
            # negation marker ("not recommended", "not more than"), just
            # the one most likely to false-positive on an unrelated
            # sentence, so it is never the *only* signal this module
            # relies on for the languages above it.
            r"\bnot\b",
        ]
    ],
    "ta": [
        # Standard Tamil clinical/prohibitive negation markers. Curated
        # starter set (same "not exhaustive by design" status as
        # terminology.GLOSSARY) — should be reviewed by a qualified
        # Tamil medical linguist before this is relied on beyond a
        # controlled pilot. re.compile with no IGNORECASE flag: Tamil
        # script has no case distinction, so it's a no-op there.
        re.compile(p)
        for p in [
            r"வேண்டாம்",  # "vendaam" — "don't" / "not needed"
            r"கூடாது",  # "koodaathu" — "must not" / "should not"
            r"முடியாது",  # "mudiyaathu" — "cannot"
            r"இல்லை",  # "illai" — "no" / "is not"
            r"அல்ல",  # "alla" — "is not" (copular negation)
            r"தவிர்",  # "thavir" — "avoid"
            # "-ாதீர்கள்" — the negative-imperative verb suffix (e.g.
            # "எடுக்காதீர்கள்"/"கொள்ளாதீர்கள்" — "do not take"), a distinct
            # standard Tamil grammatical negation construction from the
            # standalone-word markers above, not a domain-specific term.
            # Missing this caused a real false-negative in this pass's own
            # real NLLB-200 output ("Do not take this medicine at
            # bedtime." translated using this suffix form rather than a
            # standalone negation word), which the validator then flagged
            # as an unrelated mismatch instead of correctly confirming
            # negation was preserved. Grammatically unambiguous as a
            # negation marker; still subject to the same "review by a
            # qualified Tamil medical linguist" caveat as the rest of this
            # curated table.
            r"ாதீர்கள்",
        ]
    ],
}


def has_negation(text: str, lang: str) -> bool | None:
    """Returns True/False for a covered language, None if this module has
    no negation table for `lang` (unknown, not "assumed false") — callers
    must treat None as "cannot verify this field", not as "no negation
    present", per the validator's fail-closed design.
    """
    patterns = _NEGATION_PATTERNS.get(lang)
    if patterns is None:
        return None
    return any(p.search(text) for p in patterns)


def supported_languages() -> frozenset[str]:
    return frozenset(_NEGATION_PATTERNS.keys())
