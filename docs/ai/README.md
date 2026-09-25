# AI Translation Agent

## IMPORTANT: the default translation/TTS models were switched — AI translation currently does not run in this sandbox

`app/pipeline/factory.py`'s `build_default_pipeline()` — used by every
real session via `app/agent.py` — was switched from NLLB-200/MMS-TTS to
**MADLAD-400/Qwen3-TTS**, after this codebase's own license audit found
NLLB-200 and MMS-TTS are both `CC-BY-NC-4.0` (non-commercial; NLLB's own
model card states it is "not released for production deployment") — see
`docs/MODEL_LICENSE_MATRIX.md`. There is deliberately **no fallback**
configured back to the old models.

**Real, direct consequence**: MADLAD-400 and Qwen3-TTS are not downloaded
in this environment (no GPU). `build_default_pipeline()` now raises
`ModelNotAvailableError`, and `POST /v1/agent/sessions/{id}/start` returns
a clear `503` instead. Everything below describing the Day 6/7 whole-
utterance pipeline's translation/TTS behavior is now **historical** — it
describes what ran against NLLB-200/MMS-TTS before this switch, not the
current default. STT (`FasterWhisperSTT`) and every non-translation/TTS
part of the agent lifecycle are unaffected. `tests/test_pipeline_live_integration.py`
and the `build_default_pipeline`-dependent cases in
`tests/pipeline/test_pipeline_models.py` now `skip` with an explicit
reason rather than passing — see `docs/MODEL_LICENSE_MATRIX.md`'s
"Finding" section for the full reasoning, options, and current state
(licensing resolved; certification and GPU availability are the two
remaining gates).

## Streaming architecture (post-Day-7 addition)

A new, OPT-IN streaming pipeline (default off:
`AI_AGENT_STREAMING_PIPELINE_ENABLED=false`) sits alongside the
whole-utterance pipeline documented below, adding real-time partial ASR,
incremental commit/safety/TTS staging, and a language-registry-driven
router for new translation/TTS/STT models. It has NOT replaced or been
wired into the live LiveKit audio path documented in this file. See:

- `docs/ai/streaming.md` — architecture, data flow, why it's a separate
  opt-in path, and what has/hasn't been verified
- `docs/ai/models.md` — every model provider class and its real status
- `docs/ai/language-registry.md` — how a language pair is routed and
  certified
- `docs/ai/latency.md` — real measured latency of the new components
- `docs/MODEL_LICENSE_MATRIX.md` — the licensing finding and the default-
  pipeline model switch above — read this before any commercial
  deployment decision

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
| Safety validator | custom, deterministic | Compares a normalized "safety entity" object (numbers, dosage value+unit, frequency, duration value+unit, food-timing constraints, negation, protected medicine/Ayurveda terms) between source and translated text; blocks TTS/publication on any critical-field mismatch or on empty output for non-empty input. See "Safety validator" below for the full design. Verified to actually block (not just warn) in `tests/pipeline/test_pipeline_models.py` and `tests/pipeline/test_tts_gate.py` |
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
- **FIXED (previously CRITICAL): the safety validator used to compare
  only numeric digit sequences** — a unit swap, a dropped/flipped
  negation, and a medicine-name substitution with matching dosage
  numbers all previously passed as `safe=True`. This is fixed — see the
  dedicated "Safety validator" section below for the full design,
  `tests/pipeline/test_safety_validator_corpus.py` for the regression
  corpus (75 cases) that proves each of those three specific failure
  modes is now rejected, and the accompanying release report for the
  before/after verification.
- **CPU-only inference.** Translation (~0.6-1s/sentence) and TTS
  (~0.4s/sentence) on CPU are acceptable for a demo/test pipeline but not
  production-grade real-time latency; a production deployment should use
  GPU inference or a managed API for the heavier stages.
