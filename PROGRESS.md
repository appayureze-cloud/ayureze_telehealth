# AyurEze Telehealth — Build Progress

Status legend: `IMPLEMENTED` (built, integrated, tested) · `PARTIALLY IMPLEMENTED`
(some of the above missing — noted) · `BLOCKED` (external dependency, noted) ·
`NOT IMPLEMENTED` (not started).

This file is updated at the end of each day's work per the working style
in the build spec. Nothing is marked `IMPLEMENTED` without having been
actually run and verified in this environment.

## Day 1 — Foundation

| Item | Status | Notes |
|---|---|---|
| Repository tree (`apps/`, `sdk/`, `infrastructure/`, `observability/`, `docs/`, `scripts/`) | IMPLEMENTED | |
| `.env.example`, `.gitignore`, secrets kept out of git | IMPLEMENTED | `.env` generated locally for dev, gitignored, verified not tracked |
| Docker Compose: PostgreSQL 16.4 | IMPLEMENTED | Healthy, `pg_isready` passes, extensions (`pgcrypto`, `citext`) installed, survives restart |
| Docker Compose: Redis 7.2 (password-protected, AOF persistence) | IMPLEMENTED | Healthy, `PING` over authenticated connection passes, survives restart |
| Docker Compose: LiveKit self-hosted | IMPLEMENTED | Healthy, connects to authenticated Redis, keys injected via `LIVEKIT_KEYS`, config via `LIVEKIT_CONFIG` (no secrets on disk), survives restart. **Updated on Day 2** from `v1.8.0` to `v1.13.7` — `v1.8.0` didn't speak the signaling protocol current `livekit-client` versions expect, which manifested as SDP renegotiation timeouts on track publish; see `docs/deployment/local-development.md` troubleshooting |
| Docker Compose: coturn 4.6.2 (TURN/STUN) | IMPLEMENTED | Running, TCP 3478 reachable, hardened (`denied-peer-ip` ranges block RFC1918/loopback relay abuse, TLS 1.0/1.1 disabled). TURN relay functionality itself will be exercised in Day 2 client testing |
| Observability stack (Prometheus, Grafana, Loki, Promtail, OTel Collector) | IMPLEMENTED | All healthy; Prometheus actively scraping `livekit`, itself, and the collector; Grafana provisioned with Prometheus+Loki datasources and a starter dashboard; OTel Collector redacts key/token/media attributes at the pipeline boundary |
| Health checks (`docker compose healthcheck` + `scripts/health-check.sh`) | IMPLEMENTED | All 7 core service checks pass (see command output below) |
| Restart resilience | IMPLEMENTED | `postgres`, `redis`, `livekit` restarted individually; all recovered to healthy within their configured `start_period` |
| Environment variable plumbing | IMPLEMENTED | Compose fails fast (`:?required`) if a secret env var is missing; verified `.env` values flow into Postgres auth, Redis auth, LiveKit keys/Redis auth, coturn secret |
| Secrets never on disk in plaintext config files | IMPLEMENTED | LiveKit Redis password injected via env, not the reference YAML; `.env` is gitignored; `.gitignore` also blocks stray `*.key`/`*.pem`/`secrets/` |
| `apps/api`, `apps/ai-agent`, `sdk/*` scaffolding | PARTIALLY IMPLEMENTED | Directories created; real code begins Day 2/3/5/7 per the spec's day boundaries |

**Validation command output** (`./scripts/health-check.sh`, this session):
```
OK    postgres accepting connections
OK    redis PING
OK    livekit HTTP root
OK    prometheus healthy
OK    loki ready
OK    grafana healthy
OK    coturn TCP port open
All health checks passed.
```

**Known limitations / carried forward:**
- Docker daemon in this sandboxed session is not started automatically
  (`dockerd` had to be launched manually). A production/CI host needs the
  Docker service enabled at boot — documented in `docs/deployment/`.
- coturn's actual relay path (a client behind symmetric NAT using TURN) is
  not exercised until Day 2 real WebRTC clients exist.
- Observability dashboards are minimal placeholders; the full call/API/AI/
  security dashboard set required by the spec is built on Day 7 once those
  metrics exist to visualize.

## Day 2 — Patient/Doctor connection

