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
