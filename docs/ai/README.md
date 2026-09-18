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

## Day 6 (not yet implemented): the translation pipeline

```
Audio -> VAD -> STT -> Language ID -> Terminology Engine -> Translation
      -> Safety Validator -> TTS -> LiveKit publication
```

Planned provider interfaces (so no single vendor/model is hard-coded):

| Stage | Initial provider | Notes |
|---|---|---|
| VAD | Silero VAD | speech/silence/turn/interruption detection |
| STT | faster-whisper | interface allows IndicWhisper, other Whisper variants, managed providers |
| Language ID | TBD | English, Tamil, Malayalam at minimum |
| Translation | IndicTrans2 | interface allows NLLB, commercial APIs, medical-specialized models |
| Terminology | custom | protects Ayurveda/Sanskrit terms, medicine names, dosage/frequency/duration, numbers from translation drift |
| Safety validator | custom, deterministic | blocks publication if numbers/dosage/frequency/duration/medicine names/negations changed — see build spec section 5 |
| TTS | TBD | provider-swappable |

This document will be updated with real status (`IMPLEMENTED`/`PARTIALLY
IMPLEMENTED`/`BLOCKED`) once Day 6 work begins — see `PROGRESS.md`.