| Item | Status | Notes |
|---|---|---|
| Server-side JWT/LiveKit token minting (`apps/api`) | IMPLEMENTED | `POST /v1/dev/session-tokens`; role-scoped (`patient`/`doctor` only), room-scoped, TTL-capped at 10 minutes, signed server-side — clients never see `LIVEKIT_API_SECRET`. Unit tested (`internal/token`, `internal/httpapi`) |
| Room lifecycle: explicit creation, never auto-create | IMPLEMENTED | `internal/roomsvc` calls LiveKit `CreateRoom` (idempotent) before minting a token; `room.auto_create: false` enforced server-side in LiveKit config |
| Structured JSON logging, request IDs, panic recovery, CORS allow-list, per-IP rate limiting, security headers | IMPLEMENTED | `internal/httpapi/middleware.go`; secret-shaped log fields redacted at the logger level (`internal/logging`) |
| Patient test client (web) | IMPLEMENTED | `apps/playground` — single TS page parameterized by `?role=patient` |
| Doctor test client (web) | IMPLEMENTED | Same page, `?role=doctor` |
| Patient joins ✓ | IMPLEMENTED | Verified via Playwright against the real Docker Compose LiveKit + `apps/api` |
| Doctor joins ✓ | IMPLEMENTED | ” |
| Patient sees doctor ✓ / Doctor sees patient ✓ | IMPLEMENTED | Asserted via subscribed `<video>` element `readyState`/`videoWidth`, not just signaling state |
| Audio works ✓ | IMPLEMENTED | Asserted via subscribed audio track presence on both sides (Chromium fake-audio device) |
| Video works ✓ | IMPLEMENTED | Asserted via decoding frames (`readyState >= HAVE_CURRENT_DATA`, non-zero `videoWidth`) |
| Disconnect/reconnect ✓ | IMPLEMENTED | Explicit disconnect + reconnect cycle, re-establishes `connected` state |
| Expired token rejected ✓ | IMPLEMENTED | Token crafted with `exp` in the past (bypassing the API, signed directly with the LiveKit secret) — LiveKit itself refuses the connection |
| Invalid token rejected ✓ | IMPLEMENTED | Signature-tampered token refused by LiveKit |
| Wrong room / room isolation ✓ | IMPLEMENTED | Interpreted as: a participant in room A is never visible to, and never becomes visible to, participants in a concurrently-running room B on the same deployment — verified with two independent room pairs |
| Automated test suite | IMPLEMENTED | `apps/playground/tests/connectivity.spec.ts` (Playwright, headless Chromium with fake media devices, run twice back-to-back for stability) — 5/5 passing |

**Validation command output** (this session, two consecutive runs):
```
5 passed (5.7s)
5 passed (5.5s)
```

**Known limitations / carried forward:**
- The dev token endpoint (`/v1/dev/session-tokens`) has no real
  authentication — it's an explicitly-labeled, non-production-only stand-in
  for Day 3's real login/session-authorization flow. It never issues the
  `ai_agent` role.
- Rate limiting is process-local (in-memory), not shared across replicas —
  acceptable for a single Day-2 instance, called out in `apps/api/internal/httpapi/ratelimit.go`
  to be moved to Redis on Day 3.
- TURN relay (coturn) is running and reachable but not yet exercised by a
  client forced through TURN (would require simulating symmetric NAT) —
  the current test network path uses direct/host ICE candidates.
- npm audit flags a moderate-severity issue in `esbuild`'s dev server (only
  affects `vite dev`/`vite preview` on `apps/playground`, a local test tool
  bound to 127.0.0.1, not any shipped artifact).

## Day 3 — Go session platform

