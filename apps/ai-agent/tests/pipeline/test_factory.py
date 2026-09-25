"""Unit tests for app/pipeline/factory.py's backend-selection logic
(_DirectionalOpusMT dispatch, _build_translator/_build_tts's unknown-
backend handling) — the parts of factory.py that don't require any real
model weights to test."""

import pytest

from app.pipeline.factory import _build_translator, _build_tts, _DirectionalOpusMT
from app.pipeline.translation import TranslationProvider


class _FakeDirectionalProvider(TranslationProvider):
    def __init__(self, tag: str):
        self._tag = tag
        self.calls: list[str] = []

    def translate(self, text, source_lang, target_lang):
        self.calls.append(text)
        return f"[{self._tag}] {text}"


def test_directional_opus_mt_dispatches_by_language_pair():
    en_ta = _FakeDirectionalProvider("en-ta")
    ta_en = _FakeDirectionalProvider("ta-en")
    dispatcher = _DirectionalOpusMT({("en", "ta"): en_ta, ("ta", "en"): ta_en})

    assert dispatcher.translate("hello", "en", "ta") == "[en-ta] hello"
    assert dispatcher.translate("vanakkam", "ta", "en") == "[ta-en] vanakkam"
    assert en_ta.calls == ["hello"]
    assert ta_en.calls == ["vanakkam"]


def test_directional_opus_mt_raises_clearly_for_unconfigured_direction():
    dispatcher = _DirectionalOpusMT({("en", "ta"): _FakeDirectionalProvider("en-ta")})
    with pytest.raises(ValueError, match="en->ml"):
        dispatcher.translate("hello", "en", "ml")


def test_build_translator_rejects_unknown_backend():
    with pytest.raises(ValueError, match="ai_translation_backend"):
        _build_translator("nonexistent-backend")


def test_build_tts_rejects_unknown_backend():
    with pytest.raises(ValueError, match="ai_tts_backend"):
        _build_tts("nonexistent-backend", None, None)


def test_build_tts_none_backend_returns_none_without_touching_any_model():
    assert _build_tts("none", None, None) is None
