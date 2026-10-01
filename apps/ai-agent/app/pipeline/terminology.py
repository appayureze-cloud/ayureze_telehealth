"""Ayurveda/medical terminology protection AND (this pass) the full
normalized "safety entity" extraction the deterministic safety validator
(safety.py) compares source vs. translated text against — numbers,
dosages (value+unit), frequency, duration (value+unit), food-timing
constraints, negation, and protected medicine/Ayurveda terms.

Everything here is regex/lookup-table based, on purpose: this must stay
predictable and auditable (no model in the loop), per the build spec and
docs/ai/README.md's safety-validator design. Every normalization rule is
documented inline next to the table/pattern that implements it, per this
task's "document normalization rules" requirement — see also
docs/ai/README.md's "Safety validator" section for the consolidated
version of these rules.

This build does not fine-tune the translation model to leave marked spans
untranslated; instead, protected spans are verified post-translation by
safety.py, using the extraction functions below on both the source and
the translated text.
"""

from __future__ import annotations

import re

from .types import DosageEntity, DurationEntity, ProtectedSpan, SafetyEntities, TerminologyAnalysis

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
    "agni",
    "ama",
    "prakriti",
    "rasayana",
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


# =====================================================================
# Extended safety-entity extraction (this pass — see docs/ai/README.md's
# "Safety validator" section for the human-readable summary of every rule
# below).
# =====================================================================

# --- Numeric normalization (Step 2) ----------------------------------
#
# Normalization rule: "5", "5.0", "5.00" all normalize to the float value
# 5.0 and compare equal — Python's float() does this for free. Simple
# fractions ("1/2") and the common Unicode vulgar-fraction characters
# normalize to their decimal value, so "1/2 tablet" and "½ tablet" compare
# equal, but a genuinely different fraction ("1/2" vs "1/4") does not.
# Ranges ("5-10 mg", "5 to 10 mg") are not special-cased for the numeric
# multiset check — each bound is just its own number, so a range
# collapsing to a single value, or a bound changing, is still caught.
_UNICODE_FRACTIONS = {
    "½": 0.5,  # ½
    "¼": 0.25,  # ¼
    "¾": 0.75,  # ¾
    "⅓": 1 / 3,  # ⅓
    "⅔": 2 / 3,  # ⅔
    "⅕": 0.2,  # ⅕
    "⅘": 0.6,  # ⅗
}
_NUMBER_TOKEN_RE = re.compile(r"\d+/\d+|\d+(?:\.\d+)?|[" + "".join(_UNICODE_FRACTIONS) + "]")


def extract_numeric_values(text: str) -> list[float]:
    """Every numeric value in `text`, normalized to float (percentages
    included — the '%' sign itself is handled separately as a unit, see
    extract_dosages). Used as a multiset (order-independent) — legitimate
    reordering across languages must not trigger a false rejection, but a
    dropped, added, or altered value must."""
    return [v for v in (_parse_number_token(m.group(0)) for m in _NUMBER_TOKEN_RE.finditer(text)) if v is not None]


def _parse_number_token(tok: str) -> float | None:
    """Normalizes one matched number token (decimal, simple fraction, or
    Unicode vulgar fraction) to its float value. Shared by
    extract_numeric_values and extract_dosages so a dosage's value
    ("½ tablet") is parsed the same way the generic numeric-preservation
    check parses it — otherwise a fraction-based dosage could silently
    fall out of the unit-pairing check even though the plain numeric
    check still sees it."""
    if tok in _UNICODE_FRACTIONS:
        return _UNICODE_FRACTIONS[tok]
    if "/" in tok:
        num, den = tok.split("/", 1)
        try:
            return float(num) / float(den)
        except ZeroDivisionError:
            return None
    return float(tok)


