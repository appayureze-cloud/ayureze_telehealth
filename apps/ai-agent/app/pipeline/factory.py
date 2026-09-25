"""Builds the default (real-model) pipeline. Kept as one place so
apps/ai-agent/app/agent.py and tests both construct the identical provider
set — swapping any provider means changing this function, not every call
site.

Translation and TTS default to MADLAD-400 and Qwen3-TTS, NOT
NLLBTranslationProvider/MmsTTSProvider. This is a deliberate switch away
from the existing NLLB-200/MMS-TTS models after this codebase's own
license audit found both are CC-BY-NC-4.0 (non-commercial) — see
docs/MODEL_LICENSE_MATRIX.md. NLLBTranslationProvider/MmsTTSProvider
remain in translation.py/tts.py (still used by other tests and available
for direct construction) but are no longer the default production choice.

IMPORTANT, real consequence of this switch: MADLAD-400 and Qwen3-TTS are
NOT downloaded in this environment (no GPU, AI_ALLOW_MODEL_DOWNLOAD=false
by default) — see ModelNotAvailableError in model_lifecycle.py. Calling
this function here will raise that error. This is intentional: the
default pipeline now correctly refuses to silently fall back to the
non-commercial models rather than running on them unlicensed. It becomes
usable again once AI_ALLOW_MODEL_DOWNLOAD=true is set on a real GPU host
with these packages installed — see docs/ai/models.md.
"""

from __future__ import annotations

from .lid import LangidProvider
from .orchestrator import TranslationPipeline
from .stt import FasterWhisperSTT
from .translation import MADLADProvider
from .tts import Qwen3TTSProvider


def build_default_pipeline(
    whisper_model_size: str = "tiny",
    translation_size: str = "3b",
    tts_ref_audio: str | None = None,
    tts_ref_text: str | None = None,
) -> TranslationPipeline:
    translator = MADLADProvider(size=translation_size)
    translator.load()

    tts = Qwen3TTSProvider(ref_audio=tts_ref_audio, ref_text=tts_ref_text)
    tts.load()

    return TranslationPipeline(
        stt=FasterWhisperSTT(model_size=whisper_model_size),
        lid=LangidProvider(),
        translator=translator,
        tts=tts,
    )
