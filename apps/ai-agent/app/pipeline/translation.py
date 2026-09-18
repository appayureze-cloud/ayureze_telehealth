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

from abc import ABC, abstractmethod
from pathlib import Path

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
