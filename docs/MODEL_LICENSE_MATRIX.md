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

## Finding: this build's EXISTING, already-shipped models were non-commercial — RESOLVED (license-wise) by making the default backend both commercial AND CPU-feasible

This was the single most important result of this pass's license audit.
**`facebook/nllb-200-distilled-600M` and `facebook/mms-tts-{eng,tam,mal}` —
the translation and TTS models this codebase shipped since Day 6 — are
both licensed `CC-BY-NC-4.0` (non-commercial).** NLLB-200's own model
card explicitly states it is "not released for production deployment."
This was not previously documented anywhere in this repo and was not
flagged by any earlier license/security pass.

**Action taken, in two rounds**: the first fix pointed
`build_default_pipeline()` at MADLAD-400/Qwen3-TTS (Apache-2.0) — correct
on licensing, but both are **GPU-only** per their own docs, and this
build's actual deployment target turned out to be a **CPU-only VPS**.
`build_default_pipeline()` was made deploy-time SELECTABLE instead
(`app/config.py`'s `AI_TRANSLATION_BACKEND`/`AI_TTS_BACKEND`), with
`opus-mt` (`Helsinki-NLP/opus-mt-en-dra`/`opus-mt-dra-en`, Apache-2.0,
small MarianMT models, genuinely CPU-feasible) as the new **default**
translation backend, and `madlad` kept available as the GPU-path
alternative — nothing removed, both real options. TTS defaults to `none`
(captions-only): no candidate found so far is both commercially licensed
AND CPU-feasible — see below. The same default was applied in
`app/pipeline/language_registry.py`'s `en<->ta`/`en<->ml` entries
(primary = opus-mt, fallback = madlad/qwen3-tts).

**Two more candidates investigated for CPU-friendly TTS, both rejected**:
- **k2-fsa/OmniVoice**: codebase is Apache-2.0, but its **pretrained
  weights are `CC-BY-NC`** — "due to constraints from its training data
  (e.g., Emilia)" per its own model card. Same non-commercial problem as
  NLLB/MMS-TTS. Also GPU-oriented (CUDA/Apple Silicon documented, no CPU
  inference path), and Tamil support isn't explicitly confirmed in its
  documented language list.
- **Piper TTS**: engine is MIT and genuinely CPU-fast, but its specific
  Tamil voice model's license depends on the training dataset and is
  unverified/mixed — not confirmed commercially clean without deeper
  per-voice research not done this pass.

**This resolves the LICENSING gate for translation, but opens a different,
equally real one: CERTIFICATION.** The prior "certified" status for
en<->ta was real regression evidence (the 75-case safety corpus, a live
end-to-end integration test, a measured latency benchmark) measured
against NLLB-200's actual translation output specifically — it does not
transfer to OPUS-MT's different output without re-running that same
evidence. `language_registry.py` correctly resets en<->ta's certification
to `"testing"` (all flags `False`) rather than carrying the old status
forward. **`LanguageRegistry.is_production_ready("en", "ta")` is still
`False`** — now because of missing certification evidence, not licensing.

**Availability in THIS sandbox**: none of these models (OPUS-MT included)
are downloaded here — `AI_ALLOW_MODEL_DOWNLOAD=false` by default, no model
is fetched implicitly regardless of backend. `build_default_pipeline()`
raises `ModelNotAvailableError` in this sandbox, and `main.py`'s
`/v1/agent/sessions/{id}/start` returns a clear `503`. **On a real deploy
with `AI_ALLOW_MODEL_DOWNLOAD=true`, the default `opus-mt`/`none` backends
need no GPU and will actually load and run** — this is the meaningful
difference from the MADLAD/Qwen3-TTS default, which would need GPU
infrastructure regardless of that flag. USABLE still does not mean
CERTIFIED — the safety-corpus regression run against OPUS-MT's specific
output is still outstanding work.

`NLLBTranslationProvider`/`MmsTTSProvider` remain in the codebase (other
tests and `StreamingMmsTTSProvider` still use them directly) but are the
default nowhere. `MADLADProvider`/`Qwen3TTSProvider` also remain fully
intact as the selectable GPU-path backend.

## Matrix

| Model | Checkpoint | Code License | Weights License | Commercial Use | Redistribution | Attribution | Source URL | Verification Date | Status |
|---|---|---|---|---|---|---|---|---|---|
| NLLB-200 (no longer the default translation model) | `facebook/nllb-200-distilled-600M` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/nllb-200-distilled-600M | 2026-09-25 | ⚠️ **NOT commercially approved — removed from `build_default_pipeline()`/en\<->ta registry entry; class remains in the codebase, not the default anywhere** |
| MMS-TTS (no longer the default TTS model) | `facebook/mms-tts-eng`, `-tam`, `-mal` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/mms-tts-eng | 2026-09-25 | ⚠️ **NOT commercially approved — removed from `build_default_pipeline()`/en\<->ta registry entry; still used directly by `StreamingMmsTTSProvider` and some tests, not the production default** |
| faster-whisper (existing/fallback STT) | `SYSTRAN/faster-whisper` (tiny) | MIT | MIT (OpenAI Whisper weights) | Yes | Yes | Yes | https://github.com/SYSTRAN/faster-whisper | 2026-09-25 | ✅ Approved (existing, still the only STT provider `build_default_pipeline()` uses) |
| Qwen3-ASR (new primary STT) | `Qwen/Qwen3-ASR-1.7B` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-ASR-1.7B | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass**; not wired into `build_default_pipeline()` |
| **OPUS-MT en\<->Dravidian (`AI_TRANSLATION_BACKEND=opus-mt`, the default)** | `Helsinki-NLP/opus-mt-en-dra` (en->ta/ml, needs a `>>tam<<`/`>>mal<<` target tag) and `opus-mt-dra-en` (ta/ml->en) | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Helsinki-NLP/opus-mt-en-dra | 2026-09-25 | ✅ License approved AND genuinely **CPU-feasible** (small MarianMT models, not 3B parameters) — **NOT downloaded/certified this pass**, but no GPU is needed once it is |
| OPUS-MT per-pair specialist (e.g. de->en) | `Helsinki-NLP/opus-mt-de-en` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Helsinki-NLP/opus-mt-de-en | 2026-09-25 | ✅ License approved for **this checkpoint only** — **NOT downloaded/certified this pass**. Re-verify per-pair; do not assume for any other `opus-mt-*` checkpoint. |
| MADLAD-400 3B (`AI_TRANSLATION_BACKEND=madlad`, GPU-path alternative) | `google/madlad400-3b-mt` (loaded via the `jbochi/madlad400-3b-mt` transformers-compatible re-upload) | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/google/madlad400-3b-mt | 2026-09-25 | ✅ License approved but **GPU-only** per its own docs — selectable, not the default; **NOT downloaded/certified this pass** |
| MADLAD-400 7B (selectable, never auto-used) | `google/madlad400-7b-mt` (`jbochi/madlad400-7b-mt`) | Apache-2.0 | Apache-2.0 (assumed same family license as 3B — re-verify the 7B card specifically before enabling) | Yes | Yes | Yes | https://huggingface.co/google/madlad400-7b-mt | not independently re-fetched — verify before enabling | ⚠️ Verify independently before use; not downloaded/certified this pass |
| Qwen3-TTS (`AI_TTS_BACKEND=qwen3-tts`, GPU-path alternative) | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base | 2026-09-25 | ✅ License approved but **GPU-only** — selectable, not the default (default is `none`/captions-only); **NOT downloaded/certified this pass**; still requires a reference voice clip per language even once downloaded |
| CosyVoice3 (alternative TTS, not wired into a config backend) | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass**; requires a reference voice clip per language (same open question) |
| k2-fsa/OmniVoice (investigated, REJECTED for CPU-friendly TTS) | `k2-fsa/OmniVoice` | Apache-2.0 (code) | **CC-BY-NC** (pretrained weights) | **NO** | Restricted | Yes | https://huggingface.co/k2-fsa/OmniVoice | 2026-09-25 | ❌ **NOT commercially approved** — weights license restricted by training data (e.g. Emilia dataset) despite an Apache-2.0 codebase; also GPU-oriented (no documented CPU path) and Tamil support unconfirmed |
| Piper TTS (investigated, license unverified for the relevant voice) | Piper engine (MIT) + a Tamil voice model | MIT (engine) | **Unverified/mixed** (per-voice, depends on training dataset) | Unverified | Unverified | Depends on voice | https://huggingface.co/rhasspy/piper-voices | 2026-09-25 | ⚠️ **Unknown = NOT APPROVED** for the Tamil voice specifically — engine itself is genuinely CPU-fast and MIT-licensed; would need dataset-level license research on the specific voice before use |

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