# --- Unit normalization (Step 3) --------------------------------------
#
# Normalization rule: spelling/case/pluralization variants of the SAME
# physical unit canonicalize to one code (e.g. "mg"/"milligram"/
# "milligrams" -> "mg"; "ml"/"mL"/"milliliter"/"millilitre" -> "ml").
# Critical rule (never relaxed): two DIFFERENT canonical unit codes are
# NEVER treated as equivalent — there is no safe-equivalence table between
# mg and ml, or between any two physically different units, only between
# spelling variants of the same one. Temperature units require an
# explicit "°"/"degrees" marker so a bare letter is never misread as a
# unit.
_UNIT_VARIANTS: dict[str, str] = {
    # weight
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "mcg": "mcg", "microgram": "mcg", "micrograms": "mcg", "µg": "mcg", "ug": "mcg",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gram": "g", "grams": "g", "gm": "g", "gms": "g",
    # volume
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    # other clinical units
    "iu": "iu",
    "mmhg": "mmhg",
    "%": "%", "percent": "%", "percentage": "%",
    # dose forms
    "tablet": "tablet", "tablets": "tablet", "tab": "tablet", "tabs": "tablet",
    "capsule": "capsule", "capsules": "capsule", "cap": "capsule", "caps": "capsule",
    "drop": "drop", "drops": "drop",
    "teaspoon": "teaspoon", "teaspoons": "teaspoon", "tsp": "teaspoon",
}  # fmt: skip

_UNIT_ALTERNATION = "|".join(
    sorted((re.escape(v) for v in _UNIT_VARIANTS), key=len, reverse=True)
)
_TEMPERATURE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:°\s?(C|F)|degrees?\s+(celsius|fahrenheit))\b", re.IGNORECASE
)
# Same "number token" shape as _NUMBER_TOKEN_RE (decimal, simple
# fraction, or Unicode vulgar fraction) — a dosage value ("½ tablet")
# must parse the same way the generic numeric-preservation check parses
# it, or a fraction-based dose silently escapes the unit-pairing check.
_DOSAGE_UNIT_RE = re.compile(
    r"\b(\d+/\d+|\d+(?:\.\d+)?|[" + "".join(_UNICODE_FRACTIONS) + r"])"
    r"\s*(?:-|\sto\s)?\s*(\d+/\d+|\d+(?:\.\d+)?|[" + "".join(_UNICODE_FRACTIONS) + r"])?"
    r"\s*(" + _UNIT_ALTERNATION + r")\b",
    re.IGNORECASE,
)

# Tamil dose-unit *stems*, matched by prefix rather than exact word —
# Tamil is agglutinative (case/plural suffixes attach directly to the
# stem: மாத்திரை "tablet" -> மாத்திரைகளை "tablets [accusative]"), so a
# trailing \b word-boundary regex (correct for English) would miss every
# suffixed form. A stem that is a true prefix of the inflected word still
# matches via simple substring search immediately after the numeral.
# Curated starter set (same "not exhaustive by design" status as
# GLOSSARY) — verified against this build's own NLLB-200 Tamil output
# (see docs/ai/README.md), not a certified terminology authority.
_TAMIL_UNIT_STEMS: dict[str, str] = {
    "மில்லிகிராம்": "mg", "மி.கி": "mg",
    "மில்லிலிட்டர்": "ml", "மி.லி": "ml",
    # "மிலி" (bare "milli-") — this pass's own real NLLB-200 output for
    # "2.5 ml once daily for 5 days" used this shorter colloquial form
    # instead of the full "மில்லிலிட்டர்" or the dotted abbreviation
    # "மி.லி" already above, and was missed by both (a real false-positive
    # unit_mismatch rejection of an otherwise-correct translation) until
    # this entry was added. Ordered after the longer, more specific stems
    # below via _TAMIL_UNIT_STEMS_ORDERED so it never shadows them.
    "மிலி": "ml",
    "கிலோகிராம்": "kg",
    "மைக்ரோகிராம்": "mcg",
    "கிராம்": "g",
    "மாத்திரை": "tablet",
    "காப்சூல்": "capsule",
    "சொட்டு": "drop",
    "தேக்கரண்டி": "teaspoon",
}  # fmt: skip
# Longest stem first, so "மில்லிகிராம்" (mg) is tried before the shorter
# "கிராம்" (g) it would otherwise also match as a substring.
_TAMIL_UNIT_STEMS_ORDERED = sorted(_TAMIL_UNIT_STEMS.items(), key=lambda kv: len(kv[0]), reverse=True)
# A Tamil numeral is followed by optional whitespace/punctuation then the
# unit stem — no trailing \b, deliberately, per the agglutination note above.
_TAMIL_DOSAGE_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*")


