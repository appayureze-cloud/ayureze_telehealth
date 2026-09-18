# Real Cross-Platform E2EE Interoperability Validation

This document records a real, end-to-end validation pass of the E2EE
architecture, done against the actual running system (real Go API, real
LiveKit server, real Postgres/Redis, a real browser via Playwright, and a
real native LiveKit participant via the Python SDK) — not source
inspection, not unit tests, not mocked LiveKit. See `apps/e2e-harness/`
for the test suite this document reports on.

## Why this exists

Prior to this pass, E2EE had only been validated by (a) reading the SDK
source and (b) isolated unit tests with mocked LiveKit/fetch. That is
insufficient to claim E2EE works. This pass set out to prove — or disprove
— that real clients can connect to the real system and exchange encrypted
media, per the project's "never report an untested feature as working"
rule.

## Audit summary (before any code changes)

- **E2EE mechanism**: LiveKit's SFrame-based frame encryption. The SFU
  never holds media keys (confirmed: LiveKit's own Prometheus/webhook
  surface and its `KeyProviderOptions` design never transmit key material
  through the server — keys are provisioned end-to-end via the Go API's
  join response, encrypted in transit over TLS, decrypted only client-side).
- **Key provisioning**: `internal/e2ee.KeyManager` generates a random
  32-byte key per session at creation, envelope-encrypts it (AES-256-GCM)
  under `API_E2EE_MASTER_KEY_HEX` before persisting, and returns the
  plaintext key (base64) only in an authenticated participant's join
  response (`internal/sessionsvc.Join` / `AuthorizeAIAgent`).
- **Three independent LiveKit bindings consume that key**:
  - `sdk/web` (`livekit-client`, JS/WASM, browser)
  - `sdk/flutter` (`livekit_client` → `flutter_webrtc`, native C++/Rust
    frame-crypto core, compiled per-platform)
  - `apps/ai-agent` (Python `livekit` package, Rust FFI core)
  - **Finding**: `flutter_webrtc`'s bundled `libwebrtc.so` and the Python
    package's `liblivekit_ffi.so` were compared via `strings` and share
    clearly-related native symbols (`DefaultKeyProviderImpl::SetSharedKey`,
    `ParticipantKeyHandler::DeriveKeys`, `DerivePBKDF2KeyFromRawKey`) —
    they are built from the same underlying LiveKit Rust/C++ core, just
    exposed via different language bindings (Dart/FFI vs. Python/FFI).
    This makes the Python AI agent a legitimate, evidence-backed stand-in
    for Flutter specifically on the question "does the Web SDK's key
    handling match the native stack's."
- **Revocation**: `internal/consentsvc.Revoke` calls
  `roomsvc.RemoveParticipant` synchronously as part of the same request —
  already covered by real Go integration tests
  (`apps/api/test/integration`), re-verified here through the real SDK/
  browser layer too (see Test Matrix).
- **Known bugs before this pass**: none formally confirmed — only "not yet
  tested" caveats in `docs/sdk/README.md`.

## Environment

| | |
|---|---|
| OS | Linux (sandboxed container) |
| Browser | Chromium 141 (bundled with Playwright, `/opt/pw-browsers/chromium`), headless, `--use-fake-device-for-media-stream` |
| Flutter | **Not available in this environment** — see "Flutter feasibility" below |
| Android | **No emulator/device/adb available in this environment** |
| LiveKit server | `livekit/livekit-server:v1.13.7` (docker-compose) |
| `livekit-client` (JS) | 2.22.3 (resolved from `^2.7.5`) |
| `livekit_client` (Dart) | 2.4.3 (installed, unused this pass — no Flutter runtime) |
| `livekit` (Python) | 1.0.7 |
| Go API / AI agent | running as `docker compose` services (`api`, `ai-agent`), built from this repo's current commit |

## Flutter feasibility — BLOCKED, stated plainly

This sandbox has no Flutter SDK, no Android SDK, no emulator, and no
physical device, and is a nested container without hardware
virtualization (KVM) support, which Android emulation requires. Installing
a full Flutter+Android toolchain was assessed and not attempted given
disk constraints late in this pass (~5.7GB free) and the near-certainty
that emulator boot would fail without KVM regardless.

