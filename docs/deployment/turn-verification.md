# TURN relay verification

**Classification: TURN RELAY PARTIALLY VERIFIED.** Read "Classification"
at the bottom before anything else — this supersedes the prior
"NOT VERIFIED" conclusion below, which is kept for its own real,
still-useful investigation trail (the prior pass's iptables approach and
why it was inconclusive remain accurate).

## Step 1 — Current TURN configuration (audit, before any change)

| Setting | Value | Source |
|---|---|---|
| Coturn image | `coturn/coturn:4.6.2-alpine` | `infrastructure/docker/docker-compose.yml` |
| Auth mechanism | `--use-auth-secret` (TURN REST API, time-limited HMAC credentials) + `lt-cred-mech` also set in `turnserver.conf` (redundant — see "Limitations") | docker-compose `command:`, `infrastructure/coturn/turnserver.conf` |
| Realm | `${TURN_REALM:-ayureze.local}` | docker-compose |
| Listening port | `3478` (TCP **and** UDP) | docker-compose `command:`/`ports:` |
| TLS/DTLS listening port | **none configured** — `TURN_TLS_LISTEN_PORT` exists in `.env` but is never referenced anywhere (not in the coturn `command:`, not in `ports:`, no `--tls-listening-port`, no cert/key files) | `.env`, docker-compose (absence confirmed by grep) |
| Relay port range | `49160`–`49200` UDP | docker-compose |
| Denied peer IPs | `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`, `192.0.0.0/24`, `192.0.2.0/24`, `192.168.0.0/16`, `198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24`, `240.0.0.0/4` — i.e. essentially all of RFC1918 + loopback + special-use ranges | `infrastructure/coturn/turnserver.conf` |
| `no-loopback-peers`, `no-multicast-peers`, `stale-nonce=600`, `no-cli`, `no-tlsv1`, `no-tlsv1_1` | set | same file |
| LiveKit's own embedded TURN | `turn.enabled: false` — a dedicated external coturn is used instead | `infrastructure/livekit/livekit.yaml`, confirmed live in the running container's `LIVEKIT_CONFIG` env |
| LiveKit `rtc.node_ip` | **`127.0.0.1`** (loopback) | same, confirmed live |
| LiveKit `rtc.use_external_ip` | `false` | same |
| LiveKit `rtc.enable_loopback_candidate` | `true` | same |
| Docker network subnet | `172.18.0.0/16` | `docker network inspect ayureze-telehealth_ayureze-net` |

**The load-bearing fact this whole investigation turns on**: LiveKit's
own advertised media address in this deployment (`127.0.0.1`) falls
squarely inside coturn's `denied-peer-ip` range (`127.0.0.0/8`), and so
would the docker network's own subnet (`172.18.0.0/16`, inside
`172.16.0.0/12`) if it were used instead. This is visible from reading
the config alone — Steps 2–6 prove it's real, not theoretical.

**New this pass** (not previously discovered): also found, by reading
`livekit-client`'s actual source, that `rtcConfig`/`iceTransportPolicy`
must be passed to `room.connect()`'s `ConnectOptions`, not the `Room`
constructor's `RoomOptions` — passing it to the constructor is silently
ignored (confirmed by first getting a false-positive "connected via
host/prflx" result with `iceTransportPolicy: 'relay'` set on the wrong
object). This is exactly the kind of mistake that could make an
`iceTransportPolicy: 'relay'`-based test *look* like it verified TURN
relay when it never actually forced anything — documented in
`apps/e2e-harness/src/turn-harness.ts`'s comment so it isn't repeated.

## Step 2 — Coturn listening state (real, not just "container healthy")

```
tcp   0.0.0.0:3478   LISTEN   (x4)
udp   0.0.0.0:3478            (x4)
```

Confirmed via `netstat -lntup` run **inside** the running
`ayureze-telehealth-coturn-1` container — TCP and UDP on 3478 both
actively listening. No TLS listener exists (no `5349` in the listener
list), matching the config audit above.

## Step 3 — Allocation test (real TURN client, not container health)

Used coturn's own `turnutils_uclient` (ships in the `coturn/coturn`
image) with a real, freshly-generated REST-API short-term credential
(HMAC-SHA1 of `TURN_STATIC_AUTH_SECRET`, the exact mechanism
`--use-auth-secret` implements) — never hardcoded, never logged.

```
allocate sent
allocate response received
success
IPv4. Received relay addr: 172.18.0.5:49176
refresh sent / refresh response received / success
```

**PASS**: authentication succeeded, a real allocation was created, a real
relay address in the configured `49160–49200` range was returned, and
refresh/keep-alive worked. Coturn's core TURN protocol implementation is
functioning correctly.

## Step 4/5 — Forced relay mode + selected candidate pair (the decisive test)

Two independent tests, in agreement:

