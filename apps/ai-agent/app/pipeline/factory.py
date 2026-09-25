"""Builds the default (real-model) pipeline. Kept as one place so
apps/ai-agent/app/agent.py and tests both construct the identical provider
set — swapping any provider means changing this function, not every call
site.

Translation and TTS backends are DEPLOY-TIME SELECTABLE (app/config.py's
ai_translation_backend/ai_tts_backend), not hardcoded — neither backend is
removed from the codebase by choosing the other:

- translation_backend="opus-mt" (default): Helsinki-NLP/opus-mt-en-dra
  (English -> Dravidian languages incl. Tamil, needs a `>>tam<<`-style
  target tag — see OPUSMTProvider's docstring) for en->ta, and
  opus-mt-dra-en (many-to-one, no tag needed) for ta->en. Both
  Apache-2.0, verified 2026-09-25, and — unlike MADLAD-400's 3B
  parameters — small enough for real CPU inference. This is what actually
  runs on a CPU-only VPS deployment today.
- translation_backend="madlad": MADLAD-400 3B (Apache-2.0, GPU-only per
  its own docs). Select this once real GPU infrastructure exists.

- tts_backend="none" (default): CAPTIONS-ONLY (TranslationPipeline(tts=
  None) — see orchestrator.py). No TTS model currently has both a
  verified commercial license AND CPU feasibility — see
  docs/MODEL_LICENSE_MATRIX.md.
- tts_backend="qwen3-tts": Qwen3-TTS (Apache-2.0, GPU-only, also needs a
  reference voice clip per language — ai_tts_reference_audio_path/
  ai_tts_reference_text in app/config.py).

Both MADLAD-400 and Qwen3-TTS are NOT downloaded unless
AI_ALLOW_MODEL_DOWNLOAD=true AND a real GPU is present — selecting them
without that infrastructure raises ModelNotAvailableError, same as before
this function became selectable.
"""

from __future__ import annotations

from .lid import LangidProvider
from .orchestrator import TranslationPipeline
from .stt import FasterWhisperSTT
from .translation import MADLADProvider, OPUSMTProvider, TranslationProvider
from .tts import Qwen3TTSProvider, TTSProvider


class _DirectionalOpusMT(TranslationProvider):
    """Dispatches to one of several single-direction OPUSMTProvider
    instances by (source_lang, target_lang) — a single OPUSMTProvider
    only ever loads one checkpoint, but this pipeline needs both en->ta
    and ta->en for a real doctor<->patient conversation."""

    def __init__(self, providers: dict[tuple[str, str], OPUSMTProvider]):
        self._providers = providers

    def load_all(self) -> None:
        for provider in self._providers.values():
            provider.load()

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        provider = self._providers.get((source_lang, target_lang))
        if provider is None:
            raise ValueError(
                f"no OPUS-MT checkpoint configured for {source_lang}->{target_lang} "
                f"(have: {list(self._providers.keys())})"
            )
        return provider.translate(text, source_lang, target_lang)


def _build_translator(backend: str) -> TranslationProvider:
    if backend == "opus-mt":
        translator = _DirectionalOpusMT({
            ("en", "ta"): OPUSMTProvider(
                source_lang="en", target_lang="ta",
                checkpoint="Helsinki-NLP/opus-mt-en-dra", target_lang_tag=">>tam<<",
            ),
            ("ta", "en"): OPUSMTProvider(
                source_lang="ta", target_lang="en",
                checkpoint="Helsinki-NLP/opus-mt-dra-en",
            ),
        })
        translator.load_all()
        return translator
    if backend == "madlad":
        translator = MADLADProvider(size="3b")
        translator.load()
        return translator
    raise ValueError(f"unknown ai_translation_backend {backend!r}, expected 'opus-mt' or 'madlad'")


def _build_tts(backend: str, ref_audio: str | None, ref_text: str | None) -> TTSProvider | None:
    if backend == "none":
        return None
    if backend == "qwen3-tts":
        tts = Qwen3TTSProvider(ref_audio=ref_audio, ref_text=ref_text)
        tts.load()
        return tts
    raise ValueError(f"unknown ai_tts_backend {backend!r}, expected 'none' or 'qwen3-tts'")


def build_default_pipeline(
    whisper_model_size: str = "tiny",
    translation_backend: str = "opus-mt",
    tts_backend: str = "none",
    tts_ref_audio: str | None = None,
    tts_ref_text: str | None = None,
) -> TranslationPipeline:
    return TranslationPipeline(
        stt=FasterWhisperSTT(model_size=whisper_model_size),
        lid=LangidProvider(),
        translator=_build_translator(translation_backend),
        tts=_build_tts(tts_backend, tts_ref_audio, tts_ref_text),
    )
