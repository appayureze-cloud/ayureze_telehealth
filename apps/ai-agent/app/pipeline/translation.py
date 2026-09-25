"""Translation provider interface + NLLB-200 implementation.

The build spec's initial pick is IndicTrans2. This build uses
facebook/nllb-200-distilled-600M instead — a deliberate, documented
substitution (see docs/ai/README.md "Known limitations"): IndicTrans2's
gated model access and custom preprocessing toolkit (IndicTransToolkit,
language-tag + script-specific tokenization) could not be reliably
provisioned in this build environment, whereas NLLB-200 is directly usable
through standard `transformers` with official support for English, Tamil,
and Malayalam. The provider interface below is what makes swapping to
IndicTrans2 (or any other model) later a contained change, not a redesign.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from .model_lifecycle import ModelHealth, ModelLifecycle, ModelMetadata, ModelNotAvailableError

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "models" / "hf"

# ISO 639-1 (this build's internal language code) -> NLLB's FLORES-200 code.
_LANG_TO_NLLB = {
    "en": "eng_Latn",
    "ta": "tam_Taml",
    "ml": "mal_Mlym",
}


class TranslationProvider(ABC):
    @abstractmethod
    def translate(self, text: str, source_lang: str, target_lang: str) -> str: ...


class NLLBTranslationProvider(TranslationProvider):
    def __init__(self, model_id: str = "facebook/nllb-200-distilled-600M", cache_dir: Path | str = DEFAULT_CACHE_DIR):
        from transformers import (  # local import: heavy optional dep
            AutoModelForSeq2SeqLM,
            AutoTokenizer,
        )

        self._tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=str(cache_dir))
        self._model = AutoModelForSeq2SeqLM.from_pretrained(model_id, cache_dir=str(cache_dir))

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return ""
        if source_lang not in _LANG_TO_NLLB or target_lang not in _LANG_TO_NLLB:
            raise ValueError(f"unsupported language pair: {source_lang} -> {target_lang}")

        self._tokenizer.src_lang = _LANG_TO_NLLB[source_lang]
        inputs = self._tokenizer(text, return_tensors="pt")
        target_token_id = self._tokenizer.convert_tokens_to_ids(_LANG_TO_NLLB[target_lang])
        output_ids = self._model.generate(**inputs, forced_bos_token_id=target_token_id, max_new_tokens=128)
        return self._tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0]


class OPUSMTProvider(TranslationProvider, ModelLifecycle):
    """Helsinki-NLP/opus-mt-<src>-<tgt> (build spec section F) — a
    per-language-pair MarianMT checkpoint used only for pairs the language
    registry has certified as a specialist route. Each checkpoint is a
    SEPARATE HuggingFace repo with its own license entry; the build spec
    explicitly warns not to assume one verified checkpoint's license
    applies to another pair — see docs/MODEL_LICENSE_MATRIX.md, which
    tracks per-checkpoint verification, not per-model-family.

    Not downloaded in this build (AI_ALLOW_MODEL_DOWNLOAD is false by
    default) — load() raises ModelNotAvailableError, and
    TranslationRouter treats that as "use the configured fallback
    (MADLAD-400), never silently degrade to plaintext or an unapproved
    model."
    """

    def __init__(self, source_lang: str, target_lang: str, checkpoint: str | None = None,
                 cache_dir: Path | str = DEFAULT_CACHE_DIR):
        ModelLifecycle.__init__(self)
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._checkpoint = checkpoint or f"Helsinki-NLP/opus-mt-{source_lang}-{target_lang}"
        self._cache_dir = str(cache_dir)
        self._model = None
        self._tokenizer = None

    def load(self) -> None:
        if self._loaded:
            return
        if os.environ.get("AI_ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
            raise ModelNotAvailableError(
                f"{self._checkpoint}: AI_ALLOW_MODEL_DOWNLOAD is not 'true' — this build never "
                "downloads new model weights implicitly. TranslationRouter falls back to the "
                "configured backbone model instead."
            )
        try:
            from transformers import MarianMTModel, MarianTokenizer
        except ImportError as e:
            raise ModelNotAvailableError(f"{self._checkpoint}: transformers MarianMT classes unavailable ({e})") from e

        import time as _time

        t0 = _time.monotonic()
        self._tokenizer = MarianTokenizer.from_pretrained(self._checkpoint, cache_dir=self._cache_dir)
        self._model = MarianMTModel.from_pretrained(self._checkpoint, cache_dir=self._cache_dir)
        self._load_seconds = _time.monotonic() - t0
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded (see load())")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id=f"opus-mt-{self._source_lang}-{self._target_lang}",
            checkpoint=self._checkpoint,
            version="marian-nmt",
            code_license="Apache-2.0",
            # Verified directly against Helsinki-NLP/opus-mt-de-en's live model card on 2026-09-25:
            # apache-2.0. The build spec explicitly warns this can vary per checkpoint — re-verify
            # before certifying any OTHER language pair; do not assume this value for a pair this
            # class hasn't been checked against.
            weights_license="Apache-2.0",
            commercial_use=True,
            redistribution=True,
            attribution_required=True,
            source_url=f"https://huggingface.co/{self._checkpoint}",
            verified_date="2026-09-25",
            certified=False,
            notes="License verified for opus-mt-de-en specifically; re-verify per-checkpoint before certifying any other pair.",
        )

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self._loaded:
            raise RuntimeError("load() must be called before translate()")
        if not text.strip():
            return ""
        inputs = self._tokenizer(text, return_tensors="pt", padding=True)
        output_ids = self._model.generate(**inputs, max_new_tokens=128)
        return self._tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0]


# MADLAD-400 target-language tokens are plain ISO 639-1 codes for the
# languages this build might route to it (build spec: "verify... supported
# language list before enabling a model" — do not extend this table to a
# new code without checking it against the model's own sentencepiece vocab
# first).
_MADLAD_LANG_CODE = {"en": "en", "ta": "ta", "ml": "ml", "de": "de", "fr": "fr", "es": "es", "ja": "ja"}


class MADLADProvider(TranslationProvider, ModelLifecycle):
    """Google's MADLAD-400 (build spec section G) — the global backbone
    model TranslationRouter uses when no certified specialist exists for a
    pair. API verified against the live model card (2026-09-25): a T5
    model taking a `<2<target-lang>>` prefix token; MADLAD-400
    auto-detects the source language, no source tag needed.

    This build points at the `jbochi/madlad400-<size>-mt` community
    re-uploads because those are what the model's own documented
    quickstart uses for direct T5ForConditionalGeneration/T5Tokenizer
    loading; both inherit google/madlad400's Apache-2.0 license (verified
    against google/madlad400-3b-mt's own model card, 2026-09-25 — see
    docs/MODEL_LICENSE_MATRIX.md). Not downloaded in this build.

    3B is the default per the build spec's explicit "Do NOT automatically
    use 7B" instruction; 7B is selectable via size="7b" but never chosen
    automatically by the router.
    """

    CHECKPOINTS = {"3b": "jbochi/madlad400-3b-mt", "7b": "jbochi/madlad400-7b-mt"}

    def __init__(self, size: str = "3b", cache_dir: Path | str = DEFAULT_CACHE_DIR):
        ModelLifecycle.__init__(self)
        if size not in self.CHECKPOINTS:
            raise ValueError(f"unknown MADLAD size {size!r}, expected one of {list(self.CHECKPOINTS)}")
        self._size = size
        self._checkpoint = self.CHECKPOINTS[size]
        self._cache_dir = str(cache_dir)
        self._model = None
        self._tokenizer = None

    def load(self) -> None:
        if self._loaded:
            return
        if os.environ.get("AI_ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
            raise ModelNotAvailableError(
                f"{self._checkpoint}: AI_ALLOW_MODEL_DOWNLOAD is not 'true' — this build never "
                "downloads new model weights implicitly."
            )
        try:
            from transformers import T5ForConditionalGeneration, T5Tokenizer
        except ImportError as e:
            raise ModelNotAvailableError(f"{self._checkpoint}: transformers T5 classes unavailable ({e})") from e

        import time as _time

        t0 = _time.monotonic()
        self._tokenizer = T5Tokenizer.from_pretrained(self._checkpoint, cache_dir=self._cache_dir)
        self._model = T5ForConditionalGeneration.from_pretrained(
            self._checkpoint, device_map="auto", cache_dir=self._cache_dir
        )
        self._load_seconds = _time.monotonic() - t0
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded (see load())")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id=f"madlad400-{self._size}",
            checkpoint=self._checkpoint,
            version=self._size,
            code_license="Apache-2.0",
            weights_license="Apache-2.0",
            commercial_use=True,
            redistribution=True,
            attribution_required=True,
            source_url=f"https://huggingface.co/google/madlad400-{self._size}-mt",
            verified_date="2026-09-25",
            certified=False,
            notes="Global backbone, used only when no certified specialist exists (build spec section G).",
        )

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self._loaded:
            raise RuntimeError("load() must be called before translate()")
        if not text.strip():
            return ""
        target_code = _MADLAD_LANG_CODE.get(target_lang, target_lang)
        prefixed = f"<2{target_code}> {text}"
        input_ids = self._tokenizer(prefixed, return_tensors="pt").input_ids.to(self._model.device)
        output_ids = self._model.generate(input_ids=input_ids, max_new_tokens=128)
        return self._tokenizer.decode(output_ids[0], skip_special_tokens=True)