def canonicalize_unit(raw: str) -> str | None:
    return _UNIT_VARIANTS.get(raw.strip().lower())


def _extract_tamil_dosages(text: str) -> list[DosageEntity]:
    entities: list[DosageEntity] = []
    for m in _TAMIL_DOSAGE_NUMBER_RE.finditer(text):
        tail = text[m.end() : m.end() + 20]  # a short lookahead window is enough for any unit stem + suffix
        for stem, unit in _TAMIL_UNIT_STEMS_ORDERED:
            if tail.startswith(stem):
                entities.append(DosageEntity(value=float(m.group(1)), unit=unit, raw=m.group(0) + stem))
                break
    return entities


def extract_dosages(text: str) -> list[DosageEntity]:
    """Every (value, canonical unit) pair in `text`, including both
    bounds of a range ("5-10 mg" -> two entities, both unit "mg"),
    temperature readings ("37°C" / "98.6 degrees Fahrenheit"), and Tamil
    dose-unit phrases ("10 மி.கி")."""
    entities: list[DosageEntity] = []
    for m in _DOSAGE_UNIT_RE.finditer(text):
        unit = canonicalize_unit(m.group(3))
        if unit is None:
            continue
        value = _parse_number_token(m.group(1))
        if value is not None:
            entities.append(DosageEntity(value=value, unit=unit, raw=m.group(0)))
        if m.group(2):
            value2 = _parse_number_token(m.group(2))
            if value2 is not None:
                entities.append(DosageEntity(value=value2, unit=unit, raw=m.group(0)))
    for m in _TEMPERATURE_RE.finditer(text):
        scale = "c" if (m.group(2) or m.group(3) or "c").lower().startswith("c") else "f"
        entities.append(DosageEntity(value=float(m.group(1)), unit=scale, raw=m.group(0)))
    entities.extend(_extract_tamil_dosages(text))
    return entities


# --- Frequency normalization (Step 4) ---------------------------------
#
# Normalization rule: "once a day" / "once per day" / "once daily" all
# canonicalize to the same code ("once_daily") — the connector word
# ("a"/"per") and whether "day" or "daily" is used are formatting
# variants, not semantic differences. The *count* word (once/twice/
# thrice/N times) is what must be preserved — "twice daily" -> "once
# daily" changes the canonical code and is rejected.
_FREQUENCY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bonce\s+(?:a\s+day|per\s+day|daily)\b", re.IGNORECASE), "once_daily"),
    (re.compile(r"\btwice\s+(?:a\s+day|per\s+day|daily)\b", re.IGNORECASE), "twice_daily"),
    (re.compile(r"\bthrice\s+(?:a\s+day|per\s+day|daily)\b", re.IGNORECASE), "thrice_daily"),
    (re.compile(r"\bthree\s+times\s+(?:a\s+day|per\s+day|daily)\b", re.IGNORECASE), "thrice_daily"),
    (re.compile(r"\b(\d+)\s*times?\s*(?:a\s+day|per\s+day|daily)\b", re.IGNORECASE), None),  # handled specially, see below
    (re.compile(r"\bevery\s+(\d+)\s*(?:hours?|hrs?)\b", re.IGNORECASE), None),  # handled specially, see below
    (re.compile(r"\bmorning\s+and\s+(?:evening|night)\b", re.IGNORECASE), "morning_and_evening"),
    (re.compile(r"\bat\s+bedtime\b", re.IGNORECASE), "at_bedtime"),
]
# Bare "daily" with no count word — a weaker, separate signal (some count
# word may already be covered above; this catches "daily" used alone).
_BARE_DAILY_RE = re.compile(r"\bdaily\b", re.IGNORECASE)

