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
`NOT IMPLEMENTED` — not started yet.

## Day 4 — E2EE + consent
`NOT IMPLEMENTED` — not started yet.

## Day 5 — AI encrypted participant
`NOT IMPLEMENTED` — not started yet.

## Day 6 — Real-time translation pipeline
`NOT IMPLEMENTED` — not started yet.

## Day 7 — SDKs + hardening + observability completion
`NOT IMPLEMENTED` — not started yet.
