# ADR 0001: Core Technology Stack

**Status:** Accepted

## Decision

- **Real-time media:** LiveKit, self-hosted. Open-source SFU with first-class
  E2EE (SFrame) support, a mature Flutter/Web/server SDK ecosystem, webhook
  event model, and Redis-backed clustering that fits our Kubernetes-ready
  target without vendor lock-in.
- **Backend:** Go. Strong concurrency primitives for a session/signaling
  control plane, static typing, small deployable binaries, good LiveKit
  server-SDK support.
- **Database:** PostgreSQL. Relational integrity for tenants/users/sessions/
  consent/audit data where correctness and auditability matter more than
  horizontal write scale.
- **Cache/transient state:** Redis. Active session/presence state, rate
  limiting, short-lived authorization tokens — shared with LiveKit's own
  Redis-backed state.
- **TURN:** coturn. Battle-tested, standards-compliant, independently
  operable from the SFU.
- **AI agent:** Python + FastAPI. The ML ecosystem (faster-whisper, Silero
  VAD, IndicTrans2, torch) is Python-first; FastAPI gives us an async HTTP
  control surface alongside the LiveKit Python agent SDK.
- **Flutter SDK:** Dart + `livekit_client`, wrapped in a headless AyurEze API
  so the Patient/Doctor apps never depend on LiveKit internals directly.
- **Web SDK:** TypeScript + `livekit-client`.
- **Observability:** OpenTelemetry → Prometheus (metrics) + Loki (logs) +
  Grafana (dashboards); Sentry for application error tracking.
- **Infrastructure:** Docker Compose for local dev and initial deployment,
  written to be Kubernetes-ready (stateless services, externalized config,
  no host-path dependencies beyond named volumes).

## Consequences

- Self-hosting LiveKit/coturn means we own operational burden (scaling,
  TURN bandwidth costs) in exchange for full control over E2EE key handling
  and no per-minute vendor billing.
- Python for the AI agent means a second language/runtime in the stack
  beyond Go — isolated to `apps/ai-agent` and only reachable through the
  authorized-participant boundary, not embedded in the Go control plane.
- All AI providers (STT, translation, TTS, VAD) are accessed through
  interfaces (`docs/ai/`) specifically so this ADR's initial provider
  choices (faster-whisper, IndicTrans2, Silero VAD) can be swapped without
  touching the telehealth core.