# Tamil frequency phrases — substring matches (not word-boundary regex):
# Tamil words in running text are space-separated, so simple substring
# search on the multi-character phrase is both simpler and safer here
# than trying to regex-bound agglutinative morphology. Curated starter
# set, verified against this build's own NLLB-200 Tamil output.
_TAMIL_FREQUENCY_SUBSTRINGS: list[tuple[str, str]] = [
    ("தினமும் இருமுறை", "twice_daily"),
    ("நாளுக்கு இருமுறை", "twice_daily"),
    ("தினமும் மூன்று முறை", "thrice_daily"),
    ("நாளுக்கு மூன்று முறை", "thrice_daily"),
    ("தினமும் ஒருமுறை", "once_daily"),
    ("நாளுக்கு ஒருமுறை", "once_daily"),
    ("காலையிலும் மாலையிலும்", "morning_and_evening"),
    ("படுக்கும் நேரத்தில்", "at_bedtime"),
]
_TAMIL_EVERY_N_HOURS_RE = re.compile(r"ஒவ்வொரு\s*(\d+)\s*மணி\s*நேர")
# Bare "daily" with no count phrase already matched above. Tamil has
# several common synonyms for "daily"/"every day" — தினமும் and தினசரி,
# both seen in this build's own real NLLB-200 output, and நாளும் ("...also/
# every day", as in ஒவ்வொரு நாளும் "every single day") — added after this
# pass's own real-model testing surfaced OPUS-MT (a different translation
# model, added when this build switched translation providers for
# licensing reasons — see docs/MODEL_LICENSE_MATRIX.md) using this
# construction for "daily" instead of தினமும்/தினசரி. Widening this list
# only makes the validator recognize MORE genuinely-correct Tamil
# phrasings as matching — it never weakens the fail-closed guarantee for
# translations that actually dropped the frequency.
_TAMIL_BARE_DAILY_SYNONYMS = ("தினமும்", "தினசரி", "நாளும்")

# General "<Tamil number word> முறை" ("N times") + a separate daily-
# context marker anywhere in the same text — added after this pass's own
# real-model testing (tests/pipeline/test_pipeline_models.py) surfaced a
# real NLLB-200 output the fixed-phrase list above did not cover:
# "தினமும் இரண்டு முறை" ("daily two times"), which says "twice daily"
# using the spelled-out number word இரண்டு ("two") + முறை ("times")
# rather than the single compound word இருமுறை ("twice") the fixed-
# phrase list expected. Matching the count word and the daily-context
# marker independently (not as one fixed adjacent phrase) covers this
# real variation and others like it (different word order, marker choice)
# without needing to enumerate every possible phrasing.
_TAMIL_NUMBER_WORDS: dict[str, int] = {
    "ஒரு": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5,
}  # fmt: skip
_TAMIL_TIMES_COUNT_RE = re.compile(r"(" + "|".join(_TAMIL_NUMBER_WORDS) + r")\s*முறை")
# நாளும் added alongside the existing markers for the same OPUS-MT reason
# as _TAMIL_BARE_DAILY_SYNONYMS above — confirmed against this pass's own
# real OPUS-MT output ("ஒவ்வொரு நாளும் இரண்டு முறை", "every day two
# times"), where the count word and this daily marker appear as separate,
# non-adjacent words in the sentence (this function already matches them
# independently, not as one fixed phrase — see the comment above this
# block — so adding the marker alone is sufficient).
_TAMIL_DAILY_CONTEXT_MARKERS = ("தினமும்", "தினசரி", "நாளுக்கு", "நாளொன்றுக்கு", "நாளும்")
_TAMIL_FREQUENCY_CODE_FOR_COUNT = {1: "once_daily", 2: "twice_daily", 3: "thrice_daily"}