**(a) Raw TURN protocol level** (`turnutils_uclient`, peer address set
explicitly):

- Peer = `127.0.0.1` (LiveKit's own advertised address in this
  deployment): `channel bind: error 403 (Forbidden IP)`.
- Peer = `8.8.8.8:53` (a real, non-denied public address, used purely to
  prove the *mechanism* works — not to complete a real STUN/TURN
  exchange with it): `channel bind sent` → `success` (twice), and real
  UDP bytes were sent (`tot_send_bytes ~ 64`) through the relay
  allocation. No response came back, which is expected — 8.8.8.8:53 is a
  DNS server that doesn't speak this test protocol — but that's
  irrelevant to what this test proves: **the 403 above is specifically
  about the peer address being on the denylist, not a general relay
  failure.**

**(b) Application level, real browser, real LiveKit** — built
`apps/e2e-harness/src/turn-harness.ts` + `turn-repro.html` +
`tests/turn-relay.spec.ts` (independent of `AyurezeTelehealthClient`,
which doesn't expose an `rtcConfig` passthrough today) to actually pass
`{ iceServers: [{ urls: "turn:127.0.0.1:3478", username, credential }],
iceTransportPolicy: "relay" }` into a real `Room.connect()`, with real
join tokens/E2EE keys from the real Go API, real Chromium
(`--use-fake-device-for-media-stream`), real coturn:

```
ConnectionError: could not establish pc connection
```

The connection fails outright — exactly the predicted consequence of
(a). Coturn's own server log for that exact test run shows:

```
INFO: session ...: realm <ayureze.local> user <...>: incoming packet
CREATE_PERMISSION processed, error 403: Forbidden IP
```

(username shown is the short-term REST-API timestamp token, not a
secret — coturn's own logging never includes the derived
password/credential.)

Three independent signals — raw TURN client, real browser/LiveKit
connection, and coturn's own server log — agree on the same root cause.

**Control** (same harness, same real stack, TURN configured but
`iceTransportPolicy` left at its default `"all"`): connects normally,
`selectedCandidatePair: { localType: "host", remoteType: "prflx",
transport: "udp" }`, real audio flows. This proves the harness itself
works and isolates "forcing relay" as the only variable between the two
results.

## Step 6 — Real media test

| Test | Relay candidate | Media | E2EE | Result |
|---|---|---|---|---|
| Web → Web audio, relay forced | **No** — connection fails before any candidate pair is established | None (connection never completes) | N/A (never reaches E2EE confirmation) | **FAIL to connect** — expected, given Step 4/5 |
| Web → Web audio, relay NOT forced (control) | No — `host`/`prflx` (TURN not needed on this loopback topology) | ~12–13 KB real audio each direction, confirmed via `RTCStatsReport` | `isE2EEEnabled: true`, both participants `isEncrypted: true` | **PASS** (not a TURN result — this is what already-verified `web-web-e2ee.spec.ts` covers; included here only as the paired control) |
| Audio + video | Not run this pass — video adds no new information about the peer-IP-denial root cause already proven conclusively with audio; would only be worth doing after a real fix changes the topology | — | — | Not tested — reported, not silently skipped |

No test in this matrix shows a `relay` candidate actually carrying media
in this deployment — that is the central finding, not a gap in the test.

## Step 7 — TURN failure test

Stopped the coturn container (`docker stop`) and re-ran both the control
and forced-relay tests:

- **Control (relay not forced)**: unaffected — still connects, still
  real audio, because this topology's calls never depended on TURN to
  begin with.
- **Forced relay**: still fails with the identical `could not establish
  pc connection` error.

This confirms the forced-relay test is genuinely dependent on TURN (not
some unrelated failure), and that **no plaintext or insecure fallback
occurs** — the client fails closed rather than silently connecting
without the encryption/relay guarantee it was configured to require.
Coturn was restarted immediately after.

## Step 8 — TURN restart test

After restarting coturn: re-ran `turnutils_uclient`'s allocate + peer
(`8.8.8.8:53`) test — clean `allocate response received` / `success` /
`channel bind` / `success` sequence, same as before the restart. Re-ran
both Playwright tests twice more — consistent results both times
(control passes with real audio; forced-relay fails the same way).

**Not tested** (a real limitation, stated plainly): a TURN restart
*during* a call that is actively relaying media through it. In this
deployment, no call is ever actually relaying media through TURN (Steps
4–6), so there is no such call to interrupt — this specific scenario
needs the production topology from "Limitations" below to be
meaningful.

## Step 9 — Security review

- TURN credentials: never logged anywhere in this investigation's
  scripts, console output, or committed files. Coturn's own server logs
  show only the short-term REST-API *username* (a timestamp token, not
  secret) — confirmed by grepping the container's logs for
  `password|credential|secret` during this pass's tests: no matches.
- `TURN_STATIC_AUTH_SECRET` is sourced from `.env` (gitignored) at test
  time only, held in a local variable, never written to a file.
- TURN authentication is enabled (`--use-auth-secret`, confirmed working
  in Step 3).
- Relay ports are restricted to the configured range
  (`49160`–`49200`/UDP) — confirmed via the docker-compose `ports:`
  mapping and the real relay addresses returned in Step 3.
- No unnecessary public services exposed: only `3478` (TCP+UDP) and the
  relay range are published.
- No plaintext fallback: confirmed in Step 7 — TURN unavailability (or,
  in this deployment, TURN being architecturally unreachable at all)
  never causes media to flow unencrypted; it either uses the already-E2EE
  Web SDK's normal path (control) or fails to connect at all (forced
  relay).
