"""REAL MODEL TEST (Silero VAD + facebook/mms-tts-eng, no mocks).

Documents a real finding from this pass's live-audio-integration root
cause investigation (see tests/test_pipeline_live_integration.py's
xfail reason and docs/ai/README.md's "Known limitations"): Silero VAD
does not reliably classify facebook/mms-tts-eng (VITS) synthesized
speech as speech, even though the audio is genuinely loud, well-formed,
and successfully transcribed by faster-whisper (see
test_pipeline_models.py, which bypasses VAD entirely by calling
pipeline.process() with pre-segmented audio).

This was verified directly, ruling out every other candidate first:
- Confirmed the raw synthesized PCM has real signal (RMS ~0.13, min/max
  spanning most of the float range) — not silence, not clipped to zero.
- Confirmed with two independent rtc.Room() connections in one process,
  both with and without E2EE, that real audio transports correctly end
  to end (RMS ~0.15-0.16 received) — ruling out LiveKit transport/E2EE.
- Confirmed with the real, unmodified app.pipeline.streaming.LiveAudioProcessor
  wired to a real LiveKit room that genuinely loud audio (RMS up to 0.34)
  arrives at _on_frame, yet Silero VAD's speech_probability for those
  exact frames never exceeds ~0.12 (threshold is 0.5).
- Confirmed the same result feeding the raw, untransmitted TTS output
  directly into SileroVAD.speech_probability() (this test) — ruling out
  any network/transport/frame-conversion cause entirely. The gap is
  intrinsic to this specific TTS engine's acoustic characteristics vs.
  what Silero VAD was trained to recognize as speech.
- Ruled out an input-scale mismatch (int16-range vs. normalized [-1,1])
  by testing both directly against the same audio with materially
  identical (low) results.
- Confirmed the ONNX model's own declared input/output signature matches
  Silero's documented public interface exactly (not a wrong/corrupted
  model file).

This is a real audio-source/model-compatibility gap, not a defect in
VAD, TurnSegmenter, STT, translation, the safety validator, or LiveKit
transport/E2EE — all of which are independently verified elsewhere
(test_pipeline_models.py, test_failure_handling.py, kdf-compat.spec.ts).
It does not weaken, bypass, or lower the threshold of the production VAD.

Run with: pytest -m models -v tests/pipeline/test_vad_tts_compatibility.py
"""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.tts import MmsTTSProvider
from app.pipeline.vad import FRAME_SAMPLES, SileroVAD

pytestmark = pytest.mark.models


def test_mms_tts_output_has_real_nonzero_signal():
    """Sanity check: the TTS output itself is genuinely loud, real audio
    — this test exists so a future failure here (rather than in the VAD
    test below) immediately points at TTS, not VAD."""
    tts = MmsTTSProvider()
    audio = tts.synthesize("Take two tablets twice daily for seven days.", "en")

    rms = float(np.sqrt(np.mean(audio.samples.astype(np.float64) ** 2)))
    assert rms > 0.05, f"expected genuinely loud synthesized speech, got rms={rms}"
    assert audio.samples.max() > 0.3
    assert audio.samples.min() < -0.3


def test_known_gap_silero_vad_does_not_reliably_detect_mms_tts_speech():
    """Documents the real, verified finding: Silero VAD's speech
    probability for facebook/mms-tts-eng output stays far below its
    0.5 threshold throughout a genuine, loud, real utterance.

    This assertion is intentionally the OPPOSITE of what a healthy
    VAD/audio-source pairing would produce — it exists to make this
    known gap visible in regular test runs (rather than silently
    tolerated) and to immediately flag, via a failure here, if a future
    change to either model changes this behavior (for better or worse).
    If this test starts failing because probabilities now cross 0.5,
    that is good news: revisit test_pipeline_live_integration.py's
    xfail marker at that point.
    """
    tts = MmsTTSProvider()
    audio = tts.synthesize("Take two tablets twice daily for seven days.", "en")

    vad = SileroVAD()
    probabilities = []
    for start in range(0, len(audio.samples) - FRAME_SAMPLES, FRAME_SAMPLES):
        frame = audio.samples[start : start + FRAME_SAMPLES]
        probabilities.append(vad.speech_probability(frame))

    assert len(probabilities) > 20, "expected a real multi-second utterance"
    assert max(probabilities) < 0.5, (
        f"Silero VAD now crosses its speech threshold on MMS-TTS output "
        f"(max={max(probabilities):.4f}) — this known gap may be resolved; "
        f"revisit test_pipeline_live_integration.py's xfail marker."
    )
