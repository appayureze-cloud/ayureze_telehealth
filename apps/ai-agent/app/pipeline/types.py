"""Shared result types for the translation pipeline. Kept provider-agnostic
so apps/ai-agent/app/pipeline/orchestrator.py never depends on any one
vendor's SDK types — only these.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class TranscriptSegment:
    text: str
    language: str  # e.g. "en", "ta", "ml"
    language_confidence: float


@dataclass
class ProtectedSpan:
    """A substring the terminology engine has identified as
    translation-critical: numbers, dosages, frequencies, durations,
    medicine names, anatomical terms, clinical measurements. See
    terminology.py.
    """

    text: str
    kind: str  # "number" | "dosage" | "frequency" | "duration" | "medicine" | "term"


@dataclass
class TerminologyAnalysis:
    protected_spans: list[ProtectedSpan] = field(default_factory=list)


@dataclass
class DosageEntity:
    """A (value, unit) pair extracted from a dosage phrase — e.g. "10 mg"
    -> value=10.0, unit="mg" (canonical unit code, see terminology.py's
    UNIT_CANONICAL). Compared field-by-field, not as a raw string, so
    "10 mg" -> "10 milligrams" matches but "10 mg" -> "10 ml" never does.
    """

    value: float
    unit: str
    raw: str


@dataclass
class DurationEntity:
    """A (value, unit) pair extracted from a duration phrase — e.g. "7
    days" -> value=7.0, unit="day". unit is one of "day"/"week"/"month",
    deliberately never treated as equivalent to each other — "7 days" and
    "7 weeks" share a numeric value but are not the same duration.
    """

    value: float
    unit: str
    raw: str


@dataclass
class SafetyEntities:
    """The normalized, comparable representation of one side (source or
    translated) of a segment, built by terminology.extract_safety_entities().
    safety.validate() builds one of these for the source text and one for
    the translated text and compares them field-by-field — this is the
    "normalized safety object" the deterministic validator reasons about,
    never raw text similarity.
    """

    numbers: list[float] = field(default_factory=list)  # every numeric value, as a multiset (order-independent)
    dosages: list[DosageEntity] = field(default_factory=list)
    durations: list[DurationEntity] = field(default_factory=list)
    frequencies: set[str] = field(default_factory=set)  # canonical codes, e.g. "twice_daily"
    food_constraints: set[str] = field(default_factory=set)  # e.g. "empty_stomach"
    negation: bool = False
    protected_terms: set[str] = field(default_factory=set)  # canonical glossary term ids found in this text


@dataclass
class TranslationResult:
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str


@dataclass
class SafetyCheckResult:
    safe: bool
    reasons: list[str] = field(default_factory=list)
    source_numbers: list[str] = field(default_factory=list)
    translated_numbers: list[str] = field(default_factory=list)
    # Short, medical-content-free machine-readable identifiers for each
    # reason in `reasons` — e.g. "unit_mismatch", "negation_mismatch" —
    # safe to put in logs/metrics/traces where `reasons` (which can quote
    # extracted numbers/units/terms) should not go by default. See
    # docs/ai/README.md's safety-validator logging section.
    reason_codes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "safe" if self.safe else "rejected"

    def to_structured_error(self) -> dict:
        """The fail-closed structured rejection payload — never includes
        raw source/translated text, only the machine-readable summary."""
        return {
            "status": self.status,
            "reason": self.reason_codes[0] if self.reason_codes else "critical_medical_entity_mismatch",
            "reason_codes": self.reason_codes,
        }


@dataclass
class SynthesizedAudio:
    samples: np.ndarray  # float32, mono, shape (n,)
    sample_rate: int


@dataclass
class PipelineResult:
    transcript: TranscriptSegment
    terminology: TerminologyAnalysis
    translation: TranslationResult
    safety: SafetyCheckResult
    audio: SynthesizedAudio | None  # None if safety blocked publication
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return not self.safety.safe
