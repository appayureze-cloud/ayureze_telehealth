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
| Docker Compose: LiveKit v1.8.0 self-hosted | IMPLEMENTED | Healthy, connects to authenticated Redis, keys injected via `LIVEKIT_KEYS`, config via `LIVEKIT_CONFIG` (no secrets on disk), survives restart |
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
`NOT IMPLEMENTED` — not started yet.

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
