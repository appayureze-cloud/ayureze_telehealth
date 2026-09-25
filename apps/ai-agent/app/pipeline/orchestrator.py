"""Ties VAD-segmented audio through STT -> language ID -> terminology ->
translation -> safety validation -> TTS, measuring per-stage latency.

This module's process() is synchronous and CPU-bound (model inference) —
callers running an asyncio event loop (apps/ai-agent/app/agent.py) must
invoke it via an executor (e.g. `loop.run_in_executor`), never awaited
directly on the event loop thread.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from .. import metrics, tracing
from . import safety, terminology
from .lid import LanguageIDProvider, resolve_language
from .stt import STTProvider
from .translation import TranslationProvider
from .tts import TTSProvider
from .types import (
    PipelineResult,
    SynthesizedAudio,
    TranscriptSegment,
    TranslationResult,
)

SAMPLE_RATE = 16000


def _record_stage(timings: dict[str, float], stage: str, elapsed_seconds: float) -> None:
    """Records one pipeline stage's latency both into the in-band
    timings_ms dict (carried on captions, per build spec section 6's
    "expose timing metadata") and as a scrapable Prometheus histogram
    observation (build spec section 13's AI latency metrics)."""
    timings[f"{stage}_ms"] = elapsed_seconds * 1000
    metrics.PIPELINE_STAGE_LATENCY_SECONDS.labels(stage=stage).observe(elapsed_seconds)


class TranslationPipeline:
    def __init__(
        self,
        stt: STTProvider,
        lid: LanguageIDProvider,
        translator: TranslationProvider,
        tts: TTSProvider | None = None,
    ):
        """tts=None runs the pipeline in CAPTIONS-ONLY mode: transcription,
        translation, and safety validation all run normally and
        PipelineResult.translation/safety are fully populated, but
        PipelineResult.audio is always None and no TTS stage timing is
        recorded. Used when no commercially-licensed, CPU-feasible TTS
        model is configured — see app/pipeline/factory.py and
        docs/ai/README.md."""
        self._stt = stt
        self._lid = lid
        self._translator = translator
        self._tts = tts

    def transcribe(
        self, audio: np.ndarray, session_id: str = "unknown"
    ) -> tuple[TranscriptSegment, dict[str, float]]:
        """STT + language ID only — the shared first phase of process()
        and process_auto(), split out so callers that need to resolve a
        target language *from* the detected source (streaming.py) don't
        pay for a second STT pass just to re-run with a different target.
        """
        timings: dict[str, float] = {}

        with tracing.tracer().start_as_current_span("pipeline.stt") as span:
            span.set_attribute("ayureze.session_id", session_id)
            t0 = time.monotonic()
            transcript = self._stt.transcribe(audio, SAMPLE_RATE)
            elapsed = time.monotonic() - t0
            _record_stage(timings, "stt", elapsed)
            span.set_attribute("ayureze.duration_ms", elapsed * 1000)

        with tracing.tracer().start_as_current_span("pipeline.language_id") as span:
            span.set_attribute("ayureze.session_id", session_id)
            t0 = time.monotonic()
            text_lang, _text_lid_score = self._lid.identify(transcript.text)
            resolved_lang = resolve_language(transcript.language, transcript.language_confidence, text_lang)
            transcript = TranscriptSegment(
                text=transcript.text, language=resolved_lang, language_confidence=transcript.language_confidence
            )
            elapsed = time.monotonic() - t0
            _record_stage(timings, "language_id", elapsed)
            span.set_attribute("ayureze.duration_ms", elapsed * 1000)
            span.set_attribute("ayureze.resolved_language", resolved_lang)

        return transcript, timings

    def process(self, audio: np.ndarray, target_lang: str, session_id: str = "unknown") -> PipelineResult:
        """audio: float32 mono PCM at SAMPLE_RATE, one VAD-delimited
        speech segment. target_lang: the language to translate *into*.
        Use process_auto() instead when the target should be derived from
        the detected source language rather than fixed in advance.
        """
        with tracing.tracer().start_as_current_span("pipeline.process") as span:
            span.set_attribute("ayureze.session_id", session_id)
            span.set_attribute("ayureze.target_lang", target_lang)
            transcript, timings = self.transcribe(audio, session_id)
            return self._translate_and_synthesize(transcript, target_lang, timings, session_id)

    def process_auto(
        self, audio: np.ndarray, target_resolver: Callable[[str], str], session_id: str = "unknown"
    ) -> PipelineResult:
        """Like process(), but target_lang is computed from the detected
        source language via target_resolver (e.g. streaming.py's
        target_language_for), after a single transcription pass.
        """
        with tracing.tracer().start_as_current_span("pipeline.process_auto") as span:
            span.set_attribute("ayureze.session_id", session_id)
            transcript, timings = self.transcribe(audio, session_id)
            target_lang = target_resolver(transcript.language)
            span.set_attribute("ayureze.target_lang", target_lang)
            return self._translate_and_synthesize(transcript, target_lang, timings, session_id)

    def _translate_and_synthesize(
        self,
        transcript: TranscriptSegment,
        target_lang: str,
        timings: dict[str, float],
        session_id: str = "unknown",
    ) -> PipelineResult:
        with tracing.tracer().start_as_current_span("pipeline.terminology") as span:
            span.set_attribute("ayureze.session_id", session_id)
            t0 = time.monotonic()
            term_analysis = terminology.analyze(transcript.text)
            elapsed = time.monotonic() - t0
            _record_stage(timings, "terminology", elapsed)
            span.set_attribute("ayureze.duration_ms", elapsed * 1000)
            span.set_attribute("ayureze.protected_span_count", len(term_analysis.protected_spans))

        with tracing.tracer().start_as_current_span("pipeline.translation") as span:
            span.set_attribute("ayureze.session_id", session_id)
            t0 = time.monotonic()
            translated_text = self._translator.translate(transcript.text, transcript.language, target_lang)
            translation = TranslationResult(
                source_text=transcript.text,
                translated_text=translated_text,
                source_lang=transcript.language,
                target_lang=target_lang,
            )
            elapsed = time.monotonic() - t0
            _record_stage(timings, "translation", elapsed)
            span.set_attribute("ayureze.duration_ms", elapsed * 1000)
            span.set_attribute("ayureze.source_lang", transcript.language)
            span.set_attribute("ayureze.target_lang", target_lang)

        with tracing.tracer().start_as_current_span("pipeline.safety_validation") as span:
            span.set_attribute("ayureze.session_id", session_id)
            t0 = time.monotonic()
            safety_result = safety.validate(
                transcript.text, translated_text, term_analysis,
                source_lang=transcript.language, target_lang=target_lang,
            )
            elapsed = time.monotonic() - t0
            _record_stage(timings, "safety_validation", elapsed)
            span.set_attribute("ayureze.duration_ms", elapsed * 1000)
            span.set_attribute("ayureze.safe", safety_result.safe)

        audio_out: SynthesizedAudio | None = None
        if safety_result.safe and translated_text.strip() and self._tts is not None:
            with tracing.tracer().start_as_current_span("pipeline.tts") as span:
                span.set_attribute("ayureze.session_id", session_id)
                t0 = time.monotonic()
                audio_out = self._tts.synthesize(translated_text, target_lang)
                elapsed = time.monotonic() - t0
                _record_stage(timings, "tts", elapsed)
                span.set_attribute("ayureze.duration_ms", elapsed * 1000)

        timings["total_ms"] = sum(timings.values())
        metrics.PIPELINE_STAGE_LATENCY_SECONDS.labels(stage="total").observe(timings["total_ms"] / 1000)
        metrics.PIPELINE_SEGMENTS_PROCESSED_TOTAL.inc()
        if not safety_result.safe:
            metrics.PIPELINE_SEGMENTS_BLOCKED_TOTAL.inc()

        return PipelineResult(
            transcript=transcript,
            terminology=term_analysis,
            translation=translation,
            safety=safety_result,
            audio=audio_out,
            timings_ms=timings,
        )
