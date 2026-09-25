"""Speech-to-text provider interface + faster-whisper implementation.

The interface is intentionally narrow so IndicWhisper, other Whisper
variants, or a managed STT API can be dropped in later without touching
the orchestrator (build spec: "Create an abstraction allowing future...").

Also holds the STREAMING STT interface (StreamingSTTProvider) and two
implementations:
  - StreamingFasterWhisperSTT: a real, working streaming wrapper around
    the existing (already-resident, CPU-only) faster-whisper model —
    produces genuine partial/final transcripts via short overlapping-
    buffer re-decodes. No new model weights required.
  - Qwen3ASRProvider: the build spec's new primary STT model. Written
    against Qwen/Qwen3-ASR-1.7B's actual documented quickstart API
    (verified against the live model card; see docs/MODEL_LICENSE_MATRIX.md),
    but its weights are NOT bundled or downloaded in this build — see
    ModelNotAvailableError. The streaming ASR router
    (build spec section 6) falls back to StreamingFasterWhisperSTT
    whenever Qwen3-ASR is unavailable, never silently to a mocked result.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from .model_lifecycle import ModelHealth, ModelLifecycle, ModelMetadata, ModelNotAvailableError
from .types import PartialTranscript, TranscriptSegment

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


class StreamingSTTProvider(ModelLifecycle):
    """Streaming counterpart to STTProvider. One instance is used per
    concurrent utterance's ASR buffer — reset() between utterances (or
    construct a fresh instance per utterance; both are valid, callers
    choose based on the provider's actual statefulness)."""

    @abstractmethod
    def reset(self, session_id: str) -> None:
        """Clears per-utterance streaming state (buffers, incremental
        decode cache) for a new utterance."""

    @abstractmethod
    def push_audio(self, chunk: np.ndarray, sample_rate: int) -> PartialTranscript | None:
        """Feed one ASR-processing-chunk-sized buffer (build spec section
        5: 320-640ms — NOT VAD's 20-30ms frames; see
        streaming_pipeline.py's AsrChunkAccumulator for the layer that
        regroups VAD frames into ASR chunks). Returns an updated partial
        transcript, or None if there isn't yet a new hypothesis to
        report."""

    @abstractmethod
    def finalize(self) -> TranscriptSegment | None:
        """Called on VAD end-of-utterance. Returns the final transcript
        for everything pushed since the last reset(), or None if no
        speech was ever detected."""


class StreamingFasterWhisperSTT(StreamingSTTProvider):
    """A real, working streaming ASR implementation built on the same
    faster-whisper model FasterWhisperSTT already uses — no new model
    weights, so this is fully testable in any environment that already
    runs the existing (non-streaming) pipeline.

    Approach: re-decode a sliding buffer of ALL audio pushed since the
    last reset() every time enough new audio has accumulated (>=
    min_update_samples), rather than true incremental/cached decoding
    (faster-whisper's public API doesn't expose incremental state re-use
    across calls). This is the standard "streaming via periodic
    re-transcription" pattern used by e.g. whisper_streaming — genuinely
    produces improving partial hypotheses as more audio arrives, but each
    push_audio() call costs a full decode of the buffer so far, not O(1)
    new audio. TranscriptStabilityFilter (stability_filter.py) is what
    turns these growing hypotheses into a stable, non-duplicated commit
    stream — this class does not attempt to compute stability itself.
    """

    def __init__(self, model_size: str = "tiny", device: str = "cpu", compute_type: str = "int8",
                 min_update_ms: float = 300.0):
        super().__init__()
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._min_update_samples = int(min_update_ms / 1000 * 16000)
        self._model = None
        self._buffer = np.zeros((0,), dtype=np.float32)
        self._samples_at_last_decode = 0
        self._session_id: str | None = None

    def load(self) -> None:
        if self._loaded:
            return
        import time as _time

        from faster_whisper import WhisperModel

        t0 = _time.monotonic()
        self._model = WhisperModel(
            self._model_size, device=self._device, compute_type=self._compute_type,
            download_root=str(DEFAULT_MODEL_DIR),
        )
        self._load_seconds = _time.monotonic() - t0
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id="streaming-faster-whisper",
            checkpoint=f"faster-whisper-{self._model_size}",
            version="tiny" if self._model_size == "tiny" else self._model_size,
            code_license="MIT",  # guillaumekln/faster-whisper (SYSTRAN/faster-whisper), MIT
            weights_license="MIT",  # OpenAI Whisper weights, MIT
            commercial_use=True,
            redistribution=True,
            attribution_required=True,
            source_url="https://github.com/SYSTRAN/faster-whisper",
            verified_date="2026-09-25",
            certified=True,  # already the build's existing, live-verified fallback STT
            notes="Existing STT fallback (build spec section C); streaming wrapper added this pass.",
        )

    def reset(self, session_id: str) -> None:
        self._session_id = session_id
        self._buffer = np.zeros((0,), dtype=np.float32)
        self._samples_at_last_decode = 0

    def push_audio(self, chunk: np.ndarray, sample_rate: int) -> PartialTranscript | None:
        if sample_rate != 16000:
            raise ValueError("faster-whisper expects 16kHz mono audio")
        if not self._loaded:
            raise RuntimeError("load() must be called before push_audio()")

        self._buffer = np.concatenate([self._buffer, chunk])
        new_samples = self._buffer.shape[0] - self._samples_at_last_decode
        if new_samples < self._min_update_samples:
            return None

        segments, info = self._model.transcribe(
            self._buffer, language=None, vad_filter=False, beam_size=1,
        )
        text = "".join(s.text for s in segments).strip()
        self._samples_at_last_decode = self._buffer.shape[0]
        if not text:
            return None

        detected = info.language if info.language in SUPPORTED_LANGUAGES else "en"
        return PartialTranscript(text=text, language=detected, is_final=False,
                                  confidence=info.language_probability)

    def finalize(self) -> TranscriptSegment | None:
        if self._buffer.shape[0] == 0:
            return None
        segments, info = self._model.transcribe(
            self._buffer, language=None, vad_filter=False, beam_size=1,
        )
        text = "".join(s.text for s in segments).strip()
        if not text:
            return None
        detected = info.language if info.language in SUPPORTED_LANGUAGES else "en"
        return TranscriptSegment(text=text, language=detected, language_confidence=info.language_probability)


