import pytest

from app.pipeline.language_registry import Certification, LanguagePairConfig, LanguageRegistry, LicenseStatus
from app.pipeline.model_lifecycle import ModelHealth, ModelMetadata
from app.pipeline.tts_router import TTSRouter, TTSRoutingError


class FakeTTSProvider:
    def __init__(self, provider_id: str, healthy: bool = True):
        self._id = provider_id
        self._healthy = healthy

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._healthy, loaded=self._healthy)

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id=self._id, checkpoint=self._id, version="fake",
            code_license="Apache-2.0", weights_license="Apache-2.0",
            commercial_use=True, redistribution=True, attribution_required=False,
            source_url="", verified_date="2026-09-25",
        )


def _certified_registry():
    reg = LanguageRegistry()
    reg.register(LanguagePairConfig(
        source="en", target="ta",
        translation_primary="x", translation_fallback=None,
        tts_primary="primary", tts_fallback="fallback",
        certification=Certification(status="certified", medical_terms=True, dosage=True, negation=True, latency=True),
        license=LicenseStatus(verified=True),
    ))
    return reg


def test_routes_to_primary_when_healthy():
    primary = FakeTTSProvider("primary")
    router = TTSRouter(_certified_registry(), {"primary": primary, "fallback": FakeTTSProvider("fallback")})
    provider, record = router.route_for_language("ta", source_lang="en")
    assert provider is primary
    assert record.route == "primary"


def test_falls_back_when_primary_unhealthy():
    router = TTSRouter(
        _certified_registry(),
        {"primary": FakeTTSProvider("primary", healthy=False), "fallback": FakeTTSProvider("fallback")},
    )
    provider, record = router.route_for_language("ta", source_lang="en")
    assert record.provider_id == "fallback"


def test_fails_closed_when_no_provider_available():
    router = TTSRouter(
        _certified_registry(),
        {"primary": FakeTTSProvider("primary", healthy=False), "fallback": FakeTTSProvider("fallback", healthy=False)},
    )
    with pytest.raises(TTSRoutingError):
        router.route_for_language("ta", source_lang="en")


def test_fails_closed_for_uncertified_pair():
    reg = LanguageRegistry()
    reg.register(LanguagePairConfig(
        source="en", target="ml",
        translation_primary="x", translation_fallback=None,
        tts_primary="p", tts_fallback=None,
        certification=Certification(status="testing"),
        license=LicenseStatus(verified=True),
    ))
    router = TTSRouter(reg, {"p": FakeTTSProvider("p")})
    with pytest.raises(TTSRoutingError):
        router.route_for_language("ml", source_lang="en")


def test_fails_closed_for_unregistered_language():
    router = TTSRouter(LanguageRegistry(), {})
    with pytest.raises(TTSRoutingError):
        router.route_for_language("zz", source_lang="en")
