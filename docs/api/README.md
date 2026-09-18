# API Specification

## Day 2 (current)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | none | Process liveness |
| GET | `/ready` | none | Readiness (Day 3 adds DB/Redis checks) |
| GET | `/metrics` | none (internal network only in prod) | Prometheus exposition |
| POST | `/v1/dev/session-tokens` | none (dev-only) | `{room, identity, display_name, role}` → `{access_token, identity, room, role, expires_at}`. `role` must be `patient` or `doctor`. Returns `403` if `ENVIRONMENT=production` or if `role` is anything else (in particular, `ai_agent` is never issued here). Ensures the target LiveKit room exists (rooms are never auto-created by a client connecting). |

Full endpoint reference (real authenticated login, session creation/join/
end, consent, tenant, audit) is written here as each lands — see
`PROGRESS.md` at the repo root for what's implemented today.
