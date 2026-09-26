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

**Four more TTS candidates investigated for CPU-friendly, commercially-safe
audio**:
- **k2-fsa/OmniVoice — REJECTED**: codebase is Apache-2.0, but its
  **pretrained weights are `CC-BY-NC`** — "due to constraints from its
  training data (e.g., Emilia)" per its own model card. Same
  non-commercial problem as NLLB/MMS-TTS. Also GPU-oriented, and Tamil
  support isn't explicitly confirmed in its documented language list.
- **Kokoro-82M and Bark — REJECTED (checked per an explicit request for
  internationally-recognized, not region-specific, projects)**: both are
  genuinely global, well-known, permissively-licensed (Apache-2.0 / MIT)
  projects — but **neither supports Tamil at all**, confirmed directly
  against their documentation and (for Bark) the project's own GitHub
  discussions.
- **ai4bharat/indic-parler-tts — WIRED IN
  (`AI_TTS_BACKEND=indic-parler-tts`)**: Apache-2.0, confirmed
  commercially clean, confirmed real Tamil support via named speakers, a
  documented CPU fallback path. The honest tradeoff is unverified CPU
  latency (0.9B params — expected multi-second per utterance, not
  real-time) and that AI4Bharat is a regional (India-focused) research
  lab rather than a globally-branded one — its Apache-2.0 license is
  exactly as legally valid and enforceable internationally as any other
  Apache-2.0 project regardless of where it was built.
- **Piper — PARTIALLY WIRED IN (`AI_TTS_BACKEND=piper`)**: the ENGINE is a
  genuinely international, general-purpose open-source project (used
  worldwide in Home Assistant, NVDA, Mycroft), MIT-licensed in its
  archived form (current successor is GPL-3.0 — see the matrix row
  below). `PiperTTSProvider` invokes it via CLI subprocess only, never as
  an imported Python library, to stay safe under either license. The
  REAL, UNRESOLVED gap is separate: the specific community-contributed
  Tamil voice checkpoint's dataset license could not be verified despite
  real research effort — `PiperTTSProvider.metadata()` reports
  `commercial_use=False` for exactly this reason, and it should not be
  enabled in production until that specific question is resolved (or a
  different, verified voice checkpoint is substituted).

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

## 2026-09-26 update: OPUS-MT and Piper actually downloaded and run — real, CPU-only, no VPS

This sandbox's own container is CPU-only, so it is a genuine stand-in for
the actual CPU-only VPS deployment target for the two backends that don't
need a GPU at all (`opus-mt`, `piper`). With `AI_ALLOW_MODEL_DOWNLOAD=true`
set explicitly for this pass, both were actually downloaded and exercised
against real input, not just written against documentation:

- **OPUS-MT (`Helsinki-NLP/opus-mt-en-dra` + `opus-mt-dra-en`)**:
  downloaded and run for real, on CPU. `test_pipeline_models.py`'s three
  real-model integration tests now pass against this actual checkpoint
  (previously they only skipped, since no model was ever downloaded).
  Concrete findings from real output, not speculation:
  - **Negation is confirmed working**: "Do not take this medicine."
    round-trips through translation and the safety validator's negation
    comparison correctly, for real.
  - **A real terminology-recognition gap was found and fixed**:
    `terminology.py`'s Tamil "daily"/"every day" word lists were curated
    only against NLLB-200's typical phrasing (தினமும், தினசரி, etc.) and
    did not recognize OPUS-MT's own real phrasing ("நாளும்", as in
    "ஒவ்வொரு நாளும்" = "every single day") — this caused a FALSE POSITIVE
    safety block on a translation that was actually semantically correct.
    Fixed by adding "நாளும்" to both word lists; verified against real
    model output; the existing 88-case terminology/safety unit suite still
    passes with zero regressions.
  - **A real, unresolved medical-vocabulary mistranslation was found and
    is correctly caught, not fixed**: OPUS-MT translates "tablet(s)" to
    "பலகை"/"மேசை" (board/table) instead of the correct "மாத்திரை", and
    this is non-deterministic — two near-identical runs of the same
    sentence produced two different wrong nouns, and one run additionally
    dropped "twice" from "twice daily" entirely. The safety validator's
    dosage/unit and frequency comparisons correctly detected and BLOCKED
    both cases end-to-end against the real model (proving the fail-closed
    design genuinely works, not just in unit tests with synthetic
    mismatches) — but this means real digit/count-bearing dosage
    instructions will often be silently blocked (no audio, no caption)
    rather than actually delivered, which is a real functional limitation
    of OPUS-MT for medical use, not a bug in this codebase. Certification
    (`language_registry.py`) stays "testing", not "certified", for exactly
    this reason.
  - **Tamil->English (`ta_en`) was spot-checked, not certified**: a single
    hand-crafted Tamil medical sentence produced a badly garbled, unrelated
    English translation. Left as an open question — one data point isn't
    enough to say whether that's the specific input's phrasing or a real
    `ta_en` model weakness; `language_registry.py`'s `ta_en` entry
    reflects this honestly (all certification flags False, licensed but
    not certified).
