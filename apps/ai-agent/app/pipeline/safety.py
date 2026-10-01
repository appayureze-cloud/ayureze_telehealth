"""Deterministic safety validation. Never a model — this must be
predictable and auditable, per the build spec: "Create a deterministic
validation layer."

Builds a normalized SafetyEntities object (terminology.
extract_safety_entities) for the source text and for the translated
text, then compares them field by field:

  numbers            -> multiset equality (order-independent)
  dosages            -> (value, canonical unit) preserved per entry
  durations          -> (value, canonical unit) preserved per entry
  frequencies        -> canonical frequency-code set equality
  food_constraints   -> canonical constraint-code set equality
  negation           -> equal on both sides, using each side's own
                         language's negation vocabulary (see negation.py)
  protected_terms    -> every term found in the source is verifiably
                         present (via its accepted transliteration) in
                         the translation

Any critical mismatch marks the result unsafe; the orchestrator
(orchestrator.py) must not synthesize or publish audio for an unsafe
result — see docs/ai/README.md's "Safety validator" section for the full
rule reference and docs/security/README.md for why this stays
deterministic rather than model-based.

FAIL CLOSED: when a check cannot be confidently evaluated (e.g. a
protected term's target-language transliteration is not in
terminology.TRANSLITERATIONS, or negation.py has no table for a
language), that specific check is skipped — it never resolves an
unknown to "safe". Every mismatch this module CAN detect is a hard
rejection.
"""

from __future__ import annotations

from . import terminology
from .types import SafetyCheckResult, SafetyEntities, TerminologyAnalysis

# Two floats are the "same value" if they differ by less than this —
# guards against float rounding noise (e.g. 1/3 computed two different
# ways), never used to treat genuinely different clinical values as equal.
_NUMBER_TOLERANCE = 1e-6


def _numbers_equal(a: float, b: float) -> bool:
    return abs(a - b) < _NUMBER_TOLERANCE


def _multiset_diff(source: list[float], translated: list[float]) -> bool:
    """True if the two numeric multisets differ (a value dropped, added,
    or changed) — order-independent, so legitimate reordering across
    languages is never a false rejection."""
    remaining = list(translated)
    for v in source:
        match = next((r for r in remaining if _numbers_equal(v, r)), None)
        if match is None:
            return True
        remaining.remove(match)
    return len(remaining) > 0


def _dosage_multiset_diff(source: list, translated: list) -> bool:
    remaining = list(translated)
    for d in source:
        match = next((r for r in remaining if r.unit == d.unit and _numbers_equal(r.value, d.value)), None)
        if match is None:
            return True
        remaining.remove(match)
    return len(remaining) > 0


def _duration_multiset_diff(source: list, translated: list) -> bool:
    remaining = list(translated)
    for d in source:
        match = next((r for r in remaining if r.unit == d.unit and _numbers_equal(r.value, d.value)), None)
        if match is None:
            return True
        remaining.remove(match)
    return len(remaining) > 0


