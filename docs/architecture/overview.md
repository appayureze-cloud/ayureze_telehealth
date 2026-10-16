# Architecture Overview

## Product scope

AyurEze Telehealth is standalone telehealth infrastructure: authenticated
patient↔doctor video/audio consultation, end-to-end encrypted media, consent
management, and an optional authorized AI translation participant. It is
designed to be consumed by the AyurEze Patient/Doctor Flutter apps and web
apps via SDKs, and eventually third parties via API. It explicitly excludes
medical tourism, treatment-centre booking, and travel coordination — those
are separate products.

## Two operating modes

**Mode A — Pure Private Mode.** Only the patient and doctor are participants.
No AI agent is present. The platform never silently activates AI — a room
with only patient+doctor stays that way unless both sides explicitly
authorize AI translation (Day 4/5).

**Mode B — AI Translation Mode.** The AI agent joins as a third, explicitly
authorized, encrypted LiveKit participant — not a server-side media
interceptor. LiveKit (the SFU) never holds E2EE keys in either mode. Because
the AI agent must process plaintext audio to translate it, it necessarily
decrypts the media at its own endpoint once authorized — this is a
deliberate, consented trade-off, not a weakening of E2EE toward the SFU. See
`docs/e2ee/` for the full model once Day 4 lands.

## System components

```
Patient client (Flutter/Web SDK)
Doctor client  (Flutter/Web SDK)
        │  WebRTC (E2EE via LiveKit client SDK, SFrame)
        ▼
   LiveKit SFU  ──── Redis (room/participant state)
        │  webhooks (room/participant/track lifecycle only — no media)
        ▼
   Go API (apps/api): auth, session, participant, consent, tenant,
   authorization, audit, health, metrics
        │
        ▼
   PostgreSQL (tenants, users, sessions, participants, consents,
   session_events, audit_events)

AI Agent (apps/ai-agent, Python/FastAPI): joins LiveKit only when
authorized + consented; runs VAD → STT → language ID → terminology
protection → translation → safety validation → TTS → publish.

Coturn: TURN/STUN relay for clients behind restrictive NATs/firewalls.

Observability: every service emits OpenTelemetry traces/metrics/logs →
otel-collector → Prometheus (metrics) + Loki (logs); Sentry (planned, Day 7)
for application errors. See docs/monitoring/ for what is and is not allowed
into logs/dashboards.
```

## Why this stack

See `docs/decisions/0001-tech-stack.md` for the rationale behind LiveKit,
Go, PostgreSQL, Redis, Coturn, and Python/FastAPI for the AI agent.

## Status

This document reflects the target architecture. Components are built
incrementally per `PROGRESS.md` — only Day 1 infrastructure (LiveKit,
Postgres, Redis, Coturn, observability stack) is implemented and verified
as of this writing.
