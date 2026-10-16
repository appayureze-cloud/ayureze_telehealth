"""Builds the default (real-model) pipeline. Kept as one place so
apps/ai-agent/app/agent.py and tests both construct the identical provider
set — swapping any provider means changing this function, not every call
site.

Translation and TTS backends are DEPLOY-TIME SELECTABLE (app/config.py's
ai_translation_backend/ai_tts_backend), not hardcoded — neither backend is
removed from the codebase by choosing the other:

- translation_backend="opus-mt" (default): Helsinki-NLP/opus-mt-en-dra
  (English -> Dravidian languages incl. Tamil, needs a `>>tam<<`-style
  target tag — see OPUSMTProvider's docstring) for en->ta, and
  opus-mt-dra-en (many-to-one, no tag needed) for ta->en. Both
  Apache-2.0, verified 2026-09-25, and — unlike MADLAD-400's 3B
  parameters — small enough for real CPU inference. This is what actually
  runs on a CPU-only VPS deployment today.
- translation_backend="madlad": MADLAD-400 3B (Apache-2.0, GPU-only per
  its own docs). Select this once real GPU infrastructure exists.

- tts_backend="none" (default): CAPTIONS-ONLY (TranslationPipeline(tts=
  None) — see orchestrator.py).
- tts_backend="qwen3-tts": Qwen3-TTS (Apache-2.0, GPU-only, also needs a
  reference voice clip per language — ai_tts_reference_audio_path/
  ai_tts_reference_text in app/config.py).
- tts_backend="indic-parler-tts": ai4bharat/indic-parler-tts (Apache-2.0,
  confirmed commercial-clean, confirmed Tamil support via named speakers
  — no reference-voice-clip question). CPU-CAPABLE (has a documented CPU
  fallback path, unlike Qwen3-TTS/CosyVoice3) but 0.9B params — expect
  multi-second latency per utterance on CPU, not benchmarked in this pass.
- tts_backend="piper": Piper, invoked via CLI subprocess only (never
  imported as a Python library — see PiperTTSProvider's docstring for
  why: its actively-maintained successor is GPL-3.0). Genuinely CPU-fast
  by design. REAL, UNRESOLVED GAP: the specific Tamil voice checkpoint's
  dataset license could not be verified this pass — see
  docs/MODEL_LICENSE_MATRIX.md before enabling in production.

None of MADLAD-400, Qwen3-TTS, or indic-parler-tts are downloaded unless
AI_ALLOW_MODEL_DOWNLOAD=true (and, for the GPU-only ones, a real GPU is
present) — selecting them without that infrastructure raises
ModelNotAvailableError. Piper additionally requires a local `.onnx` voice
checkpoint path and the `piper` executable on PATH.
"""

from __future__ import annotations

from .lid import LangidProvider
from .orchestrator import TranslationPipeline
from .stt import FasterWhisperSTT
from .translation import M2M100Provider, MADLADProvider, OPUSMTProvider, TranslationProvider
from .tts import IndicParlerTTSProvider, PiperTTSProvider, Qwen3TTSProvider, TTSProvider


class _DirectionalOpusMT(TranslationProvider):
    """Dispatches to one of several single-direction OPUSMTProvider
    instances by (source_lang, target_lang) — a single OPUSMTProvider
    only ever loads one checkpoint, but this pipeline needs both en->ta
    and ta->en for a real doctor<->patient conversation."""

    def __init__(self, providers: dict[tuple[str, str], OPUSMTProvider]):
        self._providers = providers

    def load_all(self) -> None:
        for provider in self._providers.values():
            provider.load()

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        provider = self._providers.get((source_lang, target_lang))
        if provider is None:
            raise ValueError(
                f"no OPUS-MT checkpoint configured for {source_lang}->{target_lang} "
                f"(have: {list(self._providers.keys())})"
            )
        return provider.translate(text, source_lang, target_lang)


