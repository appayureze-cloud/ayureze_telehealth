# Disaster recovery procedures

Status per procedure: **TESTED** (executed for real this pass, with
evidence) or **DOCUMENTED ONLY** (a real procedure, but not exercised —
usually because it needs infrastructure this sandbox doesn't have).

## PostgreSQL backup — TESTED

See `docs/deployment/database-redis-hardening.md`'s "Backup/restore
procedure" section for the exact commands. Executed this pass against
the live dev database (240 tenants / 480 users / 173 sessions,
accumulated from this audit's own testing): `pg_dump` → restore into a
freshly created database → verified exact row-count match and spot-
checked specific row content survived byte-for-byte. Zero errors.

## PostgreSQL restore — TESTED

Same procedure as above; restore is the second half of that same test.
Production should add: scheduled automated backups (not done — no
scheduler exists in this build), off-host backup storage (not done —
backups today only exist wherever `pg_dump` is run), and point-in-time
recovery via WAL archiving if RPO requirements need better than
"since the last full backup."

## Redis recovery — DOCUMENTED, partially observed

Redis runs with `--appendonly yes` (confirmed live via `redis-cli
CONFIG GET appendonly` → `yes` this pass), so an AOF file exists on the
`redis-data` volume and a container restart replays it. **Not
separately tested this pass** as a full data-loss-and-recover drill
(e.g. deleting the volume and confirming a fresh container starts clean
vs. restoring the AOF file from a backup copy) — what Redis holds here
(refresh-token hashes, rate-limit counters) is intentionally
non-critical/re-derivable state, not the system of record, so this is
lower priority than the Postgres procedures above, which do protect the
system of record.

## LiveKit restart — TESTED

`docker restart ayureze-telehealth-livekit-1`, then confirmed the server
responds (`curl http://localhost:7880/` → 200) within ~8 seconds, and a
full real Web↔Web E2EE session (`apps/e2e-harness/tests/
web-web-e2ee.spec.ts`) completes successfully immediately after — real
encrypted audio+video, both directions, confirmed post-restart. Any
in-flight calls during the restart itself would drop (not separately
tested — this sandbox has no way to time a restart mid-call
deterministically), consistent with `docs/e2ee/VALIDATION.md`'s
reconnect testing, which covers client-side reconnect after network
loss, a related but distinct scenario from a server-side restart.

## API restart — TESTED

`docker restart ayureze-telehealth-api-1`, confirmed `/health` returns
200 within ~8 seconds, and the same live E2EE session test passed
immediately after. The API is stateless (Postgres/Redis hold all real
state — see `docs/deployment/multi-replica-readiness.md`), so a restart
has no data-loss risk by design, only a brief availability gap.

## AI Agent restart — TESTED

`docker restart ayureze-telehealth-ai-agent-1`, confirmed `docker
inspect` reports `healthy` within ~15 seconds (its own curl-based
Dockerfile `HEALTHCHECK`). Any AI agent active in a session at the
moment of restart would be dropped (in-process `AgentRegistry` state is
lost on restart — see `docs/deployment/multi-replica-readiness.md`);
this is the same fundamental limitation that document describes, not a
new finding, and reconnecting would require the Go API/consent layer to
re-authorize a fresh agent instance (the existing `AuthorizeAIAgent`
flow), not an automatic reconnect.

## Key-management failure — DOCUMENTED ONLY

If `API_E2EE_MASTER_KEY_HEX` is lost (today's local-dev-only static env
var): every already-encrypted session key in Postgres becomes
permanently undecryptable — there is no recovery, by design, since a
recoverable master key would defeat the point of envelope encryption.
This is exactly why `docs/deployment/secrets-management.md` recommends
a real KMS/Vault backend for production: those systems have their own
key-rotation and multi-region-replication guarantees this build's
static env var does not. **Not testable in this sandbox** without a
real KMS to exercise its own DR story against.

## GPU failure — N/A

This build is CPU-only inference throughout (`docs/ai/README.md`'s
"Known limitations" — no GPU exists in any environment this repo has
run in during this project). Nothing to test.

## Complete VPS/host failure — DOCUMENTED ONLY

Not testable inside a single sandboxed container (there is no second
host to fail over to). The real procedure for a single-VPS deployment:
restore Postgres from the most recent off-host backup (not yet
automated — see above) onto a new host, redeploy via `docker compose up`
from this repository's `infrastructure/docker/docker-compose.yml`
against fresh `.env` secrets (pulled from wherever they're actually
managed in production — see `docs/deployment/secrets-management.md`,
never committed), and repoint DNS/load balancer at the new host. RTO
for this path is bounded by backup restore time + redeploy time, neither
of which has been measured against a realistically-sized production
database (this pass's test database, ~900 total rows across
tenants/users/sessions, restored in well under a second — real
production data volumes would need their own timing test before this
number means anything at production scale).
