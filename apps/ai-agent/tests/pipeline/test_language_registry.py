from app.pipeline.language_registry import Certification, LanguagePairConfig, LanguageRegistry, LicenseStatus, default_registry


def test_default_registry_has_en_ta_and_ta_en():
    reg = default_registry()
    assert reg.get("en", "ta") is not None
    assert reg.get("ta", "en") is not None


def test_unregistered_pair_returns_none():
    reg = default_registry()
    assert reg.get("fr", "zh") is None


def test_en_ta_was_switched_from_nllb_mms_tts_to_madlad_qwen3_tts():
    """Real change this pass: en->ta's default translation/TTS providers
    were switched away from NLLB-200/MMS-TTS (found CC-BY-NC-4.0,
    non-commercial) to MADLAD-400/Qwen3-TTS (Apache-2.0), with NO fallback
    configured back to the old models — a deliberate full removal from
    this pair's production routing, not just a reordering."""
    reg = default_registry()
    cfg = reg.get("en", "ta")
    assert cfg.translation_primary == "madlad400-3b"
    assert cfg.translation_fallback is None
    assert cfg.tts_primary == "qwen3-tts"
    assert cfg.tts_fallback is None


def test_en_ta_license_is_now_verified_but_certification_was_reset():
    """The new models are commercially licensed, so license.verified is
    now True — but certification was correctly RESET to "testing" rather
    than carried over from NLLB/MMS-TTS: the real regression evidence
    behind the old "certified" status was measured against NLLB/MMS-TTS's
    actual output, and does not transfer to a different model without
    re-verification. is_production_ready() is still False, now for a
    different, equally real reason."""
    reg = default_registry()
    cfg = reg.get("en", "ta")
    assert cfg.license.verified is True
    assert cfg.certification.is_certified is False
    assert cfg.certification.status == "testing"
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