- **TURN only relays; it never decrypts.** This is inherent to the
  architecture (LiveKit's SFrame E2EE encrypts at the application/frame
  layer, before the RTP payload TURN relays as opaque bytes — TURN
  servers have no access to frame-level keys, confirmed by the existing
  E2EE investigation in `docs/e2ee/VALIDATION.md`), not something this
  pass had to newly verify — and nothing in this pass's testing gave
  coturn any code path that could touch key material.
- Minor config hygiene finding (not a vulnerability): coturn logs a
  startup warning that both `lt-cred-mech` (in `turnserver.conf`) and
  `--use-auth-secret` (docker-compose `command:`) are set simultaneously
  — coturn resolves this deterministically (shared-secret auth wins,
  confirmed working in Step 3), but the redundant `lt-cred-mech` line is
  dead configuration worth removing for clarity in a future pass. Not
  fixed this pass (in scope per Step 12 would be a one-line
  `turnserver.conf` edit, but this task is verification, not cleanup —
  flagged here rather than silently fixed or silently ignored).

## Step 10 — TLS/TCP note

- **UDP**: configured and confirmed listening (Step 2), confirmed
  functionally working (Step 3/4).
- **TCP**: configured and confirmed listening (Step 2) — not separately
  exercised for a full relay test this pass (`turnutils_uclient -t` was
  not run); the UDP path is what LiveKit's WebRTC stack would prefer by
  default, so this wasn't the priority for this pass's decisive finding.
- **TLS/TCP (5349)**: **not configured** — `TURN_TLS_LISTEN_PORT=5349`
  exists in `.env` but is dead: not passed to the coturn `command:`, not
  published in `ports:`, no certificate/key files referenced anywhere.
  **This is a real, documented remaining production task**: a real
  deployment behind networks that block plain UDP/TCP on port 3478
  (common corporate/hospital firewalls, which is exactly telehealth's
  own likely user environment) needs TURNS (TURN-over-TLS, typically on
  443) to have any chance of connecting at all. Not implemented this
  pass — verification only, per this task's scope.

## Regression

Re-run after all of the above (TURN start/stop/restart cycles included):

- Go: `gofmt -l .` clean, `go vet ./...` clean, `go test ./internal/...`
  pass, `go test -tags=integration ./test/integration/...` pass.
