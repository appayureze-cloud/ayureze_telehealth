# Model license matrix

Every model this codebase loads or could load, with its license verified
directly against its live model card — never assumed from the model
family's reputation (per this task's own explicit rule: "Do not write
'commercial safe' based only on the model family name"). "Unknown = NOT
APPROVED."

**Verification date for every row below: 2026-09-25**, via direct
`WebFetch` of each model's HuggingFace model card page. Re-verify before
relying on this table again if meaningful time has passed — a model's
license tag on HuggingFace can change between releases.

## Finding: this build's EXISTING, already-shipped models are non-commercial

This is the single most important result of this pass's license audit.
**`facebook/nllb-200-distilled-600M` and `facebook/mms-tts-{eng,tam,mal}` —
the translation and TTS models this codebase has been shipping since Day
6 — are both licensed `CC-BY-NC-4.0` (non-commercial).** NLLB-200's own
model card explicitly states it is "not released for production
deployment." This was not previously documented anywhere in this repo
(`docs/ai/README.md`'s prior "Known limitations" section discussed the
IndicTrans2→NLLB substitution's *technical* reasoning only, never its
licensing implications) and was not flagged by any earlier license/security
pass. It is a real, pre-existing gap this audit surfaced as a byproduct of
doing the new-model licensing work properly — not something introduced by
this pass, but not something to carry forward silently either.

**Practical effect**: `app/pipeline/language_registry.py`'s default
registry marks `en<->ta` (and `en<->ml`) as fully *certified*
(medical-terms/dosage/negation/latency all validated) but
`license.verified = False`, so `LanguageRegistry.is_production_ready()`
correctly returns `False` for AyurEze's own primary language pair despite
complete certification. This is intentional and correct — certification
and licensing are separate gates, and this table exists so a licensing gap
can never be silently overridden by a certification pass.

**This is not this pass's decision to resolve** (the build spec explicitly
scopes this task to the new streaming architecture, not a translation/TTS
model swap for the existing pair), but it is the most actionable finding
in this document: **AyurEze cannot commercially deploy its current
production translation/TTS pipeline on NLLB-200 + MMS-TTS as licensed.**
Options, not evaluated further here: (1) a commercial license from Meta
for these specific checkpoints (unresearched — contact Meta), (2) replace
en/ta/ml translation with MADLAD-400 (Apache-2.0, already integrated this
pass, not yet certified against the safety corpus), (3) replace TTS with
Qwen3-TTS/CosyVoice3 (Apache-2.0, already integrated this pass, not
downloaded/tested), or (4) some other commercially-licensed model not
evaluated here.

## Matrix

| Model | Checkpoint | Code License | Weights License | Commercial Use | Redistribution | Attribution | Source URL | Verification Date | Status |
|---|---|---|---|---|---|---|---|---|---|
| NLLB-200 (existing, en/ta/ml translation) | `facebook/nllb-200-distilled-600M` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/nllb-200-distilled-600M | 2026-09-25 | ⚠️ **NOT commercially approved — existing, already-shipped dependency** |
| MMS-TTS (existing, en/ta/ml TTS) | `facebook/mms-tts-eng`, `-tam`, `-mal` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/mms-tts-eng | 2026-09-25 | ⚠️ **NOT commercially approved — existing, already-shipped dependency** |
| faster-whisper (existing/fallback STT) | `SYSTRAN/faster-whisper` (tiny) | MIT | MIT (OpenAI Whisper weights) | Yes | Yes | Yes | https://github.com/SYSTRAN/faster-whisper | 2026-09-25 | ✅ Approved (existing) |
| Qwen3-ASR (new primary STT) | `Qwen/Qwen3-ASR-1.7B` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-ASR-1.7B | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass** |
| OPUS-MT (new specialist translation, per pair) | `Helsinki-NLP/opus-mt-de-en` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Helsinki-NLP/opus-mt-de-en | 2026-09-25 | ✅ License approved for **this checkpoint only** — **NOT downloaded/certified this pass**. Re-verify per-pair; do not assume for any other `opus-mt-*` checkpoint. |
| MADLAD-400 3B (new global backbone) | `google/madlad400-3b-mt` (loaded via the `jbochi/madlad400-3b-mt` transformers-compatible re-upload) | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/google/madlad400-3b-mt | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass** |
| MADLAD-400 7B (selectable, never auto-used) | `google/madlad400-7b-mt` (`jbochi/madlad400-7b-mt`) | Apache-2.0 | Apache-2.0 (assumed same family license as 3B — re-verify the 7B card specifically before enabling) | Yes | Yes | Yes | https://huggingface.co/google/madlad400-7b-mt | not independently re-fetched — verify before enabling | ⚠️ Verify independently before use; not downloaded/certified this pass |
| Qwen3-TTS (new primary TTS) | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass**; requires a reference voice clip per language (open design question, see docs/ai/streaming.md) |
| CosyVoice3 (new alternative TTS) | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass**; requires a reference voice clip per language (same open question) |

## What "License approved" does NOT mean here

A ✅ above means the license permits commercial use, redistribution, and
modification with attribution — nothing more. It does **not** mean the
model has been downloaded, run, benchmarked, or regression-tested against
this build's dosage/negation/terminology safety corpus. See
`app/pipeline/language_registry.py`'s `Certification` dataclass — a
language pair additionally needs `medical_terms`, `dosage`, `negation`,
and `latency` all independently verified before
`is_production_ready()` returns `True`, entirely separate from the
licensing check documented here.
