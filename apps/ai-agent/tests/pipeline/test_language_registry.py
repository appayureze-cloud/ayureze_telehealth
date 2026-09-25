from app.pipeline.language_registry import Certification, LanguagePairConfig, LanguageRegistry, LicenseStatus, default_registry


def test_default_registry_has_en_ta_and_ta_en():
    reg = default_registry()
    assert reg.get("en", "ta") is not None
    assert reg.get("ta", "en") is not None


def test_unregistered_pair_returns_none():
    reg = default_registry()
    assert reg.get("fr", "zh") is None


def test_en_ta_is_fully_certified_but_not_production_ready_due_to_license():
    """Real finding from this pass: NLLB-200/MMS-TTS are CC-BY-NC-4.0
    (non-commercial). Certification alone must never be enough —
    is_production_ready() requires BOTH certification AND a verified
    commercial-compatible license."""
    reg = default_registry()
    cfg = reg.get("en", "ta")
    assert cfg.certification.is_certified is True
    assert cfg.license.verified is False
    assert reg.is_production_ready("en", "ta") is False


def test_uncertified_pair_is_never_production_ready_even_with_verified_license():
    reg = default_registry()
    cfg = reg.get("de", "en")
    assert cfg.license.verified is True
    assert cfg.certification.is_certified is False
    assert reg.is_production_ready("de", "en") is False


def test_certification_requires_all_four_flags():
    cert = Certification(status="certified", medical_terms=True, dosage=True, negation=True, latency=False)
    assert cert.is_certified is False  # latency flag missing despite status="certified"


def test_register_and_overwrite_a_pair():
    reg = LanguageRegistry()
    assert reg.get("es", "en") is None
    reg.register(LanguagePairConfig(
        source="es", target="en", translation_primary="opus-mt-es-en", translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="certified", medical_terms=True, dosage=True, negation=True, latency=True),
        license=LicenseStatus(verified=True),
    ))
    assert reg.is_production_ready("es", "en") is True
    assert len(reg.all_pairs()) == 1


def test_ja_en_routes_directly_to_madlad_with_no_fallback():
    """Build spec's own worked example: no certified specialist for
    Japanese -> English, so MADLAD-400 IS the primary route, not a
    fallback behind something else."""
    reg = default_registry()
    cfg = reg.get("ja", "en")
    assert cfg.translation_primary == "madlad400-3b"
    assert cfg.translation_fallback is None
