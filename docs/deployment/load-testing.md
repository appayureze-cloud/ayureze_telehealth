# Load testing — real results, honestly scoped

## Method

`apps/e2e-harness/load-test-driver.mjs` (not part of the permanent test
suite) drives N concurrent doctor+patient session pairs through the
**real** stack: real Go API login/create/join calls, real LiveKit rooms,
real E2EE (`sdk/web`'s actual client, not mocked), audio-only (kept
deliberately lighter than audio+video to isolate the concurrency ceiling
rather than the codec cost). Container CPU/RAM sampled via
`docker stats --no-stream` partway through each run; host memory via
`free -h`. Environment: 4 vCPU / 15GB RAM sandbox, all synthetic clients
originate from a single Chromium process (multiple pages) on
`127.0.0.1` — this last point matters a great deal for interpreting the
results below, see "What this test cannot measure."

## Results (measured, not projected)

| N | Succeeded | Failed | Avg join latency | Max join latency | Failure modes |
|---|---|---|---|---|---|
| 1 | 1/1 | 0 | 602ms | 602ms | none |
| 5 | 5/5 | 0 | 1,088ms | 1,261ms | none |
| 10 | 8/10 | 2 | 2,866ms | 3,398ms | 2× Chromium `NotReadableError: Could not start audio source` |
| 25 | 13/25 | 12 | 8,219ms | 12,482ms | 6× Chromium `NotReadableError`, 6× Go API `too many requests` |

Backend container resource usage across every run stayed low: Postgres
peaked at **14.37% CPU** (during the N=25 run — its highest reading in
any run), API/LiveKit/Redis never exceeded single-digit CPU percent, and
host memory usage stayed under 2.3GB used of 15GB throughout — **no
service was anywhere close to resource exhaustion at any tested scale.**

## What actually failed, and why it's not "the system caps out at ~13-25 real users"

Two distinct failure modes, neither of which is the AyurEze backend
running out of capacity:

1. **`NotReadableError: Could not start audio source`** — Chromium's
   synthetic fake-audio-device implementation has its own concurrency
   ceiling for how many simultaneous fake capture streams one browser
   process can open. This is a **test-harness artifact**: it reflects
   headless Chromium's fake-device limits in this sandbox, not
   AyurEze's WebRTC/media pipeline failing.
2. **`ApiError: too many requests`** — this is the Go API's own
   `internal/redisstate.RateLimiter` (`API_RATE_LIMIT_PER_MINUTE`,
   default 120/min) correctly doing its job — but doing it against a
   methodological artifact of this test: **every synthetic client in
   this run originates from the same IP** (`127.0.0.1`, since all pages
   run inside one Chromium process on one host), and the rate limiter
   is per-IP. 25 real users on 25 real distinct IPs would not trigger
   this the same way; this result demonstrates the rate limiter working
   correctly against a single noisy IP, which is a genuine security
   property re-confirmed under load (matches this pass's red-team
   findings in `docs/security/README.md`), not a discovered capacity
   ceiling for real traffic.

## What this test cannot measure, and would need to

A true concurrent-user capacity number needs: multiple real source IPs
(or the rate limiter's per-IP scoping deliberately disabled/loosened
for the test, then re-enabled), real distributed load generation (not
one Chromium process on one host — e.g. a real WebRTC load-testing tool
or multiple worker machines), and ideally real audio/video codec load
rather than audio-only. None of that infrastructure exists in this
sandbox. **No capacity number (e.g. "the system supports N concurrent
calls") is claimed by this document** — only what was actually measured
above, which is: the backend's own resource usage stayed low at every
scale tested, and the two failure modes found are both artifacts of
this specific test's methodology, not backend resource exhaustion.

## Recommended real load test before production

Run this same driver's core logic (or a proper WebRTC load tool — e.g.
LiveKit's own `load-test` tool, built for exactly this) from multiple
distinct source hosts/IPs against a staging deployment, scaling past
where `docker stats`/`top` on the actual service hosts shows real CPU/
memory pressure, not where an artifact of the test tool itself is hit
first. Track: API latency, LiveKit CPU/participant count, Postgres
connection pool saturation (`apps/api/internal/db/pool.go`'s
`MaxConns = 10` per replica — this is a real, current ceiling worth
testing against directly), and Redis memory (currently unbounded per
`docs/deployment/database-redis-hardening.md` — fix that before a real
load test, so a memory spike fails predictably rather than taking the
host down).
