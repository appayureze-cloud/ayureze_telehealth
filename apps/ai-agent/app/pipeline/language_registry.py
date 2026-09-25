"""Machine-readable language registry (build spec section 25): the single
source of truth for which translation/TTS provider a language pair routes
to, its certification status, and its license-verification status. A pair
cannot be used by TranslationRouter/TTSRouter in production mode until
`Certification.is_certified` AND `LicenseStatus.verified` are both true —
"testing"/"uncertified" pairs fail closed unless a caller explicitly opts
in (e.g. a controlled internal benchmark run).

The default registry below reflects this build's ACTUAL, evidenced state,
not aspiration: en<->ta is the only pair with a real, passing 75-case
safety corpus, real live end-to-end integration test, and a measured
latency benchmark behind it, so it is the only pair marked `certified`.
Every other entry (en<->ml, de->en, ja->en) exists to demonstrate the
registry/router mechanism the build spec asks for and is deliberately left
`testing`/`uncertified` until it actually earns that status the same way.
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
    # en<->ta: this build's actual, evidenced primary pair. NLLB-200 is the
    # existing translation provider (already live-verified, not a new
    # build-spec model), so "certified" here reflects real regression
    # evidence (tests/pipeline/test_safety_validator_corpus.py, 75 cases,
    # both directions) plus a real measured latency benchmark.
    #
    # license.verified is FALSE here — a genuine, previously-undocumented
    # finding from this pass's license-verification work (build spec
    # section 26): facebook/nllb-200-distilled-600M and
    # facebook/mms-tts-eng/-tam/-mal are BOTH licensed CC-BY-NC-4.0
    # (verified directly against their live HuggingFace model cards,
    # 2026-09-25) — non-commercial, and NLLB's own model card explicitly
    # states it is "not released for production deployment." This is an
    # EXISTING, already-shipped dependency of this build, not something
    # this pass introduced, but section 26's "Unknown = NOT APPROVED" rule
    # applies just as much to a pair already in production as a new one —
    # see docs/MODEL_LICENSE_MATRIX.md for the full finding and
    # docs/ai/README.md's "Known limitations" for the pre-existing
    # decision to substitute NLLB for the spec's original IndicTrans2
    # pick, made without this specific licensing check at the time.
    en_ta = LanguagePairConfig(
        source="en", target="ta",
        translation_primary="nllb-200-distilled-600m",
        translation_fallback="madlad400-3b",
        tts_primary="mms-tts",
        tts_fallback="qwen3-tts",
        certification=Certification(status="certified", medical_terms=True, dosage=True, negation=True, latency=True),
        license=LicenseStatus(verified=False, notes="NLLB-200 and MMS-TTS are both CC-BY-NC-4.0 (non-commercial) per their live HuggingFace model cards, verified 2026-09-25 — see docs/MODEL_LICENSE_MATRIX.md. is_production_ready() correctly returns False for this pair until resolved (see notes there), despite full certification."),
    )
    ta_en = LanguagePairConfig(
        source="ta", target="en",
        translation_primary="nllb-200-distilled-600m",
        translation_fallback="madlad400-3b",
        tts_primary="mms-tts",
        tts_fallback="qwen3-tts",
        certification=Certification(status="certified", medical_terms=True, dosage=True, negation=True, latency=True),
        license=LicenseStatus(verified=False, notes="Same as en->ta."),
    )
    # en<->ml: existing models technically support this pair (NLLB has
    # mal_Mlym, MMS-TTS has facebook/mms-tts-mal), but the safety
    # validator's negation/terminology tables are English/Tamil-only today
    # (docs/ai/README.md's own known-limitations) — genuinely "testing",
    # not certified, on top of the same licensing gap as en->ta.
    en_ml = LanguagePairConfig(
        source="en", target="ml",
        translation_primary="nllb-200-distilled-600m",
        translation_fallback="madlad400-3b",
        tts_primary="mms-tts",
        tts_fallback="qwen3-tts",
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=False, notes="Same CC-BY-NC-4.0 licensing gap as en->ta; safety-validator language coverage is a second, separate blocker."),
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
