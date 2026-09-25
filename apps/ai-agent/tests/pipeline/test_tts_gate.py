"""Proves the TTS gate at the orchestrator level (not just safety.validate()
in isolation): a pipeline run whose translation fails safety validation
must produce PipelineResult.audio is None, and the real TTS provider must
never even be called. Uses fake STT/LID/translation/TTS providers (no ML
models loaded) so this stays fast and deterministic — the point is
proving the *wiring* (translation -> safety -> TTS, no bypass), which
does not require real inference.

See also Step 11's repo-wide grep confirming
TranslationPipeline._translate_and_synthesize is the only production
call site of TTSProvider.synthesize(), gated by
`if safety_result.safe and translated_text.strip()`.
"""

from __future__ import annotations

import numpy as np

from app.pipeline.lid import LanguageIDProvider
from app.pipeline.orchestrator import TranslationPipeline
from app.pipeline.stt import STTProvider
from app.pipeline.tts import TTSProvider
from app.pipeline.translation import TranslationProvider
from app.pipeline.types import SynthesizedAudio, TranscriptSegment


class _FakeSTT(STTProvider):
    def __init__(self, text: str, lang: str = "en"):
        self._text = text
        self._lang = lang

    def transcribe(self, audio, sample_rate):
        return TranscriptSegment(text=self._text, language=self._lang, language_confidence=0.99)


class _FakeLID(LanguageIDProvider):
    def __init__(self, lang: str = "en"):
        self._lang = lang

    def identify(self, text):
        return self._lang, 10.0


class _FakeTranslator(TranslationProvider):
    def __init__(self, output: str):
        self._output = output

    def translate(self, text, source_lang, target_lang):
        return self._output


class _TTSCallRecorder(TTSProvider):
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text, lang):
        self.calls.append((text, lang))
        return SynthesizedAudio(samples=np.zeros(10, dtype=np.float32), sample_rate=16000)


def _build_pipeline(source_text: str, translated_text: str, lang: str = "en"):
    tts = _TTSCallRecorder()
    pipeline = TranslationPipeline(
        stt=_FakeSTT(source_text, lang),
        lid=_FakeLID(lang),
        translator=_FakeTranslator(translated_text),
        tts=tts,
    )
    return pipeline, tts


def test_unsafe_translation_never_reaches_tts():
    # "Do not take" -> "Take" is a negation flip: safety.validate() must
    # reject it, and TTSProvider.synthesize must never be called.
    pipeline, tts = _build_pipeline("Do not take this medicine.", "Take this medicine.")
    result = pipeline.process(np.zeros(160, dtype=np.float32), target_lang="en")

    assert result.blocked
    assert result.audio is None
    assert tts.calls == [], "TTS must never be invoked for a safety-rejected translation"


def test_dosage_mutation_never_reaches_tts():
    pipeline, tts = _build_pipeline("Take 10 mg twice daily.", "Take 100 mg twice daily.")
    result = pipeline.process(np.zeros(160, dtype=np.float32), target_lang="en")

    assert result.blocked
    assert result.audio is None
    assert tts.calls == []


def test_safe_translation_does_reach_tts():
    # Sanity check on the other side of the gate: a safe translation
    # must still actually reach TTS — the gate is not fail-closed to the
    # point of blocking everything.
    pipeline, tts = _build_pipeline("Take 10 mg twice daily.", "Take 10 mg twice daily.")
    result = pipeline.process(np.zeros(160, dtype=np.float32), target_lang="en")

    assert not result.blocked
    assert result.audio is not None
    assert len(tts.calls) == 1
    assert tts.calls[0] == ("Take 10 mg twice daily.", "en")


def test_process_auto_also_respects_the_gate():
    pipeline, tts = _build_pipeline("Do not take this medicine.", "Take this medicine.")
    result = pipeline.process_auto(np.zeros(160, dtype=np.float32), target_resolver=lambda src_lang: "en")

    assert result.blocked
    assert result.audio is None
    assert tts.calls == []


def test_captions_only_mode_when_tts_is_none():
    """app/pipeline/factory.py's real default (no commercially-licensed,
    CPU-feasible TTS exists — see docs/MODEL_LICENSE_MATRIX.md):
    TranslationPipeline(tts=None) must still produce a full, correct
    translation/safety result — audio is simply always None, and this is
    NOT the same thing as `blocked` (a safe translation with no TTS
    configured is not a safety rejection)."""
    pipeline = TranslationPipeline(
        stt=_FakeSTT("Take 10 mg twice daily.", "en"),
        lid=_FakeLID("en"),
        translator=_FakeTranslator("Take 10 mg twice daily."),
        tts=None,
    )
    result = pipeline.process(np.zeros(160, dtype=np.float32), target_lang="en")

    assert not result.blocked
    assert result.safety.safe is True
    assert result.translation.translated_text == "Take 10 mg twice daily."
    assert result.audio is None
    assert "tts_ms" not in result.timings_ms


def test_captions_only_mode_still_blocks_unsafe_translations():
    """The safety gate is independent of whether TTS is configured — an
    unsafe translation is still `blocked` even with tts=None, not
    silently treated as "safe, just no audio.\""""
    pipeline = TranslationPipeline(
        stt=_FakeSTT("Do not take this medicine.", "en"),
        lid=_FakeLID("en"),
        translator=_FakeTranslator("Take this medicine."),
        tts=None,
    )
    result = pipeline.process(np.zeros(160, dtype=np.float32), target_lang="en")

    assert result.blocked
    assert result.audio is None
