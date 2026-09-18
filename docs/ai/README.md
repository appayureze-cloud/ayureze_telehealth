# AI Translation Agent

## Day 5: the agent as a real encrypted LiveKit participant

The Python AI agent (`apps/ai-agent`) is a genuine LiveKit participant, not
a server-side media interceptor. Its connection lifecycle:

```
REQUESTED -> AUTHORIZED -> JOINING -> CONNECTED -> PROCESSING -> PUBLISHING
                                             \-> REVOKED
                                             \-> DISCONNECTED
                                             \-> FAILED (from any non-terminal state)
```

enforced by `app/lifecycle.py`'s explicit transition table — an attempt to
skip a state (e.g. `REQUESTED` straight to `CONNECTED`) raises
`InvalidTransition`, and no transition is allowed out of a terminal state.

1. **Authenticate** — the agent presents `AI_AGENT_SERVICE_SECRET` to the
   Go API's `POST /internal/ai-agent/sessions/{id}/authorize`
   (`app/api_client.py`). It has no tenant/user identity of its own; this
   is a service credential, not a login.
2. **Verify authorization / session / consent** — entirely the Go API's
   job (`internal/sessionsvc.AuthorizeAIAgent`, Day 4): session must exist,
   not be ended, and have a currently-**active** `ai_translation` consent
   row. The agent does not (and architecturally cannot) bypass this — it
   has no other way to obtain a LiveKit token.
3. **Join the encrypted room** — using the token and the session's real
   E2EE key returned by that call, the agent enables LiveKit's SFrame E2EE
   (`rtc.E2EEOptions` / `rtc.KeyProviderOptions(shared_key=...)`) and
   connects. This is real encryption, verified in
   `tests/test_agent_integration.py` by having a second real LiveKit
   participant publish an encrypted audio track with the same session key
   and confirming the agent actually receives and subscribes to it.
4. **Subscribe to authorized media** — `auto_subscribe=True` within the
   room its token grants access to (and only that room — see
   `internal/token` on the Go side for the room-scoping).
5. **Process** — Day 5 transitions to `PROCESSING` the moment a real,
   decrypted audio track is subscribed, proving the encrypted media path
   works end-to-end. The actual VAD → STT → language ID → terminology →
   translation → safety validation → TTS pipeline that would run here, and
   the `PUBLISHING` transition once it publishes translated audio, is
   **Day 6 scope** — not yet implemented. See "Day 6" below.
6. **Leave/revoke correctly** — the agent distinguishes *why* it
   disconnected: LiveKit's `DisconnectReason.PARTICIPANT_REMOVED` (the Go
   API force-removing it on consent revocation, Day 4) maps to lifecycle
   state `REVOKED`; anything else maps to `DISCONNECTED`. Both are
   terminal — a revoked agent does not silently rejoin.

**"AI must not join automatically merely because a room exists"**: the
agent only ever attempts to connect when explicitly told to via
`POST /v1/agent/sessions/{id}/start` — nothing in this service watches
LiveKit for new rooms and auto-joins them.

## Day 6: the translation pipeline

```
Audio -> VAD -> STT -> Language ID -> Terminology Engine -> Translation
      -> Safety Validator -> TTS -> LiveKit publication
```

All seven stages are implemented behind provider interfaces
(`apps/ai-agent/app/pipeline/`) so no vendor/model is hard-coded, and
wired live into the Day 5 agent (`app/pipeline/streaming.py`) — see
`apps/ai-agent/README.md`'s test descriptions for what's actually been
run end-to-end against the real stack.

| Stage | Provider used | Notes |
|---|---|---|
| VAD | Silero VAD | ONNX inference directly via `onnxruntime` (not the `silero-vad` PyPI package, which pulls in a full PyTorch install just to run a 2MB model — see "Known limitations"). Turn segmentation with hangover + minimum-duration filtering in `vad.py`'s `TurnSegmenter` |
| STT | faster-whisper (`tiny` by default) | Swappable to IndicWhisper/other Whisper variants/managed providers via `STTProvider` |
| Language ID | `langid` (text-based) cross-checked against Whisper's audio-based guess | Restricted to English/Tamil/Malayalam per build spec section 5; `lid.resolve_language()` prefers the text-based signal when audio-based confidence is low (typical for short clinical utterances) |
| Terminology | custom, deterministic | Regex/glossary-based extraction of numbers, dosage (`\d+\s*mg/tablets/...`), frequency ("twice daily", "every N hours"), duration ("N days/weeks"), and a curated Ayurveda/medicine glossary |
| Translation | **facebook/nllb-200-distilled-600M**, not IndicTrans2 | Documented substitution — see below |
| Safety validator | custom, deterministic | Compares digit sequences between source and translated text; blocks TTS/publication on any mismatch or on empty output for non-empty input. Verified to actually block (not just warn) in `tests/pipeline/test_pipeline_models.py` |
| TTS | facebook/mms-tts-{eng,tam,mal} (VITS) | Swappable via `TTSProvider` |

### Why NLLB-200 instead of IndicTrans2

The build spec's initial pick is IndicTrans2. In this build environment,
`ai4bharat/indictrans2-en-indic-dist-200M` returned `401 Unauthorized` from
Hugging Face (gated access), and IndicTrans2's inference additionally
requires a custom preprocessing toolkit (`IndicTransToolkit`: language-tag
+ script-specific tokenization) beyond a standard `transformers` load. NLLB-200
is directly usable through standard `transformers` with official support
for `eng_Latn`/`tam_Taml`/`mal_Mlym`, so it was used instead — a real,
working translation model, not a stub. `TranslationProvider` is exactly
the seam that makes swapping to IndicTrans2 later (once access/tooling are
resolved) a contained change: a new class, not a pipeline redesign.

### Known limitations

- **MMS-TTS has no number-normalization front-end.** Feeding it bare
  digits ("2 tablets") produces badly mispronounced audio that Whisper
  then mis-transcribes — observed directly in this build's own testing
  (`tests/pipeline/test_pipeline_models.py`'s comments). Spelled-out
  numbers ("two tablets") round-trip correctly. This affects the
  TTS→STT-input path specifically (relevant when testing with
  synthesized audio); it does not affect the translation-stage digit
  preservation the safety validator checks, which is verified directly
  against text in `tests/pipeline/test_safety.py`. A production system
  should add text normalization before TTS.
- **The terminology/safety layer protects digit-form numbers**, not
  spelled-out number words ("seven" vs "7") — growing this to a fuller
  NLP-based numeric-entailment check is future work.
- **CPU-only inference.** Translation (~0.6-1s/sentence) and TTS
  (~0.4s/sentence) on CPU are acceptable for a demo/test pipeline but not
  production-grade real-time latency; a production deployment should use
  GPU inference or a managed API for the heavier stages.
- **`onnxruntime`/`faster-whisper`/`transformers`+CPU-only `torch` are
  deliberately kept separate from the default PyPI `torch` wheel** (which
  pulls in the full CUDA/NVIDIA toolkit — observed to add ~15GB even on a
  machine with no GPU during this build). See
  `apps/ai-agent/requirements-pipeline.txt`.
- The `PUBLISHING` → translated-audio-republish path has been verified
  live end-to-end (`tests/test_pipeline_live_integration.py`), but latency
  budgets, jitter under sustained conversation, and Malayalam TTS have not
  been separately load-tested.
