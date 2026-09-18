# Security Model

## Authentication

- `POST /v1/auth/login` exchanges `{tenant, email, password}` for a
  short-lived access JWT (`API_ACCESS_TOKEN_TTL_SECONDS`, default 300s) and
  a single-use refresh token (`API_REFRESH_TOKEN_TTL_SECONDS`, default 7d).
- Passwords are hashed with bcrypt (`internal/authn/password.go`).
- Access tokens are signed HS256 with `API_JWT_SIGNING_SECRET` and carry
  `uid` (user id), `tid` (tenant id), `role`, and a random `jti` — verified
  on every authenticated request by `httpapi.RequireAuth`.
- Refresh tokens are opaque random values; only their SHA-256 hash is
  stored (in Redis, with a TTL), so a Redis dump never contains a usable
  token. Redeeming one revokes it immediately (`internal/redisstate/refresh.go`).
- Login never distinguishes "unknown tenant" / "unknown email" / "wrong
  password" in its response — all three return the same generic `401`, so
  the endpoint cannot be used to enumerate valid tenants or accounts. Every
  attempt, success or failure, is audited.

## Authorization (RBAC + resource-level)

Three roles: `patient`, `doctor`, `admin` (`internal/domain.Role`).

Role checks alone are not sufficient — every session-scoped action also
checks the caller against that *specific* session's `doctor_id`/`patient_id`
in `internal/sessionsvc`:

