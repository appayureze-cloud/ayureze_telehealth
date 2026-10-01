# Multi-replica readiness

## Go API — already safe, re-verified this pass

`apps/api` has no process-local state: authentication (JWT, stateless by
design), refresh tokens (Redis, single-use/rotated — `internal/
redisstate/refresh.go`), rate limiting (Redis-backed fixed window,
shared across replicas — `internal/redisstate.RateLimiter`), and all
session/consent/audit state (Postgres). Any number of API replicas can
sit behind a load balancer today with no code change. This was a design
claim before this pass; it is re-confirmed by this pass's own red-team
testing (`docs/security/README.md`) exercising refresh-token rotation
and rate-limiting through the real, single-instance deployment used here
— behavior that only works at all if the state genuinely lives in Redis/
Postgres rather than in the process, which it does per the code read
above.

## AI Agent — genuinely different, and genuinely harder

`apps/ai-agent/app/registry.py`'s `AgentRegistry` is **in-process, real
state, not incidental**: `self._agents: dict[str, AIAgent]` holds actual
running `AIAgent` objects — each one owns a live LiveKit room connection,
a running `asyncio.Task`, and (once Day 6's pipeline is active) loaded ML
models and per-segment pipeline state. This is not a cache that can be
moved to Redis unchanged — Redis can hold *pointers* to where an agent
runs, never the agent's live WebRTC connection or loaded model weights
themselves. This is a fundamentally different scaling problem than the
Go API's: the AI agent is a **stateful compute worker**, not a stateless
request handler.

### What actually breaks today with >1 replica

- `POST /v1/agent/sessions/{id}/start` (routed to whichever replica the
  LB happens to send it to) calls `registry.start()` on *that* replica
  only. A second `/start` for the same session, routed to a *different*
  replica, would not see the first replica's in-memory entry and could
  start a second, duplicate agent for the same session — two AI
  participants publishing/consuming the same room.
- `POST /v1/agent/sessions/{id}/stop` and any status-read endpoint
  (`registry.get()`) only see agents running on the replica that
  received the request — a stop routed to the wrong replica silently
  no-ops (`registry.stop()` returns `False`, per line 30-35 above), which
  combined with `internal/consentsvc.Revoke`'s force-removal path
  (`docs/security/README.md`'s red-team results confirm this works
  *today*, single-replica) is a real correctness risk once there's more
  than one replica to route to.
- `AI_AGENT_ACTIVE_SESSIONS` (the Prometheus gauge) would only reflect
  one replica's count, not the fleet's true active-session count.

### The right fix — sticky routing + a shared coordination layer, not a Redis-backed registry rewrite

Do not try to make `AgentRegistry` itself distributed (serializing an
`AIAgent` — a live LiveKit connection and loaded models — into Redis
makes no sense). Instead:

1. **Session-affine routing at the load balancer/gateway**: route every
   request for a given `session_id` to the *same* replica for that
   session's lifetime (consistent hashing on `session_id`, or an
   explicit routing table). This is the standard pattern for stateful
   WebSocket/media workers (the same class of problem LiveKit's own SFU
   solves for room-to-node assignment) — the AI agent is architecturally
   closer to a media SFU node than to a stateless API replica, and
   should be scaled/routed the same way.
2. **A shared "which replica owns this session" registry in Redis** —
   this is the one piece that *does* belong in Redis: not the agent
   object itself, just `session_id -> replica_id`, written by
   `registry.start()` (`SET session:{id}:owner {replica_id} NX` — the
   `NX` flag is what prevents two replicas from both believing they
   successfully started the same session, closing the duplicate-agent
   gap above) and read by the Go API before routing `/start`/`/stop`
   calls, or by any replica that receives a request for a session it
   doesn't own (proxy it to the owning replica, or reject with a
   redirect).
3. **Liveness**: an owner key with a TTL, refreshed by the owning
   replica's own heartbeat (already has `AI_AGENT_ACTIVE_SESSIONS`
   wired to a periodic gauge update per `app/main.py:69` — the same loop
   can refresh the ownership TTL), so a crashed replica's sessions
   become re-startable after the TTL expires rather than being
   permanently stuck "owned" by a dead process.

None of this is implemented in this pass — it is a real architecture
decision (which load balancer, whether routing lives at an API gateway
or the Go API itself proxies) that depends on the actual production
target, which this build does not have. Implementing a partial version
without that context risks exactly the kind of unplanned, unverified
change this audit's stop condition prohibits ("do not redesign the
AyurEze architecture"). This document exists so the decision is
made deliberately later, not discovered as an incident when a second
replica is added.

### What's safe today

**Single AI agent replica is fully safe and is what this build assumes
throughout** (`docs/deployment/README.md` already states this). Nothing
in this pass changes that assumption or requires it to change before
any near-term deployment — this document is forward-looking, not a
blocker for a single-replica production deployment.
