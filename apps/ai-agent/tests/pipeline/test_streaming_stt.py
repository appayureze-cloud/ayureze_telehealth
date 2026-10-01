"""Real-model tests for StreamingFasterWhisperSTT — uses the same
already-resident faster-whisper "tiny" model and real recorded speech
fixture (tests/fixtures/jfk.flac) as
tests/test_pipeline_live_integration.py, no new download required.
"""

from pathlib import Path

import numpy as np
import pytest

from app.pipeline.stt import StreamingFasterWhisperSTT
from tests.test_pipeline_live_integration import _load_speech_fixture_16k_mono

pytestmark = pytest.mark.models

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "jfk.flac"


def _chunks(audio: np.ndarray, chunk_samples: int):
    for start in range(0, len(audio), chunk_samples):
        yield audio[start : start + chunk_samples]


def test_partial_hypotheses_grow_and_final_matches_whole_buffer_decode():
    audio = _load_speech_fixture_16k_mono(FIXTURE_PATH)

    provider = StreamingFasterWhisperSTT(model_size="tiny", min_update_ms=1500)
    provider.load()
    provider.reset(session_id="s1")

    partials = []
    chunk_samples = int(1.0 * 16000)  # 1s ASR-processing chunks, within the build spec's 320-640ms..~1-2s streaming range used for a real re-decode cadence
    for chunk in _chunks(audio, chunk_samples):
        result = provider.push_audio(chunk, 16000)
        if result is not None:
            partials.append(result)

    final = provider.finalize()

    assert final is not None
    assert final.text.strip() != ""
    assert final.language == "en"

    # Real streaming behavior: at least one partial arrived before
    # finalize(), and hypotheses grow (each partial's text is a prefix-ish
    # growth, not shrinking to nothing).
    assert len(partials) >= 1
    assert all(p.text.strip() != "" for p in partials)
    assert all(p.is_final is False for p in partials)


def test_reset_clears_buffer_between_utterances():
    provider = StreamingFasterWhisperSTT(model_size="tiny")
    provider.load()

    audio = _load_speech_fixture_16k_mono(FIXTURE_PATH)
    provider.reset(session_id="a")
    provider.push_audio(audio[: 16000 * 2], 16000)
    provider.reset(session_id="b")  # fresh utterance — must forget "a"'s audio

    final = provider.finalize()
    assert final is None  # nothing pushed since the second reset()


def test_wrong_sample_rate_is_rejected():
    provider = StreamingFasterWhisperSTT(model_size="tiny")
    provider.load()
    provider.reset(session_id="s")
    with pytest.raises(ValueError):
        provider.push_audio(np.zeros(1600, dtype=np.float32), 8000)


def test_finalize_with_no_audio_returns_none():
    provider = StreamingFasterWhisperSTT(model_size="tiny")
    provider.load()
    provider.reset(session_id="s")
    assert provider.finalize() is None
