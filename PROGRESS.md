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
| Web ↔ native (Python AI agent) E2EE | **FIXED + VERIFIED (fifth pass)** | Two concrete AyurEze bugs (KDF-input mismatch, key-size mismatch) found by reading LiveKit's real native crypto source and fixed — see `docs/e2ee/VALIDATION.md`'s "Fifth pass". Real native publisher → real Web subscriber decrypts successfully; reverse direction reports zero errors. Not an upstream LiveKit limitation as previously (incorrectly) classified. |
| Flutter (any combination) | FIX APPLIED, NOT DEVICE-VERIFIED | Same root-cause fix applied to `sdk/flutter`'s key handling by source-level reasoning; no Flutter SDK or Android emulator/device available in any sandbox pass so far to confirm it for real |

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
platform key-derivation mismatch (Web ↔ native) was **fixed in a later
pass** (see "Fifth pass — root cause found and fixed" in
`docs/e2ee/VALIDATION.md`): two concrete AyurEze bugs, not an upstream
LiveKit limitation. `apps/e2e-harness/tests/kdf-compat.spec.ts` — kept as
the permanent regression trip-wire throughout — now passes both
directions against the real stack.

**Production implication, updated**: Web ↔ native (the Python AI agent)
is fixed and verified — the restriction below no longer applies to that
pairing. It still applies to Flutter until a real device/emulator test
confirms the same fix there: do not deploy a configuration where Web
clients and Flutter clients are expected to decrypt each other's
encrypted media until that device-tier verification happens — see
`docs/e2ee/VALIDATION.md`'s "Fifth pass" and "Flutter feasibility".

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

### Third pass — compatibility investigation (version matrix, not a fix attempt)

A dedicated pass, scoped strictly to answering "does an officially
supported LiveKit Server/Web/Flutter/native version combination make
Web ↔ native E2EE work" — not to redesigning anything.

- **Issue #4247 re-checked directly**: still open, zero maintainer
  comments, no linked fix, no "resolved as of vX" note.
- **One concrete version-specific lead tested**: Python SDK 1.1.7 adds
  `KeyProviderOptions.key_derivation_function`, letting the native side
  explicitly select PBKDF2 or HKDF for the first time (1.0.7 never
  exposed this at all). Upgraded `apps/ai-agent` to `livekit==1.1.7` and
  retested twice: once with the native side left on its new implicit
  default, once with it explicitly set to HKDF and matched against the
  Web SDK's own HKDF code path. **Both failed identically** to every
  prior attempt (`InvalidKey: Decryption failed: OperationError`).
- **This rules out "KDF algorithm choice" as the root cause with
  certainty** — the first time both algorithms were tested explicitly
  matched on both sides, not just left on defaults. Across all three
  passes, 8 total parameter/version combinations have been tried; none
  work.
- The `livekit==1.1.7` upgrade is kept regardless (real, current,
  independently-justified fix per its own changelog — re-verified with
  the full `ai-agent` test suite, 22/22, and the real agent-lifecycle
  integration test), but it does **not** resolve the interop gap.
- `sdk/web/src/client.ts` was temporarily reconfigured to test the HKDF
  path, then fully reverted — no production code changed as a result of
  this pass.
- Classification: given three full passes and no access to the native
  frame-crypto core's C++ source, this is now assessed as an **upstream
  LiveKit limitation**, not an AyurEze integration bug. See
  `docs/e2ee/VALIDATION.md`'s "Third-pass note" for full detail.

### Fourth pass — minimal reproduction confirms classification C

A follow-up pass built a reproduction with **zero AyurEze code anywhere
in the chain**: room created directly via LiveKit's own
`RoomService.CreateRoom`, JWTs hand-minted with raw PyJWT against
LiveKit's public token spec, a freshly random key generated inline, and
raw `livekit-client`/`livekit` (Python) SDK calls only — no Go API, no
`internal/e2ee`, no `internal/token`, no `sdk/web`'s
`AyurezeTelehealthClient`. Result: identical failure (`InvalidKey:
Decryption failed: OperationError`, 61KB of real audio received, remote
`isEncrypted: true`). With every AyurEze-authored line removed, the
mismatch persists exactly as before — this rules out an AyurEze
integration bug with high confidence and **confirms classification C
(LiveKit upstream limitation)**, not merely "probable." See
`docs/e2ee/VALIDATION.md`'s "Fourth pass" and "Final classification"
sections.

