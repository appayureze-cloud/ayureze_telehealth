# API Specification

All authenticated endpoints require `Authorization: Bearer <access_token>`
where `access_token` comes from `/v1/auth/login` or `/v1/auth/refresh` —
this is the platform's own JWT (`internal/authn`), distinct from the
LiveKit room-access tokens returned by `/v1/sessions/{id}/join`.

## Health / meta

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | none | Process liveness |
| GET | `/ready` | none | Checks Postgres + Redis connectivity; `503` if either is down |
| GET | `/metrics` | none (internal network only in prod) | Prometheus exposition |

## Auth

| Method | Path | Auth | Body | Notes |
|---|---|---|---|---|
| POST | `/v1/auth/login` | none | `{tenant, email, password}` | Returns `{access_token, refresh_token, expires_at, user}`. Unknown tenant, unknown email, and wrong password all return the same `401` (no enumeration) and are all audited |
| POST | `/v1/auth/refresh` | none | `{refresh_token}` | Single-use — each call revokes the old refresh token and issues a new pair |
| POST | `/v1/auth/logout` | none | `{refresh_token}` | Revokes the refresh token |

## Sessions (all require auth)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/v1/sessions` | doctor (or admin) | `{patient_email}` — creates a session scoped to the caller's tenant, authorizes exactly the doctor (caller) and named patient as participants, and creates the LiveKit room |
| GET | `/v1/sessions/{id}` | session's doctor/patient, or admin | Returns session + participant list. `404` (not `403`) for anyone else, including same-tenant users not on this session, and cross-tenant callers |
| POST | `/v1/sessions/{id}/join` | session's doctor/patient, or admin | Mints a room-scoped LiveKit token. `404` if not found/wrong tenant/not a participant, `409` if the session has ended |
| POST | `/v1/sessions/{id}/end` | session's doctor, or admin | Ends the session and deletes the LiveKit room |
| POST | `/v1/sessions/{id}/consent/ai-translation/grant` | session's doctor or patient | Day 3: schema + CRUD only — Day 4 wires this into the AI agent's join authorization |
| POST | `/v1/sessions/{id}/consent/ai-translation/revoke` | session's doctor or patient | ” |

## Internal

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/internal/webhooks/livekit` | LiveKit webhook signature (verified via `LIVEKIT_API_KEY`/`SECRET`) | Room/participant lifecycle events → participant status + Redis presence + `session_events`. Never carries media |

## Dev-only (Day 2, kept for `apps/playground`)

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/dev/session-tokens` | `403` if `ENVIRONMENT=production`. No real authentication — mints `patient`/`doctor` LiveKit tokens directly. Superseded by the authenticated session flow above for anything beyond local connectivity testing |

## Error shape

Every non-2xx response is `{"error": "<kind>", "message": "<human-readable>"}`
where `kind` is one of `not_found`, `forbidden`, `unauthorized`, `conflict`,
`invalid`, `internal_error`, or an endpoint-specific code (e.g.
`rate_limited`, `missing_fields`). See `internal/apperr` for the mapping
from service-layer errors to HTTP status.