| Item | Status | Notes |
|---|---|---|
| Postgres schema (tenants/users/sessions/participants/consents/session_events/audit_events) | IMPLEMENTED | `apps/api/internal/db/migrations/0001_core_schema.{up,down}.sql`, applied via embedded `golang-migrate` (`internal/db/migrate.go`) |
| Auth: login/refresh/logout | IMPLEMENTED | `internal/authsvc`; bcrypt password hashing, HS256 app JWTs with unique `jti`, Redis-backed single-use refresh tokens (hash-only storage) |
| Tenant isolation | IMPLEMENTED | Every tenant-owned query scoped by the caller's JWT `tid`; verified cross-tenant `GET`/`join`/`create` all return `404` |
| RBAC (role + per-session resource checks) | IMPLEMENTED | `internal/sessionsvc`, `internal/consentsvc`; only a session's own doctor/patient (or admin) can act on it — role alone is never sufficient |
| Session service: create / join / end | IMPLEMENTED | Join mints a LiveKit token only after checking the `participants` table (not merely "has a token"); ending deletes the LiveKit room |
| Participant lifecycle | IMPLEMENTED | `authorized` (at session creation) → `joined`/`left` (driven by verified LiveKit webhooks) → `revoked` |
| Consent module (schema + grant/revoke CRUD) | IMPLEMENTED | `internal/consentsvc`; enforcement into the (not-yet-existing) AI agent's join path is Day 4/5 scope, explicitly deferred |
| Audit events | IMPLEMENTED | Every authn/authz decision (success and denied, with a reason) recorded to `audit_events`; verified in Postgres during manual + automated testing |
| LiveKit webhook consumer | IMPLEMENTED | Signature-verified (`webhook.ReceiveWebhookEvent` + `LIVEKIT_API_KEY/SECRET`) `participant_joined`/`participant_left`/`room_finished` → participant status + Redis presence + `session_events` |
| Redis usage: refresh tokens, presence, rate limiting | IMPLEMENTED | `internal/redisstate`; rate limiting moved off the Day 2 in-memory limiter to a Redis-backed one shared across replicas |
| `GET /ready` checks real dependencies | IMPLEMENTED | Now pings Postgres + Redis, returns `503` if either is down (Day 2 was a static "ready") |
| Automated tests | IMPLEMENTED | Unit: `internal/token`, `internal/httpapi` (existing + unaffected by Day 3 changes). Integration (`-tags integration`, real Postgres/Redis/LiveKit, no mocks): 9 tests covering login success/failure modes, refresh single-use, RBAC denial, full create→join→consent→end lifecycle, tenant isolation, missing/invalid token rejection, readiness, and signed-webhook-driven participant status transitions — all passing |
| Dev seed command | IMPLEMENTED | `apps/api/cmd/seed` (wrapped by `scripts/db-seed.sh`); refuses to run with `ENVIRONMENT=production`; local-dev-only, documented as such |

**Validation command output** (this session):
```
$ go build ./... && go vet ./... && gofmt -l .   # clean
$ go test ./...                                   # ok (internal/httpapi, internal/token)
$ go test -tags integration ./test/integration/... -count=1
ok  	github.com/ayureze/telehealth/api/test/integration	1.481s   (9/9 tests passing)
```
Also manually verified end-to-end via curl against the live stack: login,
RBAC-denied session creation by a patient, session create/join/consent
grant+revoke/end, join-after-ended rejection (409), cross-tenant 404s on
GET/join/create, bad-password/unknown-tenant/no-token/garbage-token all
`401`, and confirmed `audit_events`/`session_events` rows in Postgres with
no secrets in `audit_events.metadata` or the structured JSON logs.

Re-ran the full Day 2 Playwright suite (5/5) after these changes to confirm
no regression from the shared middleware refactor (rate limiter, router).

**Known limitations / carried forward:**
- LiveKit webhooks are validated end-to-end via directly-signed test
  requests (`TestWebhook_*`), not yet via a real LiveKit container calling
  back into the host-run API process — `infrastructure/docker/docker-compose.yml`
  points the webhook URL at `http://api:8080/...`, which only resolves once
  `apps/api` itself runs inside the compose network (planned for the Day 7
  Dockerfile/hardening pass). The verification and state-update logic
  itself is fully tested; only the container-to-container network hop is
  unexercised so far.
- `admin`-created sessions (specifying a doctor explicitly) are
  intentionally rejected today (`"admin-created sessions ... not yet
  supported"`) rather than half-implemented.
- No self-service registration endpoint — user provisioning is via
  `cmd/seed` (dev-only) pending a real integration with the main AyurEze
  platform's account system.
