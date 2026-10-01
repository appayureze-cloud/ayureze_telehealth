"""REAL MODEL TEST (Silero VAD + facebook/mms-tts-eng, no mocks).

CORRECTED this pass. A prior version of this file concluded "Silero VAD
does not reliably classify MMS-TTS synthesized speech as speech" and
pinned that as an accepted gap. That conclusion was wrong: further
investigation (root-causing why a real recorded human speech sample —
tests/fixtures/jfk.flac — ALSO failed to cross the VAD threshold, which
should never happen for genuine continuous speech) found the real bug:
app/pipeline/vad.py's SileroVAD was missing the 64-sample "context"
buffer Silero's own official calling convention requires (confirmed
against snakers4/silero-vad's utils_vad.py OnnxWrapper.__call__, and
against this exact bundled model file by SHA-256 match to their current
release) — every streaming call must prepend the trailing 64 samples of
the PREVIOUS chunk before calling the model, or its internal conv/LSTM
layers receive an incomplete receptive field and return near-zero
probability regardless of real audio content. This affected ALL audio,
TTS and real speech alike, uniformly — it was never actually a TTS
acoustic-compatibility issue.

With the context buffer now added, both a real recorded speech sample
and MMS-TTS output are correctly detected: sustained ~0.95-1.0
probability during actual speech, near-zero during real pauses, exactly
the trace a healthy VAD/audio-source pairing should produce.

Run with: pytest -m models -v tests/pipeline/test_vad_tts_compatibility.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.pipeline.tts import MmsTTSProvider
from app.pipeline.vad import FRAME_SAMPLES, SileroVAD

pytestmark = pytest.mark.models

_JFK_FIXTURE = Path(__file__).parents[1] / "fixtures" / "jfk.flac"


def _load_fixture_16k_mono(path: Path) -> np.ndarray:
    import av

    container = av.open(str(path))
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    frames = []
    for frame in container.decode(audio=0):
        for rframe in resampler.resample(frame):
            frames.append(rframe.to_ndarray())
    container.close()
    pcm16 = np.concatenate(frames, axis=1).flatten()
    return pcm16.astype(np.float32) / 32768.0


def test_mms_tts_output_has_real_nonzero_signal():
    """Sanity check: the TTS output itself is genuinely loud, real audio
    — this test exists so a future failure here (rather than in the VAD
    tests below) immediately points at TTS, not VAD."""
    tts = MmsTTSProvider()
    audio = tts.synthesize("Take two tablets twice daily for seven days.", "en")

    rms = float(np.sqrt(np.mean(audio.samples.astype(np.float64) ** 2)))
    assert rms > 0.05, f"expected genuinely loud synthesized speech, got rms={rms}"
    assert audio.samples.max() > 0.3
    assert audio.samples.min() < -0.3


def test_silero_vad_correctly_detects_mms_tts_speech():
    """Regression for the fixed context-buffer bug: MMS-TTS output must
    now cross the speech threshold for the large majority of its
    duration (a continuous ~4s medical instruction sentence)."""
    tts = MmsTTSProvider()
    audio = tts.synthesize("Take two tablets twice daily for seven days.", "en")

    vad = SileroVAD()
    probabilities = [
        vad.speech_probability(audio.samples[start : start + FRAME_SAMPLES])
        for start in range(0, len(audio.samples) - FRAME_SAMPLES, FRAME_SAMPLES)
    ]

    assert len(probabilities) > 20, "expected a real multi-second utterance"
    above_threshold = sum(1 for p in probabilities if p >= vad.threshold)
    assert above_threshold / len(probabilities) > 0.5, (
        f"expected the majority of frames in a continuous spoken sentence to cross "
        f"the speech threshold; got {above_threshold}/{len(probabilities)} "
        f"(max={max(probabilities):.4f}) — the context-buffer fix may have regressed"
    )


def test_silero_vad_correctly_detects_real_recorded_speech():
    """The decisive real-speech check: a genuine, non-synthetic
    recording (see tests/fixtures/README.md) must show a sensible,
    sustained speech/pause pattern, not just occasional spikes."""
    audio = _load_fixture_16k_mono(_JFK_FIXTURE)

    vad = SileroVAD()
    probabilities = [
        vad.speech_probability(audio[start : start + FRAME_SAMPLES])
        for start in range(0, len(audio) - FRAME_SAMPLES, FRAME_SAMPLES)
    ]

    assert len(probabilities) > 100, "expected a real multi-second recording"
    above_threshold = sum(1 for p in probabilities if p >= vad.threshold)
    # This ~11s clip is mostly continuous speech with a few natural pauses
    # — real measured value at fix time was 68%; guard against regression
    # with a conservative floor.
    assert above_threshold / len(probabilities) > 0.4, (
        f"expected most of a continuous real-speech recording to cross the "
        f"speech threshold; got {above_threshold}/{len(probabilities)} "
        f"(max={max(probabilities):.4f})"
    )


def test_silero_vad_context_buffer_matters():
    """Directly demonstrates why the context buffer is required: the
    SAME real speech audio, fed through the model WITHOUT prepending
    context (the pre-fix behavior), must NOT reliably cross the
    threshold — proving the fix's mechanism, not just its symptom."""
    import onnxruntime as ort

    from app.pipeline.vad import DEFAULT_MODEL_PATH, SAMPLE_RATE

    audio = _load_fixture_16k_mono(_JFK_FIXTURE)
    session = ort.InferenceSession(str(DEFAULT_MODEL_PATH), providers=["CPUExecutionProvider"])
    sr = np.array(SAMPLE_RATE, dtype=np.int64)

    state = np.zeros((2, 1, 128), dtype=np.float32)
    probabilities_without_context = []
    for start in range(0, len(audio) - FRAME_SAMPLES, FRAME_SAMPLES):
        chunk = audio[start : start + FRAME_SAMPLES].astype(np.float32).reshape(1, -1)
        out, state = session.run(None, {"input": chunk, "state": state, "sr": sr})
        probabilities_without_context.append(float(out[0][0]))

    above_threshold = sum(1 for p in probabilities_without_context if p >= 0.5)
    assert above_threshold / len(probabilities_without_context) < 0.1, (
        "expected the pre-fix (no-context) calling convention to fail to detect "
        "real continuous speech reliably — if this now passes, the ONNX model "
        "itself may have changed behavior"
    )
