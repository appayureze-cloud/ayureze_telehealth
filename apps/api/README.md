# apps/api

Go session/auth/consent platform for AyurEze Telehealth.

## Modules

| Package | Responsibility |
|---|---|
| `internal/authn` | Application JWT issuing/verifying, password hashing |
| `internal/authsvc` | Login / refresh / logout |
| `internal/sessionsvc` | Session create / join / end — the join-authorization boundary |
| `internal/consentsvc` | AI-translation consent grant/revoke (schema+CRUD; Day 4 wires enforcement) |
| `internal/webhooksvc` | Consumes LiveKit's signed room/participant webhooks |
| `internal/store` | All SQL (parameterized, tenant-scoped where applicable) |
| `internal/redisstate` | Refresh tokens, participant presence, distributed rate limiting |
| `internal/roomsvc`, `internal/token` | LiveKit room lifecycle + access-token minting (Day 2) |
| `internal/db` | Postgres pool + embedded migrations |
| `internal/appwire` | Wires the full object graph — shared by `cmd/api` and the integration test suite |

## Run locally

```bash
../../scripts/dev-up.sh        # start Postgres/Redis/LiveKit/coturn/observability
../../scripts/db-seed.sh       # apply migrations + insert a dev tenant/doctor/patient
../../scripts/run-api.sh       # starts the API on :8080 against the stack above
```

`db-seed.sh` prints the seeded doctor/patient emails and a shared dev
password — use them to log in.

## Endpoints

See `docs/api/README.md` at the repo root for the full reference.

## Tests

```bash
go build ./... && go vet ./... && gofmt -l .
go test ./...                                    # unit tests, no external deps
go test -tags integration ./test/integration/...  # requires the stack above + db-seed.sh
```

The integration suite exercises the real HTTP API against live Postgres,
Redis, and LiveKit (via signed webhook requests) — no mocks. It seeds its
own unique tenant/users per test run, so it's safe to run repeatedly and
never collides with `cmd/seed`'s fixed dev accounts.
