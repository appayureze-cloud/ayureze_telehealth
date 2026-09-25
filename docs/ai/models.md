# Model providers reference

Every STT/translation/TTS provider class in `app/pipeline/`, what it
implements, and its real, current status in this build. See
`docs/MODEL_LICENSE_MATRIX.md` for licensing and
`docs/ai/language-registry.md` for how a language pair chooses between
these.

## STT

| Class | File | Status | Notes |
|---|---|---|---|
| `FasterWhisperSTT` | `stt.py` | ✅ Existing, live-verified | Whole-utterance, non-streaming. The current default and the only STT path wired into the live LiveKit audio pipeline. |
| `StreamingFasterWhisperSTT` | `stt.py` | ✅ New, real, tested against real audio | Streaming wrapper around the SAME model as above — periodic re-decode of the growing buffer (not O(1) incremental; faster-whisper's public API has no incremental decode state). See `docs/ai/latency.md` for its real measured cost growth. |
| `Qwen3ASRProvider` | `stt.py` | ⚠️ Written, not downloaded/run | `Qwen/Qwen3-ASR-1.7B`. GPU-only per its own docs; true streaming needs a separate vLLM backend, not the `transformers`-style path this class implements. `load()` raises `ModelNotAvailableError` in this build (no GPU, `AI_ALLOW_MODEL_DOWNLOAD=false`). Not yet switched into `build_default_pipeline()` — STT default is still `FasterWhisperSTT`. |

## Translation

| Class | File | Status | Notes |
|---|---|---|---|
| `MADLADProvider` | `translation.py` | 🔄 **Now `build_default_pipeline()`'s translator** — not downloaded/run | `jbochi/madlad400-{3b,7b}-mt` (transformers-compatible re-uploads of `google/madlad400-*-mt`, Apache-2.0). 3B is the config default; 7B is selectable, never auto-chosen. `build_default_pipeline()` calls `.load()` eagerly and raises `ModelNotAvailableError` in this sandbox (no GPU) — see `docs/MODEL_LICENSE_MATRIX.md`. |
| `OPUSMTProvider` | `translation.py` | ⚠️ Written, not downloaded/run | Per-language-pair `Helsinki-NLP/opus-mt-<src>-<tgt>` checkpoints. License verified for `opus-mt-de-en` specifically (Apache-2.0) — re-verify per pair before certifying any other. Not wired into `build_default_pipeline()`. |
| `NLLBTranslationProvider` | `translation.py` | ⚠️ No longer the default | `facebook/nllb-200-distilled-600M`. **CC-BY-NC-4.0 — non-commercial.** Removed from `build_default_pipeline()` and the language registry's en\<->ta entry this pass (see `docs/MODEL_LICENSE_MATRIX.md`) — class remains in the codebase but is not used as a default anywhere. |

## TTS

| Class | File | Status | Notes |
|---|---|---|---|
| `Qwen3TTSProvider` | `tts.py` | 🔄 **Now `build_default_pipeline()`'s TTS provider** — not downloaded/run | `Qwen/Qwen3-TTS-12Hz-1.7B-Base`. Advertises real streaming ("Extreme Low-Latency Streaming Generation") but no distinct streaming method signature is publicly documented as of verification date — this class implements the documented batch `generate_voice_clone()` path, plus a `.synthesize()` adapter (consumes its own `.stream()` to completion) so it satisfies the old, non-streaming `TTSProvider` interface `build_default_pipeline()` needs. Requires a reference voice clip per language (open design question, see `docs/ai/streaming.md`) — `build_default_pipeline()` doesn't supply one, so `load()` fails on that ground even before the GPU/download check would matter. |
| `StreamingMmsTTSProvider` | `tts.py` | ✅ New, real, tested against real audio | Wraps `MmsTTSProvider` — synthesizes the FULL utterance (VITS is non-autoregressive), then chunks the output for ordered/cancellable delivery. **Does not reduce first-audio latency** — see `docs/ai/latency.md`'s real finding. Independent of the default-pipeline switch above (used by the new streaming architecture, not `build_default_pipeline()`). |
| `MmsTTSProvider` | `tts.py` | ⚠️ No longer the default | `facebook/mms-tts-{eng,tam,mal}`. **CC-BY-NC-4.0 — non-commercial.** Removed from `build_default_pipeline()` this pass; still used directly by `StreamingMmsTTSProvider` and by some tests as a synthetic "microphone" input generator (not as the pipeline's own TTS output). |
| `CosyVoice3Provider` | `tts.py` | ⚠️ Written, not downloaded/run | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`. Has a REAL documented `stream=True` flag (unlike Qwen3-TTS above), but every inference method requires a reference speaker (same open question), needs a local checkpoint directory (not a bare HF repo id), and needs `third_party/Matcha-TTS` on the Python path. |

## Why "written, not downloaded/run" instead of skipping these entirely

The task instructed implementing the new models' code without downloading
weights (no GPU, and downloads were explicitly out of scope for this
pass). Every such class:

1. Is written against its model's REAL, verified quickstart API (see each
   class's own docstring for the exact verified code sample and
   verification date) — not invented or guessed.
2. Raises `ModelNotAvailableError` from `load()` when weights/GPU/package
   aren't available, with a clear message naming what's missing and what
   the router falls back to.
3. Is wired into `TranslationRouter`/`TTSRouter` behind the language
   registry's certification gate, so a router can never silently use one
   of these as if it were verified.

This means the moment real GPU infrastructure and `AI_ALLOW_MODEL_DOWNLOAD=true`
exist, these classes are ready to actually load and run without further
code changes — the remaining work at that point is certification
(regression-testing against the safety corpus) and the two open design
questions in `docs/ai/streaming.md`, not re-writing provider code.
