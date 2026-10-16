from app.pipeline.language_registry import Certification, LanguagePairConfig, LanguageRegistry, LicenseStatus, default_registry


def test_default_registry_has_en_ta_and_ta_en():
    reg = default_registry()
    assert reg.get("en", "ta") is not None
    assert reg.get("ta", "en") is not None


def test_unregistered_pair_returns_none():
    reg = default_registry()
    assert reg.get("fr", "zh") is None


def test_en_ta_was_switched_off_nllb_mms_tts_with_two_selectable_routes():
    """Real change this pass: en->ta's default translation/TTS providers
    were switched away from NLLB-200/MMS-TTS (found CC-BY-NC-4.0,
    non-commercial). Two routes now exist, matching app/config.py's
    deploy-time-selectable ai_translation_backend/ai_tts_backend:
    primary = OPUS-MT (Apache-2.0, CPU-feasible — what actually runs on
    this build's real CPU-only VPS deployment today), fallback = MADLAD-400
    /Qwen3-TTS (Apache-2.0, GPU-only — the path once GPU infra exists).
    Neither old model (NLLB/MMS-TTS) appears in either slot."""
    reg = default_registry()
    cfg = reg.get("en", "ta")
    assert cfg.translation_primary == "opus-mt-en-ta"
    assert cfg.translation_fallback == "madlad400-3b"
    assert cfg.tts_primary is None
    assert cfg.tts_fallback == "qwen3-tts"


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


def test_dedicated_apache_pairs_from_2026_09_26_market_research_are_registered():
    """A real market-language-compatibility pass (2026-09-26) verified
    Apache-2.0 dedicated OPUS-MT checkpoints for these languages —
    registered as "uncertified" (license-clean, not yet regression-tested),
    not silently absent."""
    reg = default_registry()
    for code in ("ar", "hi", "ur", "tl", "id", "cy", "es", "fr", "ru", "uk", "it"):
        for source, target in ((("en", code)), (code, "en")):
            cfg = reg.get(source, target)
            assert cfg is not None, f"expected a registered pair for {source}->{target}"
            assert cfg.license.verified is True
            assert cfg.certification.status == "uncertified"


def test_license_traps_are_routed_through_the_apache_alternative_not_the_trap():
    """Real finding: opus-mt-tr-en/opus-mt-tc-big-en-tr and
    opus-mt-tc-big-en-pt are CC-BY-4.0 despite looking like ordinary
    Helsinki-NLP checkpoints. The registry must route Turkish/Portuguese
    through the Apache-2.0 group-model alternative, never the trap."""
    reg = default_registry()
    assert reg.get("en", "tr").translation_primary == "opus-mt-en-trk"
    assert reg.get("tr", "en").translation_primary == "opus-mt-trk-en"
    assert reg.get("en", "pt").translation_primary == "opus-mt-en-ROMANCE"


def test_zh_en_is_registered_as_cc_by_4_0_not_apache_a_real_different_license():
    """zh->en's only decent-quality checkpoint is CC-BY-4.0 (commercially
    usable, but a genuinely different compliance obligation than every
    Apache-2.0 pair elsewhere in this table) -- this must be visible in
    the registry, not silently glossed over as "the same as everything
    else"."""
    reg = default_registry()
    zh_en = reg.get("zh", "en")
    assert zh_en.translation_primary == "opus-mt-zh-en"
    assert "CC-BY-4.0" in zh_en.license.notes
    # en->zh, by contrast, really is Apache-2.0.
    en_zh = reg.get("en", "zh")
    assert en_zh.translation_primary == "opus-mt-en-zh"
    assert "Apache-2.0" in en_zh.license.notes


def test_m2m100_backed_pairs_reflect_the_real_2026_09_26_cpu_spot_check():
    """Real CPU spot-check results (no VPS) must be reflected honestly:
    en->fa/en->ps/en->bn are "testing" (plausible output observed);
    en->ne is "uncertified" because it silently dropped the dosage count
    -- a real accuracy failure, not just "not yet tested". bn->en uses
    OPUS-MT's own dedicated checkpoint, not M2M-100, because a better
    option actually exists for that direction."""
    reg = default_registry()
    assert reg.get("en", "fa").certification.status == "testing"
    assert reg.get("en", "ps").certification.status == "testing"
    assert reg.get("en", "bn").certification.status == "testing"
    assert reg.get("en", "ne").certification.status == "uncertified"
    assert "dropped" in reg.get("en", "ne").license.notes.lower()
    assert reg.get("bn", "en").translation_primary == "opus-mt-bn-en"


def test_catastrophically_failed_and_genuinely_unsolved_pairs_have_no_route():
    """Real finding: M2M-100 produced degenerate repetition loops (not
    real translations) for en->si and en->gu on a real CPU spot-check --
    these must have NO registry entry, not a route pointing at a model
    known to fail outright. Kurdish/Cantonese/Hokkien remain genuinely
    unsolved for the same reason (no adequate model found at all)."""
    reg = default_registry()
    for source, target in (
        ("en", "si"), ("si", "en"), ("en", "gu"), ("gu", "en"), ("en", "pa"),
        ("en", "ku"), ("ku", "en"), ("en", "yue"), ("yue", "en"), ("en", "nan"), ("nan", "en"),
    ):
        assert reg.get(source, target) is None, f"{source}->{target} should have no route (known failure/unsolved)"
