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

## What's not yet covered here

The AI agent's own connection lifecycle (Day 5) and the translation
pipeline (Day 6) are not yet built — `docs/ai/` and `PROGRESS.md` track
current status. A full threat model is written once those land.
