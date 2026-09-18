"""Speech-to-text provider interface + faster-whisper implementation.

The interface is intentionally narrow so IndicWhisper, other Whisper
variants, or a managed STT API can be dropped in later without touching
the orchestrator (build spec: "Create an abstraction allowing future...").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from .types import TranscriptSegment

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "whisper"

# Restricting the candidate set to what this build actually supports
# (English, Tamil, Malayalam — build spec section 5 "Language Detection")
# measurably improves faster-whisper's language-ID accuracy on short
# clinical utterances versus letting it guess across all 99 Whisper
# languages.
SUPPORTED_LANGUAGES = ("en", "ta", "ml")


class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptSegment: ...


class FasterWhisperSTT(STTProvider):
    def __init__(self, model_size: str = "tiny", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import (
            WhisperModel,  # local import: keep this heavy dep optional
        )

        self._model = WhisperModel(
            model_size, device=device, compute_type=compute_type, download_root=str(DEFAULT_MODEL_DIR)
        )

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptSegment:
        if sample_rate != 16000:
            raise ValueError("faster-whisper expects 16kHz mono audio")

        segments, info = self._model.transcribe(
            audio,
            language=None,  # auto-detect, then restricted below
            vad_filter=False,  # VAD segmentation already done upstream (pipeline/vad.py)
            beam_size=1,  # favor latency over marginal accuracy for a real-time agent
        )
        text = "".join(s.text for s in segments).strip()

        detected = info.language if info.language in SUPPORTED_LANGUAGES else "en"
        return TranscriptSegment(text=text, language=detected, language_confidence=info.language_probability)
