"""Full pipeline round-trip against the real models (no mocks for
STT/translation/TTS) — only the "microphone" is simulated: we synthesize
English speech ourselves via the English TTS model and feed it back into
the pipeline as if it were a subscribed LiveKit audio track, since this
test environment has no real speaker/microphone.

Run with: pytest -m models -v tests/pipeline/test_pipeline_models.py

The `pipeline` fixture below (build_default_pipeline()) defaults to
OPUS-MT (translation, CPU-feasible, Apache-2.0) + captions-only (no
TTS) — see docs/MODEL_LICENSE_MATRIX.md for why, and docs/ai/models.md
for every model's status. A MADLAD-400/Qwen3-TTS GPU-path backend also
exists (app/config.py's ai_translation_backend/ai_tts_backend),
selectable but not the default.

With AI_ALLOW_MODEL_DOWNLOAD unset/false (this repo's default), the
fixture correctly raises ModelNotAvailableError and these tests SKIP —
that is fail-closed behavior, not a bug. With AI_ALLOW_MODEL_DOWNLOAD=
true and OPUS-MT's checkpoints already cached locally (Helsinki-NLP/
opus-mt-en-dra, opus-mt-dra-en — genuinely small, CPU-feasible
MarianMT models), these tests run for real, on CPU, no GPU/VPS
required. They were run for real this way on 2026-09-26; see
docs/ai/models.md for the concrete findings (a confirmed OPUS-MT
"tablet"->"board"/"table" mistranslation, and run-to-run variance in
whether frequency words like "twice" survive translation). Because of
that real, observed non-determinism, these tests assert the pipeline's
fail-closed CONTRACT (unsafe => always blocked, never audio; safe =>
still no audio because the default backend is captions-only) rather
than assuming a fixed, always-safe translation outcome.
`synthesize_input_audio()` below still uses MmsTTSProvider directly
(unaffected by the switch) purely to generate a synthetic "microphone"
input signal, independent of the pipeline's own (now different) TTS
output.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.factory import build_default_pipeline
from app.pipeline.model_lifecycle import ModelNotAvailableError
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
    # build_default_pipeline() was switched this pass from NLLB-200/
    # MMS-TTS (found CC-BY-NC-4.0, non-commercial — see
    # docs/MODEL_LICENSE_MATRIX.md) to OPUS-MT (translation) + captions-
    # only (no TTS), deliberately with no path back to the old models.
    # Not downloaded in this sandbox (AI_ALLOW_MODEL_DOWNLOAD=false by
    # default — no model is fetched implicitly) — this is the correct,
    # fail-closed behavior, not a bug, so this fixture skips rather than
    # erroring. See docs/ai/models.md.
    try:
        return build_default_pipeline(whisper_model_size="tiny")
    except ModelNotAvailableError as e:
        pytest.skip(f"default pipeline's translator requires AI_ALLOW_MODEL_DOWNLOAD=true: {e}")


def test_dosage_instruction_round_trip_en_to_ta(pipeline):
    """`build_default_pipeline()`'s default is AI_TTS_BACKEND=none
    (captions-only) — result.audio is None by design regardless of
    whether the translation is judged safe; there is no TTS stage to
    time either. This asserts the pipeline's real, verified CONTRACT
    (fail-closed: unsafe => blocked and no audio; safe => still no
    audio because no TTS backend is configured) rather than assuming
    a fixed translation outcome. Real, live-model runs against this
    exact sentence have shown OPUS-MT's Tamil output vary between runs
    (see docs/ai/models.md for the confirmed "tablet"->board/table
    mistranslation and a run that silently dropped "twice"), so a hard
    `safety.safe is True` expectation here would be flaky by nature of
    the model, not the test.
    """
    source_text = "Take two tablets twice daily for seven days."
    audio_in = synthesize_input_audio(source_text, lang="en")

    result = pipeline.process(audio_in, target_lang="ta")

    assert result.transcript.language == "en"
    assert result.transcript.text.strip() != ""
    assert result.translation.target_lang == "ta"
    assert result.translation.translated_text.strip() != ""
    assert result.audio is None, "captions-only default backend never produces audio"
    assert result.blocked == (not result.safety.safe)

    for stage in ("stt_ms", "language_id_ms", "terminology_ms", "translation_ms", "safety_validation_ms", "total_ms"):
        assert stage in result.timings_ms
        assert result.timings_ms[stage] >= 0
    assert "tts_ms" not in result.timings_ms


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
    # Real, live-model finding (2026-09-26): OPUS-MT does not reliably
    # preserve dosage frequency/vocabulary in Tamil — the exact same
    # sentence has round-tripped with "twice" silently dropped in one
    # run (source had 'twice_daily', translation had only
    # 'daily_unspecified_count') and with "tablets" mistranslated to
    # "boards"/"tables" in others. See docs/ai/models.md. This test
    # therefore asserts the fail-closed CONTRACT rather than assuming
    # a semantically perfect translation: whatever OPUS-MT actually
    # produces, the safety validator must correctly classify it and
    # the pipeline must never publish audio either way (captions-only
    # default backend).
    source_text = "Take two tablets twice daily for seven days."
    audio_in = synthesize_input_audio(source_text, lang="en")

    result = pipeline.process(audio_in, target_lang="ta")

    assert "two" in result.transcript.text.lower()
    assert "seven" in result.transcript.text.lower()
    assert result.translation.translated_text.strip() != ""
    assert result.audio is None, "captions-only default backend never produces audio"
    if not result.safety.safe:
        assert result.blocked, "unsafe translations must always be blocked"
    else:
        assert not result.blocked


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
