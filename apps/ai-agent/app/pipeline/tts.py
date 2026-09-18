"""Text-to-speech provider interface + MMS-TTS (VITS) implementation.

facebook/mms-tts-<lang> models are used as the initial open-source,
self-hostable TTS backend (build spec: "Initial implementation may use a
suitable open-source or managed TTS engine depending on latency and
language quality"). Swapping to a different engine is a new class behind
this same interface, not a redesign.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from .types import SynthesizedAudio

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "models" / "hf"

_LANG_TO_MMS_MODEL = {
    "en": "facebook/mms-tts-eng",
    "ta": "facebook/mms-tts-tam",
    "ml": "facebook/mms-tts-mal",
}


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, lang: str) -> SynthesizedAudio: ...


class MmsTTSProvider(TTSProvider):
    """Lazily loads one VITS model per language on first use (each is
    ~150-200MB; loading all three upfront would waste memory for a session
    that only ever needs one direction)."""

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR):
        self._cache_dir = str(cache_dir)
        self._models: dict[str, object] = {}
        self._tokenizers: dict[str, object] = {}

    def _load(self, lang: str):
        if lang in self._models:
            return self._models[lang], self._tokenizers[lang]
        if lang not in _LANG_TO_MMS_MODEL:
            raise ValueError(f"no TTS model configured for language {lang!r}")

        from transformers import (  # local import: heavy optional dep
            AutoTokenizer,
            VitsModel,
        )

        model_id = _LANG_TO_MMS_MODEL[lang]
        model = VitsModel.from_pretrained(model_id, cache_dir=self._cache_dir)
        tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=self._cache_dir)
        self._models[lang] = model
        self._tokenizers[lang] = tokenizer
        return model, tokenizer

    def synthesize(self, text: str, lang: str) -> SynthesizedAudio:
        import torch

        model, tokenizer = self._load(lang)
        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = model(**inputs).waveform
        samples = waveform.squeeze().cpu().numpy().astype(np.float32)
        return SynthesizedAudio(samples=samples, sample_rate=model.config.sampling_rate)
