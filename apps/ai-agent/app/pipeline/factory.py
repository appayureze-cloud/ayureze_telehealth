"""Builds the default (real-model) pipeline. Kept as one place so
apps/ai-agent/app/agent.py and tests both construct the identical provider
set — swapping any provider (e.g. IndicTrans2 in for NLLB once available)
means changing this function, not every call site.
"""

from __future__ import annotations

from .lid import LangidProvider
from .orchestrator import TranslationPipeline
from .stt import FasterWhisperSTT
from .translation import NLLBTranslationProvider
from .tts import MmsTTSProvider


def build_default_pipeline(whisper_model_size: str = "tiny") -> TranslationPipeline:
    return TranslationPipeline(
        stt=FasterWhisperSTT(model_size=whisper_model_size),
        lid=LangidProvider(),
        translator=NLLBTranslationProvider(),
        tts=MmsTTSProvider(),
    )
