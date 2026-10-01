# TLS architecture (production)

## Current state (this build)

Every service in `infrastructure/docker/docker-compose.yml` speaks plain
HTTP/WS inside the compose network: the Go API on `:8080`, LiveKit's
signaling on `ws://:7880`, the AI agent's control surface on `:8090`.
This is correct for local dev (all traffic stays inside one trusted
Docker network on one host) and explicitly **not** a production
configuration — `docs/deployment/README.md` already calls this out. This
document is the concrete architecture for what replaces it.

## Production topology

```
Browser/Flutter client
        |  HTTPS (REST) / WSS (LiveKit signaling)
        v
  TLS-terminating edge (cloud LB / nginx / Caddy / Envoy)
        |  plain HTTP/WS, but now on a private network segment only
        v
  Go API (:8080)         LiveKit SFU (:7880 signaling, :7881/UDP media)
        |                         |
        v                         v
  Postgres / Redis         Coturn (TURN, its own TLS on :5349 for
  (private network,         TURNS — separate from the LB above)
   TLS optional per
   docs/deployment/database-redis-hardening.md)
```

Three distinct TLS surfaces, not one:

1. **Client ↔ edge (HTTPS/WSS)** — the only one a browser/mobile app
   directly experiences. Standard reverse-proxy TLS termination (a real
   certificate from a CA — ACME/Let's Encrypt or an org-issued cert), HTTP
   redirected to HTTPS, `wss://` for LiveKit's signaling WebSocket and for
   the Go API if it ever adds a WS endpoint. LiveKit's own `livekit.yaml`
   supports terminating TLS itself if not fronted by a separate LB — this
   build's `infrastructure/livekit/livekit.yaml` does not enable that
   (`development: true`, no `tls` block), matching its local-dev-only
   status stated in that file's own header comment.
2. **Client ↔ TURN (TURNS)** — a *separate* TLS certificate/listener from
   (1), because TURN-over-TLS is a distinct protocol (RFC 5766 TURN
   inside a TLS tunnel on its own port, conventionally `5349`) from HTTPS.
   `infrastructure/coturn/turnserver.conf` already sets `no-tlsv1` /
   `no-tlsv1_1` (modern TLS only) but does not itself configure a
   certificate path — that's a deployment-time addition (cert-manager /
   ACME cert mounted into the coturn container, `cert=`/`pkey=` directives
   pointed at it).
3. **Edge ↔ backend services (internal)** — plain HTTP is acceptable only
   as long as "edge" and "backend" share a fully trusted network segment
   (a VPC, a k8s namespace with NetworkPolicies, or literally the same
   docker-compose network as today). The moment that assumption doesn't
   hold — multi-region, a shared cluster with other tenants' workloads,
   compliance requirements — this needs mTLS or at minimum one-way TLS
   between the edge and the Go API/LiveKit/AI agent, not just between the
   client and the edge.

## What this build does and does not provide

- **Does provide**: every service already listens on a port a
  TLS-terminating proxy can sit in front of without any application code
  change — the Go API and AI agent are plain `net/http`/FastAPI servers
  with no hardcoded scheme assumptions, and `sdk/web`/`sdk/flutter` take
  the LiveKit/API URLs as configuration (`livekitUrl`, `apiBaseUrl`), so
  switching them to `https://`/`wss://` endpoints is a config change, not
  a code change — confirmed by reading `sdk/web/src/client.ts` and
  `sdk/flutter`'s equivalent constructor, both of which just pass the URL
  through to `fetch`/LiveKit's `Room.connect` unmodified.
- **Does not provide**: any actual TLS termination, certificate
  provisioning/rotation (ACME client, cert-manager, or equivalent), or
  the reverse-proxy/LB configuration itself — none of that exists in this
  repo, and none of it was added this pass (out of scope: this build has
  no target cloud/hosting environment specified to configure it against).

## Before production

- Pick the edge (cloud LB with managed certs is the lowest-maintenance
  option; nginx/Caddy/Envoy with cert-manager if self-hosting/k8s).
- Point `LIVEKIT_URL`/`API_BASE_URL` config at the `https://`/`wss://`
  edge addresses — no SDK code changes needed per above.
- Add a TURNS listener + certificate to the coturn deployment separately
  from the HTTP/WS edge.
- Decide whether edge↔backend also needs TLS based on the actual network
  trust boundary of wherever this deploys (see point 3 above) — this is
  an infrastructure decision, not one this document can make without a
  target environment.