- **FIXED (previously misdiagnosed): `SileroVAD` was missing Silero's
  required 64-sample context buffer.** A prior pass concluded "Silero
  VAD does not reliably classify MMS-TTS-synthesized speech as speech"
  and treated it as an accepted TTS-acoustic-compatibility gap. That
  conclusion was wrong. Root-causing why a real recorded human speech
  sample (`tests/fixtures/jfk.flac`) *also* failed to cross the VAD
  threshold — which should never happen for genuine continuous speech —
  found the actual bug: every streaming call to Silero's ONNX model must
  prepend the trailing 64 samples of the *previous* chunk (confirmed
  against `snakers4/silero-vad`'s own official `OnnxWrapper.__call__`
  reference implementation, and against this exact bundled model file by
  SHA-256 match to their current release), or the model's internal
  conv/LSTM layers receive an incomplete receptive field and return
  near-zero probability regardless of real audio content. This affected
  ALL audio uniformly — TTS and real recorded speech alike — it was
  never actually about MMS-TTS's acoustic characteristics. Fixed in
  `app/pipeline/vad.py` (`SileroVAD._context`); see
  `tests/pipeline/test_vad_tts_compatibility.py` (4/4 passing, including
  a test that directly demonstrates the pre-fix calling convention fails
  on the same real speech sample the fix now correctly detects with a
  sustained, textbook speech/pause probability trace).
- **FIXED: `test_live_translation_pipeline_produces_captions` now
  passes (3/3 consecutive runs).** After the VAD fix above, the test
  still received exactly zero-RMS audio, but only within its full
  Go-API + FastAPI + AIAgent orchestration — three minimal
  reproductions (two `rtc.Room()` connections in one process, with and
  without E2EE, and the real unmodified `LiveAudioProcessor` wired
  directly) all received correct audio and didn't reproduce it,
  disproving VAD, transport, and (via a real token-swap experiment) the
  LiveKit token-grants hypothesis in turn. The actual root cause: the
  test itself (not `app/agent.py`, which was always correct) called
  `base64.b64decode(join_resp["e2ee_key"])` before handing the result to
  `KeyProviderOptions` — decoding a value this codebase has documented,
  since commit `4d14357`, must be passed as the UTF-8 encoding of the
  base64 *text* itself, never decoded first. The doctor and the agent
  were silently encrypting/decrypting with two different, incompatible
  keys: real encrypted RTP genuinely arrived (confirmed via
  `AYUREZE_AUDIO_DIAG=1` raw-frame RMS during this investigation) but
  decrypted to all-zero PCM — a symptom none of the VAD/transport/token
  hypotheses could have explained, because none of them were the actual
  cause. Fixed in `tests/test_pipeline_live_integration.py` (one-line
  key derivation fix, test-only — no production code changed).

## Safety validator

Deterministic and auditable by design — never a model in the loop, per
the build spec's explicit requirement. `app/pipeline/safety.py` builds a
normalized, comparable representation of the source text and the
translated text (`terminology.extract_safety_entities`, a
`SafetyEntities` object — see `app/pipeline/types.py`) and rejects on any
critical-field mismatch between the two.

### Protected entities and normalization rules

