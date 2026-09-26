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
    # en<->te (Telugu): same en-dra/dra-en checkpoint as ta/ml, `>>tel<<`
    # target tag confirmed against the model's own README. Same
    # captions-only/testing status as en<->ta.
    en_te = LanguagePairConfig(
        source="en", target="te",
        translation_primary="opus-mt-en-te",
        translation_fallback="madlad400-3b",
        tts_primary=None,
        tts_fallback="qwen3-tts",
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=True, notes="Same opus-mt-en-dra checkpoint as en->ta/en->ml (Apache-2.0, >>tel<< tag). Not separately regression-tested from Tamil/Malayalam."),
    )
    te_en = LanguagePairConfig(
        source="te", target="en",
        translation_primary="opus-mt-te-en",
        translation_fallback="madlad400-3b",
        tts_primary=None,
        tts_fallback="qwen3-tts",
        certification=Certification(status="testing", medical_terms=False, dosage=False, negation=False, latency=False),
        license=LicenseStatus(verified=True, notes="Same opus-mt-dra-en checkpoint as ta->en/ml->en (Apache-2.0, no tag needed)."),
    )

    # Dedicated bilingual OPUS-MT checkpoints, verified Apache-2.0 directly
    # against each checkpoint's OWN HuggingFace model card on 2026-09-26 (a
    # market-language-compatibility research pass covering UAE/Saudi/Qatar/
    # Oman/Kuwait/Bahrain/Singapore/Malaysia/UK/Germany's major languages —
    # see docs/MODEL_LICENSE_MATRIX.md's "2026-09-26 update"). NOT
    # downloaded or regression-tested against this build's safety corpus in
    # this pass — same "written and license-verified, not yet certified"
    # status as de->en/ja->en below; certification stays "uncertified"
    # until each pair earns real evidence individually. Built via a small
    # loop rather than 22 near-identical blocks — see factory.py's
    # _OPUS_MT_ROUTES for the actual checkpoint names each of these
    # resolves to (they follow the plain `opus-mt-<src>-<tgt>` pattern).
    _dedicated_pairs: dict[tuple[str, str], LanguagePairConfig] = {}
    for _code, _name in {
        "ar": "Arabic", "hi": "Hindi", "ur": "Urdu", "tl": "Tagalog/Filipino (code is tl, not fil)",
        "id": "Indonesian", "cy": "Welsh", "es": "Spanish", "fr": "French",
        "ru": "Russian", "uk": "Ukrainian", "it": "Italian",
    }.items():
        for _source, _target in (("en", _code), (_code, "en")):
            _dedicated_pairs[(_source, _target)] = LanguagePairConfig(
                source=_source, target=_target,
                translation_primary=f"opus-mt-{_source}-{_target}",
                translation_fallback="madlad400-3b",
                tts_primary=None,
                tts_fallback="qwen3-tts",
                certification=Certification(status="uncertified"),
                license=LicenseStatus(
                    verified=True,
                    notes=f"opus-mt-{_source}-{_target} ({_name}) verified Apache-2.0 directly from its own model card, 2026-09-26. Not downloaded/regression-tested in this pass.",
                ),
            )

    # Directions where only ONE side has a usable dedicated/group route —
    # the other direction is deliberately absent (not an oversight): its
    # only checkpoint is either a real license trap (pa/pl) or doesn't
    # exist at all (ro), and pointing it at a weak/wrong-licensed fallback
    # would misrepresent capability.
    pa_en = LanguagePairConfig(
        source="pa", target="en",
        translation_primary="opus-mt-pa-en",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-pa-en (Punjabi->English) verified Apache-2.0, 2026-09-26. en->pa deliberately has NO entry: its only options are a poor OPUS-MT group fallback (BLEU ~8) and M2M-100 (real 2026-09-26 spot-check silently dropped the dosage count) — neither is safe to route for medical dialogue yet."),
    )
    pl_en = LanguagePairConfig(
        source="pl", target="en",
        translation_primary="opus-mt-pl-en",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-pl-en verified Apache-2.0, 2026-09-26. en->pl's dedicated checkpoint doesn't exist; a real Apache-2.0 group route (opus-mt-en-sla) exists but this build hasn't confirmed its exact target tag yet — do not add en->pl without that."),
    )
    en_ro = LanguagePairConfig(
        source="en", target="ro",
        translation_primary="opus-mt-en-ro",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-en-ro verified Apache-2.0, 2026-09-26. ro->en has no dedicated checkpoint at all -- see ro_en below (ROMANCE group)."),
    )
    # Romance group checkpoint (many-to-one direction, no target tag
    # needed): the only route for pt->en and ro->en, neither of which has
    # a dedicated bilingual checkpoint.
    pt_en = LanguagePairConfig(
        source="pt", target="en",
        translation_primary="opus-mt-ROMANCE-en",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-ROMANCE-en verified Apache-2.0, 2026-09-26; pt confirmed in its source-language list. No isolated Portuguese BLEU published for this group model."),
    )
    ro_en = LanguagePairConfig(
        source="ro", target="en",
        translation_primary="opus-mt-ROMANCE-en",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="Same opus-mt-ROMANCE-en checkpoint as pt->en; ro confirmed in its source-language list, no isolated Romanian BLEU published."),
    )
    # en->pt: the obvious dedicated-ish checkpoint (opus-mt-tc-big-en-pt)
    # is CC-BY-4.0 and a heavier model -- routed through the Apache-2.0
    # ROMANCE group instead. Target tag CONFIRMED from the model's own
    # README (2026-09-26): `>>pt<<`, not `>>por<<`.
    en_pt = LanguagePairConfig(
        source="en", target="pt",
        translation_primary="opus-mt-en-ROMANCE",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-en-ROMANCE verified Apache-2.0, 2026-09-26, chosen specifically to avoid opus-mt-tc-big-en-pt's CC-BY-4.0 license. Target tag confirmed >>pt<<."),
    )
    # Turkish: opus-mt-tr-en / opus-mt-tc-big-en-tr are BOTH CC-BY-4.0 --
    # a real license trap. The Apache-2.0 `trk` (Turkic) group model is
    # the fix, confirmed to score BETTER (BLEU 34.6/26.8) than the CC-BY
    # pair, not just legally cleaner. Target tag CONFIRMED: `>>tur<<`.
    en_tr = LanguagePairConfig(
        source="en", target="tr",
        translation_primary="opus-mt-en-trk",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-en-trk (Turkic group) verified Apache-2.0, 2026-09-26 -- deliberately NOT opus-mt-tr-en/opus-mt-tc-big-en-tr, both CC-BY-4.0. Target tag confirmed >>tur<<; BLEU 34.6, better than the CC-BY pair."),
    )
    tr_en = LanguagePairConfig(
        source="tr", target="en",
        translation_primary="opus-mt-trk-en",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-trk-en verified Apache-2.0, 2026-09-26 -- same license-trap avoidance as en->tr. No tag needed (many-to-one). BLEU 26.8."),
    )
    # Mandarin Chinese: en->zh is a real Apache-2.0 checkpoint. zh->en's
    # ONLY dedicated checkpoint is CC-BY-4.0 (a real, different license
    # family -- commercially usable, attribution required, NOT the same
    # terms as the rest of this table) -- used anyway because it measures
    # ~10 BLEU points better (36.1) than the only Apache-2.0 alternative
    # (opus-mt-mul-en, 25.8), and CC-BY-4.0 has no non-commercial clause.
    # This is a real compliance difference a production rollout must
    # actually handle (a visible attribution credit), not just a license
    # string -- see docs/MODEL_LICENSE_MATRIX.md.
    en_zh = LanguagePairConfig(
        source="en", target="zh",
        translation_primary="opus-mt-en-zh",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-en-zh verified Apache-2.0, 2026-09-26. Target tag >>cmn_Hans<< (Simplified Mandarin) used deliberately instead of the bare >>cmn<</>>zho<< tokens to avoid an ambiguous script variant. This checkpoint's vocabulary technically also covers Cantonese (>>yue<<) and Hokkien (>>nan<<) but NEITHER has a published benchmark score -- deliberately not registered as a separate pair; see factory.py's _OPUS_MT_ROUTES comment."),
    )
    zh_en = LanguagePairConfig(
        source="zh", target="en",
        translation_primary="opus-mt-zh-en",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-zh-en is CC-BY-4.0 (confirmed 2026-09-26), NOT Apache-2.0 -- commercially usable but requires a visible attribution credit, a real product decision this build has documented but not yet implemented in-app. Chosen over the Apache-2.0 opus-mt-mul-en alternative for a ~10 BLEU point quality gain (36.1 vs 25.8) on a medical-accuracy-sensitive product."),
    )
    # M2M-100 (facebook/m2m100_418M, MIT) -- the CPU-feasible backbone for
    # languages OPUS-MT can't serve well. REAL spot-check run on CPU in
    # this build's own sandbox, 2026-09-26 (no VPS) -- see
    # M2M100Provider's docstring for the exact inputs/outputs. en->fa,
    # en->ps, and en->bn produced plausible translations; en->ne dropped
    # the dosage count. bn->en instead uses OPUS-MT's own dedicated
    # apache-2.0 checkpoint (better quality than routing it through
    # M2M-100 too). en->pa, en->si, en->gu, and any Kurdish/Cantonese/
    # Hokkien direction are DELIBERATELY ABSENT from this registry: en->pa
    # dropped the dosage count same as ne; en->si and en->gu failed
    # OUTRIGHT (degenerate repetition loops, not real translations); ku
    # isn't in M2M-100's language list at all; yue/nan aren't either.
    en_fa = LanguagePairConfig(
        source="en", target="fa",
        translation_primary="m2m100-418M",
        translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="testing"),
        license=LicenseStatus(verified=True, notes="facebook/m2m100_418M verified MIT, 2026-09-26. Real spot-check: plausible, structurally sound translation of a dosage instruction. One data point, not a certification."),
    )
    fa_en = LanguagePairConfig(
        source="fa", target="en",
        translation_primary="m2m100-418M",
        translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="facebook/m2m100_418M verified MIT, 2026-09-26. This direction not spot-checked (only en->fa was) -- uncertified pending that."),
    )
    en_ps = LanguagePairConfig(
        source="en", target="ps",
        translation_primary="m2m100-418M",
        translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="testing"),
        license=LicenseStatus(verified=True, notes="facebook/m2m100_418M verified MIT, 2026-09-26. Real spot-check: plausible, structurally sound translation of a dosage instruction."),
    )
    ps_en = LanguagePairConfig(
        source="ps", target="en",
        translation_primary="m2m100-418M",
        translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="facebook/m2m100_418M verified MIT, 2026-09-26. This direction not spot-checked (only en->ps was)."),
    )
    en_bn = LanguagePairConfig(
        source="en", target="bn",
        translation_primary="m2m100-418M",
        translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="testing"),
        license=LicenseStatus(verified=True, notes="facebook/m2m100_418M verified MIT, 2026-09-26. Real spot-check on a negation sentence ('Do not take this medicine if you are pregnant.'): plausible, structurally sound. OPUS-MT has no dedicated en->bn checkpoint (only a poor group fallback, BLEU ~17) -- M2M-100 is the better option here."),
    )
    bn_en = LanguagePairConfig(
        source="bn", target="en",
        translation_primary="opus-mt-bn-en",
        translation_fallback="madlad400-3b",
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="opus-mt-bn-en verified Apache-2.0, 2026-09-26 -- a real dedicated OPUS-MT checkpoint exists for THIS direction (unlike en->bn), so it's used instead of M2M-100. Not downloaded/regression-tested in this pass."),
    )
    en_ne = LanguagePairConfig(
        source="en", target="ne",
        translation_primary="m2m100-418M",
        translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="facebook/m2m100_418M verified MIT, 2026-09-26. Real spot-check found a REAL PROBLEM: the tablet COUNT ('two') was silently dropped from the translation ('take medicine twice for seven days', not 'two tablets'). Left uncertified rather than testing -- this is a genuine dosage-accuracy failure on the exact kind of sentence this product needs to get right, not a minor wording issue."),
    )
    ne_en = LanguagePairConfig(
        source="ne", target="en",
        translation_primary="m2m100-418M",
        translation_fallback=None,
        tts_primary=None, tts_fallback=None,
        certification=Certification(status="uncertified"),
        license=LicenseStatus(verified=True, notes="facebook/m2m100_418M verified MIT, 2026-09-26. This direction not spot-checked."),
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

    all_configs: dict[tuple[str, str], LanguagePairConfig] = {
        (c.source, c.target): c for c in (
            en_ta, ta_en, en_ml, en_te, te_en,
            pa_en, pl_en, en_ro, pt_en, ro_en, en_pt, en_tr, tr_en, en_zh, zh_en,
            en_fa, fa_en, en_ps, ps_en, en_bn, bn_en, en_ne, ne_en,
            de_en, ja_en,
        )
    }
    all_configs.update(_dedicated_pairs)
    return all_configs


def default_registry() -> LanguageRegistry:
    return LanguageRegistry(_default_pairs())