- **Piper engine**: `piper-tts` v1.8.0 installed globally (never imported
  into the app's own venv, per the subprocess-only design above) and
  exercised for real via `PiperTTSProvider.synthesize()` against a small,
  well-known, disk-cheap English voice (`en_US-lessac-medium`) — the
  legally-unverified Tamil voice checkpoint was deliberately NOT
  downloaded or used, since its license question (see the matrix row
  below) remains genuinely unresolved. Produced real, correct, non-silent
  audio (RMS ≈0.135). Measured CPU synthesis latency over 5 runs of a
  representative dosage sentence: **median ≈1.41s, range 1.30–1.43s**
  (single utterance, no batching, no GPU) — confirms Piper is genuinely
  fast enough for interactive use once a commercially-clear voice
  checkpoint is available; it is the engine's speed being verified here,
  not the unverified Tamil voice's suitability.
- **`ai4bharat/indic-parler-tts` was deliberately NOT downloaded this
  pass**: at ~0.9B parameters its real on-disk footprint is estimated at
  4GB+, and this sandbox's own writable-disk allowance had only ~3.8-4.1GB
  free after the OPUS-MT downloads above — attempting it risked a
  corrupted partial download or exhausting the sandbox outright for no
  test benefit. This is an honest resource constraint, not a finding about
  the model itself; it remains wired in and ready to actually test the
  moment more disk (or real VPS/GPU infrastructure) is available.

## Matrix

| Model | Checkpoint | Code License | Weights License | Commercial Use | Redistribution | Attribution | Source URL | Verification Date | Status |
|---|---|---|---|---|---|---|---|---|---|
| NLLB-200 (no longer the default translation model) | `facebook/nllb-200-distilled-600M` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/nllb-200-distilled-600M | 2026-09-25 | ⚠️ **NOT commercially approved — removed from `build_default_pipeline()`/en\<->ta registry entry; class remains in the codebase, not the default anywhere** |
| MMS-TTS (no longer the default TTS model) | `facebook/mms-tts-eng`, `-tam`, `-mal` | MIT (transformers) | **CC-BY-NC-4.0** | **NO** | Yes (non-commercial) | Yes | https://huggingface.co/facebook/mms-tts-eng | 2026-09-25 | ⚠️ **NOT commercially approved — removed from `build_default_pipeline()`/en\<->ta registry entry; still used directly by `StreamingMmsTTSProvider` and some tests, not the production default** |
| faster-whisper (existing/fallback STT) | `SYSTRAN/faster-whisper` (tiny) | MIT | MIT (OpenAI Whisper weights) | Yes | Yes | Yes | https://github.com/SYSTRAN/faster-whisper | 2026-09-25 | ✅ Approved (existing, still the only STT provider `build_default_pipeline()` uses) |
| Qwen3-ASR (new primary STT) | `Qwen/Qwen3-ASR-1.7B` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-ASR-1.7B | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass**; not wired into `build_default_pipeline()` |
| **OPUS-MT en\<->Dravidian (`AI_TRANSLATION_BACKEND=opus-mt`, the default)** | `Helsinki-NLP/opus-mt-en-dra` (en->ta/ml, needs a `>>tam<<`/`>>mal<<` target tag) and `opus-mt-dra-en` (ta/ml->en) | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Helsinki-NLP/opus-mt-en-dra | 2026-09-25 | ✅ License approved AND genuinely **CPU-feasible** — **actually downloaded and run on CPU 2026-09-26** (no VPS, this sandbox stood in for one); real output confirmed negation works and surfaced/fixed a Tamil terminology gap, but also confirmed a real, unresolved "tablet"->board/table mistranslation — see the 2026-09-26 update above. Still NOT certified (`language_registry.py` stays "testing") |
| OPUS-MT per-pair specialist (e.g. de->en) | `Helsinki-NLP/opus-mt-de-en` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Helsinki-NLP/opus-mt-de-en | 2026-09-25 | ✅ License approved for **this checkpoint only** — **NOT downloaded/certified this pass**. Re-verify per-pair; do not assume for any other `opus-mt-*` checkpoint. |
| MADLAD-400 3B (`AI_TRANSLATION_BACKEND=madlad`, GPU-path alternative) | `google/madlad400-3b-mt` (loaded via the `jbochi/madlad400-3b-mt` transformers-compatible re-upload) | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/google/madlad400-3b-mt | 2026-09-25 | ✅ License approved but **GPU-only** per its own docs — selectable, not the default; **NOT downloaded/certified this pass** |
| MADLAD-400 7B (selectable, never auto-used) | `google/madlad400-7b-mt` (`jbochi/madlad400-7b-mt`) | Apache-2.0 | Apache-2.0 (assumed same family license as 3B — re-verify the 7B card specifically before enabling) | Yes | Yes | Yes | https://huggingface.co/google/madlad400-7b-mt | not independently re-fetched — verify before enabling | ⚠️ Verify independently before use; not downloaded/certified this pass |
| Qwen3-TTS (`AI_TTS_BACKEND=qwen3-tts`, GPU-path alternative) | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base | 2026-09-25 | ✅ License approved but **GPU-only** — selectable, not the default (default is `none`/captions-only); **NOT downloaded/certified this pass**; still requires a reference voice clip per language even once downloaded |
| CosyVoice3 (alternative TTS, not wired into a config backend) | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 | 2026-09-25 | ✅ License approved — **NOT downloaded/certified this pass**; requires a reference voice clip per language (same open question) |
| k2-fsa/OmniVoice (investigated, REJECTED for CPU-friendly TTS) | `k2-fsa/OmniVoice` | Apache-2.0 (code) | **CC-BY-NC** (pretrained weights) | **NO** | Restricted | Yes | https://huggingface.co/k2-fsa/OmniVoice | 2026-09-25 | ❌ **NOT commercially approved** — weights license restricted by training data (e.g. Emilia dataset) despite an Apache-2.0 codebase; also GPU-oriented (no documented CPU path) and Tamil support unconfirmed |
| **ai4bharat/indic-parler-tts (`AI_TTS_BACKEND=indic-parler-tts`, wired in)** | `ai4bharat/indic-parler-tts` (0.9B params) | Apache-2.0 | Apache-2.0 | Yes | Yes | Yes | https://huggingface.co/ai4bharat/indic-parler-tts | 2026-09-25 | ✅ **License approved AND CPU-capable** (own example code has a documented CPU fallback path) — confirmed real Tamil support via named speakers ("Jaya"/"Kavitha"), no reference-voice-clip requirement. **NOT downloaded/benchmarked this pass** — CPU latency expected multi-second per utterance (0.9B params), not verified |
| **Piper — ENGINE only (`AI_TTS_BACKEND=piper`, wired in)** | `rhasspy/piper` (archived, last release) or `OHF-Voice/piper1-gpl` (current) | **MIT** (archived rhasspy/piper, verified 2026-09-25) — current successor is **GPL-3.0** | N/A (engine, not weights) | Yes (MIT) / Yes-with-copyleft (GPL-3.0) | Yes | Yes | https://github.com/rhasspy/piper / https://github.com/OHF-Voice/piper1-gpl | 2026-09-25 | ✅ Engine license is fine either way **PROVIDED it is invoked via CLI subprocess only, never imported as a Python library** (`PiperTTSProvider` in `tts.py` does this deliberately) — GPL-3.0's copyleft attaches to linking/derivative works, not separate-process invocation ("mere aggregation", the same pattern commercial products use for other GPL CLI tools like ffmpeg builds). **Engine mechanics actually verified 2026-09-26** against a small, commercially-clean, non-Tamil voice (`en_US-lessac-medium`, deliberately not the unverified Tamil voice below) — real audio out, median ≈1.41s CPU synthesis latency per utterance |
| **Piper — Tamil VOICE checkpoint (`ta_IN-Valluvar-medium.onnx`)** | `rhasspy/piper-voices` (ta_IN) | N/A | **UNVERIFIED** — its own listing defers to "the original dataset license," which could not be identified despite real research effort this pass | **UNKNOWN** | Unknown | Unknown | https://huggingface.co/rhasspy/piper-voices | 2026-09-25 | ⚠️ **Unknown = NOT APPROVED.** This is SEPARATE from the engine question above — the engine being safe to invoke does not make an unverified voice checkpoint's dataset license safe. `PiperTTSProvider.metadata()` deliberately reports `commercial_use=False` for this reason. **Do not enable in production without resolving this specific question** (contact the voice's uploader/dataset source, or use a different, verified voice checkpoint). |

### Rejected as "internationally recognized but no Tamil support"

Investigated per an explicit request for a globally-recognized (not
region-specific) open-source TTS project. Both are genuinely
international, well-known, and permissively licensed — but neither
supports Tamil at all, confirmed directly:

| Model | License | Tamil support |
|---|---|---|
| Kokoro-82M (`hexgrad/Kokoro-82M`) | Apache-2.0 | ❌ Confirmed NOT supported (8 languages: English/Chinese/Japanese/Spanish/French/Hindi/Italian/Portuguese) |
| Bark (`suno-ai/bark`) | MIT | ❌ Confirmed NOT supported (community has requested it in the project's own GitHub discussions; never shipped) |

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