def extract_frequencies(text: str) -> set[str]:
    codes: set[str] = set()
    covered = [False] * (len(text) + 1)

    def mark(start: int, end: int) -> None:
        for i in range(start, end):
            covered[i] = True

    for pattern, code in _FREQUENCY_RULES:
        for m in pattern.finditer(text):
            if code is not None:
                codes.add(code)
            elif "times" in pattern.pattern:
                codes.add(f"{m.group(1)}_times_daily")
            else:  # "every N hours"
                codes.add(f"every_{m.group(1)}_hours")
            mark(m.start(), m.end())

    # Only add the generic "daily" signal if no more specific count-word
    # frequency already matched that same span — otherwise "twice daily"
    # would (correctly) set twice_daily AND (incorrectly, redundantly)
    # also set a generic "daily" that could mask a real change if the
    # translation dropped the count word but kept "daily".
    for m in _BARE_DAILY_RE.finditer(text):
        if not covered[m.start()]:
            codes.add("daily_unspecified_count")

    for phrase, code in _TAMIL_FREQUENCY_SUBSTRINGS:
        idx = text.find(phrase)
        if idx != -1:
            codes.add(code)
            mark(idx, idx + len(phrase))

    for m in _TAMIL_EVERY_N_HOURS_RE.finditer(text):
        codes.add(f"every_{m.group(1)}_hours")
        mark(m.start(), m.end())

    daily_context_match: tuple[int, int] | None = None
    for marker in _TAMIL_DAILY_CONTEXT_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            daily_context_match = (idx, idx + len(marker))
            break

    times_matches = list(_TAMIL_TIMES_COUNT_RE.finditer(text))
    if times_matches and daily_context_match is not None:
        for m in times_matches:
            count = _TAMIL_NUMBER_WORDS[m.group(1)]
            codes.add(_TAMIL_FREQUENCY_CODE_FOR_COUNT.get(count, f"{count}_times_daily"))
            mark(m.start(), m.end())
        mark(*daily_context_match)

    for synonym in _TAMIL_BARE_DAILY_SYNONYMS:
        idx = text.find(synonym)
        if idx != -1 and not covered[idx]:
            codes.add("daily_unspecified_count")
            break

    return codes


# --- Duration normalization (Step 5) -----------------------------------
#
# Normalization rule: value and unit (day/week/month) are compared
# separately and explicitly — day/week/month are never treated as
# interchangeable regardless of value, so "7 days" -> "7 weeks" is
# rejected even though the numeric value "7" alone is unchanged (this is
# exactly the case a pure numeric-preservation check cannot catch).
_DURATION_UNIT_VARIANTS = {
    "day": "day", "days": "day",
    "week": "week", "weeks": "week",
    "month": "month", "months": "month",
}  # fmt: skip
_DURATION_VALUE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(days?|weeks?|months?)\b", re.IGNORECASE
)


# Tamil duration stems. Unlike the dose-unit stems above, Tamil's plural
# for these particular words is not simple suffix concatenation (நாள்
# "day" -> நாட்கள் "days" changes ள் to ட்க், an irregular/sandhi form,
# not a suffix on the singular) — so the stem here is the common prefix
# of the *inflected* forms actually seen in translated output ("நாட்க"
# covers நாட்கள்/நாட்களுக்கு), not the dictionary singular.
#
# Deliberately NOT the bare 3-letter prefixes "வார"/"மாத": testing this
# against real NLLB-200 output caught a real false-positive — "மாத"
# ("month") is also the literal first three characters of "மாத்திரை"
# ("tablet"), so a bare-"மாத" stem match incorrectly turned "2 tablets"
# into a fabricated "2 months" duration. Each stem below includes the
# character that actually distinguishes it from மாத்திரை (a "ம்"/"ங்க"
# continuation, not "்திர") — verified with the exact reproduction case
# in tests/pipeline/test_terminology.py. Curated starter set, verified
# against this build's own NLLB-200 Tamil output, same "not exhaustive by
# design" status as GLOSSARY.
_TAMIL_DURATION_STEMS: dict[str, str] = {
    "நாட்க": "day",     # நாட்கள் / நாட்களுக்கு ("days" / "for days")
    "நாள்": "day",      # singular "day"
    "வாரங்க": "week",   # வாரங்கள் / வாரங்களுக்கு
    "வாரம்": "week",    # singular "week"
    "மாதங்க": "month",  # மாதங்கள் / மாதங்களுக்கு
    "மாதம்": "month",   # singular "month" — NOT bare "மாத", see above
}  # fmt: skip
_TAMIL_DURATION_STEMS_ORDERED = sorted(_TAMIL_DURATION_STEMS.items(), key=lambda kv: len(kv[0]), reverse=True)


