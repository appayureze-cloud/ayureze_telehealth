# AyurEze Telehealth

Production-grade, modular, secure, multilingual telehealth infrastructure:
patient ↔ doctor video/audio consultation with end-to-end encrypted media,
an optional authorized AI translation participant, consent management, and
first-class observability. Built to be embedded into the AyurEze Patient
and Doctor apps (Flutter/Web) via SDKs, not as a standalone product.

**Out of scope:** medical tourism, treatment-centre booking/referral, travel
coordination. This repository is telehealth infrastructure only.

See [`PROGRESS.md`](./PROGRESS.md) for the day-by-day build status —
every feature there is marked `IMPLEMENTED`, `PARTIALLY IMPLEMENTED`,
`BLOCKED`, or `NOT IMPLEMENTED`; nothing is claimed as done until tested.

## Architecture at a glance

```
Patient 🔐 ───────────┐
                       ▼
                   LiveKit (SFU)
                       ▲
Doctor 🔐 ─────────────┘

                       +
                AI Agent 🔐  (only when explicitly authorized)
                       │
              VAD → STT → Language ID
                       ↓
                  Terminology Engine
                       ↓
                   Translation
                       ↓
                 Safety Validator
                       ↓
                      TTS
                       ↓
              Translated, encrypted audio
```

LiveKit (the SFU) never holds E2EE media keys. The AI agent, when
authorized, joins as a real encrypted participant — it is not a
server-side interceptor. See `docs/e2ee/` and `docs/ai/` for the full
model, and `docs/security/threat-model.md` for what this does and does
not protect against.

## Repository layout

```
apps/
├── api/          Go session/auth/consent platform
├── ai-agent/     Python FastAPI AI translation participant
└── playground/   Manual test clients (patient/doctor) for local verification

sdk/
├── flutter/      Flutter SDK for the AyurEze Patient/Doctor apps
└── web/          Web SDK

infrastructure/
├── docker/       docker-compose stack (Postgres, Redis, LiveKit, Coturn, observability)
├── livekit/      LiveKit reference configuration
└── coturn/       TURN server configuration

observability/
├── prometheus/   Metrics scrape config
├── grafana/      Dashboards + datasource provisioning
├── loki/         Log aggregation + promtail scrape config
└── otel/         OpenTelemetry Collector config

docs/             Architecture, security, E2EE, AI, API, SDK, deployment, monitoring, decisions
scripts/          Dev environment scripts
```

## Local development quickstart

Requirements: Docker + Docker Compose v2, Go 1.24+, Python 3.11+, Node 22+.

```bash
cp .env.example .env   # fill in real secrets — never commit .env
./scripts/dev-up.sh
./scripts/health-check.sh
```

This starts PostgreSQL, Redis, LiveKit, Coturn, and the observability stack
(Prometheus, Grafana, Loki, Promtail, OpenTelemetry Collector).

- LiveKit:    http://localhost:7880
- Grafana:    http://localhost:3001  (admin / see `.env` `GRAFANA_ADMIN_PASSWORD`)
- Prometheus: http://localhost:9090
- Loki:       http://localhost:3100

Stop the stack: `./scripts/dev-down.sh`

The Go API, AI agent, and SDKs are added incrementally — see `PROGRESS.md`
for what exists today and how to run/test it.

## Documentation

- [`docs/architecture/`](./docs/architecture/) — system architecture
- [`docs/security/`](./docs/security/) — security model, threat model
- [`docs/e2ee/`](./docs/e2ee/) — end-to-end encryption design
- [`docs/ai/`](./docs/ai/) — AI translation pipeline and provider model
- [`docs/api/`](./docs/api/) — Go API specification
- [`docs/sdk/`](./docs/sdk/) — Flutter/Web SDK usage
- [`docs/deployment/`](./docs/deployment/) — local dev and deployment
- [`docs/monitoring/`](./docs/monitoring/) — observability and privacy rules
- [`docs/decisions/`](./docs/decisions/) — architecture decision records
