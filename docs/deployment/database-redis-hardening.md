# PostgreSQL / Redis production hardening

Real findings from this pass, checked against the actual running
`docker compose` stack and actual config files — not a generic checklist.

## PostgreSQL

| Item | Status | Evidence |
|---|---|---|
| Authentication required | **PASS** | `POSTGRES_PASSWORD:?required` — compose refuses to start without it (confirmed earlier this pass: an unset `POSTGRES_PASSWORD` produces a hard compose error, not a silent default) |
| Least privilege | **PARTIAL** | The API connects as the single `POSTGRES_USER` (typically superuser-equivalent in this image's default setup) — no separate least-privilege app role/schema-level grants. Acceptable for this build's single-service-owns-its-schema model; a production deployment with multiple services sharing one Postgres instance should create per-service roles with `GRANT`s scoped to their own tables. |
| Network isolation | **PASS (dev), N/A (prod)** | Only reachable via the compose-internal `ayureze-net` network plus one published host port (`POSTGRES_PORT`, for local dev tooling) — a production deployment should not publish this port publicly at all; connect only from the API's own network/VPC. |
| TLS | **NOT ENABLED** | `DATABASE_URL` uses `sslmode=disable` throughout this build (local dev, trusted docker network). Production must set `sslmode=require` (or `verify-full` with a real CA) once the API and Postgres are not guaranteed to share a fully trusted network segment. |
| Connection limits | **PASS** | `apps/api/internal/db/pool.go` sets `pgxpool` `MaxConns = 10` — a real, code-enforced per-replica cap (not unbounded), confirmed by reading the actual pool config, not assumed. |
| Backups | **PASS — tested this pass with real data** | Ran a real `pg_dump` against the live dev database (240 tenants / 480 users / 173 sessions accumulated from this audit's own testing), restored it into a freshly created database, and verified **exact row-count match and correct content** (spot-checked specific tenant names survived the round trip byte-for-byte). Zero errors during restore. See "Backup/restore procedure" below for the exact commands used — this is not a hypothetical, it was executed. |
| Migration safety | **NOT RE-VERIFIED THIS PASS** | `golang-migrate` migrations exist (`apps/api/internal/db/migrations`) and were exercised during initial development; this pass did not specifically test a rollback-mid-migration or concurrent-migration-race scenario — recommended follow-up, not claimed as done. |
| Resource limits (CPU/memory caps) | **NOT SET** | No `deploy.resources.limits` in `docker-compose.yml` for any service, Postgres included — a runaway query or unexpected load could consume unbounded host memory/CPU. Production (whether compose, k8s, or ECS) should set explicit limits. |
| Tenant isolation | **PASS — re-verified live this pass** | Every query scoped by the caller's own `tenant_id`; cross-tenant access returns `404` (see this pass's red-team results in `docs/security/README.md`), confirmed via `TestTenantIsolation` (Go integration test, passing) and live `curl` red-team testing. |

### Backup/restore procedure (tested, real commands)

```bash
# Backup (run against the live container)
docker exec ayureze-telehealth-postgres-1 \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > backup.sql

# Restore (into a fresh database — never restore directly over a live one
# without a maintenance window and a second, verified-good backup first)
docker exec ayureze-telehealth-postgres-1 \
  psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE restore_target;"
docker exec -i ayureze-telehealth-postgres-1 \
  psql -U "$POSTGRES_USER" -d restore_target < backup.sql
```

Production should replace this manual flow with scheduled
`pg_dump`/WAL-archiving (or the managed-Postgres provider's own
point-in-time-recovery feature) and store backups off the same host —
none of that infrastructure exists in this build, which is compose-only
local dev.

## Redis

| Item | Status | Evidence |
|---|---|---|
| Authentication required | **PASS** | `--requirepass ${REDIS_PASSWORD:?required}` — same hard-fail-without-secret pattern as Postgres. |
| Persistence | **PASS, confirmed live** | `--appendonly yes` in the compose command; confirmed via `redis-cli CONFIG GET appendonly` against the live container → `yes`. AOF persists refresh tokens/rate-limit counters/presence state across a container restart. |
| Memory limits | **NOT SET — real gap** | `redis-cli CONFIG GET maxmemory` against the live container returned `0` (unbounded). Under sustained load this can consume all available host memory before anything else notices. Production should set `maxmemory` with an eviction policy appropriate to the data (refresh tokens/rate limits are fine to evict under `allkeys-lru` pressure since they're not the system of record — Postgres is — but this should be a deliberate choice, not the current default-unbounded state). |
| Network isolation | **PASS (dev), N/A (prod)** | Same pattern as Postgres — compose-internal network plus one dev-convenience published port; do not publish in production. |
| TLS | **NOT ENABLED** | Plaintext `redis://` throughout, same trusted-network rationale as Postgres — needs `rediss://` + certs once network trust can't be assumed. |
| Tenant isolation | **N/A at the Redis layer** | Redis here holds only refresh-token hashes, rate-limit counters, and presence/session-cache state, all keyed by opaque IDs already tenant-scoped upstream by the Go API — there is no Redis-level tenant boundary to enforce because no tenant-identifying or session-content data is stored unscoped. |

## Summary of real gaps found this pass (not fixed, documented per this
audit's stop condition against unplanned infra changes)

1. **Redis `maxmemory` unset** — cheap, low-risk fix (one compose command
   flag), recommended before any real load-testing so a memory leak/spike
   fails predictably (eviction) rather than taking the host down.
2. **No `deploy.resources.limits` anywhere in `docker-compose.yml`** —
   same category of gap across every service, not just the data layer.
3. **No TLS for Postgres/Redis connections** — acceptable only because
   today's deployment target is a single trusted docker network; must be
   fixed before any deployment where that assumption doesn't hold.
4. **No automated/scheduled backup mechanism** — this pass proved the
   manual `pg_dump`/restore procedure works correctly; it did not add
   scheduling, off-host storage, or point-in-time recovery, none of which
   exist yet.
