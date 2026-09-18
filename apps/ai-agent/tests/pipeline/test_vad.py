import numpy as np
import pytest

from app.pipeline.vad import FRAME_SAMPLES, SileroVAD, TurnSegmenter


@pytest.fixture(scope="module")
def vad():
    return SileroVAD()


def silence_frame() -> np.ndarray:
    return np.zeros(FRAME_SAMPLES, dtype=np.float32)


def tone_frame(freq: float = 440.0, sr: int = 16000) -> np.ndarray:
    t = np.arange(FRAME_SAMPLES) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_silence_has_low_speech_probability(vad):
    vad.reset()
    prob = vad.speech_probability(silence_frame())
    assert 0.0 <= prob < 0.3


def test_rejects_wrong_frame_size(vad):
    with pytest.raises(ValueError):
        vad.speech_probability(np.zeros(256, dtype=np.float32))


def test_turn_segmenter_ignores_pure_silence():
    vad = SileroVAD()
    segmenter = TurnSegmenter(vad, hangover_frames=3, min_speech_frames=2)
    for _ in range(50):
        assert segmenter.push(silence_frame()) is None


def test_turn_segmenter_discards_speech_shorter_than_minimum(monkeypatch):
    vad = SileroVAD()

    calls = {"n": 0}

    def fake_is_speech(frame):
        calls["n"] += 1
        return calls["n"] <= 1  # exactly one "speech" frame, then silence

    monkeypatch.setattr(vad, "is_speech", fake_is_speech)
    segmenter = TurnSegmenter(vad, hangover_frames=2, min_speech_frames=5)

    result = None
    for _ in range(10):
        r = segmenter.push(silence_frame())
        if r is not None:
            result = r
    assert result is None  # too short (1 frame) to count as an utterance


def test_turn_segmenter_emits_segment_after_hangover(monkeypatch):
    vad = SileroVAD()
    frame_sequence = [True] * 6 + [False] * 5  # 6 speech frames, then silence
    calls = {"i": -1}

    def fake_is_speech(frame):
        calls["i"] += 1
        return frame_sequence[calls["i"]] if calls["i"] < len(frame_sequence) else False

    monkeypatch.setattr(vad, "is_speech", fake_is_speech)
    segmenter = TurnSegmenter(vad, hangover_frames=3, min_speech_frames=3)

    emitted = None
    for _ in range(len(frame_sequence)):
        r = segmenter.push(silence_frame())
        if r is not None:
            emitted = r
    assert emitted is not None
    assert emitted.shape[0] == FRAME_SAMPLES * 9  # 6 speech + 3 hangover frames
