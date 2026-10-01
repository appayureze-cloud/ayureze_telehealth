# apps/playground

Manual and automated test client for verifying patient/doctor LiveKit
connectivity end-to-end. **Not a product surface** — the real SDKs live in
`sdk/flutter` and `sdk/web` (Day 7). This exists purely to validate the
infrastructure and Go API from Day 2 onward using real WebRTC connections.

A single page (`src/main.ts`) serves both roles, selected via URL query
params: `?role=patient|doctor&room=<name>&identity=<id>`.

## Manual use

```bash
npm install
npm run dev
```

Open two browser tabs:
- `http://localhost:5173/?role=patient&room=demo`
- `http://localhost:5173/?role=doctor&room=demo`

Grant camera/mic permissions in both. Each should show the other's video.

## Automated E2E tests (Playwright)

Drives real headless Chromium instances with fake camera/mic devices
(`--use-fake-device-for-media-stream`) against the live Docker Compose
stack + a running `apps/api` instance — no mocking of LiveKit or WebRTC.

```bash
# 1. Infra + API must be running:
../../scripts/dev-up.sh
(cd ../api && set -a && source ../../.env && set +a && go run ./cmd/api &)

# 2. Build the playground and run the suite:
npm install
npm run build
npx playwright test
```

Covers: patient/doctor join + see/hear each other (real audio+video tracks
flowing), disconnect/reconnect, expired-token rejection, tampered-token
rejection, and room isolation (a participant never sees another room's
participants). See `tests/connectivity.spec.ts`.

`tests/helpers/livekit-jwt.ts` crafts LiveKit-shaped JWTs directly (bypassing
the Go API) so the expired/tampered-token tests exercise LiveKit's own
rejection behavior, independent of the API's token TTL policy.
