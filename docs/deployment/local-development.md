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

## 5. Running the API and the patient/doctor test clients (Day 2+)

```bash
# Go token/session API
cd apps/api
set -a && source ../../.env && set +a
go run ./cmd/api

# In another shell: the playground web test client
cd apps/playground
npm install
npm run dev
```

Then open `http://localhost:5173/?role=patient&room=demo` and
`http://localhost:5173/?role=doctor&room=demo` in two tabs. See
`apps/playground/README.md` for the automated Playwright E2E suite that
exercises real WebRTC connectivity (join, disconnect/reconnect, expired/
tampered token rejection, room isolation) headlessly.

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

**WebRTC connects (signaling OK) but publishing a track hangs / repeatedly
reconnects with `NegotiationError: negotiation timed out`** — this is a
LiveKit *server* vs. `livekit-client` *protocol* mismatch, not a networking
issue (ICE will show `connected` in `chrome://webrtc-internals` while SDP
renegotiation silently times out). The client library moves faster than
pinned self-hosted server images; keep `infrastructure/docker/docker-compose.yml`'s
`livekit/livekit-server` tag reasonably current with whatever `livekit-client`
version `apps/playground/package.json` / `sdk/web` resolve to, rather than
downgrading the client.

**Browser (host) can signal to LiveKit but media never flows, or ICE stays
in `checking`** — in a single-machine Docker Compose dev setup, LiveKit by
default advertises its *internal container IP* in ICE candidates, which a
browser running on the host cannot route to. This is why `rtc.node_ip` is
pinned to `127.0.0.1` in both `infrastructure/livekit/livekit.yaml` (reference)
and the `LIVEKIT_CONFIG` in `docker-compose.yml` — traffic then flows over
the published `50000-50100/udp` port range on loopback. This is a
local-dev-only setting; production must use `use_external_ip: true` with a
STUN server, or a real routable node IP.