# Every (source, target) pair this build knows how to route through
# OPUS-MT, and the exact (checkpoint, target_lang_tag) OPUSMTProvider needs
# for it — the single place this is declared, so language_registry.py (which
# pair exists, its certification) and this factory (how to actually build
# it) cannot drift apart. Every checkpoint below was verified Apache-2.0
# directly against its OWN HuggingFace model card on 2026-09-25/26 — per
# the project's own rule, one Helsinki-NLP checkpoint's license is NEVER
# assumed to apply to another (confirmed real traps: opus-mt-zh-en and
# opus-mt-tr-en are CC-BY-4.0 despite looking like ordinary Helsinki-NLP
# pairs — deliberately NOT in this table; see docs/MODEL_LICENSE_MATRIX.md).
#
# A group checkpoint serves several languages via a `>>xxx<<`-style
# sentence-initial target tag on the ONE-TO-MANY direction only (verified
# against opus-mt-en-dra's own model card) — the MANY-TO-ONE direction
# (always translating into English) never needs one.
#
# Deliberately excluded pending further work, not silently forgotten:
#   - en->pl: a real Apache-2.0 group route exists (opus-mt-en-sla) but
#     this build hasn't yet confirmed its exact target tag for Polish —
#     do not guess a `>>xxx<<` token, a wrong one silently mistranslates.
#   - en->yue, en->nan (Cantonese/Hokkien): opus-mt-en-zh's vocabulary
#     technically includes `>>yue<<`/`>>nan<<` target tokens (Apache-2.0),
#     but NO benchmark score exists for either — for a medical product,
#     shipping an unbenchmarked translation direction is irresponsible,
#     not a missing config entry. Same for the reverse direction via
#     opus-mt-mul-en's yue/nan source support. Neither M2M-100 (below)
#     covers these languages either — genuinely unsolved as of 2026-09-26.
#     See docs/MODEL_LICENSE_MATRIX.md.
#   - Kurdish (any direction): OPUS-MT's only path is a group-model
#     fallback with BLEU ~4.0 that also lumps Kurmanji/Sorani into one
#     checkpoint; M2M-100 (below) does not include Kurdish in its
#     100-language list at all. Genuinely unsolved.
_OPUS_MT_ROUTES: dict[tuple[str, str], tuple[str, str | None]] = {
    # Existing default pair + same-checkpoint Dravidian-group extensions.
    ("en", "ta"): ("Helsinki-NLP/opus-mt-en-dra", ">>tam<<"),
    ("ta", "en"): ("Helsinki-NLP/opus-mt-dra-en", None),
    ("en", "ml"): ("Helsinki-NLP/opus-mt-en-dra", ">>mal<<"),
    ("ml", "en"): ("Helsinki-NLP/opus-mt-dra-en", None),
    ("en", "te"): ("Helsinki-NLP/opus-mt-en-dra", ">>tel<<"),
    ("te", "en"): ("Helsinki-NLP/opus-mt-dra-en", None),
    # Dedicated bilingual checkpoints, both directions Apache-2.0.
    ("de", "en"): ("Helsinki-NLP/opus-mt-de-en", None),
    ("en", "ar"): ("Helsinki-NLP/opus-mt-en-ar", None),
    ("ar", "en"): ("Helsinki-NLP/opus-mt-ar-en", None),
    ("en", "hi"): ("Helsinki-NLP/opus-mt-en-hi", None),
    ("hi", "en"): ("Helsinki-NLP/opus-mt-hi-en", None),
    ("en", "ur"): ("Helsinki-NLP/opus-mt-en-ur", None),
    ("ur", "en"): ("Helsinki-NLP/opus-mt-ur-en", None),
    ("en", "tl"): ("Helsinki-NLP/opus-mt-en-tl", None),  # Tagalog/Filipino; code is "tl", not "fil"
    ("tl", "en"): ("Helsinki-NLP/opus-mt-tl-en", None),
    ("en", "id"): ("Helsinki-NLP/opus-mt-en-id", None),
    ("id", "en"): ("Helsinki-NLP/opus-mt-id-en", None),
    ("en", "cy"): ("Helsinki-NLP/opus-mt-en-cy", None),
    ("cy", "en"): ("Helsinki-NLP/opus-mt-cy-en", None),
    ("en", "es"): ("Helsinki-NLP/opus-mt-en-es", None),
    ("es", "en"): ("Helsinki-NLP/opus-mt-es-en", None),
    ("en", "fr"): ("Helsinki-NLP/opus-mt-en-fr", None),
    ("fr", "en"): ("Helsinki-NLP/opus-mt-fr-en", None),
    ("en", "ru"): ("Helsinki-NLP/opus-mt-en-ru", None),
    ("ru", "en"): ("Helsinki-NLP/opus-mt-ru-en", None),
    ("en", "uk"): ("Helsinki-NLP/opus-mt-en-uk", None),
    ("uk", "en"): ("Helsinki-NLP/opus-mt-uk-en", None),
    ("en", "it"): ("Helsinki-NLP/opus-mt-en-it", None),
    ("it", "en"): ("Helsinki-NLP/opus-mt-it-en", None),
    # Directions with a dedicated pair on only ONE side; the other
    # direction's dedicated checkpoint is either non-Apache (pa/pl - see
    # above) or nonexistent (ro) — those directions are handled by a group
    # model below instead, never silently by the excluded direction.
    ("pa", "en"): ("Helsinki-NLP/opus-mt-pa-en", None),
    ("pl", "en"): ("Helsinki-NLP/opus-mt-pl-en", None),
    ("en", "ro"): ("Helsinki-NLP/opus-mt-en-ro", None),
    # Romance group checkpoint, many-to-one direction only (no target tag
    # needed — always translates into English): covers pt->en and ro->en,
    # for which no dedicated bilingual checkpoint exists at all.
    ("pt", "en"): ("Helsinki-NLP/opus-mt-ROMANCE-en", None),
    ("ro", "en"): ("Helsinki-NLP/opus-mt-ROMANCE-en", None),
    # en->pt: dedicated checkpoint is CC-BY-4.0 (opus-mt-tc-big-en-pt) and
    # a heavier model; the Apache-2.0 ROMANCE group instead. Tag CONFIRMED
    # from the model's own README target-language list (2026-09-26): it is
    # `>>pt<<`, NOT `>>por<<` (this group uses ISO 639-1-style codes).
    ("en", "pt"): ("Helsinki-NLP/opus-mt-en-ROMANCE", ">>pt<<"),
    # Turkish: the obvious opus-mt-tr-en/opus-mt-tc-big-en-tr are CC-BY-4.0;
    # the `trk` (Turkic) Apache-2.0 group model is the fix, and scores
    # BETTER than the CC-BY pair (BLEU 34.6/26.8 vs. the dedicated model's
    # own reported numbers). Tag CONFIRMED from the model's own README
    # (2026-09-26): `>>tur<<`.
    ("en", "tr"): ("Helsinki-NLP/opus-mt-en-trk", ">>tur<<"),
    ("tr", "en"): ("Helsinki-NLP/opus-mt-trk-en", None),
    # Mandarin Chinese: en->zh's own dedicated checkpoint is Apache-2.0.
    # zh->en's dedicated checkpoint (opus-mt-zh-en) is CC-BY-4.0 -- a real,
    # different license family (commercially usable, attribution required,
    # confirmed 2026-09-26), NOT Apache-2.0; deliberately used anyway
    # because it measures ~10 BLEU points better (36.1 vs. 25.8) than the
    # only Apache-2.0 alternative (opus-mt-mul-en) for a medical-accuracy-
    # sensitive product, and CC-BY-4.0 has no non-commercial restriction —
    # see docs/MODEL_LICENSE_MATRIX.md for the full tradeoff and the
    # resulting attribution obligation. `>>cmn_Hans<<` (Simplified
    # Mandarin, confirmed present in the model's target-language list) is
    # used for en->zh rather than the bare `>>cmn<<`/`>>zho<<` tokens to
    # avoid an ambiguous/unintended script variant.
    ("en", "zh"): ("Helsinki-NLP/opus-mt-en-zh", ">>cmn_Hans<<"),
    ("zh", "en"): ("Helsinki-NLP/opus-mt-zh-en", None),  # CC-BY-4.0 — see note above
}

