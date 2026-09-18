# Local Development

## Prerequisites

- Docker Engine + Docker Compose v2 (`docker compose version` should print v2.x)
- Go 1.24+ (for `apps/api`, from Day 3)
- Python 3.11+ (for `apps/ai-agent`, from Day 5)
- Node 22+ (for `sdk/web` and `apps/playground`, from Day 2)
- OpenSSL (for generating local dev secrets)

## 1. Configure environment

```bash
cp .env.example .env
```

Fill in every `change-me-*` placeholder with a strong unique value. For a
quick local-only setup you can generate random values:

```bash
sed -i \
  -e "s/change-me-strong-password/$(openssl rand -hex 16)/" \
  -e "s/change-me-redis-password/$(openssl rand -hex 16)/" \
  -e "s/LIVEKIT_API_SECRET=change-me-livekit-secret-min-32-chars/LIVEKIT_API_SECRET=$(openssl rand -hex 24)/" \
  -e "s/change-me-turn-shared-secret/$(openssl rand -hex 16)/" \
  -e "s/change-me-turn-password/$(openssl rand -hex 12)/" \
  -e "s/change-me-api-jwt-secret-min-32-chars/$(openssl rand -hex 24)/" \
  -e "s/change-me-grafana-password/$(openssl rand -hex 12)/" \
  .env
```

`.env` is gitignored. Never commit it.

## 2. Start the stack

```bash
./scripts/dev-up.sh
./scripts/health-check.sh
```

`dev-up.sh` runs `docker compose -f infrastructure/docker/docker-compose.yml
--env-file .env up -d`. `health-check.sh` verifies every core service
(Postgres, Redis, LiveKit, coturn, Prometheus, Loki, Grafana) is actually
healthy, not just "container running".

## 3. Service endpoints (local)

| Service | URL | Notes |
|---|---|---|
| LiveKit | ws://localhost:7880 | API key/secret from `.env` |
| PostgreSQL | localhost:5432 | `ayureze` / see `.env` |
| Redis | localhost:6379 | password from `.env` |
| coturn | localhost:3478 (udp+tcp) | shared secret from `.env` |
| Prometheus | http://localhost:9090 | |
| Grafana | http://localhost:3001 | admin / see `.env` |
| Loki | http://localhost:3100 | queried via Grafana |
| OTel Collector | localhost:4317 (gRPC), :4318 (HTTP) | OTLP ingest |

## 4. Stopping / resetting

```bash
./scripts/dev-down.sh              # stop containers, keep volumes
./scripts/dev-down.sh -v           # stop and wipe all data (Postgres/Redis/Grafana/etc.)
```

## Troubleshooting

**`docker: Cannot connect to the Docker daemon`** — the daemon isn't
running. On most Linux hosts: `sudo systemctl start docker`. In a
minimal/sandboxed container without systemd, start it directly:
`dockerd &` (requires root/CAP_SYS_ADMIN and will not work inside another
unprivileged container without `--privileged` or equivalent capabilities).

**LiveKit restarts in a crash loop citing Redis auth** — `REDIS_PASSWORD` in
`.env` doesn't match what LiveKit was given. LiveKit's Redis password is
injected via `LIVEKIT_CONFIG` in `docker-compose.yml`, not the static
`infrastructure/livekit/livekit.yaml` reference file — if you change
`REDIS_PASSWORD`, run `docker compose ... up -d livekit` to re-inject it.

**Loki fails with `compactor.delete-request-store should be configured`** —
this is set in `observability/loki/loki-config.yaml`
(`compactor.delete_request_store: filesystem`); if you're on a newer Loki
image than the pinned `3.1.1`, check the Loki upgrade notes for further
compactor config changes.
