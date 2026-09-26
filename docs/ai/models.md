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

`build_default_pipeline()`'s backend is deploy-time selectable via
`app/config.py`'s `AI_TRANSLATION_BACKEND` (`_build_translator()` in
`factory.py`) — neither option removes the other from the codebase.

| Class | File | Status | Notes |
|---|---|---|---|
| `OPUSMTProvider` (via `_DirectionalOpusMT`) | `translation.py` / `factory.py` | 🔄 **`AI_TRANSLATION_BACKEND=opus-mt`, the default** — not downloaded/run in this sandbox | `Helsinki-NLP/opus-mt-en-dra` (en->ta/ml, `>>tam<</>>mal<<` target tag) + `opus-mt-dra-en` (ta/ml->en). Apache-2.0, small MarianMT models — genuinely CPU-feasible, unlike MADLAD's 3B params. `_DirectionalOpusMT` in `factory.py` dispatches between the two single-direction `OPUSMTProvider` instances by `(source_lang, target_lang)`. |
| `MADLADProvider` | `translation.py` | 🔄 `AI_TRANSLATION_BACKEND=madlad` — selectable GPU-path alternative, not downloaded/run | `jbochi/madlad400-{3b,7b}-mt` (Apache-2.0). GPU-only per its own docs — select this once real GPU infrastructure exists. |
| `NLLBTranslationProvider` | `translation.py` | ⚠️ No longer a `build_default_pipeline()` option | `facebook/nllb-200-distilled-600M`. **CC-BY-NC-4.0 — non-commercial.** Class remains in the codebase but isn't wired into either selectable backend. |

## TTS

`AI_TTS_BACKEND` selects between `none` (default, captions-only),
`qwen3-tts`, `indic-parler-tts`, and `piper`.

| Class | File | Status | Notes |
|---|---|---|---|
| *(none — captions-only)* | `orchestrator.py` | 🔄 **`AI_TTS_BACKEND=none`, the default** | `TranslationPipeline(tts=None)` — transcription/translation/safety all run for real; `PipelineResult.audio` is always `None`. |
| `IndicParlerTTSProvider` | `tts.py` | 🔄 `AI_TTS_BACKEND=indic-parler-tts` — selectable, not downloaded/benchmarked | `ai4bharat/indic-parler-tts` (0.9B). Apache-2.0, confirmed commercially clean, confirmed Tamil support via named speakers ("Jaya"/"Kavitha") — no reference-voice-clip requirement, unlike Qwen3-TTS/CosyVoice3. Has a documented CPU fallback path but CPU latency is unverified (expected multi-second per utterance at 0.9B params). Needs the separate `parler-tts` package. |
| `PiperTTSProvider` | `tts.py` | 🔄 `AI_TTS_BACKEND=piper` — selectable, not downloaded/benchmarked | Invoked via CLI subprocess only (`piper --model <voice.onnx> ...`), **never imported as a Python library** — deliberately, since the actively-maintained successor (`OHF-Voice/piper1-gpl`) is GPL-3.0 while the archived original is MIT; subprocess invocation is safe under either. Genuinely CPU-fast by design. **The specific Tamil voice checkpoint's dataset license is unverified** — `metadata().commercial_use` is deliberately `False` for this reason. Do not enable in production without resolving that first. |
| `Qwen3TTSProvider` | `tts.py` | 🔄 `AI_TTS_BACKEND=qwen3-tts` — selectable GPU-path alternative, not downloaded/run | `Qwen/Qwen3-TTS-12Hz-1.7B-Base`. Advertises real streaming ("Extreme Low-Latency Streaming Generation") but no distinct streaming method signature is publicly documented as of verification date — this class implements the documented batch `generate_voice_clone()` path, plus a `.synthesize()` adapter (consumes its own `.stream()` to completion) so it satisfies the old, non-streaming `TTSProvider` interface `build_default_pipeline()` needs. Requires a reference voice clip per language (`AI_TTS_REFERENCE_AUDIO_PATH`/`AI_TTS_REFERENCE_TEXT` — open design question, see `docs/ai/streaming.md`). |
| `StreamingMmsTTSProvider` | `tts.py` | ✅ New, real, tested against real audio | Wraps `MmsTTSProvider` — synthesizes the FULL utterance (VITS is non-autoregressive), then chunks the output for ordered/cancellable delivery. **Does not reduce first-audio latency** — see `docs/ai/latency.md`'s real finding. Used by the new streaming architecture, not `build_default_pipeline()`. |
| `MmsTTSProvider` | `tts.py` | ⚠️ No longer a `build_default_pipeline()` option | `facebook/mms-tts-{eng,tam,mal}`. **CC-BY-NC-4.0 — non-commercial.** Still used directly by `StreamingMmsTTSProvider` and by some tests as a synthetic "microphone" input generator (not as the pipeline's own TTS output). |
| `CosyVoice3Provider` | `tts.py` | ⚠️ Written, not wired into a config backend, not downloaded/run | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`. Has a REAL documented `stream=True` flag (unlike Qwen3-TTS above), but every inference method requires a reference speaker (same open question), needs a local checkpoint directory (not a bare HF repo id), and needs `third_party/Matcha-TTS` on the Python path. |
| k2-fsa/OmniVoice, Kokoro-82M, Bark | — (not implemented) | ❌ Investigated and rejected | See `docs/MODEL_LICENSE_MATRIX.md` — OmniVoice's pretrained weights are CC-BY-NC despite Apache-2.0 code; Kokoro/Bark are internationally well-known and permissively licensed but confirmed to not support Tamil at all. No provider class written for any of these. |

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