# facebook/m2m100_418M (MIT, ai_translation_backend="m2m100") — the
# CPU-feasible "backbone" model for language pairs OPUS-MT can't serve
# well: no dedicated bilingual checkpoint exists for Persian/Nepali/
# Pashto, and Bengali/Sinhala/Punjabi/Gujarati only have a poor-quality
# OPUS-MT group-model fallback (real BLEU checked 2026-09-26: ~1-19
# depending on direction/language — see docs/MODEL_LICENSE_MATRIX.md).
# M2M-100 supports 100 languages in total; confirmed to include all of
# fa/ne/ps/bn/si/pa/gu — confirmed NOT to include Kurdish, Cantonese, or
# Hokkien, so it does not solve those. Per-language quality for these
# specific pairs is unverified (no published BLEU table for them) — this
# is a CPU-feasibility and licensing fix, not a quality guarantee;
# language_registry.py keeps these "uncertified"/"testing" until real
# regression evidence exists. See M2M100Provider's docstring
# (translation.py) for the exact verified quickstart API.


def _build_translator(backend: str, language_pairs: list[tuple[str, str]] | None = None) -> TranslationProvider:
    if backend == "opus-mt":
        pairs = language_pairs if language_pairs is not None else [("en", "ta"), ("ta", "en")]
        providers: dict[tuple[str, str], OPUSMTProvider] = {}
        for pair in pairs:
            route = _OPUS_MT_ROUTES.get(pair)
            if route is None:
                raise ValueError(
                    f"no verified OPUS-MT route configured for {pair[0]}->{pair[1]} — see "
                    "_OPUS_MT_ROUTES in factory.py and docs/MODEL_LICENSE_MATRIX.md for what's "
                    "actually verified before adding one"
                )
            checkpoint, tag = route
            providers[pair] = OPUSMTProvider(
                source_lang=pair[0], target_lang=pair[1], checkpoint=checkpoint, target_lang_tag=tag,
            )
        translator = _DirectionalOpusMT(providers)
        translator.load_all()
        return translator
    if backend == "madlad":
        translator = MADLADProvider(size="3b")
        translator.load()
        return translator
    if backend == "m2m100":
        translator = M2M100Provider(size="418M")
        translator.load()
        return translator
    raise ValueError(f"unknown ai_translation_backend {backend!r}, expected 'opus-mt', 'madlad', or 'm2m100'")


