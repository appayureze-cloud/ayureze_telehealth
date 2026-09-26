"""Unit tests for app/pipeline/factory.py's backend-selection logic
(_DirectionalOpusMT dispatch, _build_translator/_build_tts's unknown-
backend handling) — the parts of factory.py that don't require any real
model weights to test."""

import pytest

from app.pipeline.factory import _build_translator, _build_tts, _DirectionalOpusMT, _OPUS_MT_ROUTES, parse_language_pairs
from app.pipeline.model_lifecycle import ModelNotAvailableError
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


def test_build_translator_rejects_an_unconfigured_language_pair_before_touching_any_model():
    # No AI_ALLOW_MODEL_DOWNLOAD set here at all — this must fail on the
    # route lookup, not get as far as trying to download anything, for a
    # pair this build has explicitly NOT verified (see factory.py's
    # _OPUS_MT_ROUTES comment on Kurdish/Cantonese/Hokkini being
    # genuinely unsolved, not just unconfigured by oversight).
    with pytest.raises(ValueError, match=r"no verified OPUS-MT route configured for en->ku"):
        _build_translator("opus-mt", language_pairs=[("en", "ku")])


@pytest.mark.parametrize("pair", [
    ("en", "ar"), ("ar", "en"), ("en", "hi"), ("hi", "en"), ("en", "ur"), ("ur", "en"),
    ("en", "tl"), ("tl", "en"), ("en", "id"), ("id", "en"), ("en", "cy"), ("cy", "en"),
    ("en", "es"), ("es", "en"), ("en", "fr"), ("fr", "en"), ("en", "ru"), ("ru", "en"),
    ("en", "uk"), ("uk", "en"), ("en", "it"), ("it", "en"), ("en", "te"), ("te", "en"),
    ("pa", "en"), ("pl", "en"), ("en", "ro"), ("pt", "en"), ("ro", "en"),
    ("en", "pt"), ("en", "tr"), ("tr", "en"), ("en", "zh"), ("zh", "en"),
])
def test_opus_mt_routes_table_has_a_real_checkpoint_and_correct_tag_semantics(pair):
    from app.pipeline.factory import _OPUS_MT_ROUTES

    checkpoint, tag = _OPUS_MT_ROUTES[pair]
    assert checkpoint.startswith("Helsinki-NLP/opus-mt-")
    source_lang, target_lang = pair
    # Many-to-one (X -> en) checkpoints never need a target tag; the
    # multi-target group checkpoints used for a one-to-many direction
    # (dra/ROMANCE/trk/zh groups) always do.
    if target_lang == "en":
        assert tag is None
    elif checkpoint.endswith("-dra") or checkpoint.endswith("-ROMANCE") or checkpoint.endswith("-trk") or checkpoint.endswith("-zh"):
        assert tag is not None and tag.startswith(">>") and tag.endswith("<<")


def test_opus_mt_routes_excludes_known_license_traps():
    from app.pipeline.factory import _OPUS_MT_ROUTES

    # opus-mt-tr-en and opus-mt-tc-big-en-tr/en-pt are CC-BY-4.0 traps —
    # the table must route Turkish/Portuguese through the Apache-2.0 group
    # models instead, never the trapped dedicated checkpoints.
    assert _OPUS_MT_ROUTES[("en", "tr")][0] == "Helsinki-NLP/opus-mt-en-trk"
    assert _OPUS_MT_ROUTES[("tr", "en")][0] == "Helsinki-NLP/opus-mt-trk-en"
    assert _OPUS_MT_ROUTES[("en", "pt")][0] == "Helsinki-NLP/opus-mt-en-ROMANCE"


def test_build_translator_m2m100_fails_closed_without_download_permission():
    with pytest.raises(ModelNotAvailableError, match="AI_ALLOW_MODEL_DOWNLOAD"):
        _build_translator("m2m100")


def test_build_tts_rejects_unknown_backend():
    with pytest.raises(ValueError, match="ai_tts_backend"):
        _build_tts("nonexistent-backend", None, None)


def test_build_tts_none_backend_returns_none_without_touching_any_model():
    assert _build_tts("none", None, None) is None


def test_build_tts_indic_parler_tts_fails_closed_without_download_permission():
    with pytest.raises(ModelNotAvailableError, match="AI_ALLOW_MODEL_DOWNLOAD"):
        _build_tts("indic-parler-tts", None, None)


def test_parse_language_pairs_splits_comma_separated_spec():
    assert parse_language_pairs("en-ta,ta-en,en-ar,ar-en") == [
        ("en", "ta"), ("ta", "en"), ("en", "ar"), ("ar", "en"),
    ]


def test_parse_language_pairs_ignores_blank_entries_and_whitespace():
    assert parse_language_pairs(" en-ta , ,ta-en,") == [("en", "ta"), ("ta", "en")]


def test_parse_language_pairs_rejects_a_malformed_entry():
    with pytest.raises(ValueError, match="malformed language pair"):
        parse_language_pairs("en-ta,noseparator")
    with pytest.raises(ValueError, match="malformed language pair"):
        parse_language_pairs("en-")


def test_build_tts_piper_fails_closed_without_a_checkpoint_configured():
    import os

    old = os.environ.get("AI_ALLOW_MODEL_DOWNLOAD")
    os.environ["AI_ALLOW_MODEL_DOWNLOAD"] = "true"
    try:
        with pytest.raises(ModelNotAvailableError, match="no local voice checkpoint"):
            _build_tts("piper", None, None, piper_checkpoint=None)
    finally:
        if old is None:
            os.environ.pop("AI_ALLOW_MODEL_DOWNLOAD", None)
        else:
            os.environ["AI_ALLOW_MODEL_DOWNLOAD"] = old
