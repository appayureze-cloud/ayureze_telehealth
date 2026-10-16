# E2EE / cross-platform validation harness

Real integration tests for the AyurEze E2EE architecture — see
`docs/e2ee/VALIDATION.md` for the full findings this suite produced. This
is **not** a mocked test suite: every test here runs against the real Go
API, real LiveKit server, real Postgres/Redis (via `docker compose`), a
real browser (Playwright/Chromium), and — where relevant — a real native
LiveKit participant (`tests/helpers/native_participant.py`, using the
Python `livekit` SDK against the AI agent's own virtualenv).

## What loads the real SDK

`vite.config.ts` aliases `@ayureze/telehealth-web` directly to
`../../sdk/web/src/index.ts` (TypeScript source, not a built/published
package) — every test exercises the actual SDK code under active
development, with zero build-step drift.

## Running locally

```bash
# 1. Full stack up (api + ai-agent containerized, see infrastructure/docker/docker-compose.yml)
../../scripts/dev-up.sh
../../scripts/db-seed.sh

# 2. Install deps
npm install

# 3. Run everything
npx playwright test

# ...or one file
npx playwright test tests/kdf-compat.spec.ts --reporter=list
```

Each test seeds its own unique tenant/doctor/patient via
`tests/helpers/seed.ts` (shells out to `go run ./cmd/seed`), so tests
never collide with each other or with manually-seeded dev data.

## What each test needs — CI hardware/service requirements

| Test file | Docker (full stack) | Real browser | Python venv (`apps/ai-agent/.venv`) | Notes |
|---|---|---|---|---|
| `web-web-e2ee.spec.ts` | required | required | — | Two browser contexts |
| `private-mode.spec.ts` | required | required | — | |
| `ai-mode.spec.ts` | required | required | — | Drives the real AI agent's HTTP control surface; `AI_AGENT_ENABLE_PIPELINE=false` is sufficient (lifecycle-only, no model weights needed) |
| `ai-authorization-boundaries.spec.ts` | required | required | — | Same as above |
| `reconnect.spec.ts` | required | required | — | Uses Playwright's CDP-backed `context.setOffline()` — real network cut, not a mock |
| `bug-hunting.spec.ts` | required | required | — | |
| `kdf-compat.spec.ts` | required | required | **required** | The only file needing the Python native participant; skip in any CI runner without `apps/ai-agent/.venv` provisioned (`pip install -r requirements.txt`) |

None of these tests need an Android emulator/device or Flutter SDK — no
Flutter test exists in this harness today because this environment has
neither available (see `docs/e2ee/VALIDATION.md`'s "Flutter feasibility"
section). If a CI runner or dev machine has a real Flutter+Android
toolchain, the highest-value next addition is a Flutter integration test
mirroring `kdf-compat.spec.ts`'s structure — same native participant
helper, Flutter side driven via `flutter test integration_test/` or a
real device/emulator — to finally close the "Flutter — BLOCKED" gaps in
the validation matrix.

## Why `kdf-compat.spec.ts`'s first test is expected to fail

It is a real, accurate, intentionally-left-red regression trip-wire for a
confirmed, unresolved cross-platform E2EE key-derivation mismatch between
the Web SDK and the native LiveKit stack (Flutter/Python) — see
`docs/e2ee/VALIDATION.md`'s Finding 3. Do not "fix" this by loosening the
test; fix the underlying key derivation once a working configuration is
found, and this test will pass on its own.
