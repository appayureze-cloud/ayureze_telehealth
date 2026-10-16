# Production secrets management

## Current state (local dev / this build)

Every secret (`API_JWT_SIGNING_SECRET`, `API_E2EE_MASTER_KEY_HEX`,
`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`, `AI_AGENT_SERVICE_SECRET`,
`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `TURN_STATIC_AUTH_SECRET`,
`GRAFANA_ADMIN_PASSWORD`) is injected via a `.env` file read by
`docker compose` at container start (`infrastructure/docker/
docker-compose.yml`'s `${VAR:?required}` substitutions). `.env` is
git-ignored and never baked into an image. This is a correct, safe
**local-dev** pattern; it is not a production secret-management story —
no rotation, no audit trail of who read a secret, no revocation short of
redeploying every service, and the secret sits in host/container
environment variables (visible to `docker inspect`, process environment
dumps, and anyone with shell access to the host) for the process's
entire lifetime.

## The one abstraction that matters: `MasterKeyProvider`

Of all the secrets above, only one — `API_E2EE_MASTER_KEY_HEX` — protects
data whose confidentiality is the product's core promise (patient
session E2EE keys, envelope-encrypted at rest in Postgres). This pass
refactored `apps/api/internal/e2ee` (`e2ee.go`) so that master-key
handling sits entirely behind one small interface:

```go
type MasterKeyProvider interface {
    Encrypt(plaintext []byte) ([]byte, error)
    Decrypt(ciphertext []byte) ([]byte, error)
}
```

`KeyManager` (what `internal/sessionsvc` actually calls —
`GenerateSessionKey`, `Encrypt`, `Decrypt`) holds a `MasterKeyProvider`
and knows nothing about how it works. `EnvMasterKeyProvider`
(AES-256-GCM over the hex env var) remains the local-dev default.

A second, real implementation now exists:
`VaultMasterKeyProvider` (`apps/api/internal/e2ee/vault_provider.go`),
backed by HashiCorp Vault's Transit secrets engine. It is selected by
setting `E2EE_MASTER_KEY_PROVIDER=vault` (see `.env.example`), which
`internal/appwire.buildKeyManager` reads to choose between the two —
nothing in `internal/sessionsvc`, `internal/consentsvc`, or any HTTP
handler needs to know or care which one is active. `VaultMasterKeyProvider`:

- Authenticates via Vault's **Kubernetes auth method** — a direct
  `POST /v1/auth/kubernetes/login` call using the pod's own projected
  ServiceAccount token (`/var/run/secrets/kubernetes.io/serviceaccount/token`),
  not the Vault Agent Injector sidecar. This keeps the API container
  self-contained: no sidecar/webhook coordination beyond what every pod
  already gets from its ServiceAccount.
- Calls `POST /v1/transit/encrypt/<key>` / `/v1/transit/decrypt/<key>`
  per operation — the master key material never leaves Vault, and this
  process only ever holds per-call ciphertext/plaintext and a
  short-lived Vault token (cached in memory, transparently re-acquired
  within 30s of lease expiry or on a 403 from a revoked/expired token).
- Is unit-tested against a fake in-process Vault HTTP server
  (`vault_provider_test.go`): login, encrypt/decrypt round trip, the
  403-then-relogin retry path, and config validation. **Not yet
  verified against a real Vault server** — no Vault instance exists in
  this sandbox; see `infrastructure/k8s/` for the ClusterRole/Role
  binding Vault's Kubernetes auth method needs on the cluster side, and
  run the same three `EnvMasterKeyProvider` test shapes (tamper-fails,
  fresh-nonce-per-call isn't applicable here since Transit handles that
  server-side, mismatched-key-fails-closed) against a real `vault -dev`
  server before trusting this in production.

This is deliberately the *only* abstraction introduced. The other
secrets above (`API_JWT_SIGNING_SECRET`, `LIVEKIT_API_KEY/SECRET`,
`AI_AGENT_SERVICE_SECRET`, database passwords) are read once at startup
as plain strings and used directly (HMAC signing, static comparison) —
they don't need a runtime `Encrypt`/`Decrypt` seam the way envelope
encryption does. For those, the production answer is **where the value
comes from at startup**, not a new code abstraction: inject them from a
real secret store into the container's environment at deploy time (every
option below supports this — AWS Secrets Manager via ECS/EKS secret
injection, Vault Agent's template/env sidecar, k8s Sealed Secrets/
External Secrets Operator) rather than a literal value in `.env` or a
compose file. `internal/config` already reads every secret from an env
var and nowhere else, so this requires zero application code changes —
only deployment tooling.

## Choosing a `MasterKeyProvider` backend

Do not implement all three "just in case" — pick one based on where the
system actually deploys. This repo targets vanilla Kubernetes (see
`infrastructure/k8s/`), so **HashiCorp Vault (Transit engine)** is the
one implemented for real (`VaultMasterKeyProvider`, above). AWS KMS and
GCP KMS remain sketches only — implement one of those instead of Vault
only if the actual deploy target changes to that cloud's managed k8s,
and give it the same real-backend verification Vault still needs.

| Backend | When to pick it | Sketch |
|---|---|---|
| **AWS KMS** | Deploying on AWS (ECS/EKS/EC2) | `Encrypt`/`Decrypt` call `kms:Encrypt`/`kms:Decrypt` (or, for less per-call KMS API cost, use KMS only to wrap a locally-generated data key — "envelope encryption" in AWS's own terminology — and cache the unwrapped data key in memory with a short TTL). IAM role scoped to exactly this one CMK's `Encrypt`/`Decrypt`/`GenerateDataKey` actions, nothing broader. |
| **GCP KMS** | Deploying on GCP (GKE/Cloud Run/GCE) | Same shape via `cloudkms.googleapis.com/v1/.../cryptoKeys/*:encrypt`\|`:decrypt`, workload identity scoped to one key. |
| **HashiCorp Vault (transit engine)** | Self-hosted / multi-cloud / already running Vault for other secrets | `POST /v1/transit/encrypt/<key-name>` / `/v1/transit/decrypt/<key-name>` over mTLS, short-lived Vault token (AppRole or k8s auth), transit key never leaves Vault. |

Whichever is picked, the production `MasterKeyProvider` implementation
must satisfy the same properties `EnvMasterKeyProvider` already does and
its unit tests already assert: `Decrypt` on tampered ciphertext fails
loudly (never returns corrupted plaintext), `Encrypt` output differs
across calls on identical input (fresh nonce/IV per call), and a
mismatched key context fails closed. Write the same three test shapes
against the real backend (or its official local emulator —
`localstack` for AWS KMS, a `vault -dev` server for Vault) before
trusting it in production; a unit test against a hand-rolled fake proves
the interface is wired correctly, not that the real backend behaves as
expected.

## What never changes regardless of backend

- The plaintext session key is still only ever generated in this
  process's memory (`KeyManager.GenerateSessionKey`), still only ever
  leaves the API in a join response over TLS to an already-authorized
  participant, and still never reaches Postgres, Redis, LiveKit, or a
  log line — none of that depends on which `MasterKeyProvider` is
  active.
- `API_E2EE_MASTER_KEY_HEX` (or its replacement credential — an IAM
  role, a Vault token, never a literal key) is still read once at
  startup from environment/config, never from a request.
- No production credential of any kind belongs in this repository. This
  document describes the abstraction and the backend options; it
  contains no keys, tokens, account IDs, or endpoints for any real
  deployment.
