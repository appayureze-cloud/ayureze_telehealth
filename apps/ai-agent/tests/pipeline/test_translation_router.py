import pytest

from app.pipeline.language_registry import Certification, LanguagePairConfig, LanguageRegistry, LicenseStatus
from app.pipeline.model_lifecycle import ModelHealth, ModelMetadata
from app.pipeline.translation_router import RoutingError, TranslationRouter


class FakeProvider:
    """A fake ModelLifecycle+TranslationProvider, matching this repo's own
    established pattern (test_tts_gate.py) of using fake providers to keep
    router/orchestration tests fast and independent of real model
    weights."""

    def __init__(self, provider_id: str, healthy: bool = True, output: str = "translated"):
        self._id = provider_id
        self._healthy = healthy
        self._output = output
        self.calls = []

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._healthy, loaded=self._healthy)

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id=self._id, checkpoint=self._id, version="fake",
            code_license="Apache-2.0", weights_license="Apache-2.0",
            commercial_use=True, redistribution=True, attribution_required=False,
            source_url="", verified_date="2026-09-25",
        )

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        self.calls.append((text, source_lang, target_lang))
        return self._output


def _certified_registry(primary_id="primary", fallback_id="fallback"):
    reg = LanguageRegistry()
    reg.register(LanguagePairConfig(
        source="en", target="ta",
        translation_primary=primary_id, translation_fallback=fallback_id,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="certified", medical_terms=True, dosage=True, negation=True, latency=True),
        license=LicenseStatus(verified=True),
    ))
    return reg


def test_routes_to_primary_when_healthy():
    primary = FakeProvider("primary")
    fallback = FakeProvider("fallback")
    router = TranslationRouter(_certified_registry(), {"primary": primary, "fallback": fallback})

    result, record = router.route("en", "ta", "take two tablets")

    assert result == "translated"
    assert record.provider_id == "primary"
    assert record.route == "primary"
    assert primary.calls == [("take two tablets", "en", "ta")]
    assert fallback.calls == []


def test_falls_back_when_primary_unhealthy():
    primary = FakeProvider("primary", healthy=False)
    fallback = FakeProvider("fallback")
    router = TranslationRouter(_certified_registry(), {"primary": primary, "fallback": fallback})

    result, record = router.route("en", "ta", "text")

    assert record.provider_id == "fallback"
    assert record.route == "fallback"
    assert fallback.calls == [("text", "en", "ta")]


def test_fails_closed_when_neither_provider_is_available():
    primary = FakeProvider("primary", healthy=False)
    fallback = FakeProvider("fallback", healthy=False)
    router = TranslationRouter(_certified_registry(), {"primary": primary, "fallback": fallback})

    with pytest.raises(RoutingError):
        router.route("en", "ta", "text")


def test_fails_closed_for_unregistered_pair():
    router = TranslationRouter(LanguageRegistry(), {})
    with pytest.raises(RoutingError):
        router.route("fr", "zh", "text")


def test_fails_closed_for_uncertified_pair_by_default():
    reg = LanguageRegistry()
    reg.register(LanguagePairConfig(
        source="de", target="en",
        translation_primary="opus", translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True),
    ))
    router = TranslationRouter(reg, {"opus": FakeProvider("opus")})
    with pytest.raises(RoutingError):
        router.route("de", "en", "hallo")


def test_allow_uncertified_opt_in_permits_an_uncertified_pair():
    reg = LanguageRegistry()
    reg.register(LanguagePairConfig(
        source="de", target="en",
        translation_primary="opus", translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True),
    ))
    opus = FakeProvider("opus")
    router = TranslationRouter(reg, {"opus": opus}, allow_uncertified=True)
    result, record = router.route("de", "en", "hallo")
    assert result == "translated"
    assert record.provider_id == "opus"


def test_route_record_never_contains_the_translated_text_or_source_text():
    primary = FakeProvider("primary")
    router = TranslationRouter(_certified_registry(), {"primary": primary, "fallback": FakeProvider("fallback")})
    _, record = router.route("en", "ta", "patient reported severe abdominal pain")

    record_fields = vars(record)
    for value in record_fields.values():
        if isinstance(value, str):
            assert "patient" not in value
            assert "abdominal" not in value
