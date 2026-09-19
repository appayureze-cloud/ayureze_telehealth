# TURN relay verification

## What was attempted (real, not skipped)

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

## Why this is INCONCLUSIVE, not a pass

A `relay` candidate pair would have been unambiguous proof of real TURN
usage. Getting `host`/`prflx` again after blocking the ports this build's
LiveKit config documents as its direct media path (`infrastructure/
livekit/livekit.yaml`'s `rtc.tcp_port`/`rtc.port_range_start/end`) most
likely means LiveKit's WebRTC stack has an additional ICE-TCP fallback
candidate on the *same port as the WebSocket signaling connection*
(`7880`) that this test did not block — blocking `7880` was avoided
deliberately because it would also kill the signaling channel itself,
making it impossible to distinguish "TURN saved the call" from "the call
failed entirely and there's no result to observe." Confirming or ruling
out that specific hypothesis would need either LiveKit's own
documentation/source on its ICE-TCP fallback behavior, or a network
topology where signaling and media aren't collapsed onto the same
loopback-reachable port set (i.e. a real client on a different network
segment than the SFU, which this single-host sandbox cannot provide).

## Verdict

**NOT VERIFIED — requires an appropriate NAT/network test environment.**
Per this task's own instruction for exactly this situation. What *is*
confirmed: `coturn` is running, healthy, and configured with real
security hardening (`no-loopback-peers`, denied RFC1918/loopback/
link-local relay targets to prevent SSRF-style relay abuse, `stale-nonce`,
TLS 1.0/1.1 disabled — see `infrastructure/coturn/turnserver.conf`), and
the port is reachable. What is **not** confirmed: that a real client
behind a restrictive NAT (UDP fully blocked, only outbound TCP/443
allowed — the actual production scenario TURN exists for) successfully
completes a call through it, because this sandbox has no such network
topology to test against and forcing one via firewall rules on a
single-host loopback deployment could not be made conclusive in the time
available for this pass.

## Recommended real verification (before production)

Run this exact test topology in a real staging environment with two
genuinely separate network paths — e.g. one client on a residential/
mobile network behind symmetric NAT (or a container explicitly denied
direct UDP egress to the SFU's public IP, only allowed to reach the TURN
server's public IP) — and assert the resulting `RTCRtpReceiver.getStats()`
`candidate-pair` shows `candidateType: "relay"` on the succeeded pair,
with real bytes flowing. `apps/e2e-harness/tests/helpers/` already has
the harness/stats-reading pattern needed (see `getRemoteMediaStats` in
`src/harness.ts`); only the network topology is missing, and it cannot
be manufactured inside one Docker host.