| Entity | Extraction | Normalization rule |
|---|---|---|
| Numbers | `terminology.extract_numeric_values` | Decimals (`5`/`5.0`/`5.00`), simple fractions (`1/2`), and Unicode vulgar fractions (`½`) all normalize to the same float value and compare as an order-independent multiset — legitimate reordering across languages is never a false rejection, but a dropped/added/altered value always is. |
| Dosage (value + unit) | `terminology.extract_dosages` | Spelling/case/pluralization variants of the *same* unit canonicalize to one code (`mg`/`milligram`/`milligrams` → `mg`; `ml`/`mL` → `ml`). **Two different canonical units are never treated as equivalent** — there is no mg↔ml (or any cross-unit) equivalence table, only same-unit spelling variants. Temperature requires an explicit `°`/`degrees` marker. Range dosages (`5-10 mg`) produce two entities, both bounds checked. |
| Frequency | `terminology.extract_frequencies` | `once`/`twice`/`thrice`/`N times` + `a day`/`per day`/`daily` all canonicalize by *count*, not by connector wording — `"twice a day"` and `"twice daily"` match; `"twice daily"` and `"once daily"` do not. `every N hours` keeps N exact. Tamil: both fixed phrases (`தினமும் இருமுறை`) and the general `<number-word> முறை` + a separate daily-context marker (`தினமும்`/`தினசரி`/`நாளுக்கு`) are matched independently, verified against this build's own real NLLB-200 output (see "Real-model verification" below), not assumed. |
| Duration (value + unit) | `terminology.extract_durations` | day/week/month are **never** interchangeable regardless of numeric value — `"7 days"` → `"7 weeks"` is rejected even though the digit `7` is unchanged, which a pure numeric check cannot catch. Tamil day/week/month stems are the common prefix of the *inflected* forms actually seen in output, not the dictionary singular (Tamil pluralizes some of these irregularly). |
| Food-timing constraints | `terminology.extract_food_constraints` | `empty_stomach`/`before_food`/`after_food`/`with_food`/`bedtime` — compared as a set; dropping "on an empty stomach" is a rejection even with everything else unchanged. |
| Negation | `negation.has_negation(text, lang)` | Language-aware: checks the *target* language's own negation vocabulary against the translated text, never the source language's words against the target text. Covers English (`do not`/`don't`/`never`/`avoid`/`without`/bare `not`, etc.) and Tamil (`வேண்டாம்`/`கூடாது`/`இல்லை`/`அல்ல`/etc.). Returns `None` (not `False`) for an uncovered language (e.g. Malayalam) — the validator skips the negation comparison rather than silently treating unknown as "no negation". |
| Protected medicine/Ayurveda terms | `terminology.detect_protected_terms` / `term_preserved` | `TRANSLITERATIONS` maps each `GLOSSARY` term to its accepted form per language. A term found in the source must have its target-language form verifiably present in the translation — this distinguishes **safe transliteration** ("Ashwagandha" → "அஸ்வகந்தா") from **semantic substitution** (a different drug's name appearing instead). Tamil matching strips the final virama-marked consonant before substring search (`_tamil_match_form`) because several terms' accusative case changes their final consonant via sandhi (தோஷம் → தோஷத்தை) rather than simple suffixation — found and fixed via this pass's own test corpus, not assumed correct. |

### Rejection rules

Any one of: number multiset mismatch, dosage value+unit mismatch,
frequency code-set mismatch, duration value+unit mismatch, food-
constraint set mismatch, negation mismatch (only when both languages are
covered), or a protected term found in the source but not verifiably
present in the translation. Each produces both a human-readable reason
(`SafetyCheckResult.reasons`, may quote extracted numbers/units/terms —
not for routine logging) and a short reason code (`reason_codes`, safe
for logs/metrics — see "Logging" below).

### Fail-closed behavior

`SafetyCheckResult.to_structured_error()` returns
`{"status": "rejected", "reason": "<code>", "reason_codes": [...]}`.
When a check cannot be evaluated (e.g. a protected term has no
transliteration table entry for the target language, or negation.py has
no table for the language), that specific check is skipped — it never
resolves an unknown to "safe"; only mismatches this module can actually
detect cause rejection, and nothing here ever weakens that to "warn."
`app/pipeline/orchestrator.py`'s TTS call
(`self._tts.synthesize(...)`) is gated by
`if safety_result.safe and translated_text.strip()`, confirmed the only
production call site of `TTSProvider.synthesize` by a full-repo grep, and
proven at the orchestrator level (not just unit-tested in isolation) by
`tests/pipeline/test_tts_gate.py`, which records every TTS call and
asserts zero calls for a rejected translation.

### Known limitations

- **English/Tamil only.** Malayalam is a supported pipeline language
  (`lid.py`) but has no negation table and no transliteration entries —
  `has_negation` returns `None` (skipped, not "safe") and
  `detect_protected_terms`/dosage-unit/frequency/duration extraction for
  Malayalam-specific vocabulary is not implemented. Extend the same way
  Tamil was added, not by guessing.
- **Curated, not exhaustive**, same status as `GLOSSARY` always had: the
  unit table, frequency/duration patterns, negation markers, and
  `TRANSLITERATIONS` table are a real, tested starting point verified
  against this build's own NLLB-200 output — not a certified medical-
  linguistics authority. Should be reviewed by a qualified Tamil medical
  terminologist before relying on it beyond a controlled pilot.
- **Real-model verification surfaced real gaps this pass, since fixed**:
  running the actual pipeline (`tests/pipeline/test_pipeline_models.py`,
  real NLLB-200 inference, not synthetic text) found real Tamil output
  the initial curated pattern set missed — `"இரண்டு முறை"` ("two times",
  spelled-out number word) for "twice", and `"தினசரி"` as a synonym for
  "daily" alongside `"தினமும்"`. Both are now handled generally (a
  number-word + `முறை` pattern, a daily-synonym list) rather than as
  one-off literal-phrase patches — but this is real evidence that any
  vocabulary table facing genuinely open-ended model output should be
  expected to need incremental growth, not treated as complete.
- **A known, pre-existing, unrelated flake**: MMS-TTS's poor bare-digit
  pronunciation (see the bullet above) occasionally causes Whisper to
  mis-transcribe a *spelled-out* number too in the real-model test
  (`test_numeric_dosage_is_preserved_end_to_end`, ~1-in-3 runs observed
  this pass) — always failing at the transcript-content assertion, never
  at a safety-validator false-rejection of a correctly-transcribed
  segment. This is STT/TTS audio quality noise, not a safety-validator
  defect; re-running the test confirms it passes whenever transcription
  is clean.

### Logging

`app/pipeline/streaming.py`'s `translation_blocked_by_safety_validator`
log line carries `validation_status` and `reason_codes` only — never
`SafetyCheckResult.reasons` (whose human-readable strings can quote
extracted numbers/units/terms from the actual conversation). See
`docs/security/README.md` and `docs/monitoring/privacy.md`.

### Performance

Measured directly (`safety.validate()`, 2000 iterations per case, warm
cache, this build's environment): **~0.13-0.16ms per call** across
representative English/Tamil, dosage, and Ayurveda-terminology cases —
negligible next to STT (~500ms), translation (~600-1000ms), and TTS
(~500ms) in the same pipeline run. The safety layer is not a bottleneck.

### Test coverage

`tests/pipeline/test_safety_validator_corpus.py` (75 cases): numeric/
unit/frequency/duration/negation/terminology reject cases, safe-
reformatting and safe-transliteration pass cases, Tamil↔English in both
directions, adversarial mutation tests (every critical field mutated
independently against one baseline sentence), and false-positive
avoidance tests (legitimate reformatting must still pass).
`tests/pipeline/test_tts_gate.py` (4 cases): orchestrator-level proof the
TTS gate cannot be bypassed. `tests/pipeline/test_safety.py` and
`tests/pipeline/test_terminology.py` (9 cases): the original baseline
tests, unchanged and still passing. `tests/pipeline/test_pipeline_models.py`
(3 cases): real NLLB-200/MMS-TTS/faster-whisper inference, not mocked.
- **`onnxruntime`/`faster-whisper`/`transformers`+CPU-only `torch` are
  deliberately kept separate from the default PyPI `torch` wheel** (which
  pulls in the full CUDA/NVIDIA toolkit — observed to add ~15GB even on a
  machine with no GPU during this build). See
  `apps/ai-agent/requirements-pipeline.txt`.
- The `PUBLISHING` → translated-audio-republish path has been verified
  live end-to-end (`tests/test_pipeline_live_integration.py`), but latency
  budgets, jitter under sustained conversation, and Malayalam TTS have not
  been separately load-tested.