def parse_language_pairs(spec: str) -> list[tuple[str, str]]:
    """Parses app/config.py's `ai_translation_language_pairs` setting
    ("en-ta,ta-en,en-ar,ar-en") into [("en","ta"), ("ta","en"), ...]."""
    pairs = []
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        source, _, target = entry.partition("-")
        if not source or not target:
            raise ValueError(f"malformed language pair {entry!r} in {spec!r}, expected 'src-tgt'")
        pairs.append((source, target))
    return pairs


def _build_tts(
    backend: str, ref_audio: str | None, ref_text: str | None, piper_checkpoint: str | None = None,
) -> TTSProvider | None:
    if backend == "none":
        return None
    if backend == "qwen3-tts":
        tts = Qwen3TTSProvider(ref_audio=ref_audio, ref_text=ref_text)
        tts.load()
        return tts
    if backend == "indic-parler-tts":
        tts = IndicParlerTTSProvider()
        tts.load()
        return tts
    if backend == "piper":
        tts = PiperTTSProvider(checkpoint=piper_checkpoint)
        tts.load()
        return tts
    raise ValueError(
        f"unknown ai_tts_backend {backend!r}, expected 'none', 'qwen3-tts', 'indic-parler-tts', or 'piper'"
    )


def build_default_pipeline(
    whisper_model_size: str = "tiny",
    translation_backend: str = "opus-mt",
    translation_language_pairs: list[tuple[str, str]] | None = None,
    tts_backend: str = "none",
    tts_ref_audio: str | None = None,
    tts_ref_text: str | None = None,
    tts_piper_checkpoint: str | None = None,
) -> TranslationPipeline:
    return TranslationPipeline(
        stt=FasterWhisperSTT(model_size=whisper_model_size),
        lid=LangidProvider(),
        translator=_build_translator(translation_backend, translation_language_pairs),
        tts=_build_tts(tts_backend, tts_ref_audio, tts_ref_text, tts_piper_checkpoint),
    )