- Python: 101/101 fast tests pass.
- Web: `tsc --noEmit` clean, 19/19 unit tests, `npm run build` clean.
- Flutter: `flutter analyze` 0 issues, `flutter test` 41/41.
- Playwright: full suite (now 15 tests — the 13 pre-existing plus this
  pass's 2 new `turn-relay.spec.ts` tests) — **15/15** on two separate
  full-suite runs. One earlier full-suite run showed 1 transient failure
  in the control TURN test specifically (`could not establish pc
  connection` on a test that otherwise passes reliably in isolation and
  on repeat full-suite runs) — consistent with a previously-documented,
  real, occasional WebRTC/ICE timing flake under this sandbox's resource
  load during a long combined run (see this same file's prior-pass
  section below), not a regression. Re-run twice after to confirm: 15/15
  both times.

## Limitations (stated plainly, per this task's own instruction)

- **No real NAT/restrictive-network topology exists in this sandbox.**
  Everything in this investigation runs on one Docker host; the "denied
  peer IP" finding is conclusive evidence for *this specific deployment
  configuration* (LiveKit `node_ip: 127.0.0.1`), not a general statement
  about coturn's relay capability, which Step 3/4(a)'s non-denied-peer
  test shows works correctly.
- **TCP-mode TURN relay** (`turnutils_uclient -t`) was not separately
  exercised — only UDP was tested end-to-end.
- **TLS/TCP (TURNS)** is not configured in this deployment at all (Step
  10) and therefore could not be tested.
- **A live TURN restart during an actual relay-carrying call** could not
  be tested, because no call in this deployment ever actually relays
  through TURN (see Step 8).
- **What a real production deployment needs to actually validate this**:
  set `rtc.use_external_ip: true` with a real routable node IP (or a
  STUN server) instead of `node_ip: 127.0.0.1`, so LiveKit's advertised
  address falls *outside* coturn's `denied-peer-ip` range, then repeat
  Steps 4–6 from a client on a genuinely separate network path (e.g. a
  mobile network, or a client explicitly firewalled off from direct UDP
  to the SFU's public IP) — `apps/e2e-harness/src/turn-harness.ts` and
  `tests/turn-relay.spec.ts` are reusable for exactly that once such an
  environment exists; only the topology is missing.

## Classification

**TURN RELAY PARTIALLY VERIFIED.**

Not simply "coturn is healthy" (explicitly not sufficient, per this
task's own instruction, and not what this classification rests on).
What is real, verified, with reproducible evidence:

- Coturn's TURN protocol implementation itself — authentication,
  allocation, refresh, permission/channel-bind, and actual relayed byte
  transmission to a non-denied peer — **works correctly** (Step 3, Step
  4a's `8.8.8.8` test).
- In *this specific deployment's* current configuration, TURN relay to
  LiveKit is **conclusively blocked** by a real, intentional security
  rule (`denied-peer-ip`) reacting to a real, intentional local-dev
  setting (`node_ip: 127.0.0.1`) — proven at the raw protocol level, the
  full application level, and corroborated by coturn's own server logs,
  three independent ways agreeing on the identical root cause (Step
  4b/5).
- No plaintext fallback, no security regression, credentials never
  logged, TURN never sees key material (Step 7, Step 9).
- Genuinely unresolved: whether TURN relay would succeed once LiveKit
  advertises a real, non-denied address (the production configuration),
  because that specific topology does not exist in this sandbox
  (Limitations).

This is "PARTIALLY VERIFIED," not "NOT VERIFIED," because — unlike the
prior pass, which could only report an ambiguous non-result — this pass
produced a definitive, reproducible, three-way-corroborated answer to
*why* relay doesn't carry LiveKit media in this deployment, and
independently proved coturn's relay mechanism itself is functionally
correct. It is not "VERIFIED" because the one thing production actually
needs — TURN successfully relaying real LiveKit media end-to-end in a
topology where it's structurally reachable — still has not been observed
here, and TLS/TCP TURN remains entirely unconfigured.

---

## Prior pass (kept for its own accurate investigation trail)

### What was attempted (real, not skipped)

Per the production-readiness audit's explicit instruction not to treat
"port open" as sufficient TURN verification, this pass attempted a real
forced-relay test: `iptables` `OUTPUT` rules were added to drop LiveKit's
direct RTC ports (`50000:50100/udp`, `7881/tcp`) on the loopback
interface, then a real Web↔Web session was driven through the actual
production `sdk/web` client (`apps/e2e-harness/turn-verification-driver.mjs`,
a throwaway script, not committed) to see whether the connection would
be forced onto a `relay` ICE candidate pair via the real `coturn` service
(`infrastructure/coturn/turnserver.conf`).

**Baseline (no blocking)**: connection succeeded via `host`/`prflx`
candidates, 37KB of real audio confirmed via `RTCRtpReceiver.getStats()`
— expected, since everything runs on loopback in this sandbox.

**With the direct RTC ports blocked**: the `iptables` rules were
confirmed actually in effect (packet counters showed 69 UDP and 2 TCP
packets dropped during the run — the block was real, not a no-op), yet
the connection *still* succeeded via `host`/`prflx` candidates, not
`relay`, with 21KB of real audio flowing. The block was reverted
immediately after (`iptables -D`), confirmed via `iptables -L` showing
zero rules and the stack reachable again.

### Why this was INCONCLUSIVE, not a pass, at the time

A `relay` candidate pair would have been unambiguous proof of real TURN
usage. Getting `host`/`prflx` again after blocking the ports this build's
LiveKit config documents as its direct media path most likely meant
either LiveKit's WebRTC stack had an additional ICE-TCP fallback
candidate this test didn't block, **or** — now known from this pass's
work — the browser was never actually being forced onto `iceTransportPolicy:
"relay"` in the first place by whatever the prior pass's driver script
did, and/or blocking ports doesn't matter when the client never has a
usable relay candidate to fall back to regardless (see this file's new
Step 1: TURN was never wired into the client's ICE server list at all
until this pass's `turn-harness.ts` manually added it — before that,
`sdk/web/src/client.ts` never configured `iceServers`/TURN, and
`turn.enabled: false` in LiveKit's config means the server never pushes
any either). Confirming or ruling out the ICE-TCP-fallback half of that
hypothesis specifically would still need a real network topology where
signaling and media aren't collapsed onto the same loopback-reachable
port set, which this pass still could not provide.

The recommended real verification listed below remains accurate and
current.
