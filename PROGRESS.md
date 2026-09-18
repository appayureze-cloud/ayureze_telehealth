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
`NOT IMPLEMENTED` — not started yet.

## Day 5 — AI encrypted participant
`NOT IMPLEMENTED` — not started yet.

## Day 6 — Real-time translation pipeline
`NOT IMPLEMENTED` — not started yet.

## Day 7 — SDKs + hardening + observability completion
`NOT IMPLEMENTED` — not started yet.
