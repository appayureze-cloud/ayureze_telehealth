# TURN relay verification

**Classification: TURN PRODUCTION TOPOLOGY FIXED — EXTERNAL RELAY
VERIFICATION PENDING.** Read "Production topology (this pass)" below and
"External relay verification procedure" before anything else — this
supersedes the prior "TURN RELAY PARTIALLY VERIFIED" conclusion, which is
kept (further down) for its own real, still-useful investigation trail:
the root-cause finding there (coturn's `denied-peer-ip` correctly
rejecting LiveKit's local-dev loopback address) is exactly *why* this
pass's fix targets making that address configurable to a real one,
rather than disabling or weakening the protection that caught it.

## Production topology (this pass)

### Phase 1 — Audit: what deployment target actually exists

Checked for: Terraform/Ansible/cloud-init, a `scripts/` deploy target, any
VPS reference in `docs/`, this environment's own network identity.

**Finding, stated plainly (per this task's own instruction not to
invent one): no production VPS is provisioned or referenced anywhere in
this repository.** `docs/deployment/disaster-recovery.md` discusses a
"single-VPS deployment" only as the *architecture this system is designed
for*, not a deployed instance with a known address — confirmed by
grepping the whole repo for VPS/public-IP/cloud-provider references and
finding only that one architectural mention, plus generic KMS-provider
docs (AWS/GCP) that don't imply an actual account or host. This sandbox's
own network identity (`hostname -I` → `192.0.2.2`, an RFC 5737
documentation-reserved address; outbound HTTP requests exit via
`160.79.106.129`, this session's outbound proxy's address, not an
inbound-reachable address assigned to this container) is not a
production host either — using either as a stand-in "public IP" would be
exactly the kind of fabrication this task explicitly prohibits, so
neither is used anywhere below.

Answers to Phase 1's specific questions, from what the repo/environment
actually shows:

| # | Question | Answer |
|---|---|---|
| 1 | Expected VPS/public IP | **Not determinable — none exists in this repo/environment.** Must come from whoever provisions the real deployment. |
| 2 | LiveKit in Docker? | Yes — `infrastructure/docker/docker-compose.yml`, `livekit/livekit-server:v1.13.7` |
| 3 | Coturn in Docker? | Yes — same file, `coturn/coturn:4.6.2-alpine` |
| 4 | Publicly exposed ports | See "Firewall / port audit" below |
| 5 | Docker network | `ayureze-net`, bridge, `172.18.0.0/16` (confirmed via `docker network inspect`) |
| 6 | IP LiveKit advertises | `127.0.0.1` (local-dev default) — now configurable, see Phase 2 |
| 7 | IP coturn advertises for relay | Container's own Docker-assigned address by default (no `external-ip` was set) — now configurable, see Phase 3 |
| 8 | NAT between VPS and Internet | Unknown — depends on the real VPS provider, not determinable here |
| 9 | VPS behind another NAT/LB | Unknown — same |
| 10 | Cloud firewall/security group | None exists — no cloud provider is configured in this repo |
| 11 | UDP 49160–49200 publicly reachable | Not applicable here (no public deployment); locally, yes, via the docker-compose `ports:` mapping |
| 12 | TCP 3478 publicly reachable | Same caveat — locally yes, via `ports:` |
| 13 | TCP/TLS 5349 configured | **No** — confirmed absent from both the coturn `command:` and `ports:` (see Step 10 below, unchanged this pass) |
| 14 | LiveKit real externally routable node IP | Not available — no VPS to have one |
| 15 | Is `use_external_ip` required for this topology | **Yes, for any real deployment** — was hardcoded `false` before this pass (see Phase 2) |

### Phase 2 — LiveKit external networking: made configurable, not guessed

**Before this pass**: `infrastructure/docker/docker-compose.yml` hardcoded
`use_external_ip: false` — there was no way to enable external-IP
advertising at all without editing the compose file directly (`node_ip`
was already parameterized via `LIVEKIT_NODE_IP`, but flipping
`use_external_ip` required a code change).

**This pass**: `use_external_ip: ${LIVEKIT_USE_EXTERNAL_IP:-false}` — a
new env var, defaulting to `false` (byte-for-byte identical resolved
config to before when unset, confirmed via `docker compose config`).
Production sets `LIVEKIT_USE_EXTERNAL_IP=true` **and**
`LIVEKIT_NODE_IP=<the VPS's real public IP>` together — LiveKit then
advertises that address directly to clients instead of the local-dev
loopback address. No IP is hardcoded or guessed anywhere in this change;
the value is supplied entirely at deploy time via `.env`, which is
already gitignored.

### Phase 3 — Coturn external networking: made configurable, not guessed

**Before this pass**: no way to tell coturn its relay addresses should be
reported under a different (public) IP than its own Docker-assigned one
— no `external-ip` directive anywhere, and coturn's own image default
CMD (`--external-ip=$(detect-external-ip)`, confirmed by inspecting the
`coturn/coturn:4.6.2-alpine` image directly) was silently discarded,
because this project's `command:` fully replaces the image's default CMD
rather than merging with it.

**This pass**: added `${COTURN_EXTERNAL_IP:+--external-ip=${COTURN_EXTERNAL_IP}}`
to the coturn `command:` block — a new env var. When unset (local dev,
the default), this resolves to nothing and the command is identical to
before (verified with `docker compose config`, and by recreating the
containers and re-running the full TURN + Web↔Web test suite — no
change in behavior). When set, it becomes a real
`--external-ip=<value>` argument, telling coturn to report that address
in `XOR-RELAYED-ADDRESS` responses instead of its own container IP.
`denied-peer-ip` (the SSRF protection Step 4/5 below proves is actually
enforced) is completely untouched by this change — it governs which
*destination peer* addresses coturn will relay *to*, a different
mechanism from which address it *reports itself as*.

### Phase 4 — Firewall / port audit

| Purpose | Port | Protocol | Local dev (docker-compose) | Production (must be opened at VPS firewall + cloud security group, in addition to Docker publishing the port) |
|---|---|---|---|---|
| Go API | `8080` | TCP | Published to host | Only if the API itself is directly public (commonly it sits behind a reverse proxy on 443 instead — out of this task's scope) |
| LiveKit signaling/HTTP | `7880` | TCP (WS upgrade) | Published to host | Required |
| LiveKit RTC (TCP fallback) | `7881` | TCP | Published to host | Required |
| LiveKit RTC (UDP, preferred) | `50000`–`50100` | UDP | Published to host | Required — this is the range clients connect to directly when ICE succeeds without TURN |
| Coturn STUN/TURN | `3478` | TCP + UDP | Published to host (both) | Required |
| Coturn relay | `49160`–`49200` | UDP | Published to host | Required — this is the range TURN clients actually exchange relayed media on |
| Coturn TURNS (TLS) | `5349` | TCP (TLS) | **Not configured, not published** | Only if TLS TURN is implemented (see Step 10 — not done this pass, by design) |

Docker's own `ports:` publishing (confirmed present for every row above
except the TLS one, by reading `infrastructure/docker/docker-compose.yml`
directly) is necessary but not sufficient in production — the real VPS's
host firewall (`ufw`/`iptables`/`nftables`) and, if the VPS is behind a
cloud provider's security group/network ACL, that layer too, must both
also allow the same ports. Neither of those layers exists to audit here,
since no real VPS is provisioned — this is the exact "required production
checks" list an operator provisioning one needs to work through, not a
claim that they're already open somewhere.

**Do not open broader ranges than this table.** In particular, the UDP
relay range should stay at the minimum span the deployment's expected
concurrent-call volume needs (each active relayed stream typically uses
one port from this range) — widening it "to be safe" only enlarges the
attack surface without benefit.

## External relay verification procedure (for whoever has real infrastructure)

This sandbox has no second network and no real VPS — genuinely proving
`candidate type: relay` carrying real media between two externally
separated clients cannot happen here, and this document does not claim
otherwise. This is the exact, concrete procedure to run once real
infrastructure exists — built directly on the tooling this investigation
already produced (`apps/e2e-harness/src/turn-harness.ts`,
`apps/e2e-harness/tests/turn-relay.spec.ts`), not a new implementation:

1. **Deploy** the stack to a real VPS with a static public IP. Set
   `LIVEKIT_USE_EXTERNAL_IP=true`, `LIVEKIT_NODE_IP=<that public IP>`,
   `COTURN_EXTERNAL_IP=<that public IP>` in the deployment's `.env` (both
   phases above). Open the ports in the Phase 4 table at the VPS's host
   firewall and cloud security group.