### Fifth pass — Flutter SDK tooling available this session; still no device tier

Unlike prior sessions, this execution environment ships a real Flutter
SDK (`3.27.1`). Re-ran, for real: `flutter pub get` (clean), `flutter
analyze` (**0 issues**), `flutter test` (**18/18 passing**) — independently
re-confirming `docs/sdk/README.md`'s existing Flutter-SDK claims under
real execution rather than trusting them at face value. `flutter doctor`
confirms no Android SDK, no `adb`, no emulator, no physical device, and
no `/dev/kvm` — installing a full Android SDK + emulator was assessed
and not attempted (only ~5.7GB free disk, and no KVM means any emulator
would run in software-only mode, frequently non-functional in headless
containers). **Device/emulator-level Flutter testing (any real
connect/publish/subscribe/E2EE exercise on an actual Android/iOS target)
remains BLOCKED** — not claimed, not assumed.

### Sixth pass — root cause found and fixed (classification C overturned)

**Classification C ("confirmed LiveKit upstream limitation") was wrong.**
A dedicated pass re-investigated E2EE-FINDING-3 using a capability none
of the first five passes had: `git clone`/`raw.githubusercontent.com`
access to LiveKit's own source (`api.github.com` stayed blocked, as
always, but plain `git`/raw-HTTP paths worked in this session). Instead
of trying more KDF parameter combinations (explicitly ruled out), this
pass read the actual native crypto implementation
(`api/crypto/frame_crypto_transformer.h`/`.cc` in `webrtc-sdk/webrtc`,
the real WebRTC fork LiveKit's native SDKs compile against) and found two
concrete, fixable AyurEze bugs:

1. **KDF input mismatch**: native/Flutter code base64-decoded the join
   response's E2EE key before deriving from it; the Web SDK derives from
   the base64 *text* itself. Same PBKDF2 salt/iterations/hash on both
   sides, but different input bytes — proved with a byte-level synthetic
   test vector (Node's real WebCrypto vs. Python's `hashlib.pbkdf2_hmac`).
2. **Key-size mismatch — the one that actually broke decryption**:
   LiveKit's native `SetKeyFromMaterial()` hardcodes a 128-bit derived
   key with no way to configure it otherwise (confirmed directly from
   source — the 256-bit derivation calls in the same file are ratchet-
   only, never the initial key). The Web SDK's own default is `keySize:
   128` for exactly this reason, but `sdk/web/src/client.ts` explicitly
   overrode it to `keySize: 256` — an AyurEze customization that made the
   Web client derive an AES-256-GCM key native can never produce.

**Fixed**: `sdk/web/src/client.ts` (drop the `keySize` override),
`apps/ai-agent/app/agent.py` + `apps/e2e-harness/tests/helpers/
native_participant.py` (stop base64-decoding before deriving),
`sdk/flutter/lib/src/ayureze_client.dart` (pass the base64 text straight
through, same reasoning). Also fixed an unrelated pre-existing
test-harness hang (`nativeParticipant.ts`'s `waitDone()` never resolving
after `kill()`) found while verifying the real fix.

**Verified for real, not by static analysis**:
`apps/e2e-harness/tests/kdf-compat.spec.ts` now passes both directions
against the live stack — a real native (Python) publisher's encrypted
audio decrypts successfully on a real Web subscriber (down from 5
`InvalidKey` errors before the fix, to zero), and the reverse direction
reports zero errors using the same now-matching key material. Web ↔ Web
re-verified unaffected. Full regression suite green: Python 101/101, Go
gofmt/vet/unit/integration clean, Web typecheck+19/19 unit+build clean,
Flutter 0 analyze issues + 18/18 tests, full Playwright suite 13/13.

**New classification: D — application implementation bug, found and
fixed** (not C). Flutter's fix is applied and reasoned identically to the
verified Web/Python fix, but — consistent with every prior pass — could
not be exercised on a real Android device/emulator in this sandbox;
treat it as fixed by inspection, not device-verified. Full writeup:
`docs/e2ee/VALIDATION.md`'s "Fifth pass — root cause found and fixed"
section (VALIDATION.md's own pass numbering is independent of this
document's; both describe the same work).

## Post-audit — AI safety validator hardening (critical fix)

The production-readiness audit's highest-priority finding — the
deterministic AI translation safety validator only compared numeric
digit sequences, so a unit swap, a negation flip, or a medicine-name
substitution all passed as `safe=True` — is now **FIXED and VERIFIED**.

- Rebuilt `apps/ai-agent/app/pipeline/safety.py` around a normalized
  `SafetyEntities` comparison (numbers as an order-independent multiset,
  dosage value+unit pairs, frequency canonical codes, duration
  value+unit pairs, food-timing constraints, language-aware negation,
  protected medicine/Ayurveda term preservation distinguishing safe
  transliteration from semantic substitution) — still fully
  deterministic, no model added anywhere in the validation path.
- New `apps/ai-agent/app/pipeline/negation.py`: language-aware negation
  detection (English + Tamil), returns `None` (not `False`) for an
  uncovered language so "unknown" is never silently treated as "safe."
- Extended `terminology.py` with unit canonicalization, dosage/
  frequency/duration extraction (English and Tamil, including Tamil-
  specific agglutination/sandhi handling — found and fixed two real
  linguistic edge cases via this pass's own testing: a duration-stem
  collision between "month" (மாத) and "tablet" (மாத்திரை), and Tamil
  case-inflection changing a protected term's final consonant), and a
  `TRANSLITERATIONS` table for Ayurveda/medicine term preservation
  across English/Tamil.
- 75-case synthetic test corpus
  (`tests/pipeline/test_safety_validator_corpus.py`): every example in
  the hardening task's spec (unit/numeric/frequency/duration/negation/
  medicine-substitution rejects, safe-reformatting/safe-transliteration
  passes, Tamil↔English both directions, adversarial mutations, false-
  positive avoidance) — all passing. Plus a 4-case orchestrator-level
  test (`test_tts_gate.py`) proving the TTS gate can't be bypassed, using
  fake providers so it stays fast.
- Re-verified against **real NLLB-200 inference**
  (`tests/pipeline/test_pipeline_models.py`), not just synthetic text —
  this surfaced and fixed two additional real gaps the initial curated
  Tamil pattern set missed (a spelled-out-number-word phrasing of
  "twice", and "தினசரி" as an alternate word for "daily"), both fixed
  generally rather than patched as one-off literal phrases.
- Measured, not invented: validator latency ~0.13-0.16ms/call — negligible
  next to STT/translation/TTS (hundreds of ms each) in the same pipeline
  run.
- Logging hardened alongside the fix: `streaming.py`'s block-event log
  line now carries only `reason_codes` (e.g. `"unit_mismatch"`), never
  the full human-readable `reasons` text, which can quote extracted
  numbers/units/terms.
- Full regression re-run clean after the change: Go (unit+integration),
  Web (typecheck/unit/build), Flutter (analyze/test), AI agent (101
  fast unit tests + real-model tests), and the full Playwright
  `apps/e2e-harness` suite — `kdf-compat.spec.ts` untouched, still
  intentionally red as the E2EE regression trip-wire.
- See `docs/ai/README.md`'s "Safety validator" section for the full
  design/normalization-rule reference and current known limitations
  (English/Tamil only; Malayalam not yet covered; curated, not
  exhaustive, vocabulary tables) and `docs/security/README.md` for the
  updated red-team finding status.

## Post-audit — Live AI integration: VAD bug, then E2EE key-derivation bug (both fixed)

Closed the last two software-side gaps in `test_pipeline_live_integration.py`
(the full Go API → FastAPI → AI Agent → real LiveKit room → real E2EE →
real STT/translation/TTS chain, no mocks), across two passes:

- **Pass 1 — Silero VAD bug**: `app/pipeline/vad.py`'s `SileroVAD` was
  missing the 64-sample context buffer Silero's own official calling
  convention requires, confirmed against the SHA-256-matched official
  model file and `snakers4/silero-vad`'s own reference implementation.
  Fixed; added `tests/pipeline/test_vad_tts_compatibility.py` (4/4
  passing) and a real recorded-speech fixture (`tests/fixtures/jfk.flac`,
  openai/whisper's own MIT-licensed public-domain JFK sample) so the live
  test no longer depends on TTS-synthesized audio's acoustic quirks.
- **Pass 2 — token-grants hypothesis disproven, real root cause found**:
  after the VAD fix, the live test still received zero-RMS audio, but
  only inside its full orchestration — three minimal reproductions
  (bare `rtc.Room()` pairs, with/without E2EE, and the real
  `LiveAudioProcessor` wired directly) all received correct audio.
  Systematically ruled out, each with real evidence: event-loop
  blocking (real blocking `httpx.Client` calls didn't break a known-good
  repro), the token-grants hypothesis (disproven twice — a structural
  JWT comparison showing identical grants, and a real controlled
  token-swap experiment where both the Go-issued and a self-minted
  token failed identically), and the FastAPI/ASGI/registry scaffolding
  (bypassed entirely by driving the real `AIAgent` class directly —
  still failed). Root cause: the test itself (not `app/agent.py`, which
  was always correct) called `base64.b64decode(e2ee_key)` before handing
  it to `KeyProviderOptions`, when this codebase's documented convention
  (since commit `4d14357`) is to pass the UTF-8 encoding of the base64
  *text* itself, never decoded. The doctor and the AI agent were
  encrypting/decrypting with two different keys — real encrypted RTP
  genuinely arrived, but decrypted to all-zero PCM, exactly the observed
  symptom and exactly what no other hypothesis could explain.
- **Fix**: one line in `tests/test_pipeline_live_integration.py`
  (`key_bytes = join_resp["e2ee_key"].encode("utf-8")`), test-only — no
  production code changed. `xfail(strict=True)` marker removed.
- **Verified**: `test_live_translation_pipeline_produces_captions` now
  passes reliably (4 consecutive real runs). Full regression re-run
  clean: Go tests, AI-agent Python unit (116) + integration (2) +
  real-model (7) suites, Web SDK (19), Flutter (41), Playwright (15).
- **Result**: no software-side blocker remains on the live AI
  integration path. The only open items are external-environment
  verification — VPS deployment, a real TURN relay test against that
  deployment, and a real Android/Flutter device E2EE test — none of
  which are reproducible inside this sandbox.

## Post-audit — Full streaming architecture (opt-in, alongside the existing pipeline)

Added the full streaming translation architecture requested (real-time
partial ASR, incremental commit/safety/TTS staging, a language registry +
routers for new STT/translation/TTS models) as a NEW, OFF-BY-DEFAULT path
(`AI_AGENT_STREAMING_PIPELINE_ENABLED=false`) alongside the existing
whole-utterance pipeline, which remains untouched and the default —
explicit instruction: don't remove or risk existing working functionality.
Full detail in `docs/ai/streaming.md`, `docs/ai/models.md`,
`docs/ai/language-registry.md`, `docs/ai/latency.md`, and
`docs/MODEL_LICENSE_MATRIX.md`.

**Environment constraints, established before writing any code**: no GPU
(`nvidia-smi` absent, no CUDA), and only 4.2GB free disk — insufficient
for even one of the five new large models. Per explicit instruction, no
new model weights were downloaded; every new provider class is written
against its model's real, verified API but reports
`ModelNotAvailableError` in this build.

**New, real, fully-tested components** (57 new tests, all passing, no
existing test modified): `TranscriptStabilityFilter` + `CommitPolicy`
(the build spec's own "I have a stomach pain" anti-duplication example
verified directly), `SafetyCommitPolicy` (wraps — never replaces — the
existing deterministic `safety.validate()`; the "Take 5" incomplete-dosage
example and a real Tamil 5mg→50mg mutation block both verified),
`LanguageRegistry`/`TranslationRouter`/`TTSRouter` (fail-closed, real
tests), `AudioOutputBuffer` (sequencing/dedup/stale/missing-chunk
handling), `StreamingSessionPipeline` (bounded-queue async orchestration,
barge-in, backpressure — tested against fake providers), and two REAL
streaming wrappers around this build's OWN already-resident models:
`StreamingFasterWhisperSTT` (real partial/final transcripts from the real
JFK speech fixture) and `StreamingMmsTTSProvider` (real chunked/cancellable
audio from real MMS-TTS synthesis).

**New provider classes, written but not downloaded/certified**:
`Qwen3ASRProvider`, `OPUSMTProvider`, `MADLADProvider`, `Qwen3TTSProvider`,
`CosyVoice3Provider` — each against its real, `WebFetch`-verified
quickstart API and license (verification date 2026-09-25), each failing
closed with a clear `ModelNotAvailableError` rather than silently
degrading.

**Real finding, independent of the streaming work itself**: this license
audit surfaced that `facebook/nllb-200-distilled-600M` and
`facebook/mms-tts-{eng,tam,mal}` — the models this build has been
**shipping since Day 6** for its primary en↔ta pair — are both
`CC-BY-NC-4.0` (non-commercial); NLLB's own model card states it is "not
released for production deployment." Not previously documented in this
repo. `LanguageRegistry`'s default entry for en↔ta reflects this
correctly: fully certified (real safety-corpus + live-integration
evidence) but `license.verified = False`, so `is_production_ready()`
correctly returns `False` despite complete certification. See
`docs/MODEL_LICENSE_MATRIX.md` for options.

**Real finding**: `StreamingMmsTTSProvider`'s first-audio-chunk latency
equals its total synthesis latency (measured: 1286.5ms both) — VITS is
non-autoregressive and cannot emit audio before the whole utterance is
synthesized, so chunking its output gives ordering/barge-in benefits but
no first-audio latency improvement. Reaching the build spec's ~1-1.5s
first-audio target needs a genuinely incremental model (Qwen3-TTS/
CosyVoice3), neither downloaded this pass.

**What was NOT done, explicitly**: no model weights downloaded; no GPU
benchmarking (none available); `StreamingSessionPipeline` not wired into
the live LiveKit audio path and not run end-to-end with real
STT+translation+TTS together (only against fakes) — see
`docs/ai/streaming.md`'s "Open design questions." Two open design
questions (a default reference voice per language for the voice-cloning
TTS models; Qwen3-ASR's real streaming needs a separate vLLM backend) are
documented, not resolved.

**Full regression, re-run clean after every addition**: Go
(build/vet/test), AI-agent Python unit (173, up from 116), real-model (15,
up from 7 — includes real streaming STT/TTS tests), integration (2,
unchanged and still passing — confirms the existing live path is
untouched), Web SDK (19), Flutter (41), Playwright (15).

## Post-audit — Switched the default translation/TTS models off NLLB-200/MMS-TTS (explicit request)

Following the licensing finding above, explicitly requested: switched
`app/pipeline/factory.py`'s `build_default_pipeline()` — the function
every real session uses — from NLLB-200/MMS-TTS to MADLAD-400/Qwen3-TTS
(both Apache-2.0), with no fallback configured back to the old models.
Same switch made in `language_registry.py`'s default en<->ta/en<->ml
entries. `NLLBTranslationProvider`/`MmsTTSProvider` remain in the codebase
(other tests and `StreamingMmsTTSProvider` still use them directly) but
are the default nowhere anymore.

**Explicitly accepted, real consequence**: MADLAD-400/Qwen3-TTS are not
downloaded in this sandbox (no GPU) — `build_default_pipeline()` now
raises `ModelNotAvailableError`. **AI translation does not currently run
in this environment.** Added a matching fix in `main.py`'s
`POST /v1/agent/sessions/{id}/start`: this now returns a clear `503`
instead of an unhandled 500, since the previous code had no handling for
this failure mode at all. `tests/test_pipeline_live_integration.py` and
the 3 `build_default_pipeline`-dependent cases in
`tests/pipeline/test_pipeline_models.py` now `pytest.skip()` with an
explicit reason instead of failing or passing falsely.

**Certification correctly reset, not carried over**: en<->ta's prior
"certified" status was real evidence measured against NLLB-200/MMS-TTS's
actual translation output — it does not transfer to MADLAD-400/Qwen3-TTS
without re-running the same regression evidence. `language_registry.py`
resets it to `"testing"` (all flags `False`). Licensing is now resolved
for this pair (`license.verified=True`); certification and GPU
availability are the two remaining, real gates —
`is_production_ready("en", "ta")` is still `False`, now for those reasons
instead.

**Full regression re-run clean**: AI-agent Python unit (174, up from 173
— 1 test rewritten into 2 to reflect the new registry state), real-model
(12 passed + 3 skip cleanly, down from 15 passed — the 3 skips are the
direct, expected, accepted consequence above), integration (1 passed + 1
skips cleanly — `test_ai_agent_full_lifecycle` unaffected,
`test_live_translation_pipeline_produces_captions` skips with a clear
reason instead of failing). Go/Web/Flutter/Playwright not re-run for this
specific change — no shared code touched, already confirmed green earlier
this session.

## Post-audit — Real deployment target is a CPU-only VPS: made the translation/TTS backend deploy-time selectable, defaulted to a CPU-feasible commercial option

The prior switch to MADLAD-400/Qwen3-TTS was licensing-correct but
GPU-only per both models' own docs — the real deployment target turned
out to be a **CPU-only VPS**, so neither would actually run there either.
Investigated two more candidates for CPU-friendly, commercially-licensed
TTS: **k2-fsa/OmniVoice** (pretrained weights are CC-BY-NC despite an
Apache-2.0 codebase — same non-commercial problem, plus GPU-oriented with
unconfirmed Tamil support) and **Piper TTS** (engine is MIT and genuinely
CPU-fast, but its Tamil voice's specific license is unverified/mixed,
depending on training dataset) — both rejected, real gap remains open for
TTS specifically.

For translation, found a genuinely CPU-feasible commercial option:
`Helsinki-NLP/opus-mt-en-dra`/`opus-mt-dra-en` (Apache-2.0, small MarianMT
models covering English<->Tamil/Malayalam/Kannada/Telugu, needs a
`>>tam<<`-style target tag for the one-to-many direction — verified
against the live model cards). `OPUSMTProvider` gained `target_lang_tag`
support for this. Built `_DirectionalOpusMT` (`factory.py`) to dispatch
between the two single-direction checkpoints a real doctor<->patient
conversation needs.

**Made `build_default_pipeline()` deploy-time selectable** rather than
picking one backend and removing the other — `app/config.py`'s new
`AI_TRANSLATION_BACKEND` (`opus-mt` default | `madlad`) and
`AI_TTS_BACKEND` (`none` default | `qwen3-tts`). Nothing is deleted:
MADLAD-400/Qwen3-TTS remain fully intact as the GPU-path option for when
real GPU infrastructure exists. `language_registry.py`'s en<->ta/en<->ml
entries updated to match (primary = opus-mt, fallback = madlad/qwen3-tts).

**Made TTS genuinely optional** in the orchestrator
(`TranslationPipeline(tts=None)`) rather than only offering "a working
TTS or a crashed pipeline" — real transcription/translation/safety
validation all still run; `PipelineResult.audio` is simply `None`. This is
CAPTIONS-ONLY mode, the real default now: no TTS candidate investigated so
far is both commercially licensed and CPU-feasible. `main.py`'s
`/start` handler unaffected by this specific change (still returns 503 on
`ModelNotAvailableError`, now from the OPUS-MT translator specifically in
this sandbox rather than MADLAD).

**Real, meaningful difference from the previous switch**: with the new
defaults (`opus-mt`/`none`), `build_default_pipeline()` needs NO GPU at
all — only `AI_ALLOW_MODEL_DOWNLOAD=true` on a real deploy. It still
doesn't run in THIS sandbox (no downloads happen here either, by
instruction), but a real CPU-only VPS deployment now has a genuine,
non-GPU-blocked path to real translation (captions), not just a
GPU-blocked one.

Added real unit tests: `_DirectionalOpusMT` dispatch logic and
backend-selection error handling (`test_factory.py`, 5 tests), captions-only
orchestrator behavior including that the safety gate still applies with
no TTS configured (`test_tts_gate.py`, +2 tests). Full regression re-run
clean: AI-agent Python unit (181, up from 174), real-model (12 passed + 3
skip cleanly, same skip count as before — still gated on
`AI_ALLOW_MODEL_DOWNLOAD`, now for the CPU-feasible model), integration (1
passed + 1 skips cleanly, unchanged).

## Post-audit — Two more CPU-friendly TTS candidates investigated and wired in as selectable backends

Explicitly asked to reconsider NLLB-200 (confirmed non-commercial — user
decided against it once told AyurEze is/will be a commercial product) and
to find an "internationally acceptable" TTS. Checked Kokoro-82M and Bark —
both genuinely global, well-known, permissively-licensed (Apache-2.0/MIT)
— against Tamil support directly: **neither supports Tamil at all**,
confirmed via their own documentation and (for Bark) the project's own
GitHub discussions.

User then asked to use ai4bharat and Piper specifically. Verified both for
real:

- **ai4bharat/indic-parler-tts**: Apache-2.0, confirmed commercial-clean,
  confirmed real Tamil support via named speakers ("Jaya"/"Kavitha" — no
  reference-voice-clip requirement, unlike Qwen3-TTS/CosyVoice3's
  voice-cloning architecture). Has a documented CPU fallback path in its
  own example code (0.9B params — real, honest caveat: CPU latency is
  unverified, expected multi-second per utterance, not benchmarked).
  Added `IndicParlerTTSProvider` (`tts.py`) and wired it in as
  `AI_TTS_BACKEND=indic-parler-tts`.
- **Piper**: found and flagged a real, consequential fact mid-investigation
  — the actively-maintained successor repo (`OHF-Voice/piper1-gpl`, the
  original `rhasspy/piper` is archived as of Oct 2025) is **GPL-3.0**, not
  MIT. Verified the archived original really was MIT (confirmed verbatim
  from its `LICENSE.md`). Designed `PiperTTSProvider` to invoke Piper via
  CLI subprocess ONLY, never `import piper` as a Python library into this
  process — the standard safe pattern for consuming GPL command-line tools
  commercially (GPL's copyleft attaches to linking/derivative works, not
  separate-process invocation), verified with a real AST-based test that
  the class contains no `import piper`/`from piper` statement. This makes
  the provider safe regardless of which engine version is actually
  installed. The genuinely unresolved gap: the specific community Tamil
  voice checkpoint (`ta_IN-Valluvar-medium.onnx`)'s dataset license could
  not be identified despite real research effort across multiple angles —
  `PiperTTSProvider.metadata()` deliberately reports `commercial_use=False`
  for this reason, and it should not be enabled in production until that
  specific question is resolved. Wired in as `AI_TTS_BACKEND=piper`.

Both new classes are real, tested, and wired into `factory.py`'s
`_build_tts()` alongside the existing `none`/`qwen3-tts` options — nothing
removed, all four backends coexist. Added 16 new tests: 9 in
`test_cpu_tts_candidates.py` (metadata correctness including the
deliberately-conservative `commercial_use=False` on Piper, fail-closed
paths for both providers, and the AST-verified "never imports piper as a
library" safety property) and 2 more in `test_factory.py` (backend
dispatch for both new options). Full regression re-run clean: AI-agent
Python unit (192, up from 181), real-model (12 passed + 3 skip cleanly,
unchanged).
