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
CC-BY-NC-4.0 (non-commercial) — see docs/MODEL_LICENSE_MATRIX.md.

en<->ta/ta<->en/en<->ml now offer TWO translation routes, matching
app/config.py's deploy-time-selectable ai_translation_backend — neither
removes the other from the codebase:
  primary:  `Helsinki-NLP/opus-mt-en-dra`/`opus-mt-dra-en` — Apache-2.0
            AND genuinely CPU-feasible (a real CPU-only VPS is this
            build's actual current deployment target). This is what
            actually runs today.
  fallback: `madlad400-3b` — Apache-2.0 but GPU-only per its own docs;
            the path once real GPU infrastructure exists.
TTS is `None`/captions-only by default with `qwen3-tts` as the fallback
for the same reason (GPU + a reference voice per language, neither
available today) — no TTS candidate is currently both commercially
licensed and CPU-feasible (k2-fsa/OmniVoice's pretrained weights are
CC-BY-NC despite an Apache-2.0 codebase; Piper TTS's Tamil voice license
is unverified/mixed per-voice) — see `docs/MODEL_LICENSE_MATRIX.md`.

Certification was reset to `testing` rather than carried over when the
primary route changed from NLLB-200 to OPUS-MT: the prior evidence was
against a DIFFERENT model's actual translations and does not transfer
without re-running the same regression evidence against the new one.
Every other entry (de->en, ja->en) exists to demonstrate the
registry/router mechanism the build spec asks for and is likewise
`testing`/`uncertified` until it
earns that status with real evidence.
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
    # en<->ta: this build's primary pair. TWO translation backends are
    # available (app/config.py's ai_translation_backend, deploy-time
    # selectable — neither removes the other from the codebase):
    #
    #   primary "opus-mt-en-ta": Helsinki-NLP/opus-mt-en-dra (needs a
    #     `>>tam<<` target tag) — Apache-2.0, small MarianMT model
    #     (hundreds of MB), genuinely CPU-feasible. This is what actually
    #     runs on a CPU-only VPS deployment today.
    #   fallback "madlad400-3b": Apache-2.0 but GPU-only per its own
    #     docs — the path once real GPU infrastructure exists.
    #
    # See app/pipeline/factory.py's build_default_pipeline() for the
    # actual selection logic (a _DirectionalOpusMT dispatcher for the
    # opus-mt backend, since a single OPUSMTProvider only loads one
    # direction).
    #
    # tts_primary is None (captions-only): no TTS model has both a
    # verified commercial license AND CPU feasibility yet. Qwen3-TTS/
    # CosyVoice3 need GPU; k2-fsa/OmniVoice's pretrained weights are
    # CC-BY-NC (non-commercial, due to its training data) despite an
    # Apache-2.0 codebase; Piper TTS's Tamil voice license is unverified/
    # mixed per-voice — see docs/MODEL_LICENSE_MATRIX.md. tts_fallback
    # points at qwen3-tts for the future GPU path (also needs a reference
    # voice clip per language — see app/config.py).
    #
    # certification stays "testing"/all-False even after this pass's real
    # CPU-sandbox regression run (2026-09-26, no VPS — see
    # docs/ai/models.md for the full evidence): status="certified"
    # requires medical_terms AND dosage AND negation AND latency all
    # True, and dosage genuinely is NOT true yet for real reasons found
    # by actually running opus-mt-en-dra's live output through the
    # safety validator:
    #   - negation: confirmed working ("Do not take this medicine."
    #     round-trips and is correctly compared).
    #   - frequency recognition: was a FALSE POSITIVE (terminology.py's
    #     Tamil "daily" word list was curated against NLLB-200's
    #     phrasing and didn't recognize OPUS-MT's own "நாளும்" — fixed
    #     in this pass; verified against real model output, zero
    #     regressions in the existing 88-case terminology/safety suite).
    #   - dosage/medical vocabulary: OPUS-MT genuinely mistranslates
    #     "tablet(s)" -> "பலகை"/"மேசை" (board/table) instead of the
    #     correct "மாத்திரை", non-deterministically across otherwise-
    #     identical runs, and has also been observed to silently drop
    #     "twice" from "twice daily". The safety validator correctly
    #     catches and blocks both (fail-closed proven working end-to-end
    #     against the real model), but that means real digit/count-
    #     bearing dosage instructions will often be blocked rather than
    #     actually delivered — a genuine, unresolved OPUS-MT quality
    #     limitation, not a safety-validator bug. Certification cannot
    #     honestly move to "certified" until this is fixed (e.g. a
    #     medical-vocabulary glossary/constrained-decoding step, or a
    #     different model) and the full 75-case corpus is re-run.
    en_ta = LanguagePairConfig(
        source="en", target="ta",
        translation_primary="opus-mt-en-ta",
        translation_fallback="madlad400-3b",
        tts_primary=None,
        tts_fallback="qwen3-tts",
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=True, latency=False),
        license=LicenseStatus(verified=True, notes="opus-mt-en-dra (checkpoint backing the primary route) is Apache-2.0, verified 2026-09-25 — see docs/MODEL_LICENSE_MATRIX.md. License is no longer the blocker; certification is, and specifically the real 'tablet'->board/table mistranslation found in this build's own 2026-09-26 CPU-sandbox regression run (see docs/ai/models.md) — not lack of testing infrastructure. No TTS model is both commercially licensed and CPU-feasible yet — captions-only until qwen3-tts's GPU/reference-voice prerequisites are met."),
    )
    ta_en = LanguagePairConfig(
        source="ta", target="en",
        translation_primary="opus-mt-ta-en",
        translation_fallback="madlad400-3b",
        tts_primary=None,
        tts_fallback="qwen3-tts",
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=True, notes="opus-mt-dra-en (checkpoint backing the primary route) is Apache-2.0, verified 2026-09-25. A single hand-crafted Tamil medical sentence produced a badly garbled, semantically unrelated English translation in this build's own 2026-09-26 spot check (see docs/ai/models.md) — not yet enough test cases to know if that's this specific input's phrasing or a genuine ta->en model weakness, so negation/dosage/latency are left False pending a real multi-case check, not assumed working by symmetry with en->ta."),
    )
    # en<->ml: same CPU-feasible OPUS-MT checkpoint (opus-mt-en-dra also
    # covers Malayalam) and captions-only TTS status as en->ta. Was
    # already "testing" before any model switch (safety validator's
    # negation/terminology tables are English/Tamil-only today) — a
    # second, independent, still-open blocker on top of certification.
    en_ml = LanguagePairConfig(
        source="en", target="ml",
        translation_primary="opus-mt-en-ml",
        translation_fallback="madlad400-3b",
        tts_primary=None,
        tts_fallback="qwen3-tts",
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=True, notes="Same opus-mt-en-dra checkpoint as en->ta (Apache-2.0). Safety-validator language coverage remains a separate, still-open blocker for this pair specifically."),
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