| Action | Who |
|---|---|
| Create a session | `doctor` or `admin` (the doctor becomes that session's doctor) |
| Join a session | that session's doctor, that session's patient, or `admin` |
| End a session | that session's doctor, or `admin` (not the patient) |
| Grant/revoke AI-translation consent | that session's doctor or patient |

A LiveKit token is only ever minted after these checks pass — token
possession alone is never treated as authorization.

## Tenant isolation

Every tenant-owned table (`users`, `sessions`, ...) carries `tenant_id`,
and every lookup in `internal/store` that serves an authenticated request
is scoped by the caller's `tenant_id` from their JWT claims — never by a
client-supplied tenant. A session in tenant A is `404` (not `403`) to a
caller from tenant B, so the API never confirms the session even exists to
someone outside its tenant. Verified in
`apps/api/test/integration/session_flow_test.go::TestTenantIsolation`.

## Audit trail

`internal/store.AuditStore` records authn/authz decisions — logins
(success/denied with a reason), session create/join/end, and consent
grant/revoke — to the `audit_events` table, with outcome
(`success`/`denied`/`error`), actor, resource, and non-sensitive metadata.
Audit records never contain passwords, tokens, or medical content. See
`docs/monitoring/privacy.md` for what may and may not appear in any log,
metric, or audit record.

## Rate limiting

`internal/redisstate.RateLimiter` is a Redis-backed fixed-window counter
per client IP, shared across API replicas (replacing the Day 2 in-memory,
single-instance limiter). The limiter fails open on Redis errors rather
than taking the API down, which is a deliberate availability/security
trade-off — see `httpapi/ratelimit.go`.

## E2EE key management and AI agent authorization

See `docs/e2ee/README.md` for the full key lifecycle (generate → encrypt
at rest → distribute on authorized join → invalidate on revocation) and
the `POST /internal/ai-agent/sessions/{id}/authorize` endpoint, which is
the single enforcement point ensuring the AI agent never joins without
currently-active, revocable consent.

## AI agent authentication and threat surface

`apps/ai-agent` authenticates to the Go API with `AI_AGENT_SERVICE_SECRET`
(a static shared secret, checked by `httpapi.RequireAIAgentServiceSecret`)
— a service credential, not a human login, since the agent is a trusted
backend process. It never receives a human's password or a privileged
LiveKit token except through `AuthorizeAIAgent`, which itself requires an
active `ai_translation` consent row (see "E2EE key management" above). The
agent's own control-plane endpoints (`/v1/agent/sessions/{id}/start|stop`)
are unauthenticated by design in this build — they are intended to be
called only by the Go API/an internal orchestrator on a network the AI
agent's Dockerfile documents as internal-only; a production deployment
should add a network policy or a second shared secret rather than exposing
port 8090 publicly. This is called out explicitly here (not silently
assumed secure) rather than in a Known Limitations footnote only.

## Threat model (STRIDE-style summary)

| Threat | Mitigation | Where |
|---|---|---|
| **Spoofing** — a client claims to be a different user/tenant | JWT signature (HS256, server-held secret) verified on every request; `uid`/`tid`/`role` come only from verified claims, never client-supplied headers/body fields | `httpapi.RequireAuth`, `internal/authn` |
| **Spoofing** — a non-agent process calls the AI-authorization endpoint | Static service-secret check, separate from human auth | `httpapi.RequireAIAgentServiceSecret` |
| **Tampering** — a client mints its own LiveKit token / picks its own room role | Tokens are minted server-side only, after authorization checks; clients never see `LIVEKIT_API_SECRET` | `internal/token`, `internal/sessionsvc` |
| **Tampering** — a participant or the SFU alters call audio/video in transit | LiveKit end-to-end media encryption (SFrame, shared per-session key); the SFU only ever forwards ciphertext | `internal/e2ee`, `docs/e2ee/README.md` |
| **Tampering** — a webhook sender forges LiveKit events | Webhook signature verified (`auth.SimpleKeyProvider`) before any event is trusted | `internal/webhooksvc`, `httpapi/webhook_handlers.go` |
| **Repudiation** — "I never approved AI translation" / "I was never denied access" | Every authz decision (allow and deny) is written to `audit_events` with actor, action, outcome, reason | `internal/store.AuditStore`, this doc's "Audit trail" section |
| **Information disclosure** — session content leaks via logs/metrics/traces | No call audio/video/text ever enters a log line, metric label, or span attribute; Prometheus labels use only opaque UUIDs/enums; the OTel collector's `attributes/redact` processor strips key/token/media-payload attributes defense-in-depth | `docs/monitoring/privacy.md`, `observability/otel/otel-collector-config.yaml` |
| **Information disclosure** — a stolen refresh token is replayed | Refresh tokens are single-use (redeeming one revokes it) and stored only as a SHA-256 hash, so a Redis dump alone is not enough to forge one | `internal/redisstate/refresh.go` |
| **Information disclosure** — cross-tenant data access | Every query is scoped by the caller's own `tenant_id`; a cross-tenant lookup returns `404`, not `403`, so tenant existence isn't even confirmed | `internal/store`, `TestTenantIsolation` |
| **Denial of service** — request flooding | Redis-backed fixed-window rate limiting per IP, shared across replicas; fails open on Redis errors (an availability trade-off, not a silent security hole — logged) | `internal/redisstate.RateLimiter` |
| **Elevation of privilege** — a patient ends a session or force-joins as a doctor | Every session-scoped action re-checks the caller against that session's own `doctor_id`/`patient_id`, not just their role | `internal/sessionsvc`, table in "Authorization" above |
| **Elevation of privilege** — the AI agent joins/stays without consent, or after consent is revoked | `AuthorizeAIAgent` requires an *active* consent row at authorization time; `Revoke` immediately force-removes an already-joined agent via `roomsvc.RemoveParticipant`, not just a database flag | `internal/consentsvc.Revoke` → `enforceAIAgentRemoval` |

**Known gaps, stated plainly:** no WAF/DDoS-layer protection (expected to
sit in front of this stack, e.g. a cloud LB); no mTLS between internal
services (compose network is trusted-perimeter only, matching its
local-dev scope — see `docs/deployment/README.md`'s production
requirements); no automated dependency/vulnerability scanning wired into
CI (no CI pipeline exists in this build at all — see "What production
deployment still requires" in `docs/deployment/README.md`); the AI agent's
own HTTP control surface has no per-call authentication beyond running on
an assumed-internal network, as stated above.
