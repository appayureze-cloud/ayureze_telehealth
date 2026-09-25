"""Machine-readable language registry (build spec section 25): the single
source of truth for which translation/TTS provider a language pair routes
to, its certification status, and its license-verification status. A pair
cannot be used by TranslationRouter/TTSRouter in production mode until
`Certification.is_certified` AND `LicenseStatus.verified` are both true —
"testing"/"uncertified" pairs fail closed unless a caller explicitly opts
in (e.g. a controlled internal benchmark run).

The default registry below reflects this build's ACTUAL, evidenced state,
not aspiration. **No pair is currently marked `certified`.** en<->ta was
previously certified against NLLB-200/MMS-TTS's real output (the 75-case
safety corpus, a live end-to-end integration test, a measured latency
benchmark), but this build's own license audit found both models
CC-BY-NC-4.0 (non-commercial) — see docs/MODEL_LICENSE_MATRIX.md — so
en<->ta was switched to MADLAD-400/Qwen3-TTS (Apache-2.0) as primary, with
no fallback to the old models. Certification was reset to `testing`
rather than carried over: the prior evidence was against NLLB/MMS-TTS's
actual translations specifically and does not transfer to a different
model without re-running the same regression evidence against it — which
requires a GPU host these new models aren't downloaded on in this
sandbox (see `model_lifecycle.ModelNotAvailableError`). Every other entry
(en<->ml, de->en, ja->en) exists to demonstrate the registry/router
mechanism the build spec asks for and is likewise `testing`/`uncertified`
until it earns that status with real evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Certification:
    status: str = "uncertified"  # "uncertified" | "testing" | "certified"
    medical_terms: bool = False
    dosage: bool = False
    negation: bool = False
    latency: bool = False

    @property
    def is_certified(self) -> bool:
        return self.status == "certified" and self.medical_terms and self.dosage and self.negation and self.latency


@dataclass
class LicenseStatus:
    verified: bool = False
    notes: str = ""


@dataclass
class LanguagePairConfig:
    source: str
    target: str
    translation_primary: str  # a provider_id resolvable by TranslationRouter's provider map
    translation_fallback: str | None
    tts_primary: str | None
    tts_fallback: str | None
    certification: Certification = field(default_factory=Certification)
    license: LicenseStatus = field(default_factory=LicenseStatus)


class LanguageRegistry:
    def __init__(self, pairs: dict[tuple[str, str], LanguagePairConfig] | None = None):
        self._pairs: dict[tuple[str, str], LanguagePairConfig] = dict(pairs or {})

    def register(self, config: LanguagePairConfig) -> None:
        self._pairs[(config.source, config.target)] = config

    def get(self, source: str, target: str) -> LanguagePairConfig | None:
        return self._pairs.get((source, target))

    def is_production_ready(self, source: str, target: str) -> bool:
        cfg = self.get(source, target)
        return cfg is not None and cfg.certification.is_certified and cfg.license.verified

    def all_pairs(self) -> list[LanguagePairConfig]:
        return list(self._pairs.values())


def _default_pairs() -> dict[tuple[str, str], LanguagePairConfig]:
    # en<->ta: this build's primary pair. SWITCHED this pass from
    # NLLB-200/MMS-TTS to MADLAD-400/Qwen3-TTS as primary, with NO
    # fallback to the old models (translation_fallback/tts_fallback=None)
    # — a deliberate decision to fully remove the non-commercially-licensed
    # models from this pair's production routing after this codebase's own
    # license audit found NLLB-200 and MMS-TTS are both CC-BY-NC-4.0
    # (verified directly against their live HuggingFace model cards,
    # 2026-09-25; NLLB's own model card explicitly states it is "not
    # released for production deployment") — see
    # docs/MODEL_LICENSE_MATRIX.md for the full finding.
    #
    # certification is reset to "testing"/all-False here, NOT carried over
    # from NLLB/MMS-TTS's prior certified status: the real regression
    # evidence behind that certification (tests/pipeline/
    # test_safety_validator_corpus.py's 75 cases, the live-integration
    # test, the measured latency benchmark) was run against NLLB/MMS-TTS's
    # actual output specifically. It does not transfer to a different
    # model's translations, which can differ in phrasing/latency in ways
    # the safety validator or latency budget haven't been re-verified
    # against. Claiming "certified" for an unverified model here would be
    # exactly the kind of unevidenced claim this project's own conventions
    # exist to prevent.
    #
    # MADLAD-400/Qwen3-TTS are NOT downloaded in this build (see
    # factory.py's build_default_pipeline() and
    # model_lifecycle.ModelNotAvailableError) — is_production_ready()
    # correctly returns False for this pair, now for TWO real reasons:
    # uncertified AND (until a GPU host with AI_ALLOW_MODEL_DOWNLOAD=true
    # exists) unavailable to even attempt certification against.
    en_ta = LanguagePairConfig(
        source="en", target="ta",
        translation_primary="madlad400-3b",
        translation_fallback=None,
        tts_primary="qwen3-tts",
        tts_fallback=None,
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=True, notes="madlad400-3b and qwen3-tts are both Apache-2.0, verified 2026-09-25 — see docs/MODEL_LICENSE_MATRIX.md. License is no longer the blocker for this pair; certification (real regression evidence against these specific models) is."),
    )
    ta_en = LanguagePairConfig(
        source="ta", target="en",
        translation_primary="madlad400-3b",
        translation_fallback=None,
        tts_primary="qwen3-tts",
        tts_fallback=None,
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=True, notes="Same as en->ta."),
    )
    # en<->ml: switched the same way as en->ta/ta->en. Was already
    # "testing" (English/Tamil-only safety-validator coverage is a
    # separate, still-open blocker), so this pair's status is unchanged —
    # only its provider and license.verified value change.
    en_ml = LanguagePairConfig(
        source="en", target="ml",
        translation_primary="madlad400-3b",
        translation_fallback=None,
        tts_primary="qwen3-tts",
        tts_fallback=None,
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=True, notes="Same as en->ta — madlad400-3b/qwen3-tts are Apache-2.0. Safety-validator language coverage remains a separate, still-open blocker for this pair specifically."),
    )
    # de->en: the build spec's own worked example of a "certified
    # specialist" route. OPUS-MT is a genuinely real, small, commercially
    # licensed option for this pair, but has NOT been downloaded or
    # regression-tested against this build's dosage/negation corpus in
    # this pass — uncertified until it is.
    de_en = LanguagePairConfig(
        source="de", target="en",
        translation_primary="opus-mt-de-en",
        translation_fallback="madlad400-3b",
        tts_primary=None,  # no certified/available German TTS route configured yet
        tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-de-en license verified (Apache-2.0, 2026-09-25); certification blocked on regression testing, not licensing."),
    )
    # ja->en: the build spec's own worked example of "no certified
    # specialist -> MADLAD-400". Deliberately configured with NO
    # translation_fallback (MADLAD-400 IS the primary here, matching the
    # spec's routing diagram exactly), to demonstrate the router's
    # fail-closed behavior once MADLAD itself isn't certified either.
    ja_en = LanguagePairConfig(
        source="ja", target="en",
        translation_primary="madlad400-3b",
        translation_fallback=None,
        tts_primary=None,
        tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="madlad400-3b license verified (Apache-2.0, 2026-09-25); certification blocked on regression testing, not licensing."),
    )

    return {
        (c.source, c.target): c for c in (en_ta, ta_en, en_ml, de_en, ja_en)
    }


def default_registry() -> LanguageRegistry:
    return LanguageRegistry(_default_pairs())