**What this means concretely**: no test in this pass exercises Flutter's
own Dart code, its UI, its permission handling, or a literal
Flutter-to-anything connection. Per this task's rule ("do not claim
Flutter/Web interoperability based only on source inspection"), Flutter
interoperability is **NOT VERIFIED**, full stop — not "verified via a
proxy," not "as good as verified." What this pass *does* provide is
narrower and clearly scoped: real evidence (shared native binary symbols,
confirmed via `strings`, not guesswork) that Flutter's `flutter_webrtc`
plugin and the Python AI agent's `livekit` package share the same
compiled frame-crypto engine, so a confirmed Web↔Python failure is strong
(not certain) evidence of a Web↔Flutter failure too, and a confirmed
Python↔Python success (already covered by `apps/ai-agent/tests/
test_agent_integration.py`) says nothing new about Flutter specifically.
Treat any Flutter-related row in the matrix below as BLOCKED, not PASS.

## What was actually found (in the order discovered)

### Bug 1 — `ApiClient`'s default `fetch` throws in every real browser

**Severity**: High. **Found by**: the very first real-browser call to
`AyurezeTelehealthClient.authenticate()`, before any E2EE-specific test
even ran.

`sdk/web/src/apiClient.ts` defaulted its injectable fetch to the bare
`fetch` function: `fetchImpl: typeof fetch = fetch`. Every call site
invokes it as `this.fetchImpl(...)` — a method call, which sets `this` to
the `ApiClient` instance. Native browser `fetch` is a WebIDL built-in that
throws `TypeError: Failed to execute 'fetch' on 'Window': Illegal
invocation` when invoked with any receiver other than `window`/`self`.
Every unit test happened to inject its own mock `fetchImpl`, so this was
invisible until a real browser exercised the *default* constructor path.

