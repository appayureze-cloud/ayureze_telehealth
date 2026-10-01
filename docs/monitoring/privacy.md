# Monitoring Privacy Rules

Observability must never become a backdoor into private calls. These rules
are enforced at multiple layers (service code, the OTel Collector, and the
Promtail log pipeline) and apply to every service in this repository.

## Never logged, traced, or dashboarded

- E2EE encryption/decryption keys or key material of any kind
- Raw audio or video, or any decoded/decrypted media
- Passwords, access tokens, refresh tokens, API secrets
- Full medical conversation content or transcripts (captions shown live to
  call participants are a client-side UX feature, not a logged artifact)
- Unnecessary patient identifiers (log participant/session/tenant IDs —
  opaque UUIDs — not names, phone numbers, or medical record numbers)

## Enforcement layers

1. **Service code** is the primary control: structured loggers must be
   configured to never receive the fields above (see
   `docs/monitoring/structured-logging.md`, added Day 3 alongside the Go
   API's logger).
2. **OTel Collector** (`observability/otel/otel-collector-config.yaml`) runs
   an `attributes/redact` processor that deletes `e2ee.key`, `media.payload`,
   `auth.token`, and `auth.password` attributes on every trace/metric/log
   that reaches it, as a defense-in-depth backstop.
3. **Promtail** (`observability/loki/promtail-config.yaml`) runs a regex
   `replace` stage that redacts `password`/`secret`/`token`/`api_key`/
   `e2ee_key`-shaped JSON fields in any log line before it reaches Loki.

None of these backstops excuse a service from not logging the data in the
first place — they exist in case of a bug, not as the intended mechanism.

## What dashboards *should* show

Technical, per-call telemetry that answers "is the call working?" without
exposing what was said:

```
Call #A92F
Patient       Connected ✓
Doctor        Connected ✓
AI Agent      Connected ✓
Duration      18:24
Latency       52 ms
Packet Loss   0.2%
STT           180 ms
Translation   120 ms
TTS           210 ms
API Errors    0
Reconnects    1
E2EE          Active ✓
```

Full dashboard specifications are built out on Day 7 once the metrics they
visualize (call lifecycle, WebRTC quality, API, AI pipeline latency,
security events) exist end-to-end.
