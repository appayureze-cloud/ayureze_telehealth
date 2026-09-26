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
  None) — see orchestrator.py).
- tts_backend="qwen3-tts": Qwen3-TTS (Apache-2.0, GPU-only, also needs a
  reference voice clip per language — ai_tts_reference_audio_path/
  ai_tts_reference_text in app/config.py).
- tts_backend="indic-parler-tts": ai4bharat/indic-parler-tts (Apache-2.0,
  confirmed commercial-clean, confirmed Tamil support via named speakers
  — no reference-voice-clip question). CPU-CAPABLE (has a documented CPU
  fallback path, unlike Qwen3-TTS/CosyVoice3) but 0.9B params — expect
  multi-second latency per utterance on CPU, not benchmarked in this pass.
- tts_backend="piper": Piper, invoked via CLI subprocess only (never
  imported as a Python library — see PiperTTSProvider's docstring for
  why: its actively-maintained successor is GPL-3.0). Genuinely CPU-fast
  by design. REAL, UNRESOLVED GAP: the specific Tamil voice checkpoint's
  dataset license could not be verified this pass — see
  docs/MODEL_LICENSE_MATRIX.md before enabling in production.

None of MADLAD-400, Qwen3-TTS, or indic-parler-tts are downloaded unless
AI_ALLOW_MODEL_DOWNLOAD=true (and, for the GPU-only ones, a real GPU is
present) — selecting them without that infrastructure raises
ModelNotAvailableError. Piper additionally requires a local `.onnx` voice
checkpoint path and the `piper` executable on PATH.
"""

from __future__ import annotations

from .lid import LangidProvider
from .orchestrator import TranslationPipeline
from .stt import FasterWhisperSTT
from .translation import MADLADProvider, OPUSMTProvider, TranslationProvider
from .tts import IndicParlerTTSProvider, PiperTTSProvider, Qwen3TTSProvider, TTSProvider


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


def _build_tts(
    backend: str, ref_audio: str | None, ref_text: str | None, piper_checkpoint: str | None = None,
) -> TTSProvider | None:
    if backend == "none":
        return None
    if backend == "qwen3-tts":
        tts = Qwen3TTSProvider(ref_audio=ref_audio, ref_text=ref_text)
        tts.load()
        return tts
    if backend == "indic-parler-tts":
        tts = IndicParlerTTSProvider()
        tts.load()
        return tts
    if backend == "piper":
        tts = PiperTTSProvider(checkpoint=piper_checkpoint)
        tts.load()
        return tts
    raise ValueError(
        f"unknown ai_tts_backend {backend!r}, expected 'none', 'qwen3-tts', 'indic-parler-tts', or 'piper'"
    )


def build_default_pipeline(
    whisper_model_size: str = "tiny",
    translation_backend: str = "opus-mt",
    tts_backend: str = "none",
    tts_ref_audio: str | None = None,
    tts_ref_text: str | None = None,
    tts_piper_checkpoint: str | None = None,
) -> TranslationPipeline:
    return TranslationPipeline(
        stt=FasterWhisperSTT(model_size=whisper_model_size),
        lid=LangidProvider(),
        translator=_build_translator(translation_backend),
        tts=_build_tts(tts_backend, tts_ref_audio, tts_ref_text, tts_piper_checkpoint),
    )
