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

## Finding: this build's EXISTING, already-shipped models were non-commercial — RESOLVED (license-wise) by switching the default

This was the single most important result of this pass's license audit.
**`facebook/nllb-200-distilled-600M` and `facebook/mms-tts-{eng,tam,mal}` —
the translation and TTS models this codebase shipped since Day 6 — are
both licensed `CC-BY-NC-4.0` (non-commercial).** NLLB-200's own model
card explicitly states it is "not released for production deployment."
This was not previously documented anywhere in this repo and was not
flagged by any earlier license/security pass.

**Action taken this pass**: `app/pipeline/factory.py`'s
`build_default_pipeline()` — the function `app/agent.py` actually uses for
every real session — was switched from NLLB-200/MMS-TTS to MADLAD-400/
Qwen3-TTS (both Apache-2.0), with **no fallback configured back to the old
models**, fully removing them from this pair's production routing. The
same switch was made in `app/pipeline/language_registry.py`'s default
`en<->ta`/`en<->ml` entries.

**This resolves the LICENSING gate, but opens a different, equally real
one: CERTIFICATION.** The prior "certified" status for en<->ta was real
regression evidence (the 75-case safety corpus, a live end-to-end
integration test, a measured latency benchmark) measured against
NLLB-200/MMS-TTS's actual translation output specifically — it does not
transfer to MADLAD-400/Qwen3-TTS's different output without re-running
that same evidence. `language_registry.py` correctly resets en<->ta's
certification to `"testing"` (all flags `False`) rather than carrying the
old status forward. **`LanguageRegistry.is_production_ready("en", "ta")`
is still `False`** — now because of missing certification evidence, not
licensing.

**Also not yet resolved: availability.** MADLAD-400 and Qwen3-TTS are NOT
downloaded in this environment (no GPU, `AI_ALLOW_MODEL_DOWNLOAD=false` by
default) — `build_default_pipeline()` now raises `ModelNotAvailableError`
in this sandbox, and `main.py`'s `/v1/agent/sessions/{id}/start` returns a
clear `503` rather than the pipeline silently falling back to the
non-commercial models. **The AI translation feature does not currently run
in this sandbox as a direct, intended consequence of this change** — see
`tests/test_pipeline_live_integration.py` and
`tests/pipeline/test_pipeline_models.py`, both of which now skip with an
explicit reason rather than passing. It becomes usable again the moment a
real GPU host with `AI_ALLOW_MODEL_DOWNLOAD=true` and these packages
installed exists, and USABLE does not mean CERTIFIED — the safety-corpus
regression run against these specific models is still outstanding work.

`NLLBTranslationProvider`/`MmsTTSProvider` remain in the codebase (other
tests and `StreamingMmsTTSProvider` still use them directly) but are no
longer the default production choice anywhere.

## Matrix

| Model | Checkpoint | Code License | Weights License | Commercial Use | Redistribution | Attribution | Source URL | Verification Date | Status |
|---|---|---|---|---|---|---|---|---|---|
| NLLB-200 (no longer the default translation model) | `facebook/nllb-200-distilled-600M` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/nllb-200-distilled-600M | 2026-09-25 | ⚠️ **NOT commercially approved — removed from `build_default_pipeline()`/en\<->ta registry entry this pass; class remains in the codebase, not the default anywhere** |
| MMS-TTS (no longer the default TTS model) | `facebook/mms-tts-eng`, `-tam`, `-mal` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/mms-tts-eng | 2026-09-25 | ⚠️ **NOT commercially approved — removed from `build_default_pipeline()`/en\<->ta registry entry this pass; still used directly by `StreamingMmsTTSProvider` and some tests, not the production default** |
| faster-whisper (existing/fallback STT) | `SYSTRAN/faster-whisper` (tiny) | MIT | MIT (OpenAI Whisper weights) | Yes | Yes | Yes | https://github.com/SYSTRAN/faster-whisper | 2026-09-25 | ✅ Approved (existing) |
| Qwen3-ASR (new primary STT) | `Qwen/Qwen3-ASR-1.7B` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-ASR-1.7B | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass** |
| OPUS-MT (new specialist translation, per pair) | `Helsinki-NLP/opus-mt-de-en` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Helsinki-NLP/opus-mt-de-en | 2026-09-25 | ✅ License approved for **this checkpoint only** — **NOT downloaded/certified this pass**. Re-verify per-pair; do not assume for any other `opus-mt-*` checkpoint. |
| MADLAD-400 3B (**now the default translation model**) | `google/madlad400-3b-mt` (loaded via the `jbochi/madlad400-3b-mt` transformers-compatible re-upload) | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/google/madlad400-3b-mt | 2026-09-25 | ✅ License approved, **now `build_default_pipeline()`'s translator** — **NOT downloaded/certified this pass**; `build_default_pipeline()` raises `ModelNotAvailableError` in this sandbox as a result |
| MADLAD-400 7B (selectable, never auto-used) | `google/madlad400-7b-mt` (`jbochi/madlad400-7b-mt`) | Apache-2.0 | Apache-2.0 (assumed same family license as 3B — re-verify the 7B card specifically before enabling) | Yes | Yes | Yes | https://huggingface.co/google/madlad400-7b-mt | not independently re-fetched — verify before enabling | ⚠️ Verify independently before use; not downloaded/certified this pass |
| Qwen3-TTS (**now the default TTS model**) | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base | 2026-09-25 | ✅ License approved, **now `build_default_pipeline()`'s TTS provider** — **NOT downloaded/certified this pass**; still requires a reference voice clip per language (open design question, see docs/ai/streaming.md) even once downloaded |
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