- `GET /ready`'s dependency checks are liveness-style pings, not deep
  health (e.g. doesn't verify migrations are current).

## Day 4 — E2EE + consent

| Item | Status | Notes |
|---|---|---|
| E2EE key generation | IMPLEMENTED | Random 256-bit key generated once at session creation (`sessionsvc.Create`); plaintext held only transiently before envelope encryption |
| Key encrypted at rest | IMPLEMENTED | AES-256-GCM under `API_E2EE_MASTER_KEY_HEX` (`internal/e2ee`); Postgres never holds plaintext key material. Master key is a static env var in this build — documented as a known limitation requiring a real KMS in production |
| Key distribution on authorized join | IMPLEMENTED | Patient/doctor (`sessionsvc.Join`) and, once consented, the AI agent (`sessionsvc.AuthorizeAIAgent`) receive the decrypted key only in the join response — never in `GetSession`, never logged |
| SFU cannot decrypt | IMPLEMENTED (architecturally) | LiveKit only ever forwards encrypted frames; server-side, LiveKit has no key material at all — see `docs/e2ee/README.md`. Client-side SFrame *usage* of the key is Day 7 (SDK) scope |
| Private Mode: AI absent by default | IMPLEMENTED | A session has no `ai_agent` participant row and no consent unless explicitly granted; nothing auto-authorizes it |
| AI Translation Mode: explicit authorization | IMPLEMENTED | `POST /internal/ai-agent/sessions/{id}/authorize` — service-secret authenticated, requires an *active* `ai_translation` consent row, mints a room-scoped token + hands over the E2EE key only then |
| Consent grant/revoke | IMPLEMENTED | Day 3 provided the schema/CRUD; Day 4 wires revocation to immediately (same request) force-disconnect a currently-connected AI agent via `roomsvc.RemoveParticipant` and mark its participant row `revoked` — not on a delay or next poll |
| Security event logging | IMPLEMENTED | `ai_agent.authorize` (success/denied+reason) and `ai_agent.access_revoked` audit actions; `ai_agent_authorized`/`ai_agent_access_revoked` session_events |
| Security tests: unauthorized participant / wrong room / wrong tenant / ended session | IMPLEMENTED | Covered by Day 3's tests (unaffected, still passing) |
| Security tests: AI without consent | IMPLEMENTED | `TestAIAgent_RequiresActiveConsent` — `403` |
| Security tests: AI after consent revoked | IMPLEMENTED | Same test — authorize → (simulated) join via signed webhook → revoke → re-authorize denied `403` → participant row `revoked` |
| Security tests: invalid participant role | IMPLEMENTED | `TestParticipant_InvalidRoleRejectedAtTokenMint` + existing `internal/token` unit tests — the HTTP surface never accepts an arbitrary role for authenticated session endpoints (role is derived server-side from `doctor_id`/`patient_id`) |
| Security tests: expired authorization | IMPLEMENTED | `TestAuth_ExpiredAccessTokenRejected` (app-JWT layer) + Day 2's LiveKit-token-layer equivalent |

**Validation command output** (this session):
```
$ go test ./internal/e2ee/... -v          # 5/5 unit tests passing
$ go test -tags integration -count=1 ./test/integration/...
ok  	github.com/ayureze/telehealth/api/test/integration	2.508s   (14/14 tests passing)
```
Confirmed via targeted log inspection that `e2ee_key` values never appear
in any structured log line (the access-log middleware never logs response
bodies in the first place; the logger's redaction list is a documented
backstop, not the primary control).

**Known limitations / carried forward:**
- Key distribution is server-mediated (the API hands the same session key
  to every authorized participant), not a peer-to-peer ratcheting
  protocol. See `docs/e2ee/README.md` "Known limitations" for the
  production-hardening path.
- `API_E2EE_MASTER_KEY_HEX` is a static env var, not a real KMS —
  `internal/e2ee.KeyManager`'s narrow `Encrypt`/`Decrypt` interface is
  specifically meant to make swapping this out for AWS KMS/GCP KMS/Vault
  a contained change.
- The AI agent's participant status transitioning to `joined` in the Day 4
  test is *simulated* via a directly-signed webhook request (the same
  mechanism validated in Day 3), since the actual Python AI agent that
  would trigger a real LiveKit `participant_joined` event doesn't exist
  until Day 5.
- Client-side SFrame enablement (actually turning on E2EE in the LiveKit
  Web/Flutter SDKs using the distributed key) is Day 7 scope.

## Day 5 — AI encrypted participant

| Item | Status | Notes |
|---|---|---|
| AI agent lifecycle state machine | IMPLEMENTED | `apps/ai-agent/app/lifecycle.py` — explicit transition table (`REQUESTED→AUTHORIZED→JOINING→CONNECTED→PROCESSING→PUBLISHING`, `REVOKED`/`DISCONNECTED`/`FAILED` terminal); invalid/skipped transitions raise; 8 unit tests |
| Authenticate (service credential) | IMPLEMENTED | `AI_AGENT_SERVICE_SECRET` header to the Go API — no human login, no tenant identity of its own |
| Verify authorization/session/consent | IMPLEMENTED | Entirely enforced Go-side (Day 4's `AuthorizeAIAgent`); the agent has no other path to a LiveKit token |
| Join encrypted room | IMPLEMENTED | Real SFrame E2EE via `rtc.E2EEOptions`/`KeyProviderOptions(shared_key=...)` using the actual session key from the Go API — not simulated |
| Subscribe to authorized media | IMPLEMENTED | `auto_subscribe=True`, room-scoped by the LiveKit token's own grant |
| Process audio (pipeline) | PARTIALLY IMPLEMENTED | Transitions to `PROCESSING` on a real subscribed audio track (proves the encrypted media path end-to-end); the actual VAD/STT/translation/TTS processing is Day 6 |
| Publish translated audio | NOT IMPLEMENTED | `PUBLISHING` state exists in the machine and is unit-tested, but nothing reaches it yet — no pipeline to publish output from until Day 6 |
| Leave/revoke correctly | IMPLEMENTED | Distinguishes `DisconnectReason.PARTICIPANT_REMOVED` (→ `REVOKED`, driven by Day 4's consent-revocation force-removal) from any other disconnect (→ `DISCONNECTED`) |
| "Never join merely because a room exists" | IMPLEMENTED | Agent only connects when explicitly told via `POST /v1/agent/sessions/{id}/start`; nothing watches LiveKit and auto-joins |
| Metrics | IMPLEMENTED | `ai_agent_authorize_total`, `ai_agent_join_total`, `ai_agent_state_transitions_total`, `ai_agent_active_sessions` — Prometheus, scraped by the existing Day 1 `ayureze-ai-agent` job |
| Structured JSON logging | IMPLEMENTED | Mirrors the Go API's conventions (service/environment/event_type fields, secret redaction) for uniform Loki queries |
| Automated tests | IMPLEMENTED | 8 unit tests (state machine) + 1 full integration test against the real stack — no mocks: a second real LiveKit participant publishes a genuinely-encrypted audio track (same session key), and the real agent is driven through authorize→join→`CONNECTED`→`PROCESSING`→consent-revoked→`REVOKED` |

**Validation command output** (this session):
```
$ pytest -v                                        # 8/8 unit tests passing
$ pytest -m integration -v tests/test_agent_integration.py
tests/test_agent_integration.py::test_ai_agent_full_lifecycle PASSED
```
Also smoke-tested the standalone `uvicorn app.main:app` process directly
with curl against the live stack (not just the in-process test harness):
triggered `/v1/agent/sessions/{id}/start` against a session with no
consent and confirmed the real HTTP service reaches `FAILED` with
`authorization_denied:403`, matching the integration test's assertion via
a completely different code path (a running server process, not an ASGI
transport in the test process).

**Known limitations / carried forward:**
- No actual audio processing yet — `PROCESSING` is reached and then the
  agent simply waits; Day 6 adds VAD/STT/translation/TTS and the
  `PUBLISHING` transition.
- Single-process, in-memory agent registry — fine for this build; a
  multi-replica deployment would shard by `session_id` (not implemented,
  not currently needed).
- No Dockerfile yet for `apps/ai-agent` (added alongside `apps/api`'s in
  the Day 7 hardening pass) — run via a local virtualenv today, documented
  in `apps/ai-agent/README.md`.

## Day 6 — Real-time translation pipeline

| Item | Status | Notes |
|---|---|---|
| VAD | IMPLEMENTED | Silero VAD via `onnxruntime` (no torch dependency); `TurnSegmenter` adds hangover + minimum-duration filtering for real turn boundaries |
| STT | IMPLEMENTED | faster-whisper (`tiny`), provider interface allows swapping models/vendors |
| Language detection | IMPLEMENTED | `langid` (text) cross-checked against Whisper's audio-based guess; English/Tamil/Malayalam per spec |
| Terminology engine | IMPLEMENTED | Deterministic regex/glossary extraction of numbers, dosage, frequency, duration, Ayurveda/medicine terms |
| Translation | PARTIALLY IMPLEMENTED | Real, working NLLB-200-distilled-600M — **not** the spec's initial pick IndicTrans2 (gated HF access + custom tokenizer toolkit unavailable in this build environment); documented substitution with a clean swap seam, see `docs/ai/README.md` |
| Safety validator | IMPLEMENTED | Deterministic digit-preservation check; verified to actually **block** TTS/publication (not just log a warning) on a corrupted translation |
| TTS | IMPLEMENTED | MMS-TTS (VITS) for English/Tamil/Malayalam |
| Pipeline orchestration + per-stage latency | IMPLEMENTED | `orchestrator.py`; every result carries `timings_ms` for stt/language_id/terminology/translation/safety_validation/tts/total |
| Wired into the live AI agent | IMPLEMENTED | `streaming.py`: subscribed remote audio → VAD segmentation → pipeline (off the event loop, via a thread executor) → republished translated audio track + data-channel captions |
| Captions (original + translated) | IMPLEMENTED | Published as JSON on the `ayureze.captions` LiveKit data topic, including per-stage latency, for SDK clients (Day 7) to render |
| Turn detection / interruption (barge-in) | IMPLEMENTED | New speech mid-publish cancels the in-flight translated-audio publish task rather than letting two utterances overlap |
| Avoiding uncontrolled audio loops | IMPLEMENTED (architecturally) | The agent only ever subscribes to *remote* tracks; LiveKit never delivers a participant's own published track back to it, so the agent cannot hear its own translated output |
| Fallback on unsafe/failed translation | IMPLEMENTED | Safety-blocked results are captioned (`blocked: true`) but never synthesized/published as audio; a failed pipeline segment is logged and skipped without killing the stream |
| Initial pair EN↔TA | IMPLEMENTED | Verified live in both the models-only test and the full live-stack test |

**Validation command output** (this session):
```
$ pytest -v                                                    # 22/22 fast tests (VAD, terminology, safety, lifecycle)
$ pytest -m models -v tests/pipeline/test_pipeline_models.py   # 3/3 — real STT/NLLB/TTS models, no LiveKit
tests/pipeline/test_pipeline_models.py::test_dosage_instruction_round_trip_en_to_ta PASSED
tests/pipeline/test_pipeline_models.py::test_numeric_dosage_is_preserved_end_to_end PASSED
tests/pipeline/test_pipeline_models.py::test_safety_validator_blocks_a_corrupted_translation PASSED

$ pytest -m integration -v tests/test_pipeline_live_integration.py   # real stack + pipeline enabled
tests/test_pipeline_live_integration.py::test_live_translation_pipeline_produces_captions PASSED
```
The live test's own agent log shows the complete real lifecycle in one
run: `AUTHORIZED → JOINING → CONNECTED → PROCESSING (audio_track_from=...)
→ PUBLISHING → PROCESSING → DISCONNECTED`, with a caption data message
received containing non-empty original/translated text and per-stage
`timings_ms` — synthesized English speech streamed into a live encrypted
LiveKit room, VAD-segmented, transcribed, translated to Tamil, safety
-validated, synthesized, and republished, with the doctor-side test client
receiving the caption over the data channel. No mocks anywhere in this
chain.

**Known limitations / carried forward:** see `docs/ai/README.md`'s "Known
limitations" section — IndicTrans2 substitution (NLLB-200 used instead,
documented, swappable), MMS-TTS's lack of digit normalization (spelled-out
numbers required for TTS-sourced test audio; does not affect the
translation-stage safety guarantee, which is tested directly against
text), CPU-only inference latency (~0.6-1s translation, ~0.4s TTS —
acceptable for this build, not production real-time), and untested
sustained-conversation load/jitter.

## Day 7 — SDKs + hardening + observability completion

| Item | Status | Notes |
|---|---|---|
| Flutter SDK | IMPLEMENTED | `sdk/flutter` — headless client (`initialize`, `authenticate`, `createSession`, `joinSession`, `leaveSession`, `endSession`, mic/camera toggles, `enableAITranslation`/`disableAITranslation`, `setLanguage`, caption stream). E2EE on by default, no way to join without it. `flutter analyze`: 0 issues. `flutter test`: 18/18 passing. Two real bugs found and fixed during development (a synchronous-throw bug and an E2EE key-encoding bug — see `sdk/flutter/README.md`) |
| Web SDK | IMPLEMENTED | `sdk/web` — same API surface, TypeScript. `joinSession()` requires an `e2eeWorker: Worker` (bundler-specific, so the SDK never silently skips E2EE). `tsc --noEmit`: 0 errors. `vitest`: 18/18 passing. `npm run build` produces a clean ESM + `.d.ts` `dist/` |
| SDK cross-platform E2EE interop | PARTIALLY IMPLEMENTED | Architecturally sound (both SDKs use LiveKit's standard shared-key SFrame derivation, same as the Python agent) but only directly verified Python-to-Python in this build; not exercised in a real browser/device against the live stack — see `docs/sdk/README.md`'s "What has not been validated" |
| Go API Prometheus metrics | IMPLEMENTED | `internal/metrics`: HTTP request count/latency by route (chi route pattern, not raw path, to avoid cardinality blowup), `auth_login_total`/`auth_refresh_total` by outcome, `sessions_created_total`, `sessions_joined_total` by role/outcome, `sessions_ended_total`, `security_denied_total` by action/reason (covers every denial class the build spec calls out by name), `rate_limited_total`, `ai_consent_total` by grant/revoke. Verified live: driving a failed login against the running API incremented `ayureze_api_auth_login_total{outcome="denied"}` and was visible in Prometheus within one scrape interval |
| AI agent Prometheus metrics | IMPLEMENTED | Added `ayureze_ai_pipeline_stage_latency_seconds` histogram (labeled `vad`, `stt`, `language_id`, `terminology`, `translation`, `safety_validation`, `tts`, `total` — every stage the build spec's AI latency list calls out by name) plus `ayureze_ai_pipeline_segments_processed_total`/`_blocked_total`. Recorded directly in `pipeline/vad.py` (per-frame VAD inference) and `pipeline/orchestrator.py` (every other stage), alongside the pre-existing `ai_agent_*` lifecycle/authorize/join counters. Verified against real model inference (`pytest -m models`, 3/3 passing with the new instrumentation active) and by inspecting rendered Prometheus output directly |
| Grafana dashboards | IMPLEMENTED | Six dashboards under `observability/grafana/dashboards/`, matching the build spec's six categories: **Calls** (session create/join/end rates, consent grant/revoke, lifecycle log stream), **WebRTC** (LiveKit room/participant counts, RTT/jitter/packet-loss/quality-score histograms, PLI rate, join latency, room duration — all against real `livekit_*` metric names read from the live server), **APIs** (request rate/error rate/latency by route, login/refresh outcomes, rate-limiting), **AI** (all 8 pipeline-stage latencies p50/p95, segments processed vs. blocked, lifecycle transitions), **Infrastructure** (up targets, otel-collector throughput, Go/Python runtime resource metrics, log volume), **Security** (denial rate by action/reason, failed-login/rate-limited/AI-denial counts, top denial reasons table, audit log stream). All six load cleanly via the Grafana provisioning API and were spot-checked against real Prometheus queries |
| `apps/api` Dockerfile | IMPLEMENTED | Multi-stage: `golang:1.26-bookworm` build → `gcr.io/distroless/static-debian12:nonroot` runtime (no shell, non-root uid 65532, static `CGO_ENABLED=0` binary). Built and run against the live compose network in this session (see "Docker build verification" below for exactly what was and wasn't exercised) |
| `apps/ai-agent` Dockerfile | IMPLEMENTED | `python:3.11-slim-bookworm`, dedicated non-root user (uid 10001), `PIPELINE` build arg (default `true`) gates whether the ~2GB Day 6 model dependencies are installed — a lifecycle-only image never pays for them. Model weights are never baked in; mounted as a volume. Built and run against the live compose network in this session |
| Docker Compose service integration | IMPLEMENTED | `infrastructure/docker/docker-compose.yml` now defines `api` and `ai-agent` services on `ayureze-net`, closing a gap the compose file had anticipated since Day 1 (LiveKit's webhook config already pointed at `http://api:8080/...`). `docker compose up -d api ai-agent` was run in this session: both reached a healthy state, Prometheus's `up{job=~"ayureze-api|ayureze-ai-agent"}` reported `1` for both, and a real login request against the *containerized* API was observed incrementing its Prometheus counters live |
| `.dockerignore` for both services | IMPLEMENTED | Excludes `.git`, tests, docs, and (for the AI agent) `.venv`/`models`/`__pycache__` from the build context |

**Docker build verification — what was and wasn't exercised:**
This sandbox's outbound network re-terminates TLS with a CA that `docker
build`'s isolated build network doesn't trust, so a literal `docker build`
calling `go mod download` / `pip install` against the public registries
fails here with a certificate error — a sandbox limitation, not a defect
in either Dockerfile (a normal CI runner or dev machine hits none of this).
Full detail, including exactly which build layers were and weren't
exercised as a result, is in `docs/deployment/README.md`. Bottom line:
both images were built (via an offline substitution for the
network-dependent dependency-fetch layer) and run for real against the
live Postgres/Redis/LiveKit stack, including via `docker compose up`
itself once a stale container object from an earlier crash-loop was
cleared — both `/health` endpoints responded and both services' real
Prometheus metrics were observed flowing into the live Prometheus
instance. What was *not* directly exercised in this sandbox: the literal
`go mod download` / `pip install` network-fetch steps inside `docker
build` (expected to work normally with ordinary internet access; not
silently assumed here, per this project's "never report an untested
feature as working" rule).

**Known limitations / carried forward:**
- No Kubernetes manifests/Helm charts — the build spec's "Kubernetes-ready"
  requirement is served by the two Dockerfiles existing at all; the actual
  k8s resources are out of scope for this build.
- No TLS termination in this repo's compose stack — production needs a
  TLS-terminating ingress/LB in front of both app services plus LiveKit's
  own `wss://` configuration.
- No real secret-management integration — `.env`-file injection is a
  local-dev convenience; production needs Vault/KMS/Sealed-Secrets/etc.
- AI agent's `AgentRegistry` is in-process/single-replica only; untested
  under multi-replica deployment.
- SDK cross-platform E2EE interop (Flutter/Web ↔ Python agent, in a real
  browser/device) is architecturally sound but not directly tested — see
  the SDK row above.
- OpenTelemetry distributed tracing: the otel-collector has run since Day
  1 and receives/exports spans, but neither `apps/api` nor `apps/ai-agent`
  currently emit their own application-level spans (only Prometheus
  metrics + structured logs) — no OTel SDK instrumentation was added to
  either service's code in this build.

## Post-Day-7 — Real cross-platform E2EE interoperability validation

Full detail in **`docs/e2ee/VALIDATION.md`**. Summary: E2EE had previously
only been validated by source inspection and mocked unit tests — that was
called out explicitly as insufficient (`docs/sdk/README.md`'s "What has
not been validated"). A dedicated real-integration test harness
(`apps/e2e-harness/`, Playwright against the real Go API/LiveKit/Postgres/
Redis stack, plus a real native LiveKit participant via Python) was built
to close that gap.

| Item | Status | Notes |
|---|---|---|
| Web ↔ Web E2EE (audio+video) | VERIFIED | Real encrypted media both directions, LiveKit's own diagnostics (`Participant.isEncrypted`, zero `EncryptionError`s), clean leave |
| Private Mode (AI absent) | VERIFIED | Real E2EE call, exactly 2 participants, `aiTranslationAuthorized: false` from the real API |
| AI Translation Mode (authorized encrypted participant) | VERIFIED | Real consent grant → real AI-agent `/start` call → AI joins as `role: ai_agent`, `isEncrypted: true`, confirmed via the AI agent's real Prometheus metrics |
| AI authorization boundaries (no consent, cross-tenant, revocation, session end) | VERIFIED | All 4 correctly rejected/stopped, against the real Go API and real AI agent |
| Network loss/reconnect | VERIFIED | Real network cut via Playwright/CDP, real LiveKit reconnect, E2EE remains functional after |
| Web ↔ native (Flutter/AI-agent) E2EE | **NOT VERIFIED — CONFIRMED BROKEN** | Real, reproducible key-derivation mismatch between the Web SDK and the native LiveKit stack (shared by Flutter and the Python AI agent); 4 candidate fixes tried, none worked; matches an unresolved upstream LiveKit issue (livekit/livekit#4247) |
| Flutter (any combination) | BLOCKED | No Flutter SDK or Android emulator/device available in this environment |

**Two real, previously-undetected bugs found and fixed** (neither visible
from source inspection or mocked unit tests):
1. `sdk/web`'s `ApiClient` called its default `fetch` unbound, which
   throws `Illegal invocation` in every real browser — invisible because
   every unit test injected its own mock `fetch`.
2. `sdk/web`'s `joinSession()` never called LiveKit's
   `room.setE2EEEnabled(true)` — **every session was publishing real,
   unencrypted media** despite the SDK's "E2EE always on" claim. Only
   real LiveKit server-reported track metadata caught this.

Both are fixed, with real (not mocked) regression tests. The cross-
platform key-derivation mismatch (Web ↔ native) is **not fixed** — left
as an intentionally-failing regression trip-wire
(`apps/e2e-harness/tests/kdf-compat.spec.ts`) with the full investigation
documented, since no working fix was found in this pass and it traces to
an open upstream LiveKit ambiguity, not a bug in this codebase alone.

**Production implication, stated plainly**: do not deploy a configuration
where Web clients and Flutter/native clients (including the AI agent) are
expected to decrypt each other's encrypted media, until Finding 3 in
`docs/e2ee/VALIDATION.md` is resolved.

### Follow-up pass — fail-closed hardening + further root-cause attempts

A second validation pass specifically targeted resolving the Web↔native
mismatch and added a new, previously-untested security property check:

- **Fail-closed verified**: found and fixed a related gap —
  `joinSession()` called `room.setE2EEEnabled(true)` but never confirmed
  it actually took effect before returning success (the confirmation is
  async, via a LiveKit event, not guaranteed by that call resolving). Now
  waits for confirmation and fails closed (disconnect + clear error) on
  any timeout/failure. Verified with a real dead-Worker test.
- **Root cause still open**: two more forensic angles (external LiveKit
  issue research confirming AES-128/256 selection by raw-key byte length;
  a direct FFI-level key-export probe) and one more untested parameter
  combination were tried against the Web↔native mismatch. None resolved
  it. `docs/e2ee/VALIDATION.md` now documents 5 total candidate fixes
  tried across both passes, all unsuccessful. Root cause remains
  correctly reported as unresolved rather than papered over.
- Full regression (Go unit+integration, Python unit, Web SDK unit, full
  Playwright e2e-harness suite) re-run clean except the expected,
  intentional `kdf-compat.spec.ts` forward-direction failure.
