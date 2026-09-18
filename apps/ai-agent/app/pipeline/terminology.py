"""Ayurveda/medical terminology protection.

Identifies translation-critical spans in the source text *before*
translation — numbers, dosages, frequencies, durations, and a curated
glossary of Ayurveda/Sanskrit/medical terms — so safety.py has a concrete,
source-derived checklist to verify against the translated output rather
than guessing at what mattered after the fact.

This build does not fine-tune the translation model to leave marked spans
untranslated (a real production system would evaluate constrained
decoding or a fine-tuned no-translate-span capability); instead, protected
numeric spans are verified digit-for-digit post-translation by
safety.py — NLLB-family models reliably preserve numeric digit sequences
verbatim in practice (verified in this build's own testing — see
docs/ai/README.md), so this check is a real, if second-order, guarantee
rather than the ideal first-order one.
"""

from __future__ import annotations

import re

from .types import ProtectedSpan, TerminologyAnalysis

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

_FREQUENCY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bonce\s+(a|per)\s+day\b",
        r"\btwice\s+(a|per)\s+day\b",
        r"\bthrice\s+(a|per)\s+day\b",
        r"\b\d+\s*times?\s*(a|per)?\s*day\b",
        r"\bevery\s+\d+\s*(hours?|hrs?)\b",
        r"\bdaily\b",
        r"\bmorning\s+and\s+(evening|night)\b",
    ]
]

_DURATION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b\d+\s*(days?|weeks?|months?)\b",
        r"\bfor\s+\d+\s*(days?|weeks?|months?)\b",
    ]
]

_DOSAGE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b\d+(?:\.\d+)?\s*(mg|ml|mcg|g|tablets?|tabs?|capsules?|drops?|teaspoons?|tsp)\b",
    ]
]

# A small, curated starter glossary — Ayurveda/Sanskrit terms and common
# medicine/anatomical terms whose (mis)translation would matter clinically.
# Grown incrementally; not exhaustive by design (see docs/ai/README.md).
GLOSSARY = {
    "ashwagandha",
    "triphala",
    "turmeric",
    "dosha",
    "vata",
    "pitta",
    "kapha",
    "panchakarma",
    "paracetamol",
    "ibuprofen",
    "amoxicillin",
    "metformin",
    "insulin",
    "blood pressure",
    "heart rate",
    "kidney",
    "liver",
}


def analyze(text: str) -> TerminologyAnalysis:
    spans: list[ProtectedSpan] = []

    for pattern, kind in (
        *((p, "dosage") for p in _DOSAGE_PATTERNS),
        *((p, "frequency") for p in _FREQUENCY_PATTERNS),
        *((p, "duration") for p in _DURATION_PATTERNS),
    ):
        for m in pattern.finditer(text):
            spans.append(ProtectedSpan(text=m.group(0), kind=kind))

    # Bare numbers not already captured as part of a dosage/frequency/
    # duration phrase above (those already carry their number).
    covered_ranges = set()
    for pattern, _ in (
        *((p, "dosage") for p in _DOSAGE_PATTERNS),
        *((p, "frequency") for p in _FREQUENCY_PATTERNS),
        *((p, "duration") for p in _DURATION_PATTERNS),
    ):
        for m in pattern.finditer(text):
            covered_ranges.add((m.start(), m.end()))

    for m in _NUMBER_RE.finditer(text):
        if any(start <= m.start() and m.end() <= end for start, end in covered_ranges):
            continue
        spans.append(ProtectedSpan(text=m.group(0), kind="number"))

    lowered = text.lower()
    for term in GLOSSARY:
        if term in lowered:
            spans.append(ProtectedSpan(text=term, kind="term"))

    return TerminologyAnalysis(protected_spans=spans)


def extract_numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(text)
