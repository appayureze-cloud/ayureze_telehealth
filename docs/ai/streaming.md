# Streaming translation pipeline architecture

This document describes the NEW streaming pipeline added alongside (not
replacing) the existing whole-utterance pipeline documented in
`docs/ai/README.md`. It is **opt-in and off by default**
(`AI_AGENT_STREAMING_PIPELINE_ENABLED=false`) — the existing pipeline
remains the default, live-verified path per this task's own explicit
instruction: "Do NOT remove existing working functionality" / "Do not
delete the existing implementation until [new] passes equivalent
regression tests."

## Why a separate pipeline, not a rewrite in place

The existing pipeline (`app/pipeline/orchestrator.py` +
`app/pipeline/streaming.py`'s `LiveAudioProcessor`) is the ONLY
live-verified, real end-to-end path in this codebase (`pytest -m
integration -v tests/test_pipeline_live_integration.py`, 4/4 consecutive
real passes as of this pass). Rewriting it in place, before the new
architecture had any test coverage of its own, would have put that
verification at risk for the entire duration of this work. Instead:

- Every new component (`stability_filter.py`, `commit_policy.py`,
  `safety_commit_policy.py`, `language_registry.py`,
  `translation_router.py`, `tts_router.py`, `audio_output_buffer.py`,
  `streaming_pipeline.py`, the new provider classes in `stt.py`/
  `translation.py`/`tts.py`) is unit-tested in isolation.
- `StreamingSessionPipeline` (the component that ties all of the above
  together into one asyncio-queue-based worker chain) is tested against
  FAKE translation/TTS providers — the same pattern this repo already
  uses for `test_tts_gate.py` — so its queueing, backpressure, barge-in,
  and safety-hold-and-merge logic is verified without needing real model
  weights or GPU infrastructure.
- It has **not** been wired into `LiveAudioProcessor`'s live LiveKit audio
  path, and has **not** been run end-to-end against a real LiveKit room.
  That integration point is a small, well-defined change (replacing
  `LiveAudioProcessor._process_segment`'s single
  `self._pipeline.process_auto(...)` call with
  `StreamingSessionPipeline.submit_committed_phrase(...)` calls fed by a
  streaming STT provider) — deliberately left for a follow-up pass with
  its own live-integration test, rather than claimed as done without one.

## Data flow

```
continuous audio (LiveKit AudioStream)
  -> VAD frames (Silero, existing vad.py, unchanged)
  -> ASR-processing chunks (320-640ms; StreamingSTTProvider.push_audio)
  -> PartialTranscript (growing hypothesis)
  -> TranscriptStabilityFilter (newly-stable word delta)
  -> CommitPolicy (punctuation / silence / stable-N-updates / phrase
     boundary / max-duration / end-of-utterance -> CommittedPhrase)
  -> translation_queue (bounded, asyncio.Queue)
  -> TranslationRouter (language registry -> certified specialist or
     backbone model; fails closed if uncertified)
  -> safety_queue (bounded)
  -> SafetyCommitPolicy (re-uses the existing deterministic
     safety.validate() — SAFE_TO_SPEAK / WAIT_FOR_MORE_CONTEXT / BLOCKED)
  -> tts_queue (bounded, only for SAFE_TO_SPEAK)
  -> TTSRouter -> StreamingTTSProvider.stream() (ordered audio chunks)
  -> AudioOutputBuffer (sequencing, dedup, stale/missing-chunk handling)
  -> LiveKit audio publish (unchanged path — still through the existing
     E2EE-encrypted local track)
```

## Two distinct "is this text ready" questions, deliberately kept separate

- **CommitPolicy** answers "has enough NEW text accumulated, and is this
  a good moment (punctuation/silence/timeout), to send it to translation
  at all" — a timing/chunking question, language-agnostic.
- **SafetyCommitPolicy** answers "even though CommitPolicy decided to
  flush this text, is it a clinically COMPLETE instruction, or does
  speaking it now risk speaking a truncated dosage" — a safety question,
  and (today) English-only for its extra completeness heuristic (see its
  own docstring). When SafetyCommitPolicy says `WAIT_FOR_MORE_CONTEXT`,
  `StreamingSessionPipeline` holds the accumulated SOURCE text (never the
  translated text — see below) and re-translates the full merged source
  on the next commit, rather than trying to stitch two independent
  translations together.

## Why re-translate the whole buffer instead of merging translations

Concatenating two SEPARATELY-translated fragments (e.g. translate("Take
5") + translate("mg twice daily for 7 days.")) is not linguistically
sound — grammar, word order, and agreement can differ once the model sees
the full sentence versus a fragment. `StreamingSessionPipeline` avoids this
entirely: on a `WAIT_FOR_MORE_CONTEXT` decision, it holds the SOURCE text
and re-translates the full accumulated source as one call once the next
phrase commits. This costs a redundant translation call per WAIT cycle
(a real, accepted latency cost) in exchange for translation correctness.

## Barge-in / cancellation

`StreamingSessionPipeline.begin_utterance(utterance_id)` cancels the
current `AudioOutputBuffer` (if any) and clears the safety-hold buffer,
exactly mirroring the existing pipeline's barge-in behavior
(`streaming.py`'s `_publish_task.cancel()`) but scoped to the new
architecture's own queues and TTS provider `cancel()` hooks. Verified in
`test_streaming_pipeline.py::test_barge_in_cancels_in_flight_tts_and_drops_stale_audio`.

## Backpressure

Bounded `asyncio.Queue`s at every stage (translation/safety/tts — sizes
configurable via `AI_TRANSLATION_QUEUE_SIZE` etc., defaults matching the
build spec's own example limits). On overflow, the OLDEST already-queued
item for the SAME utterance is dropped to make room (superseded context) —
never an item from a different/newer utterance, and never a final,
already-safety-cleared item once it reaches the TTS queue faster than it's
consumed (queue sizing is the mitigation there, not silent drops).

## Open design questions this pass does not resolve

- **A default reference voice per language for Qwen3-TTS/CosyVoice3**:
  both are voice-cloning architectures requiring a reference audio+text;
  this build has no doctor voice sample to clone from. A real deployment
  needs a decision here (a recorded default voice per supported language,
  most likely) before either provider can actually run.
- **True incremental TTS/ASR generation**: neither Qwen3-TTS's nor
  CosyVoice3's streaming call signature (beyond CosyVoice3's documented
  `stream=True` flag) was fully verifiable from their public model cards
  in this pass; Qwen3-ASR's own card states streaming requires a separate
  vLLM serving process. Real GPU access is needed to research and verify
  these further.
- **Live LiveKit wiring**: as above — a real follow-up pass's job, with
  its own live-integration test before any claim of end-to-end streaming
  being "live-verified."

## What has been verified

- Every unit listed under "Data flow" above, in isolation, with real
  passing tests (see each module's own test file under `tests/pipeline/`).
- `StreamingFasterWhisperSTT` and `StreamingMmsTTSProvider` against REAL
  model inference (already-resident faster-whisper/MMS-TTS weights, no
  new download) — `tests/pipeline/test_streaming_stt.py` and
  `test_streaming_tts.py`, run under `pytest -m models`.
- `StreamingSessionPipeline`'s full queueing/routing/safety-hold/barge-in
  logic against fake providers — `tests/pipeline/test_streaming_pipeline.py`.
- The full existing regression suite (Go/Python unit+integration+models/
  Web/Flutter/Playwright) re-run clean after every addition in this pass
  — see `docs/ai/latency.md`'s sibling report and the git commit message
  for exact counts.