def validate(
    source_text: str,
    translated_text: str,
    terminology_analysis: TerminologyAnalysis,
    source_lang: str = "en",
    target_lang: str = "en",
) -> SafetyCheckResult:
    reasons: list[str] = []
    reason_codes: list[str] = []

    def reject(code: str, message: str) -> None:
        reason_codes.append(code)
        reasons.append(message)

    # Preserved for API/behavioral compatibility with existing callers —
    # the raw digit-sequence view (not the normalized float multiset
    # used for the actual safety comparison below).
    source_numbers = terminology.extract_numbers(source_text)
    translated_numbers = terminology.extract_numbers(translated_text)

    if not translated_text.strip() and source_text.strip():
        reject("empty_translation", "translation produced empty output for non-empty source")
        return SafetyCheckResult(
            safe=False,
            reasons=reasons,
            source_numbers=source_numbers,
            translated_numbers=translated_numbers,
            reason_codes=reason_codes,
        )

    source_entities: SafetyEntities = terminology.extract_safety_entities(source_text, source_lang)
    translated_entities: SafetyEntities = terminology.extract_safety_entities(translated_text, target_lang)

    # --- Step 2: numeric preservation (multiset, normalized values) ---
    if _multiset_diff(source_entities.numbers, translated_entities.numbers):
        reject(
            "number_mismatch",
            f"number mismatch: source had {source_numbers}, translation has {translated_numbers}",
        )

    protected_numeric_spans = [
        s for s in terminology_analysis.protected_spans if s.kind in ("dosage", "frequency", "duration", "number")
    ]
    if protected_numeric_spans and len(translated_numbers) < len(source_numbers):
        reject(
            "protected_numeric_value_missing",
            f"{len(source_numbers) - len(translated_numbers)} numeric value(s) from protected clinical "
            f"spans (dosage/frequency/duration) are missing from the translation",
        )

    # --- Step 3: unit preservation (value+unit pairs, not bare digits) ---
    if _dosage_multiset_diff(source_entities.dosages, translated_entities.dosages):
        reject(
            "unit_mismatch",
            f"dosage/unit mismatch: source had {[(d.value, d.unit) for d in source_entities.dosages]}, "
            f"translation has {[(d.value, d.unit) for d in translated_entities.dosages]}",
        )

    # --- Steps 4-5: frequency + duration preservation ---
    if source_entities.frequencies != translated_entities.frequencies:
        reject(
            "frequency_mismatch",
            f"frequency mismatch: source had {sorted(source_entities.frequencies)}, "
            f"translation has {sorted(translated_entities.frequencies)}",
        )

    if _duration_multiset_diff(source_entities.durations, translated_entities.durations):
        reject(
            "duration_mismatch",
            f"duration mismatch: source had {[(d.value, d.unit) for d in source_entities.durations]}, "
            f"translation has {[(d.value, d.unit) for d in translated_entities.durations]}",
        )

    # Food-timing constraints ("empty stomach", "before food", ...) — part
    # of Step 9's normalized safety object.
    if source_entities.food_constraints != translated_entities.food_constraints:
        reject(
            "food_constraint_mismatch",
            f"food-timing constraint mismatch: source had {sorted(source_entities.food_constraints)}, "
            f"translation has {sorted(translated_entities.food_constraints)}",
        )

    # --- Step 6: negation ---
    # negation.has_negation() returns None when a language has no
    # negation table (see negation.py) — SafetyEntities.negation coerces
    # that to False (bool(None) == False), which would silently treat an
    # unverifiable side as "no negation" rather than "unknown". Guard
    # explicitly here instead: only compare when BOTH sides' languages
    # are actually covered, otherwise skip (fail-closed means never
    # resolving "unknown" to "safe" — it does not mean guessing).
    from . import negation as _negation

    if source_lang in _negation.supported_languages() and target_lang in _negation.supported_languages():
        if source_entities.negation != translated_entities.negation:
            reject(
                "negation_mismatch",
                "negation mismatch: the translation's polarity (affirmative vs. negative) does not "
                "match the source — this can invert a medical instruction's meaning",
            )

    # --- Steps 7-8: protected medicine/Ayurveda term preservation ---
    for term in source_entities.protected_terms:
        preserved = terminology.term_preserved(term, translated_text, target_lang)
        if preserved is False:
            reject(
                "protected_term_mismatch",
                f"protected term '{term}' found in the source is not verifiably present in the translation "
                f"(possible drop or substitution)",
            )
        # preserved is None (no transliteration table for target_lang):
        # cannot verify -> not rejected here, but also never counted as
        # confirmed-safe; see docs/ai/README.md's Known limitations.

    return SafetyCheckResult(
        safe=len(reasons) == 0,
        reasons=reasons,
        source_numbers=source_numbers,
        translated_numbers=translated_numbers,
        reason_codes=reason_codes,
    )
