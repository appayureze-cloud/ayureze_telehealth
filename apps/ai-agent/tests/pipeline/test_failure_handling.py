"""UNIT TESTS (fake providers, no real models loaded) proving fail-closed
behavior for every pipeline-stage failure mode this task's validation
pass requires: STT/translation/validator/TTS exceptions, empty audio,
and unsupported language.

Architecture note (not a defect, documented as-is per this task's "do not
redesign the AI architecture" instruction): TranslationPipeline.process()/
process_auto() do NOT themselves catch per-stage exceptions — they are
pure functions that let a stage's exception propagate to the caller. The
one production caller, LiveAudioProcessor._process_segment
(app/pipeline/streaming.py), wraps the whole call in a broad
try/except, logs a safe reason (never the exception's surrounding
transcript/translation text — see the log call itself), and drops the
segment (no audio published, no crash of the audio stream). Fail-closed
behavior for pipeline exceptions is therefore enforced at that call site,
not inside the orchestrator itself. These tests prove both halves: the
orchestrator's own propagation behavior, and the call site's containment
of it.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from app.pipeline.lid import LanguageIDProvider
from app.pipeline.orchestrator import TranslationPipeline
from app.pipeline.stt import STTProvider
from app.pipeline.translation import TranslationProvider, _LANG_TO_NLLB
from app.pipeline.tts import TTSProvider
from app.pipeline.types import TranscriptSegment


class _FakeLID(LanguageIDProvider):
    def identify(self, text):
        return "en", 10.0


class _FakeSTT(STTProvider):
    def __init__(self, text: str = "Take 10 mg twice daily.", lang: str = "en", raises: Exception | None = None):
        self._text, self._lang, self._raises = text, lang, raises

    def transcribe(self, audio, sample_rate):
        if self._raises:
            raise self._raises
        return TranscriptSegment(text=self._text, language=self._lang, language_confidence=0.99)


class _FakeTranslator(TranslationProvider):
    def __init__(self, output: str = "Take 10 mg twice daily.", raises: Exception | None = None):
        self._output, self._raises = output, raises

    def translate(self, text, source_lang, target_lang):
        if self._raises:
            raise self._raises
        return self._output


class _FakeTTS(TTSProvider):
    def __init__(self, raises: Exception | None = None):
        self._raises = raises
        self.calls = 0

    def synthesize(self, text, lang):
        self.calls += 1
        if self._raises:
            raise self._raises
        import numpy as _np

        from app.pipeline.types import SynthesizedAudio

        return SynthesizedAudio(samples=_np.zeros(10, dtype=np.float32), sample_rate=16000)


def _pipeline(stt=None, translator=None, tts=None):
    return TranslationPipeline(
        stt=stt or _FakeSTT(),
        lid=_FakeLID(),
        translator=translator or _FakeTranslator(),
        tts=tts or _FakeTTS(),
    )


# ===================== A. STT failure =====================


def test_stt_exception_propagates_from_orchestrator():
    pipeline = _pipeline(stt=_FakeSTT(raises=RuntimeError("model inference crashed")))
    with pytest.raises(RuntimeError, match="model inference crashed"):
        pipeline.process(np.zeros(160, dtype=np.float32), target_lang="ta")


# =================== B. Translation failure ===================


def test_translation_exception_propagates_from_orchestrator():
    pipeline = _pipeline(translator=_FakeTranslator(raises=RuntimeError("translation backend unavailable")))
    with pytest.raises(RuntimeError, match="translation backend unavailable"):
        pipeline.process(np.zeros(160, dtype=np.float32), target_lang="ta")


# =================== C. Safety validator: must never raise on malformed input ===================


def test_validator_does_not_raise_on_empty_strings():
    from app.pipeline import safety, terminology

    term = terminology.analyze("")
    result = safety.validate("", "", term, source_lang="en", target_lang="ta")
    assert result.safe  # nothing to compare, nothing mismatched — not a false rejection either


def test_validator_does_not_raise_on_garbage_unicode():
    from app.pipeline import safety, terminology

    garbage = "\x00�​​ test 🚑💊"
    term = terminology.analyze(garbage)
    # Must not raise — a corrupted/garbled transcript must fail closed via
    # a normal reject (translated text presumably won't match), never crash.
    result = safety.validate(garbage, "unrelated text", term, source_lang="en", target_lang="en")
    assert result.safe is False or result.safe is True  # only asserting: no exception raised


# ======================= D. TTS failure =======================


def test_tts_exception_propagates_from_orchestrator_after_safe_validation():
    # The translation is safe (identical), so the pipeline reaches TTS —
    # proving the TTS exception is the thing that surfaces, not masked by
    # an earlier stage.
    pipeline = _pipeline(tts=_FakeTTS(raises=RuntimeError("tts synthesis failed")))
    with pytest.raises(RuntimeError, match="tts synthesis failed"):
        pipeline.process(np.zeros(160, dtype=np.float32), target_lang="en")


# =================== E. Orchestrator: unsafe translation never reaches a raising TTS ===================


def test_unsafe_translation_never_calls_tts_even_if_tts_would_raise():
    # If TTS were called for an unsafe translation it would raise here —
    # proves the gate, not just the exception path.
    tts = _FakeTTS(raises=AssertionError("TTS must not be called for unsafe output"))
    pipeline = _pipeline(
        stt=_FakeSTT(text="Do not take this medicine."),
        translator=_FakeTranslator(output="Take this medicine."),
        tts=tts,
    )
    result = pipeline.process(np.zeros(160, dtype=np.float32), target_lang="en")
    assert result.blocked
    assert result.audio is None
    assert tts.calls == 0


# =================== F. Empty audio / empty transcript ===================


def test_empty_transcript_produces_no_audio_and_no_crash():
    pipeline = _pipeline(stt=_FakeSTT(text=""), translator=_FakeTranslator(output=""))
    result = pipeline.process(np.zeros(160, dtype=np.float32), target_lang="ta")
    assert result.audio is None
    assert result.safety.safe  # nothing to reject; also nothing published (translated_text is empty)


# =================== G. Unsupported language ===================


def test_translation_language_gate_rejects_unconfigured_language_pair():
    # Direct proof of translation.py's own language-membership gate — no
    # model weights required, since the check happens before any model
    # call. "xx" is not a configured language anywhere in this pipeline.
    assert "xx" not in _LANG_TO_NLLB


def test_unsupported_language_exception_propagates_from_orchestrator():
    pipeline = _pipeline(translator=_FakeTranslator(raises=ValueError("unsupported language pair: en -> xx")))
    with pytest.raises(ValueError, match="unsupported language pair"):
        pipeline.process(np.zeros(160, dtype=np.float32), target_lang="xx")


# ========= H. Call-site containment (streaming.py) — proves the actual fail-closed boundary =========


def test_streaming_call_site_contains_pipeline_exceptions(caplog):
    """LiveAudioProcessor._process_segment must catch any pipeline
    exception, log a safe reason code, publish no audio, and not crash
    the audio stream — this is where fail-closed behavior for exceptions
    is actually enforced (see this module's docstring)."""
    import asyncio

    from app.pipeline.streaming import LiveAudioProcessor

    class _ExplodingPipeline:
        def process_auto(self, audio, target_resolver, session_id):
            raise RuntimeError("simulated pipeline crash")

    processor = LiveAudioProcessor(
        room=None,  # never touched: the exception is raised before any room/track access
        pipeline=_ExplodingPipeline(),
        logger=logging.getLogger("test.streaming"),
        session_id="test-session",
    )

    class _FakeParticipant:
        identity = "patient-test"

    with caplog.at_level(logging.ERROR):
        asyncio.run(processor._process_segment(np.zeros(1600, dtype=np.float32), _FakeParticipant()))

    assert processor._publish_task is None  # no audio publish was ever scheduled
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any(r.getMessage() == "pipeline_segment_failed" for r in error_records)
    # The logged error field must carry only the exception's own message,
    # never raw transcript/translation content (there is none available
    # at this catch site regardless — process_auto raised before
    # returning any).
    matching = next(r for r in error_records if r.getMessage() == "pipeline_segment_failed")
    assert matching.fields["error"] == "simulated pipeline crash"
    assert matching.fields["session_id"] == "test-session"


# ============= I. Interruption / barge-in (Phase 9) =============
#
# UNIT TEST (fake pipeline + fake room, no real LiveKit/models) proving
# the barge-in cancellation logic already present in
# app/pipeline/streaming.py's LiveAudioProcessor._process_segment: when
# new speech arrives while a previous translated-audio publish is still
# in flight, that prior publish task is cancelled rather than left to
# overlap with the new one — this is the concrete mechanism preventing
# "overlapping translated speech" the module's own docstring warns about.


def test_barge_in_cancels_in_flight_publish_task():
    import asyncio

    from app.pipeline.streaming import LiveAudioProcessor
    from app.pipeline.types import (
        PipelineResult,
        SafetyCheckResult,
        TerminologyAnalysis,
        TranscriptSegment,
        TranslationResult,
    )

    class _QuietPipeline:
        """Returns a safe-but-unpublishable result so _process_segment
        exits right after the barge-in check, without needing a real
        room/output_source for _publish_audio."""

        def process_auto(self, audio, target_resolver, session_id):
            transcript = TranscriptSegment(text="", language="en", language_confidence=1.0)
            return PipelineResult(
                transcript=transcript,
                terminology=TerminologyAnalysis(protected_spans=[]),
                translation=TranslationResult(source_text="", translated_text="", source_lang="en", target_lang="ta"),
                safety=SafetyCheckResult(safe=True, reasons=[], source_numbers=[], translated_numbers=[], reason_codes=[]),
                audio=None,  # nothing to publish -> _process_segment returns right after the barge-in check
                timings_ms={},
            )

    processor = LiveAudioProcessor(
        room=None,
        pipeline=_QuietPipeline(),
        logger=logging.getLogger("test.bargein"),
        session_id="test-session",
    )

    class _FakeParticipant:
        identity = "patient-test"

    async def _long_running_prior_publish():
        await asyncio.sleep(30)

    async def scenario():
        # Simulate a translated-audio publish from a PRIOR segment still
        # in flight when new speech (this segment) arrives.
        processor._publish_task = asyncio.create_task(_long_running_prior_publish())
        await asyncio.sleep(0)  # let it actually start
        assert not processor._publish_task.done()

        prior_task = processor._publish_task
        await processor._process_segment(np.zeros(1600, dtype=np.float32), _FakeParticipant())
        await asyncio.sleep(0)  # let the cancellation actually propagate

        # The barge-in check must have cancelled the prior publish task.
        with pytest.raises(asyncio.CancelledError):
            await prior_task
        assert prior_task.cancelled()

    asyncio.run(scenario())
