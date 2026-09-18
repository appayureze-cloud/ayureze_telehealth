"""Full pipeline round-trip against the real models (no mocks for
STT/translation/TTS) — only the "microphone" is simulated: we synthesize
English speech ourselves via the English TTS model and feed it back into
the pipeline as if it were a subscribed LiveKit audio track, since this
test environment has no real speaker/microphone.

Run with: pytest -m models -v tests/pipeline/test_pipeline_models.py
(downloads ~2.5GB of model weights on first run — see requirements-pipeline.txt)
"""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.factory import build_default_pipeline
from app.pipeline.orchestrator import SAMPLE_RATE
from app.pipeline.tts import MmsTTSProvider

pytestmark = pytest.mark.models


def synthesize_input_audio(text: str, lang: str = "en") -> np.ndarray:
    """Stands in for a real microphone: produces real speech audio via
    TTS, resampled to the pipeline's expected 16kHz."""
    tts = MmsTTSProvider()
    audio = tts.synthesize(text, lang)
    if audio.sample_rate == SAMPLE_RATE:
        return audio.samples
    # Simple linear resample — good enough for feeding STT in a test;
    # production audio comes pre-resampled from LiveKit (see agent.py).
    duration = len(audio.samples) / audio.sample_rate
    target_len = int(duration * SAMPLE_RATE)
    x_old = np.linspace(0, 1, len(audio.samples))
    x_new = np.linspace(0, 1, target_len)
    return np.interp(x_new, x_old, audio.samples).astype(np.float32)


@pytest.fixture(scope="module")
def pipeline():
    return build_default_pipeline(whisper_model_size="tiny")


def test_dosage_instruction_round_trip_en_to_ta(pipeline):
    source_text = "Take two tablets twice daily for seven days."
    audio_in = synthesize_input_audio(source_text, lang="en")

    result = pipeline.process(audio_in, target_lang="ta")

    assert result.transcript.language == "en"
    assert result.transcript.text.strip() != ""
    assert result.translation.target_lang == "ta"
    assert result.translation.translated_text.strip() != ""
    assert result.audio is not None, f"expected published audio; safety={result.safety}"
    assert result.audio.samples.size > 0
    assert result.audio.sample_rate > 0

    for stage in ("stt_ms", "language_id_ms", "terminology_ms", "translation_ms", "safety_validation_ms", "tts_ms", "total_ms"):
        assert stage in result.timings_ms
        assert result.timings_ms[stage] >= 0


def test_numeric_dosage_is_preserved_end_to_end(pipeline):
    # Digit-form input ("2", "7") deliberately avoided here: MMS-TTS (the
    # TTS model standing in for a "microphone" in this test) has no
    # number-normalization front-end and mispronounces bare digits badly
    # enough that Whisper mis-transcribes them — a real, observed
    # limitation of that specific TTS model, documented in
    # docs/ai/README.md, and orthogonal to what this test is actually
    # checking (translation-stage digit preservation, once digits *are*
    # correctly in the transcript). Spelled-out numbers round-trip
    # correctly through TTS -> STT, which is what a doctor speaking
    # naturally ("take two tablets") would produce anyway; see
    # test_safety.py for direct digit-preservation checks against
    # controlled digit-containing text, independent of any TTS quirk.
    source_text = "Take two tablets twice daily for seven days."
    audio_in = synthesize_input_audio(source_text, lang="en")

    result = pipeline.process(audio_in, target_lang="ta")

    assert "two" in result.transcript.text.lower()
    assert "seven" in result.transcript.text.lower()
    assert result.safety.safe, f"expected safe translation, got reasons={result.safety.reasons}"
    assert result.translation.translated_text.strip() != ""


def test_safety_validator_blocks_a_corrupted_translation(pipeline, monkeypatch):
    """Injects a translator that drops a number, proving the orchestrator
    actually refuses to publish rather than merely logging a warning —
    build spec: "DO NOT automatically publish unsafe output."
    """

    class CorruptingTranslator:
        def translate(self, text, source_lang, target_lang):
            # Simulates a translation that silently drops "7 days".
            return "2 tablets twice daily"

    monkeypatch.setattr(pipeline, "_translator", CorruptingTranslator())

    source_text = "Take 2 tablets twice daily for 7 days."
    audio_in = synthesize_input_audio(source_text, lang="en")
    result = pipeline.process(audio_in, target_lang="ta")

    assert not result.safety.safe
    assert result.audio is None, "unsafe translation must never be published as audio"
    assert result.blocked
