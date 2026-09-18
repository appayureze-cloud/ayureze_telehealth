# apps/api

Go session/auth/consent platform for AyurEze Telehealth.

**Day 2 scope** (current): a minimal HTTP service that issues short-lived,
room-scoped, role-scoped LiveKit access tokens server-side, and ensures the
target room exists (LiveKit's `auto_create` is disabled — rooms are only
ever created explicitly). This stands in for the full authenticated
login/session-authorization flow built on Day 3.

## Run locally

Requires the Day 1 infrastructure stack running (`../../scripts/dev-up.sh`).

```bash
cd apps/api
set -a && source ../../.env && set +a
go run ./cmd/api
```

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness |
| GET | `/metrics` | Prometheus metrics |
| POST | `/v1/dev/session-tokens` | Mints a `patient`/`doctor`-scoped LiveKit token. **Disabled when `ENVIRONMENT=production`.** Never mints `ai_agent` tokens (Day 4/5 add the consent/authorization checks required for that). |

## Tests

```bash
go test ./...
go vet ./...
gofmt -l .
```