def _extract_tamil_durations(text: str) -> list[DurationEntity]:
    entities: list[DurationEntity] = []
    for m in _TAMIL_DOSAGE_NUMBER_RE.finditer(text):
        tail = text[m.end() : m.end() + 20]
        for stem, unit in _TAMIL_DURATION_STEMS_ORDERED:
            if tail.startswith(stem):
                entities.append(DurationEntity(value=float(m.group(1)), unit=unit, raw=m.group(0) + stem))
                break
    return entities


def extract_durations(text: str) -> list[DurationEntity]:
    entities = [
        DurationEntity(value=float(m.group(1)), unit=_DURATION_UNIT_VARIANTS[m.group(2).lower()], raw=m.group(0))
        for m in _DURATION_VALUE_RE.finditer(text)
    ]
    entities.extend(_extract_tamil_durations(text))
    return entities


# --- Food-timing constraints (part of Step 9's example) ----------------
_FOOD_CONSTRAINT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:on\s+an?\s+)?empty\s+stomach\b", re.IGNORECASE), "empty_stomach"),
    (re.compile(r"\bbefore\s+(?:food|meals?|eating)\b", re.IGNORECASE), "before_food"),
    (re.compile(r"\bafter\s+(?:food|meals?|eating)\b", re.IGNORECASE), "after_food"),
    (re.compile(r"\bwith\s+(?:food|meals?)\b", re.IGNORECASE), "with_food"),
    (re.compile(r"\bat\s+bedtime\b|\bbefore\s+bed\b", re.IGNORECASE), "bedtime"),
]


def extract_food_constraints(text: str) -> set[str]:
    return {code for pattern, code in _FOOD_CONSTRAINT_RULES if pattern.search(text)}


# --- Protected term / transliteration handling (Steps 7-8) -------------
#
# Distinguishes SAFE TRANSLITERATION (the correct term rendered in the
# target script/language — e.g. "Ashwagandha" -> "அஸ்வகந்தா") from SEMANTIC
# SUBSTITUTION (a *different* term/entity appearing instead). This is a
# curated starter table (same "not exhaustive by design" status as
# GLOSSARY above) — reviewed for common-usage plausibility, not certified
# by a professional Tamil medical terminologist; treat as a controlled-
# pilot-scope starting point, not a final authority, and grow it
# incrementally the same way GLOSSARY itself is grown.
TRANSLITERATIONS: dict[str, dict[str, list[str]]] = {
    "ashwagandha": {"en": ["ashwagandha"], "ta": ["அஸ்வகந்தா"]},
    "triphala": {"en": ["triphala"], "ta": ["திரிபலா"]},
    "turmeric": {"en": ["turmeric"], "ta": ["மஞ்சள்"]},
    "dosha": {"en": ["dosha"], "ta": ["தோஷம்"]},
    "vata": {"en": ["vata"], "ta": ["வாதம்"]},
    "pitta": {"en": ["pitta"], "ta": ["பித்தம்"]},
    "kapha": {"en": ["kapha"], "ta": ["கபம்"]},
    "agni": {"en": ["agni"], "ta": ["அக்னி"]},
    "ama": {"en": ["ama"], "ta": ["ஆமம்"]},
    "prakriti": {"en": ["prakriti"], "ta": ["பிரகிருதி"]},
    "panchakarma": {"en": ["panchakarma"], "ta": ["பஞ்சகர்மா"]},
    "rasayana": {"en": ["rasayana"], "ta": ["ரசாயனம்"]},
    "paracetamol": {"en": ["paracetamol"], "ta": ["பாராசிட்டமால்"]},
    "ibuprofen": {"en": ["ibuprofen"], "ta": ["ஐபுப்ரோஃபென்"]},
    "amoxicillin": {"en": ["amoxicillin"], "ta": ["அமாக்சிசிலின்"]},
    "metformin": {"en": ["metformin"], "ta": ["மெட்ஃபார்மின்"]},
    "insulin": {"en": ["insulin"], "ta": ["இன்சுலின்"]},
    "blood pressure": {"en": ["blood pressure"], "ta": ["இரத்த அழுத்தம்"]},
    "heart rate": {"en": ["heart rate"], "ta": ["இதய துடிப்பு"]},
    "kidney": {"en": ["kidney"], "ta": ["சிறுநீரகம்"]},
    "liver": {"en": ["liver"], "ta": ["கல்லீரல்"]},
}