2. **Client A**: any machine on the open Internet or a mobile hotspot —
   genuinely not on the VPS's own network.
3. **Client B**: a second, independent network path — a different ISP/
   location, or (more reliably reproducible) a network explicitly
   configured to block outbound UDP so only the TURN path can succeed.
4. Point `apps/e2e-harness`'s `API_BASE_URL`/`LIVEKIT_URL` constants (or
   equivalent env-driven config, worth adding if running this
   repeatedly) at the real deployment instead of `localhost`.
5. Run `tests/turn-relay.spec.ts`'s **forced-relay** test
   (`iceTransportPolicy: "relay"`, already implemented) from Client A
   against a Client B on the separate network. **Expected, if the Phase
   2/3 fix is correct**: the connection now *succeeds* (unlike in this
   sandbox, where it fails by design — see Step 4/5 below), and
   `getDiagnostics().selectedCandidatePair` reports `localType`/
   `remoteType` as `"relay"` on at least one side of the pair — that is
   the actual proof this task requires, not "allocation succeeded."
6. Run the **control** test (`iceTransportPolicy` default) the same way,
   to distinguish "TURN forced and worked" from "direct connectivity was
   available anyway" — do not report the control result as a TURN result
   (Phase 9's explicit instruction).
7. Repeat Step 8 below's failure/recovery cycle against the real
   deployment: stop coturn, confirm the forced-relay call **fails to
   connect** (not falls back to plaintext or direct), restart coturn,
   confirm a new forced-relay call succeeds again with a real `relay`
   candidate pair.
8. Repeat Phase 7's E2EE-over-TURN checklist (below) with the connection
   actually reaching a stable, relay-carried media state this time —
   record `isE2EEEnabled`, per-track `AyurezeE2EEState`/
   `AyurezeEncryptionDiagnostics`, `audioBytesReceived`, and the selected
   candidate pair together, in one run.

### Phase 7 — E2EE + TURN combined checklist (what to verify once Step 5 above succeeds)

Already wired into `turn-harness.ts`'s existing diagnostics (`isE2EEEnabled`,
per-participant `isEncrypted`, `errors` from `RoomEvent.EncryptionError`,
`audioBytesReceived`, `selectedCandidatePair`) — nothing new to build,
only to run once a topology exists where the connection reaches a stable
relay-carried state long enough to observe all of these together:

1. ICE connection succeeds. 2. Selected candidate is `relay`. 3. Real
audio flows (`audioBytesReceived > 0`). 4. `isE2EEEnabled: true`. 5. Both
participants report `isEncrypted: true`. 6. `errors: []` (no
`RoomEvent.EncryptionError`). 7. No plaintext fallback exists in this
codebase to accidentally exercise (confirmed by code inspection — there
is no fallback path in `sdk/web/src/client.ts` or `livekit-client`'s own
E2EE machinery). 8. SFU cannot decrypt media — architectural, not
newly re-verified this pass (SFrame encrypts before the RTP payload
TURN/LiveKit ever touches; see `docs/e2ee/VALIDATION.md`).

**The commit `4d14357` E2EE fix (key-derivation input + key-size) is
unmodified this pass** — confirmed by `git diff` showing zero changes to
`sdk/web/src/client.ts`, `apps/ai-agent/app/agent.py`, or
`sdk/flutter/lib/src/ayureze_client.dart`, and by the full E2EE Playwright
suite (`web-web-e2ee.spec.ts`, `kdf-compat.spec.ts`, `fail-closed.spec.ts`)
still passing after this pass's networking changes (see Regression below).

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

*(Note: this table reflects the audit as originally performed, and still
reflects local dev's unchanged defaults. `rtc.use_external_ip` and
coturn's advertised relay address are now configurable in production via
`LIVEKIT_USE_EXTERNAL_IP`/`COTURN_EXTERNAL_IP` — see "Production topology
(this pass)" above — without changing anything in this table for local
dev.)*

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

## Classification history (superseded — current classification is at the top of this document)

**Previously: TURN RELAY PARTIALLY VERIFIED.** This was the correct
classification *before* the production-topology fix above existed — kept
verbatim below because the evidence it rests on is still exactly what
justifies this pass's fix, and remains true:

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

**What changed this pass**: `node_ip`/`use_external_ip`
(LiveKit) and the relay-advertised address (coturn) are now genuinely
configurable to a real production value — see "Production topology (this
pass)" at the top — closing the exact gap this classification's own
"genuinely unresolved" bullet named. That configuration was verified
correct at the config-resolution level (`docker compose config`, both
set and unset) and confirmed not to regress local dev (containers
recreated, full TURN + Web↔Web + E2EE Playwright suite re-run, all
green). What it could **not** do, because no real VPS or second network
exists in this sandbox, is prove a `relay` candidate pair actually
carrying media between two genuinely external clients — hence the
current top-of-document classification,
**TURN PRODUCTION TOPOLOGY FIXED — EXTERNAL RELAY VERIFICATION PENDING**,
rather than an upgrade to "VERIFIED."

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
