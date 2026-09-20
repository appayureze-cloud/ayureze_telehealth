"""Voice Activity Detection provider interface + Silero VAD implementation.

Uses onnxruntime directly against Silero's published ONNX graph rather than
the `silero-vad` PyPI package, which pulls in a full PyTorch install as a
hard dependency purely to run a 2MB model — wasteful for CPU-only
inference. See docs/ai/README.md "Known limitations" for the rationale.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import onnxruntime as ort

from .. import metrics

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "silero_vad.onnx"
FRAME_SAMPLES = 512  # Silero VAD's required chunk size at 16kHz
SAMPLE_RATE = 16000


class VADProvider(ABC):
    @abstractmethod
    def speech_probability(self, frame: np.ndarray) -> float:
        """frame: float32 mono PCM, exactly FRAME_SAMPLES samples at
        SAMPLE_RATE. Returns a 0..1 speech probability."""

    @abstractmethod
    def reset(self) -> None:
        """Resets internal recurrent state (call between unrelated audio
        streams, e.g. a new participant)."""


class SileroVAD(VADProvider):
    def __init__(self, model_path: Path | str = DEFAULT_MODEL_PATH, threshold: float = 0.5):
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.threshold = threshold
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        # Diagnostic-only: the probability this instance's most recent
        # speech_probability() call returned. Never read by production
        # code — a caller wanting to *log* what the VAD just decided
        # (e.g. streaming.py's optional AYUREZE_AUDIO_DIAG instrumentation)
        # reads this instead of calling speech_probability() a second
        # time, which would incorrectly feed the same audio chunk through
        # this stateful RNN twice and corrupt self._state.
        self.last_probability: float | None = None

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def speech_probability(self, frame: np.ndarray) -> float:
        if frame.shape[-1] != FRAME_SAMPLES:
            raise ValueError(f"expected {FRAME_SAMPLES} samples, got {frame.shape[-1]}")
        chunk = frame.astype(np.float32).reshape(1, -1)
        t0 = time.monotonic()
        out, self._state = self._session.run(None, {"input": chunk, "state": self._state, "sr": self._sr})
        metrics.PIPELINE_STAGE_LATENCY_SECONDS.labels(stage="vad").observe(time.monotonic() - t0)
        probability = float(out[0][0])
        self.last_probability = probability
        return probability

    def is_speech(self, frame: np.ndarray) -> bool:
        return self.speech_probability(frame) >= self.threshold


class TurnSegmenter:
    """Turns a stream of per-frame speech probabilities into discrete
    speech segments (turn boundaries), with hangover so brief pauses
    within a sentence don't fragment it, and a minimum-duration filter so
    single noise spikes don't trigger the pipeline.

    This is what "VAD... turn boundaries" and "silence detection" from the
    build spec map to concretely.
    """

    def __init__(
        self,
        vad: VADProvider,
        hangover_frames: int = 20,  # ~640ms at 32ms/frame (512 samples @16kHz)
        min_speech_frames: int = 5,  # ~160ms minimum to count as a real utterance
    ):
        self._vad = vad
        self._hangover_frames = hangover_frames
        self._min_speech_frames = min_speech_frames
        self._in_speech = False
        self._silence_run = 0
        self._speech_frames: list[np.ndarray] = []

    @property
    def in_speech(self) -> bool:
        """Diagnostic-only read of current turn state — never mutated by
        a reader, safe to expose."""
        return self._in_speech

    @property
    def silence_run(self) -> int:
        """Diagnostic-only read of the current trailing-silence frame
        count, for comparing against hangover_frames."""
        return self._silence_run

    def push(self, frame: np.ndarray) -> np.ndarray | None:
        """Feed one FRAME_SAMPLES-length frame. Returns a concatenated
        speech segment (float32 array) when a turn just ended, else None.
        """
        speech = self._vad.is_speech(frame)

        if speech:
            self._in_speech = True
            self._silence_run = 0
            self._speech_frames.append(frame)
            return None

        if not self._in_speech:
            return None

        # We were in speech and just saw a non-speech frame.
        self._silence_run += 1
        self._speech_frames.append(frame)  # keep trailing silence for natural TTS pacing upstream
        if self._silence_run < self._hangover_frames:
            return None

        # Hangover exceeded -> turn ended.
        segment_frames = self._speech_frames
        self._speech_frames = []
        self._in_speech = False
        self._silence_run = 0

        if len(segment_frames) < self._min_speech_frames:
            return None  # too short to be a real utterance — discard, no pipeline run

        return np.concatenate(segment_frames)
