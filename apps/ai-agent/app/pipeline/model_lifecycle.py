"""Shared model-lifecycle contract for every AI model provider in the
streaming pipeline (STT/translation/TTS): load() (may be slow — downloads
or loads weights into memory/GPU), warmup() (a throwaway inference so the
FIRST real request isn't penalized by lazy kernel/JIT initialization),
health(), and shutdown(). Each stage-specific interface (StreamingSTTProvider
in stt.py, TranslationProvider in translation.py, TTSProvider in tts.py)
adds its own infer()-shaped abstract method on top of this.

Model load time must never be counted as inference latency (build spec
section 17) — callers time load()/warmup() and infer() separately; see
benchmark.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ModelNotAvailableError(RuntimeError):
    """Raised by load() when a provider's weights/runtime aren't
    available in the current environment — e.g. a GPU-only model in a
    CPU-only sandbox, or a checkpoint that AI_ALLOW_MODEL_DOWNLOAD=false
    (the default) refuses to fetch. Callers (routers) MUST treat this as
    "this provider is unavailable, use the next configured fallback or
    fail closed" — never as a reason to synthesize a plaintext/mocked
    result. See translation_router.py / tts_router.py."""


@dataclass
class ModelHealth:
    healthy: bool
    loaded: bool
    detail: str = ""


@dataclass
class ModelMetadata:
    """Everything docs/MODEL_LICENSE_MATRIX.md's columns need, held
    alongside the code so the two can never silently drift apart."""

    provider_id: str
    checkpoint: str
    version: str
    code_license: str
    weights_license: str
    commercial_use: bool
    redistribution: bool
    attribution_required: bool
    source_url: str
    verified_date: str  # YYYY-MM-DD this metadata was last checked against the live model card
    certified: bool = False
    notes: str = ""


class ModelLifecycle(ABC):
    """Every concrete model provider implements this alongside its
    narrower stage-specific interface (StreamingSTTProvider/
    TranslationProvider/TTSProvider)."""

    def __init__(self) -> None:
        self._loaded = False
        self._load_seconds: float | None = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def load_seconds(self) -> float | None:
        """Recorded once by load(); see benchmark.py's "load time must
        NOT be included in inference latency" requirement."""
        return self._load_seconds

    @abstractmethod
    def load(self) -> None:
        """Loads weights/resources. Idempotent — a second call is a
        no-op. Must not be called on the asyncio event loop thread for a
        real model (this can take seconds to minutes)."""

    def warmup(self) -> None:
        """Default no-op; override to run one throwaway inference. Must
        only be called after load()."""

    @abstractmethod
    def health(self) -> ModelHealth: ...

    @abstractmethod
    def metadata(self) -> ModelMetadata: ...

    def shutdown(self) -> None:
        """Default no-op; override to release GPU memory/file handles."""