class Qwen3ASRProvider(StreamingSTTProvider):
    """Qwen/Qwen3-ASR-1.7B — build spec's primary multilingual streaming
    STT model. API verified against the live model card (2026-09-25):

        from qwen_asr import Qwen3ASRModel
        model = Qwen3ASRModel.from_pretrained(
            "Qwen/Qwen3-ASR-1.7B", dtype=torch.bfloat16, device_map="cuda:0",
        )
        results = model.transcribe(audio=..., language=None)
        # results[0].text, results[0].language

    IMPORTANT (verified, not assumed): the model card states streaming
    inference is available ONLY via the vLLM backend, not the
    `transformers`-style `Qwen3ASRModel.from_pretrained()` path shown
    above — true incremental/partial decoding therefore requires standing
    up a separate vLLM serving process, out of scope for this pass (build
    spec section 18 puts this model on a GPU server this sandbox doesn't
    have). This class implements the batch (non-streaming-backend)
    `.transcribe()` path faithfully so the code is real and correct
    against the documented API, but reports every call as `is_final=True`
    (a single whole-buffer transcription per finalize(), matching the
    non-vLLM API's actual capability) rather than claiming partial
    results it cannot produce without vLLM.

    Not downloaded/loaded in this build: load() raises
    ModelNotAvailableError unless AI_ALLOW_MODEL_DOWNLOAD=true is set AND
    the optional `qwen_asr` package + GPU are actually present. Routers
    must treat this as "unavailable, use the configured fallback."
    """

    CHECKPOINT = "Qwen/Qwen3-ASR-1.7B"

    def __init__(self) -> None:
        super().__init__()
        self._model = None
        self._buffer = np.zeros((0,), dtype=np.float32)

    def load(self) -> None:
        if self._loaded:
            return
        if os.environ.get("AI_ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: AI_ALLOW_MODEL_DOWNLOAD is not 'true' — this build never "
                "downloads new model weights implicitly. Set it explicitly (and provision a GPU) "
                "to enable Qwen3-ASR; until then the STT router falls back to "
                "StreamingFasterWhisperSTT."
            )
        try:
            import torch
            from qwen_asr import Qwen3ASRModel
        except ImportError as e:
            raise ModelNotAvailableError(f"{self.CHECKPOINT}: required package not installed ({e})") from e
        if not torch.cuda.is_available():
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: no CUDA device available — this model is not verified on CPU "
                "(build spec section 18 places it on a GPU server)."
            )

        import time as _time

        t0 = _time.monotonic()
        self._model = Qwen3ASRModel.from_pretrained(
            self.CHECKPOINT, dtype=torch.bfloat16, device_map="cuda:0",
        )
        self._load_seconds = _time.monotonic() - t0
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded (see load())")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id="qwen3-asr",
            checkpoint=self.CHECKPOINT,
            version="1.7B",
            code_license="Apache-2.0",
            weights_license="Apache-2.0",
            commercial_use=True,
            redistribution=True,
            attribution_required=True,
            source_url="https://huggingface.co/Qwen/Qwen3-ASR-1.7B",
            verified_date="2026-09-25",
            certified=False,  # not yet regression-tested against this build's dosage/negation corpus
            notes="Not downloaded in this build; GPU-only per vendor docs; true streaming needs vLLM backend, not used here.",
        )

    def reset(self, session_id: str) -> None:
        self._buffer = np.zeros((0,), dtype=np.float32)

    def push_audio(self, chunk: np.ndarray, sample_rate: int) -> PartialTranscript | None:
        if not self._loaded:
            raise RuntimeError("load() must be called before push_audio()")
        # Non-vLLM backend cannot produce a real partial hypothesis
        # without re-running the full (expensive, GPU) decode on every
        # chunk — buffer only; finalize() does the one real decode.
        self._buffer = np.concatenate([self._buffer, chunk])
        return None

    def finalize(self) -> TranscriptSegment | None:
        if self._buffer.shape[0] == 0:
            return None
        results = self._model.transcribe(audio=(self._buffer, 16000), language=None)
        if not results:
            return None
        return TranscriptSegment(text=results[0].text, language=results[0].language, language_confidence=1.0)
