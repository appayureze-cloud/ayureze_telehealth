# Deployment

See `local-development.md` for running the full stack against
`infrastructure/docker/docker-compose.yml`. This document covers the two
service Dockerfiles added in the Day 7 hardening pass and what production
deployment still requires beyond them.

## Dockerfiles

- `apps/api/Dockerfile` — multi-stage: `golang:1.26-bookworm` compiles a
  static (`CGO_ENABLED=0`) binary, then a `gcr.io/distroless/static-debian12:nonroot`
  runtime image (no shell, no package manager, non-root uid 65532) serves
  it. Exposes 8080.
- `apps/ai-agent/Dockerfile` — `python:3.11-slim-bookworm`, runs as a
  dedicated non-root user (uid 10001). A `PIPELINE` build arg (default
  `true`) controls whether the ~2GB Day 6 translation-pipeline dependencies
  (`torch`, `transformers`, `faster-whisper`, ...) are installed via
  `requirements-pipeline.txt`; build with `--build-arg PIPELINE=false` for a
  lifecycle-only image (Mode A, AI absent, no translation). Exposes 8090.
  Model weights (`apps/ai-agent/models/`, gitignored, ~2.5GB — see
  `scripts/download_models.sh`) are **not** baked into the image; mount
  them as a volume at `/app/models` when `AI_AGENT_ENABLE_PIPELINE=true`.

Build:

```bash
docker build -t ayureze-api:latest apps/api
docker build -t ayureze-ai-agent:latest apps/ai-agent
```

### What was actually verified in this build

Both Dockerfiles were **built and run** against the real docker-compose
infrastructure stack (Postgres, Redis, LiveKit) in this build's sandbox, but
the sandbox's outbound network intercepts and re-terminates TLS with a CA
that `docker build`'s isolated build network is never configured to trust,
so a literal `docker build` using `go mod download` / `pip install` against
the public registries fails here with a certificate error — a sandbox
limitation, not a defect in the Dockerfiles (a normal CI runner or dev
machine with ordinary internet access does not hit this).

To verify the Dockerfiles' actual correctness despite that, each was built
using BuildKit's `--build-context` to substitute an already-populated local
dependency cache for the network fetch (the Go module cache for the API;
the local virtualenv's installed packages for the lite/no-pipeline AI
agent build), then the resulting containers were run against the live
compose network:

- **API**: `docker build` succeeded end-to-end (including the real
  `go mod download` step against the mounted module cache, then a real
  `CGO_ENABLED=0 go build`); the container connected to `postgres`,
  `redis`, and `livekit` over the compose network and served
  `GET /health` → `{"status":"ok"}`.
- **AI agent**: verified by substituting the pip-install layer with the
  local virtualenv's already-installed packages (same effective
  dependency set as `requirements.txt`, `PIPELINE=false`), then running
  `python -m uvicorn app.main:app` in the container; it served
  `GET /health` → `{"status":"ok"}`, `GET /ready` → `{"status":"ready"}`,
  and `GET /metrics` with real Prometheus output. The Dockerfile's own
  `pip install` layer (i.e. `RUN pip install -r requirements.txt`, and the
  `PIPELINE=true` branch that additionally installs
  `requirements-pipeline.txt`) was **not** exercised end-to-end in this
  sandbox — it is a standard `pip install` against public PyPI /
  `download.pytorch.org` and is expected to work on any host with normal
  internet access, but that specific step is unverified here. Marked here
  rather than silently assumed, per this project's "never report an
  untested feature as working" rule.

### Docker Compose services

`infrastructure/docker/docker-compose.yml` now defines `api` and `ai-agent`
services (Day 7), built from the two Dockerfiles above, on the same
`ayureze-net` network as Postgres/Redis/LiveKit — closing a gap the compose
file already anticipated (LiveKit's own webhook config has always pointed
at `http://api:8080/internal/webhooks/livekit`). `ai-agent` mounts
`apps/ai-agent/models` read-only and defaults `AI_AGENT_ENABLE_PIPELINE` to
`false` (lifecycle-only) unless overridden.

`docker compose up -d api ai-agent` was exercised in this build's sandbox;
both containers reached a healthy state and served their `/health`
endpoints. Earlier in this session the `api` container transiently failed
to resolve `postgres` over the compose network's embedded DNS
(`dial udp ...: network is unreachable`) — this tracked back to the
sandbox's Docker daemon itself needing a restart (unrelated infrastructure
hiccup in this VM, not a bug in the Dockerfile, compose config, or the
Go binary's resolver): after restarting `dockerd`, the same image, same
compose file, and same network resolved `postgres`/`redis`/`livekit`
correctly on the first try. Noted here in case it resurfaces — if it does,
check `docker ps`/`dockerd` health first before suspecting the app.

## What production deployment still requires beyond these images

- **Kubernetes manifests / Helm charts** — not written. The build spec
  calls out "Kubernetes-ready" for the Docker Compose stack; these two
  Dockerfiles are a necessary building block for that but the actual
  k8s manifests (Deployments, Services, Ingress, HPA, PodDisruptionBudgets,
  NetworkPolicies) are out of scope for this build and not implemented.
- **A real LiveKit SFU deployment** — self-hosted LiveKit in production
  needs `use_external_ip: true` (or a real routable node IP) and TURN via a
  production-grade Coturn deployment; `rtc.node_ip: 127.0.0.1` in this
  repo's `docker-compose.yml` is explicitly local-dev-only.
- **Secret management** — `.env` file injection is a local-dev convenience
  only; production needs a real secret store (Vault, cloud KMS-backed
  secrets manager, k8s Sealed Secrets, etc.) — never baked into an image or
  committed.
- **TLS termination** — this repo runs the Go API and AI agent over plain
  HTTP inside the compose network; production needs a TLS-terminating
  ingress/load balancer in front of both, and LiveKit's own TLS (`wss://`)
  configuration.
- **Model weight distribution** — `apps/ai-agent/models/` (~2.5GB) needs a
  real distribution mechanism for production (a baked image variant, an
  init container, or a persistent volume pre-populated by CI) rather than
  `scripts/download_models.sh`'s manual local-dev flow.
- **Horizontal scaling considerations** — the Go API is already
  stateless-safe for multiple replicas (Redis-backed refresh tokens, rate
  limiting, presence — see Day 3); the AI agent's `AgentRegistry` is
  in-process only and has not been evaluated for multi-replica behavior.
