# End-to-End Encryption

## What LiveKit (the SFU) can and cannot see

LiveKit never has access to session media-encryption keys, in either mode
below. Media frames are encrypted client-side (SFrame, in the LiveKit
client SDKs — `sdk/web`/`sdk/flutter`, Day 7) before they're published, and
the SFU forwards opaque encrypted packets it cannot decrypt. This is true
whether or not the AI agent is present.

## Two modes (see `docs/architecture/overview.md` for the product framing)

**Mode A — Private.** Only patient and doctor hold the session key. No
other participant (including the AI agent) is ever authorized, and the
platform never silently authorizes one.

**Mode B — AI Translation.** The AI agent, once explicitly authorized
(consent granted — see below), receives the *same* session key patient and
doctor use. This is a deliberate, consented trade-off: the agent must
decrypt plaintext audio to translate it, so once authorized it necessarily
holds key material. E2EE's guarantee here is precise: **the SFU can never
decrypt media, and no participant is ever authorized without an explicit,
revocable, audited decision** — not "the AI can process encrypted audio
without ever seeing plaintext," which would be false and is never claimed.

## Key lifecycle (`apps/api/internal/e2ee`)

1. **Generate** — a random 256-bit key is generated once, at session
   creation (`sessionsvc.Create`).
2. **Encrypt at rest** — the key is immediately envelope-encrypted
   (AES-256-GCM) under `API_E2EE_MASTER_KEY_HEX` before being persisted.
   Postgres never holds plaintext key material. The plaintext value is
   held only in a local variable, discarded after encryption.
3. **Distribute on authorized join** — the key is decrypted and included
   in the join response *only* after `sessionsvc.Join` (patient/doctor) or
   `sessionsvc.AuthorizeAIAgent` (AI agent) passes every authorization
   check. It is never included in `GetSession` or any other read endpoint,
   and never logged — `internal/logging` redacts any field literally named
   `e2ee_key` as a defense-in-depth backstop, but the primary control is
   that access-log middleware never logs response bodies at all.
4. **Invalidate on revocation** — when AI-translation consent is revoked
   (`consentsvc.Revoke`), the AI agent's `participants` row is immediately
   marked `revoked` and, if it's currently connected, force-disconnected
   from the LiveKit room (`roomsvc.RemoveParticipant`) in the same request
   — not on its next poll or on a delay.

## AI agent authorization (`POST /internal/ai-agent/sessions/{id}/authorize`)

This is the single enforcement point for "AI must never join without
explicit, currently-active consent." It:

- authenticates the caller as the AI agent service itself, via a shared
  secret (`AI_AGENT_SERVICE_SECRET`) rather than a human JWT — the agent
  has no tenant/user identity of its own;
- requires the session to exist (tenant-scoped) and not be ended;
- requires an **active** `ai_translation` consent row
  (`store.ConsentStore.ActiveFor`) — "was granted at some point" is not
  enough if it was later revoked;
- only then mints a room-scoped LiveKit token (role `ai_agent`) and
  returns the session's E2EE key.

Every call — allowed or denied, and why — is recorded to `audit_events`
under the `ai_agent.authorize` / `ai_agent.access_revoked` actions. See
`apps/api/test/integration/e2ee_consent_test.go::TestAIAgent_RequiresActiveConsent`
for the full authorize → join → revoke → re-authorize-denied cycle, run
against the real stack.

## Known limitations

- **Key distribution today is server-mediated**, not a peer-to-peer
  ratcheting protocol: the API hands the same session key to every
  authorized participant over the authenticated, TLS-protected join
  response. A production system handling real PHI should evaluate
  stronger guarantees (per-participant key wrapping, forward secrecy via
  key rotation on participant change) — tracked as a known simplification,
  not silently glossed over.
- **`API_E2EE_MASTER_KEY_HEX` is a static env var** in this build, not a
  real KMS. Production deployment must replace it with envelope encryption
  under a managed KMS (AWS KMS, GCP KMS, HashiCorp Vault, etc.) —
  `internal/e2ee.KeyManager` already isolates this behind a narrow
  interface (`Encrypt`/`Decrypt`) specifically so the master-key source
  can be swapped without touching callers.
- **Client-side SFrame integration** (actually enabling E2EE in the
  LiveKit Web/Flutter client SDKs using the key from the join response) is
  implemented in `sdk/web` and `sdk/flutter` (Day 7) and was subjected to
  a real cross-platform validation pass — see **`docs/e2ee/VALIDATION.md`**
  for the full results. Summary: Web↔Web is verified working; Web↔native
  (the AI agent's Python stack) is **verified working**, real encrypted
  media crossing the platform boundary — two concrete AyurEze bugs (a
  key-derivation input mismatch and a key-size mismatch, both in this
  system's own code, not LiveKit) were found by reading LiveKit's actual
  native crypto source and fixed. Flutter's fix was applied by the same
  source-level reasoning but **could not be exercised on a real Android
  emulator/device** in any sandbox pass so far — treat Flutter as fixed
  by inspection, not device-verified, until that test is run. Read
  VALIDATION.md's "Fifth pass" section before deploying, and do not claim
  Flutter E2EE works until a real device/emulator test confirms it.
- **`sdk/flutter` now exposes per-track E2EE diagnostics**
  (`client.e2eeStateChanges` / `client.getE2EETrackStates()`, mirroring
  LiveKit's own `MissingKey`/`DecryptionFailed`/`EncryptionFailed`/`Ok`/
  `KeyRatcheted` states with fail-closed `isSecure` semantics) — see
  `sdk/flutter/README.md`'s "E2EE diagnostics" section. This closes the
  gap where Flutter previously had no way to detect a per-track E2EE
  failure at all, unlike `sdk/web`'s `getEncryptionErrors()`/
  `getEncryptionDiagnostics()`. Code-level verified only (`flutter
  analyze` clean, 22 new unit tests passing against synthetic state) —
  not exercised against a real LiveKit connection or Android device.
