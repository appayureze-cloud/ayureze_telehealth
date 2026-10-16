# Streaming pipeline latency

Real measurements only — nothing below is estimated or extrapolated.
Methodology: `time.perf_counter()` around each call, model load time
excluded (loaded once before timing loops start, per build spec section
17), median of repeated calls reported as P50 (20-200 iterations
depending on call cost; see the exact counts inline). Measured on this
sandbox's CPU (no GPU — see "What was not measured" below).

## Old sequential pipeline (baseline, for comparison — unchanged by this pass)

```
VAD             P50 0.39 ms
STT          P50 1055.9 ms
Language ID     P50 0.25 ms
Terminology     P50 0.07 ms
Translation  P50 1345.3 ms
Safety          P50 0.30 ms
TTS            P50 898.6 ms
--------------------------------
TOTAL         P50 2718 ms
```

This is the same historical number this task's own spec cited — this pass
did not re-benchmark the OLD pipeline, since it is unchanged.

## New streaming components (measured this pass, CPU only)

| Component | P50 | P95 | Notes |
|---|---|---|---|
| `TranscriptStabilityFilter` (8-word growing utterance, full update cycle) | 0.011 ms | 0.015 ms | Pure Python, deterministic |
| `CommitPolicy` (single punctuation-triggered commit) | 0.0011 ms | 0.0018 ms | Pure Python, deterministic |
| `SafetyCommitPolicy.evaluate` (real dosage-matched case) | 0.19 ms | 0.29 ms | Wraps the existing real `safety.validate()` — consistent with Day 6's own 0.13-0.16ms measurement |
| `StreamingFasterWhisperSTT.push_audio` (1s ASR chunk, re-decode of buffer so far) | 511.8 ms | 576.9 ms | Cost scales with buffer length so far (re-decode design, documented limitation — see streaming.md) |
| `StreamingFasterWhisperSTT.finalize` (full 11s clip) | 1230.8 ms | — (single run) | One real decode of the whole utterance |
| NLLB-200 translation (short sentence, existing model, re-measured) | 907.0 ms | 1322.2 ms | Consistent with Day 6's 1345.3ms figure within normal CPU inference variance |
| `StreamingMmsTTSProvider` first chunk | 1286.5 ms | — (single run) | **Equals total synthesis time — see finding below** |
| `StreamingMmsTTSProvider` total (7 chunks, ~500ms each) | 1286.5 ms | — (single run) | |

### Real finding: MMS-TTS streaming does not reduce first-audio latency

`StreamingMmsTTSProvider`'s first-chunk latency and total latency are
identical in this measurement. This is expected and honestly documented
in the class's own docstring (`app/pipeline/tts.py`): VITS is
non-autoregressive — it produces the ENTIRE waveform in one inference
call, not incrementally — so chunking its output after the fact gives the
audio-output buffer ordering and mid-utterance cancellability (real
barge-in benefits, see `test_streaming_tts.py`'s cancellation test) but
**no reduction in time-to-first-audio** versus the old pipeline's
`MmsTTSProvider.synthesize()`. Achieving the build spec's ~1-1.5s
first-audio target with genuinely incremental TTS generation requires one
of the new GPU models (Qwen3-TTS's advertised "Extreme Low-Latency
Streaming Generation," or CosyVoice3's documented `stream=True` flag) —
neither of which is downloaded/measured in this environment (see below).

### Real finding: streaming STT via periodic re-decode has a real, quantified cost

`StreamingFasterWhisperSTT` re-decodes the ENTIRE buffer-so-far on every
`push_audio()` call (no incremental decode state in faster-whisper's
public API — documented in the class's own docstring). The 1-second-chunk
measurement above (511.8ms) is against a short buffer; this cost grows
with utterance length, since each call re-transcribes more audio than the
last. This is real, working streaming ASR (partial hypotheses genuinely
improve as more audio arrives — see `test_streaming_stt.py`), but is a
CPU-bound re-decode strategy, not O(1)-per-chunk true streaming. Qwen3-ASR
would remove this cost if its actual streaming backend (vLLM, per its own
model card — see docs/models.md) were stood up; not done in this pass.

## Primary metrics (build spec section 20)

**Time to first translated audio** and **complete utterance latency**
cannot be honestly reported end-to-end for the NEW streaming pipeline in
this pass: `StreamingSessionPipeline` (`app/pipeline/streaming_pipeline.py`)
is unit-tested against FAKE translation/TTS providers (see
`test_streaming_pipeline.py`) precisely so its queueing/backpressure/
barge-in/safety-hold logic could be verified without needing GPU
infrastructure this sandbox doesn't have — it has NOT been run end-to-end
with real STT+translation+TTS providers together, live or otherwise. See
"What was not measured" below.

A rough, explicitly-labeled composition using only the REAL numbers above
(NOT a live end-to-end measurement, added together for a first-order
estimate only):

```
streaming_stt_first_push (1s chunk) ~512ms
  + nllb_translation                ~907ms
  + safety_commit_policy            ~0.2ms
  + streaming_tts_first_chunk      ~1287ms
  ------------------------------------------
  ~2706ms   (composed estimate, NOT measured end-to-end)
```

This is barely different from the old pipeline's 2718ms — expected, since
every model in this composition IS the old pipeline's model (NLLB, MMS-TTS,
faster-whisper); the streaming ARCHITECTURE's own overhead
(stability filter + commit policy + safety commit policy) is genuinely
negligible (~0.4ms total, from the real component measurements above), but
none of the NEW GPU models that could actually reduce first-audio latency
were measured. **The build spec's ~1-1.5s first-audio / ~2-3s final-latency
targets are unreachable with this build's current CPU-only, existing-model
composition** — reaching them requires the new GPU-resident models this
pass could not download or run.

## What was not measured (and why)

- **Qwen3-ASR, MADLAD-400 (3B/7B), OPUS-MT, Qwen3-TTS, CosyVoice3**: none
  downloaded (`AI_ALLOW_MODEL_DOWNLOAD=false` by default this pass, per
  explicit instruction not to download models) or run. No GPU exists in
  this sandbox (`nvidia-smi`: not found; `torch.cuda.is_available()`:
  cannot even import torch with CUDA support) — every one of these models
  is GPU-only per its own documentation (build spec section 18 puts them
  all on a "GPU server").
- **First-token/first-audio latency for the new models' actual streaming
  backends** (Qwen3-ASR's vLLM backend, Qwen3-TTS/CosyVoice3's native
  streaming) — not verified to even exist with a documented call
  signature for Qwen3-TTS specifically (see docs/models.md); would need
  real GPU hardware to measure regardless.
- **`ayureze_gpu_utilization` / `ayureze_gpu_memory_used`**: metrics are
  declared (`app/metrics.py`) but never observed — there is no GPU
  workload in this build to measure.
- **Concurrent-session capacity**: not load-tested this pass (the
  existing Day 7 load test targeted the old pipeline only).
- **End-to-end streaming pipeline latency with real providers**: as
  above — `StreamingSessionPipeline` is real and tested, but only against
  fakes.