_TAMIL_VIRAMA = "்"


def _tamil_match_form(variant: str) -> str:
    """A Tamil dictionary form ending in a bare virama-marked consonant
    (e.g. தோஷம், வாதம்) changes that final consonant under case
    inflection (accusative தோஷம் -> தோஷத்தை, sandhi — not simple suffix
    concatenation), so matching the *full* dictionary form as a substring
    of inflected running text misses it. Stripping the final
    consonant+virama pair yields a stem ("தோஷ", "வாத") that IS a common
    prefix of every inflected form actually seen in this build's own
    NLLB-200 Tamil output (verified via tests/pipeline/test_terminology.py)
    — the same technique already used for the dosage/duration Tamil
    stems above, applied generally here instead of per-word. A variant
    NOT ending in virama (already vowel-final — common for Sanskrit-
    derived loanwords: அஸ்வகந்தா, திரிபலா, பிரகிருதி...) is returned
    unchanged, since those do not undergo this sandhi pattern."""
    if len(variant) >= 2 and variant[-1] == _TAMIL_VIRAMA:
        return variant[:-2]
    return variant


def _variant_present(variant: str, text: str, lowered_text: str) -> bool:
    if variant.isascii():
        return variant.lower() in lowered_text
    return _tamil_match_form(variant) in text


def detect_protected_terms(text: str) -> set[str]:
    """Every glossary term (see GLOSSARY) present in `text`, matched
    against EITHER its English form OR any known transliteration —
    language-agnostic on purpose, so this works whether `text` is the
    English source, the Tamil translation, or (for a Tamil-source call)
    the reverse."""
    found: set[str] = set()
    lowered = text.lower()
    for term, variants_by_lang in TRANSLITERATIONS.items():
        for variants in variants_by_lang.values():
            if any(_variant_present(v, text, lowered) for v in variants):
                found.add(term)
                break
    return found


def term_preserved(term: str, translated_text: str, target_lang: str) -> bool | None:
    """True/False if `term`'s accepted form for `target_lang` is (or
    isn't) present in `translated_text`; None if this table has no entry
    for `term` in `target_lang` — callers must treat None as "cannot
    verify", not as "safe", per the validator's fail-closed design."""
    variants = TRANSLITERATIONS.get(term, {}).get(target_lang)
    if not variants:
        return None
    lowered = translated_text.lower()
    return any(_variant_present(v, translated_text, lowered) for v in variants)


def extract_safety_entities(text: str, lang: str = "en") -> SafetyEntities:
    """Builds the normalized, comparable representation of `text` that
    safety.validate() diffs between source and translation. `lang` is
    used for language-aware negation detection (negation.has_negation) —
    everything else here is language-agnostic (numbers/units/frequency/
    duration patterns are matched the same way regardless of source
    language, since this build's protected-span vocabulary is currently
    English-pattern-based; see docs/ai/README.md's Known limitations for
    what that does and doesn't cover for Tamil-source text)."""
    from . import negation  # local import: avoids a module-level cycle risk if negation.py ever needs terminology

    negation_present = negation.has_negation(text, lang)
    return SafetyEntities(
        numbers=extract_numeric_values(text),
        dosages=extract_dosages(text),
        durations=extract_durations(text),
        frequencies=extract_frequencies(text),
        food_constraints=extract_food_constraints(text),
        negation=bool(negation_present),
        protected_terms=detect_protected_terms(text),
    )