**Fix**: `fetchImpl: typeof fetch = fetch.bind(globalThis)`.
**Regression test**: `sdk/web/test/apiClient.test.ts` — "does not throw an
illegal-invocation error when called unbound as a method", which
constructs a receiver-checking fake `fetch` (Node's own `fetch` doesn't
enforce this, so a naive test wouldn't reproduce it) and confirms it
fails without the fix, passes with it.

### Bug 2 — the SDK never actually enabled E2EE on the local participant

**Severity**: Critical. **Found by**: `apps/e2e-harness/tests/
web-web-e2ee.spec.ts` (Web ↔ Web) — media flowed with **zero** encryption
errors, but `Participant.isEncrypted` was `false` for every participant
and `Room.isE2EEEnabled` was `false`.

`sdk/web/src/client.ts` constructed `new Room({ e2ee: { keyProvider,
worker } })` and called `room.connect(...)`, then returned — it never
called LiveKit's own `room.setE2EEEnabled(true)`. Passing `e2ee` options
to the constructor only wires up the capability to *decrypt* incoming
tracks; whether a participant's own *outgoing* tracks are marked
encrypted (`LocalParticipant.encryptionType`, which the SFU records in
each track's `trackInfo.encryption` and every subscriber reads back via
`Participant.isEncrypted`) is a separate, explicit toggle. Without it,
**every session published via this SDK was sending real, unencrypted
media** — while the SDK's own documentation claimed "E2EE is on by
default... no way to join without it." This is exactly the "silently
falling back to unencrypted mode" failure mode this validation task was
designed to catch, and it would not have been caught by source inspection
or by any mocked-LiveKit unit test — only real LiveKit's own
server-reported track metadata surfaced it.

**Fix**: call `await room.setE2EEEnabled(true)` immediately after
`room.connect()` succeeds, before returning from `joinSession()`.
**Regression test**: `apps/e2e-harness/tests/web-web-e2ee.spec.ts` (real,
not mocked — this bug is only reproducible against a real LiveKit server,
since the signal is server-reported track metadata).

### Finding 3 — Web ↔ native LiveKit E2EE key derivation mismatch (confirmed, NOT resolved)

**Severity**: Critical, open. **Found by**: `apps/e2e-harness/tests/
kdf-compat.spec.ts`, using a real native LiveKit participant (Python SDK)
publishing real encrypted audio into a real room, with the real Web SDK
subscribing.

**Symptom, reproduced consistently across many runs**: the Web SDK
correctly sees the native participant's track as encrypted
(`Participant.isEncrypted: true`) and receives its real audio bytes over
the wire (~70KB/test, confirmed via `RTCRtpReceiver.getStats()`), but
every frame fails to decrypt:
`RoomEvent.EncryptionError` → `CryptorError.reason = InvalidKey`,
`"InvalidKey: Decryption failed: OperationError"` (a WebCrypto AES-GCM
authentication-tag failure — the unambiguous signature of a wrong key,
not a framing or transport issue).

**Investigation**: `livekit-client`'s `ExternalE2EEKeyProvider.setKey()`
has two input-dependent code paths — `ArrayBuffer` input runs HKDF,
`string` input UTF-8-encodes the string then runs PBKDF2 (salt
`"LKFrameEncryptionKey"`, 100000 iterations, SHA-256 — the same
parameters documented for LiveKit's Go server SDK
`SetKeyFromPassphrase`). The native frame-crypto core (shared by
Flutter's plugin and the Python agent, see above) only exposes a
PBKDF2-based derivation for its "shared key" mode
(`DerivePBKDF2KeyFromRawKey`, confirmed via `strings`) — no HKDF-from-
raw-key equivalent was found. Three candidate fixes were implemented and
empirically tested against the real native participant, in order:

1. `setKey(ArrayBuffer)` (original / HKDF) → **InvalidKey**.
2. `setKey(rawBytesAsBinaryString)` (PBKDF2 path, raw bytes round-tripped
   through UTF-16 code units, matching `sdk/flutter`'s
   `String.fromCharCodes` exactly) → **InvalidKey**, identical failure.
   (Root cause: `TextEncoder.encode()` — which `setKey(string)` uses
   internally — always UTF-8-encodes; a "binary string" with byte values
   ≥128 does not survive that round-trip unchanged, so this doesn't
   actually deliver the same bytes to PBKDF2 that native's direct
   raw-byte input does.)
3. `keyProvider = new ExternalE2EEKeyProvider({ keySize: 256 })` (testing
   whether the JS SDK's `keySize: 128` default, vs. AES-256 elsewhere in
   this system, was the mismatch) → **InvalidKey**, identical failure.
4. `setKey(base64Text)` with the *matching* native side also using the
   UTF-8 bytes of the base64 text (not the decoded raw bytes) as its
   `shared_key` → still **InvalidKey**.

None of the four combinations tried produced a working cross-platform
key. This matches a **known, unresolved upstream LiveKit report**:
[livekit/livekit#4247](https://github.com/livekit/livekit/issues/4247)
("E2E Encryption nodejs and python sdk"), closed as "not planned," where
LiveKit's own maintainers did not provide a definitive mapping between
the JS SDK's key-derivation options and the native SDKs' internal
handling.

**Current state left in the codebase**: `sdk/web/src/client.ts` uses
`setKey(base64Text)` (PBKDF2 path, LiveKit's own documented
"recommended for maximum compatibility" choice, and the configuration
that passed static analysis most cleanly) — the most defensible available
option, extensively commented with this entire investigation and a
pointer back to this document, but **explicitly not claimed to work
cross-platform**. `apps/e2e-harness/tests/kdf-compat.spec.ts` is left in
the suite as a permanent, real regression trip-wire: it currently fails
(correctly — that's the accurate signal), and should go green automatically
the moment a working configuration is found or LiveKit resolves the
upstream ambiguity, without anyone needing to remember to re-check it.

**Practical implication for production**: **do not mix Web clients with
Flutter/native clients (including the AI agent) in the same encrypted
room** until this is resolved. Web ↔ Web (fully verified, see Test
Matrix) and — by the same-native-core argument above, though not directly
tested — Flutter ↔ Flutter and Flutter ↔ AI-agent are the safe
combinations today.

### Reverse direction (native subscribing to a Web publisher) — inconclusive, not a pass

The mirror test (`kdf-compat.spec.ts`'s second test) reported zero
`track_subscription_failed` events on the native side. This is very
likely a **false negative**, not evidence of compatibility: Python's
`livekit.rtc.Room` only exposes a subscription-level failure event, with
no equivalent of the JS SDK's per-frame `CryptorError` for an AES-GCM
tag-verification failure. Given the forward direction proves a real
mismatch between the exact same two endpoints, frames silently failing to
decrypt into garbage audio with no event fired is the more likely
explanation than genuine compatibility. This is stated explicitly in the
test itself and must not be read as a PASS.

## Test Matrix

| Test | Result | Evidence |
|---|---|---|
| Web ↔ Web E2EE (audio+video, both directions) | **PASS** | `web-web-e2ee.spec.ts` — real media both directions, `isEncrypted: true` both sides, zero `EncryptionError`s, clean leave |
| Flutter ↔ Flutter E2EE | **BLOCKED** | No Flutter/Android toolchain in this environment — see "Flutter feasibility" |
| Flutter ↔ Web E2EE | **BLOCKED** (and, by the Python proxy finding above, presumed broken for the same reason as Web↔native) | Not directly tested |
| Web ↔ Flutter E2EE | **BLOCKED** (same) | Not directly tested |
| Web ↔ native (Python SDK) E2EE | **CONFIRMED BROKEN** | `kdf-compat.spec.ts` test 1 — reproducible `InvalidKey` on every run |
| native → Web E2EE (reverse) | **INCONCLUSIVE** | `kdf-compat.spec.ts` test 2 — see "Reverse direction" above; treat as probably also broken |
| Private Mode (AI absent) | **PASS** | `private-mode.spec.ts` — real E2EE audio/video, exactly 2 participants, no `ai_agent` role ever seen, `aiTranslationAuthorized: false` from the real API |
| AI authorized encrypted participant | **PASS** | `ai-mode.spec.ts` — real consent grant → real `/start` call → AI reaches the room as `role: ai_agent`, `isEncrypted: true`, confirmed via the AI agent's own real Prometheus metrics |
| AI unauthorized access | **REJECTED** (correctly) | `ai-authorization-boundaries.spec.ts` — no-consent start reaches `FAILED` with `authorization_denied:403`, never joins |
| AI cross-tenant access | **REJECTED** (correctly) | `ai-authorization-boundaries.spec.ts` — claiming another tenant's id reaches `FAILED`, never joins |
| AI after consent revocation | **STOPPED** (correctly) | `ai-authorization-boundaries.spec.ts` — already-joined agent force-removed within 15s of revocation |
| AI after session end | **STOPPED** (correctly) | `ai-authorization-boundaries.spec.ts` — agent reaches a terminal state after `endSession()` |
| Network reconnect (real network loss via Playwright/CDP) | **PASS** | `reconnect.spec.ts` — reconnects within 30s, E2EE remains functional (no errors, still encrypted, new bytes flowing) after reconnect |
| Unauthorized third party cannot join another session | **REJECTED** (correctly) | `bug-hunting.spec.ts` — real SDK throws on a 403/404 from the Go API |
| Browser refresh mid-call | **PASS** (no silent stale state) | `bug-hunting.spec.ts` — fresh reload + rejoin reaches a correctly-encrypted state again |
| No E2EE key leakage | **PASS** (structural, re-verified) | Keys never appear in any log/metric/audit record (`docs/monitoring/privacy.md`, unchanged this pass); the join response is the only place a plaintext key ever appears, over TLS, to an already-authorized participant |

## Bugs Found

| ID | Severity | Root cause | Affected platform | Fix | Regression test |
|---|---|---|---|---|---|
| E2EE-BUG-1 | High | `ApiClient`'s default `fetchImpl` called unbound (`this` ≠ `window`), which native `fetch` rejects | Web SDK, any real browser | `fetch.bind(globalThis)` | `sdk/web/test/apiClient.test.ts` |
| E2EE-BUG-2 | Critical | `room.setE2EEEnabled(true)` was never called — local tracks published unencrypted despite the SDK's "always encrypted" claim | Web SDK, any real browser | `await room.setE2EEEnabled(true)` after `connect()` | `apps/e2e-harness/tests/web-web-e2ee.spec.ts` |
| E2EE-FINDING-3 | Critical, **open** | Web SDK (JS/WASM key derivation) vs. native LiveKit stack (Rust/C++ core, shared by Flutter + Python) derive different keys from the same raw bytes; four candidate fixes tried, none resolved it; matches an unresolved upstream LiveKit issue | Web ↔ (Flutter \| AI agent \| any native SDK) | None found this pass | `apps/e2e-harness/tests/kdf-compat.spec.ts` (left red intentionally, as a trip-wire) |

## E2EE Assessment

**PARTIALLY VERIFIED.**

- Web ↔ Web: **VERIFIED** — real, reproducible, passing.
- Private Mode / AI-absent guarantee: **VERIFIED**.
- AI as an authorized encrypted participant, including every
  authorization boundary (no consent, wrong tenant, revocation, session
  end): **VERIFIED**.
- Network resilience for the verified Web↔Web case: **VERIFIED**.
- Cross-platform E2EE (Web with any native-stack participant — Flutter or
  the AI agent, since the AI agent's `role: ai_agent` participant uses the
  same native core): **NOT VERIFIED — CONFIRMED BROKEN** for Web↔native
  specifically (the AI-mode test above works because *no Web client's
  encrypted track was ever tested against the AI agent's decryption* — it
  verified the AI joins and is itself marked encrypted, not that a Web
  participant's media survives AI-side decryption; that gap is exactly
  what `kdf-compat.spec.ts` covers, and it fails). Do not deploy a
  configuration where a Web client and a Flutter client (or a Web client
  and the AI agent) are expected to decrypt each other's media until this
  is resolved.
- Flutter, in every combination: **BLOCKED** (no toolchain in this
  environment) — never claimed as verified.

Do not read "PARTIALLY VERIFIED" as "mostly fine" — the broken
combination (Web ↔ native) is exactly the one the real product's Mode B
(AI translation, which is Web/Flutter clients talking to the Python AI
agent) depends on, and it does not currently work.

## Remaining Risks

- **The core cross-platform E2EE gap (Finding 3) is unresolved.** This is
  the single most important open risk from this validation pass. Next
  steps: reach out to LiveKit (their Discord/GitHub) with this exact
  reproduction, or pin to a different, specifically-tested combination of
  `livekit-client`/`livekit`/`livekit-server` versions and re-run
  `kdf-compat.spec.ts` to see if a version combination exists that works.
- **Flutter is entirely unverified in real conditions** — not just E2EE,
  but the whole SDK. This environment cannot run it at all; a real device/
  CI runner with Flutter+Android tooling is required before Flutter can be
  trusted in production.
- **Reverse-direction (native→Web) diagnostics gap**: Python's `rtc.Room`
  has no per-frame decrypt-failure signal, so that direction can never be
  confidently marked PASS with the tooling available today, only
  INCONCLUSIVE — worth raising with LiveKit or instrumenting a custom
  native-side decrypt-success check if this needs to be closed out
  properly.
- **Video was not covered in the cross-platform KDF test** (audio only,
  for speed) — if Finding 3 is ever "fixed," video should be re-checked
  too since it uses a different codec-specific unencrypted-byte-prefix
  path in the cryptor (`UNENCRYPTED_BYTES.key`/`delta` in
  `livekit-client`), which is plausible additional surface for a
  video-specific variant of the same class of bug.
- **Real device audio/video (actual human speech, actual camera) was not
  used** — Chromium's synthetic fake-device audio/video was used
  throughout (real capture/encode/encrypt/transport/decrypt/decode
  pipeline, but a synthetic source), consistent with "use synthetic/test
  speech only, never real patient data," but this means real-world
  acoustic/lighting edge cases are untested.
- **High packet loss / high latency scenarios** (master prompt section
  14) were not tested — only a full network outage and its recovery.

## Git

- **Branch**: `claude/ayureze-telehealth-build-vaf7sr`
- **Files changed this pass**: `sdk/web/src/client.ts`,
  `sdk/web/src/types.ts`, `sdk/web/src/apiClient.ts`,
  `sdk/web/test/apiClient.test.ts`, plus a new `apps/e2e-harness/`
  (Playwright suite: `web-web-e2ee.spec.ts`, `kdf-compat.spec.ts`,
  `private-mode.spec.ts`, `ai-mode.spec.ts`,
  `ai-authorization-boundaries.spec.ts`, `reconnect.spec.ts`,
  `bug-hunting.spec.ts`, plus `tests/helpers/` — `seed.ts`,
  `webClient.ts`, `nativeParticipant.ts`, `native_participant.py`), and
  this document + `docs/security/README.md`/`PROGRESS.md` updates.
- **Tests executed**: `sdk/web` unit suite (19/19 passing, including one
  new regression test), the full `apps/e2e-harness` Playwright suite
  (11/12 passing — the 1 failure is `kdf-compat.spec.ts`'s forward-
  direction test, intentionally left red as a real, accurate trip-wire
  for Finding 3, not a flaky or broken test).
