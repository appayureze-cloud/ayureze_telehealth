"""Deterministic safety validation. Never a model — this must be
predictable and auditable, per the build spec: "Create a deterministic
validation layer." If a translation changes critical information
(currently: numbers — dosage/frequency/duration always contain a number in
this build's glossary patterns, see terminology.py), the result is marked
unsafe and the orchestrator must not publish the translated audio.
"""

from __future__ import annotations

from .terminology import extract_numbers
from .types import SafetyCheckResult, TerminologyAnalysis


def validate(source_text: str, translated_text: str, terminology: TerminologyAnalysis) -> SafetyCheckResult:
    source_numbers = extract_numbers(source_text)
    translated_numbers = extract_numbers(translated_text)

    reasons: list[str] = []

    if source_numbers != translated_numbers:
        reasons.append(
            f"number mismatch: source had {source_numbers}, translation has {translated_numbers}"
        )

    if not translated_text.strip() and source_text.strip():
        reasons.append("translation produced empty output for non-empty source")

    # A dosage/frequency/duration span existing in the source but the
    # translated text having *fewer* numbers than the source is the
    # specific failure mode the build spec calls out ("Take 2 tablets
    # twice daily for 7 days" silently losing "7") — already covered by
    # the exact-sequence check above, called out again here for a more
    # specific, actionable reason string when it's a protected span.
    protected_numeric_spans = [s for s in terminology.protected_spans if s.kind in ("dosage", "frequency", "duration", "number")]
    if protected_numeric_spans and len(translated_numbers) < len(source_numbers):
        reasons.append(
            f"{len(source_numbers) - len(translated_numbers)} numeric value(s) from protected clinical "
            f"spans (dosage/frequency/duration) are missing from the translation"
        )

    return SafetyCheckResult(
        safe=len(reasons) == 0,
        reasons=reasons,
        source_numbers=source_numbers,
        translated_numbers=translated_numbers,
    )
