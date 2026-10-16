# Observability

Real audit of this build's observability stack, checked against the
actual running `docker compose` services and actual metric/trace code —
not a description of intent.

## Stack

OpenTelemetry Collector (OTLP receiver) → Prometheus (metrics) + Loki via
Promtail (logs) + Grafana (dashboards), all defined in
`infrastructure/docker/docker-compose.yml` and `observability/`. Every
target confirmed **up** and scraping successfully this pass
(`curl http://localhost:9090/api/v1/targets`): `ayureze-api`,
`ayureze-ai-agent`, `livekit`, `otel-collector-self`,
`otel-collector-forwarded`, `prometheus`.

## Metrics coverage (confirmed against actual metric definitions, not assumed)

| Category | Coverage | Where |
|---|---|---|
| API requests/errors/latency | **PASS** | `ayureze_api_http_requests_total` (by route+status class), `ayureze_api_http_request_duration_seconds` — `apps/api/internal/metrics/metrics.go` |
| API auth failures | **PASS** | `ayureze_api_auth_login_total`, `ayureze_api_auth_refresh_total`, both labeled by outcome |
| API authorization failures | **PASS** | `ayureze_api_security_denied_total`, labeled by action/reason — this is what the red-team pass's rejected attacks would surface in production |
| LiveKit active rooms/participants/disconnects/WebRTC quality | **PASS, confirmed live this pass** | LiveKit's own `/metrics` (port 6789, scraped as job `livekit`) — confirmed emitting real data this pass (`livekit_forward_jitter`, `livekit_forward_latency_*` and the rest of LiveKit's native metric set), not just configured-but-silent |
| AI active sessions | **PASS** | `AI_AGENT_ACTIVE_SESSIONS` gauge, updated on a periodic loop — `apps/ai-agent/app/main.py` |
| AI pipeline stage latency (VAD/STT/translation/safety/TTS) | **PASS** | `PIPELINE_STAGE_LATENCY_SECONDS` histogram, labeled by `stage` — covers every stage `_record_stage()` calls, confirmed by reading `app/pipeline/orchestrator.py` |
| AI failures | **PASS** | `PIPELINE_SEGMENTS_BLOCKED_TOTAL` (safety-validator rejections), `AI_AGENT_STATE_TRANSITIONS_TOTAL` |
| GPU utilization/memory | **N/A, not a gap** | This build is CPU-only inference by design (`docs/ai/README.md`'s "Known limitations") — no GPU exists in any environment this has run in, so there is nothing to instrument yet. Should be added alongside real GPU deployment, not before. |
| Security: unauthorized access, token failures, consent violations, E2EE failures | **PASS** | `ayureze_api_security_denied_total` (unauthorized/consent), auth metrics above (token failures), `RoomEvent.EncryptionError`/`CryptorError` surfaced client-side per `docs/e2ee/VALIDATION.md` (E2EE failures — client-side by necessity, since the SFU never sees decrypted content to detect a failure server-side) |
| No raw media/keys/passwords/JWTs in metrics or logs | **PASS, re-verified this pass** | Prometheus labels use only opaque UUIDs/enums (confirmed by reading every `.WithLabelValues`/`.labels()` call site this pass — none takes email, key material, or free text); structured logs never include tokens/keys (confirmed via the same red-team pass's request/response inspection — no secret ever appeared in an `http_request` log line) |

## Distributed tracing — implemented this pass (previously a documented gap)

**Before this pass**: Prometheus metrics and structured logs existed for
every service, but zero application-level trace spans — a single
request's path (HTTP handler → session service → LiveKit RoomService
call, or VAD → STT → translation → safety → TTS) could not be followed
as one trace, only reconstructed after the fact from separately-logged
events sharing a `request_id`/`session_id`.

**This pass adds real OpenTelemetry spans**, exporting via OTLP/gRPC to
the already-deployed `otel-collector` (`OTEL_EXPORTER_OTLP_ENDPOINT`) —
a no-op (spans created, never exported) when that env var is unset, so
no test or dev-without-the-full-stack run gained a new hard dependency:

- **Go API** (`apps/api/internal/tracing`): one root span per HTTP
  request (`TraceSpan` middleware, named by chi route pattern, carrying
  the same `request_id` every structured log line already has — so a
  trace and its log lines can be joined on one ID), with a child span
  around `sessionsvc.Create`'s actual LiveKit `RoomService.EnsureRoom`
  call — concretely, the "API request → session service → LiveKit
  interaction" trace this project's tracing goal describes. Verified:
  `go build`/`go vet`/`gofmt` clean, all 5 `internal/e2ee` unit tests, 14
  integration tests, and the full Playwright `apps/e2e-harness` suite
  (12/13 — the 1 failure is the intentional `kdf-compat.spec.ts` E2EE
  finding, unrelated to tracing) re-run and passing after this change.
- **AI agent** (`apps/ai-agent/app/tracing.py`): one span per pipeline
  stage (`pipeline.stt`, `pipeline.language_id`, `pipeline.terminology`,
  `pipeline.translation`, `pipeline.safety_validation`, `pipeline.tts`),
  nested under a `pipeline.process`/`pipeline.process_auto` parent span,
  each carrying `session_id` as the correlation attribute. Verified: the
  full fast unit suite (22/22) and a real-model round-trip test
  (`test_pipeline_models.py::test_dosage_instruction_round_trip_en_to_ta`,
  real STT/translation/TTS inference, not mocked) both re-run and passing
  with tracing active — the real-model run also confirmed the exporter
  genuinely attempts a live OTLP export (observed a transient connection
  message when run outside the container network, harmless — the
  `BatchSpanProcessor` exports asynchronously and never fails the
  request it's tracing).

**What was deliberately left out of every span, in both languages**: any
medical/session content. Span attributes are limited to the same opaque-
ID/enum/language-code/boolean/duration vocabulary the existing Prometheus
metrics and structured logs already use — never a transcript, a
translated sentence, a patient/doctor email, or key material. See
`docs/monitoring/privacy.md`.

## Multi-replica readiness

See `docs/deployment/multi-replica-readiness.md` — the Go API is already
safe for N replicas (re-confirmed this pass); the AI agent's in-process
`AgentRegistry` is not, and that document lays out why a Redis-backed
rewrite of the registry itself is the wrong fix (it holds live WebRTC
connections and loaded models, not cacheable data) versus the right one
(session-affine routing + a Redis-backed ownership key, not implemented
this pass — a real infrastructure decision deferred to when a target
deployment exists to make it against).
