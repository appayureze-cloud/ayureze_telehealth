# Real Cross-Platform E2EE Interoperability Validation

This document records a real, end-to-end validation pass of the E2EE
architecture, done against the actual running system (real Go API, real
LiveKit server, real Postgres/Redis, a real browser via Playwright, and a
real native LiveKit participant via the Python SDK) — not source
inspection, not unit tests, not mocked LiveKit. See `apps/e2e-harness/`
for the test suite this document reports on.

## Final classification (read this first)

**C — LIVEKIT UPSTREAM LIMITATION, CONFIRMED.** Not RESOLVED (no working
version/configuration combination was found — see the Version Matrix in
the accompanying release report). Not an AYUREZE BUG (ruled out with high
confidence by the "Fourth pass — minimal reproduction, independent of
AyurEze business logic" below, which reproduces the identical failure
with zero AyurEze code anywhere in the chain). Not UNKNOWN (five
investigation passes, nine distinct parameter/version/independence
combinations, and a definitive negative result ruling out KDF algorithm
choice specifically, is enough evidence to classify, not defer).
**Web ↔ native/Flutter E2EE does not work in this system today, and the
evidence points at LiveKit itself, not at AyurEze's integration of it.**
`apps/e2e-harness/tests/kdf-compat.spec.ts` remains the permanent,
intentionally-red regression trip-wire. Do not deploy a configuration
where Web clients and Flutter/native clients (including the AI agent)
are expected to decrypt each other's media until LiveKit resolves
upstream issue #4247 or an equivalent fix ships.

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
| `livekit` (Python) | 1.1.7 (upgraded from 1.0.7 during the third pass — see below) |
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

**Fifth-pass update — Flutter SDK tooling now present, device tier still
absent**: a later execution environment for this repo (different session,
same investigation) *does* ship a real Flutter SDK (`3.27.1`, at
`/opt/flutter-sdk`, confirmed via `flutter --version` — not assumed).
`flutter doctor -v` was re-run for real and shows: Flutter itself ✓, but
Android toolchain ✗ ("Unable to locate Android SDK"), Chrome ✗ (only
Chromium is present, which `flutter run -d chrome` does not accept
without `CHROME_EXECUTABLE`), Linux desktop toolchain ✗ (no `libgtk-3-dev`),
no `/dev/kvm`, no `adb`, no emulator, no physical device. Given this,
`sdk/flutter`'s dependency-resolvable, device-independent checks were
re-run **for real, this session** (not re-stated from a prior claim):
`flutter pub get` (clean), `flutter analyze` (**0 issues**, matching the
existing documented claim), `flutter test` (**18/18 passing**, matching
the existing documented claim) — this independently re-confirms
`docs/sdk/README.md`'s Flutter-SDK claim under real re-execution rather
than trusting it at face value. Installing a full Android SDK + emulator
system image was assessed and not attempted: only ~5.7GB free disk
remained (a system image alone is commonly 1–2GB, plus emulator binaries
and build-tools), and with no `/dev/kvm` any emulator would have to run
in pure software-rendering mode, which is frequently non-functional or
impractically slow in headless containers even when disk allows it — an
attempt would likely have consumed most of the remaining disk for an
emulator that still might not boot, for no verifiable gain. **Device- or
emulator-level Flutter testing (Tests 1–5 in the task's required
topology: any real connect/publish/subscribe/E2EE exercise on an actual
Android/iOS target) remains BLOCKED in every session of this
investigation to date.** Static analysis and Dart unit tests are the
only Flutter-specific claims in this document backed by real execution;
nothing about Flutter's actual runtime E2EE behavior is claimed or
implied by that — see the Python-proxy caveat above, which still stands
unchanged.

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

A follow-up session added two more forensic angles and a fifth candidate:

5. **New evidence**: [livekit/client-sdk-android#952](https://github.com/livekit/client-sdk-android/issues/952)
   ("Support configurable AES-GCM key length for E2EE") confirms the
   native stack's underlying WebRTC fork picks the cipher from the raw
   key material's byte *length* — 16 bytes → `EVP_aead_aes_128_gcm()`,
   32 bytes → `EVP_aead_aes_256_gcm()` — and states plainly that "this
   option would also need equivalent support in other LiveKit client
   SDKs to work cross-platform" and "all E2EE participants must use
   matching key lengths." No maintainer response in that thread
   confirms the exact derivation path, but it corroborates that key
   length is a real, acknowledged cross-SDK variable, not a red herring.
   Since candidate 3 above (`keySize: 256`) had been tested only
   *together with* the UTF-8-unsafe binary-string input (candidate 2),
   never together with the ASCII-safe base64-text input (candidate 4),
   that untested combination — **`new ExternalE2EEKeyProvider({ keySize: 256 })`
   + `setKey(base64Text)`** — was tried next → still **InvalidKey**,
   identical failure signature (same error, same ~70KB received, same
   participant marked `isEncrypted: true` with the actual AES-GCM tag
   check failing).
6. **Direct key-material probe**: Python's `rtc.KeyProvider` exposes
   `export_shared_key(key_index)` and `ratchet_shared_key(key_index)` at
   the FFI layer, which looked like a path to extract the native side's
   actual derived key bytes for a byte-for-byte diff against a
   from-scratch WebCrypto computation of the JS side's derivation. In
   practice, both calls returned empty bytes immediately after
   `set_shared_key()` on a freshly-connected room (not an error — just
   `b""`), for reasons not established (index semantics, an async
   round-trip the Python binding doesn't await, or these calls
   genuinely only return something after a real ratchet event) —
   inconclusive, and not pursued further given the FFI's internal derive
   step almost certainly happens in the C++ layer these calls don't
   reach anyway.

A third pass re-investigated this from scratch, specifically to answer
whether a *different, officially supported version combination* — not a
different client-side parameter — resolves it, per
[livekit/livekit#4247](https://github.com/livekit/livekit/issues/4247)
("E2E Encryption nodejs and python sdk"). Re-checked directly on GitHub:
the issue is still open with **zero maintainer comments**, filed against
`livekit-server-sdk-python`/`livekit-client` describing the same class of
symptom reported here (JS and Python-side clients failing to decrypt each
other's frames), and carries no resolution, no linked fix commit, and no
"works as of vX" note. It is neither confirmed-fixed nor confirmed-
unfixable by LiveKit — it is simply unaddressed upstream.

The one concrete, version-specific lead found this pass: the Python
`livekit` package's changelog between 1.0.7 and 1.1.7 lists a fix for "E2EE
connection failure caused by missing required protobuf fields
`key_ring_size` and `key_derivation_function` in `KeyProviderOptions`" —
1.0.7 predates `KeyProviderOptions.key_derivation_function` existing at
all as an API surface, meaning 1.0.7 could never have explicitly
requested HKDF vs. PBKDF2 in the first place; it always used whatever the
native core's default was. This looked like a strong candidate: it is
the exact API surface issue #4247 discusses, present as a real change in
a real, current release, not a guess.

7. **Upgrade + retest, default/implicit KDF**: `apps/ai-agent/.venv`
   upgraded `livekit` 1.0.7 → 1.1.7 (confirmed the new
   `KeyProviderOptions.key_derivation_function` field and
   `proto_e2ee.KeyDerivationFunction` enum — `PBKDF2 = 0`, `HKDF = 1` —
   now exist), then `kdf-compat.spec.ts`'s forward test re-run unchanged
   (native side still relying on the implicit/default KDF, now backed by
   an explicit-capable SDK) against the Web SDK's committed PBKDF2 path
   (candidate 4/`keySize:256`) → still **InvalidKey**, identical failure
   signature.
8. **Explicit HKDF matched on both sides**: to close out the "maybe the
   *default* differs from what the Web SDK expects" possibility
   completely, the native side was set explicitly to
   `key_derivation_function=proto_e2ee.KeyDerivationFunction.HKDF` (via a
   throwaway script, not committed to the permanent suite), matched
   against a temporarily-reconfigured Web SDK using
   `ExternalE2EEKeyProvider.setKey(ArrayBuffer)` (the JS SDK's HKDF code
   path, confirmed by source reading, SHA-256 with a 128-byte zero `info`
   buffer) → still **InvalidKey**, identical failure signature (same
   `~70KB` of real audio bytes received, same `isEncrypted: true` remote /
   `isEncrypted: false` local, same AES-GCM tag failure). This
   experimental change was fully reverted afterward — `sdk/web/src/
   client.ts` was restored via `git checkout --` to its exact
   previously-committed content (PBKDF2, `keySize: 256`,
   `setKey(base64Text)`) once the test concluded; nothing from this
   experiment is left in the shipped SDK.

Candidates 7 and 8 together are a **definitive result, not just another
failed attempt**: they rule out "KDF algorithm choice" (PBKDF2 vs. HKDF)
as the root cause entirely, because both algorithms were tested
*explicitly matched* on both sides — not just "same default" — and both
still fail identically. This directly answers the question issue #4247
raises without resolving: the algorithm selection itself is not the
mismatch. Something else in the derivation or frame-decryption path
differs between the Web SDK and the native core — candidates not yet
tested, and not testable without native C++ source access, include the
literal byte content passed to the HKDF `info` parameter, the exact
PBKDF2 iteration count and byte encoding used natively (only confirmed
via `strings` that the function exists, not its exact call-site
parameters), `ratchetSalt` encoding, or per-participant/key-index ratchet
state handling in SFrame's `ParticipantKeyHandler`.

Combined, **none of the eight parameter combinations tried across all
three passes** (five from the first two passes, three more this pass —
the 1.1.7 upgrade re-tested against both implicit-default and
explicit-HKDF-matched native configurations, listed as 7 and 8 above; the
FFI key-export probe from pass two is not a "combination" and isn't
recounted here) produced a working cross-platform key. This matches the
**known, unresolved upstream LiveKit report**: issue #4247 above, which
remains open, uncommented-on by maintainers, and unresolved as of this
pass — not fixed in a newer release, not confirmed unsupported, just
silent. Resolving this with certainty requires either LiveKit's own
clarification or read access to the native frame-crypto core's actual
C++ source (not available via the compiled binaries + public docs used
in this investigation) — genuinely beyond what black-box empirical
testing can determine.

### Fourth pass — minimal reproduction, independent of AyurEze business logic (definitive)

A fourth pass built a reproduction with **zero AyurEze code involved
anywhere in the chain**, to answer the one question the first three
passes could not fully rule out: is this mismatch specific to something
in AyurEze's own key transport (the Go API's envelope-encrypted key
storage/retrieval, `sdk/web`'s base64/string handling, `internal/token`'s
grant construction), or does it reproduce with LiveKit's own client
libraries talking directly to each other?

**What was bypassed entirely**: `internal/sessionsvc` (no session
created), `internal/e2ee.KeyManager` (no envelope encryption/decryption,
no Postgres row), `internal/token.Minter` (no Go-issued JWT),
`sdk/web/src/client.ts` / `AyurezeTelehealthClient` (no AyurEze Web SDK
code loaded at all), and `apps/ai-agent`'s own application code. Every
piece was rebuilt from scratch, standalone:

- **Room**: created by calling LiveKit's own `RoomService.CreateRoom`
  directly (`livekit-api` Python package, `apps/e2e-harness/tests/
  helpers/minimal_repro_setup.py`) — the same public API LiveKit's own
  CLI/SDKs use, not AyurEze's session service.
- **Tokens**: hand-built JWTs via raw PyJWT against LiveKit's published
  token spec (`iss`/`sub`/`video.roomJoin` claims, HS256-signed with
  `LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`), not `internal/token.Minter`.
- **Key**: 32 random bytes from Python's `secrets.token_bytes(32)`,
  generated inline in the test script, never touching
  `internal/e2ee.KeyManager`, AES-256-GCM envelope encryption, or
  Postgres.
- **Native participant**: `native_participant.py`'s already-existing
  `run_participant()` function called directly with the token/key above
  (`minimal_native_runner.py`), bypassing its own `main_async()`/Go-API-
  calling wrapper entirely — this is pure `livekit.rtc.Room.connect()` +
  `KeyProviderOptions(shared_key=...)`, LiveKit's own Python SDK, nothing
  else.
- **Web participant**: a new, minimal page (`minimal-repro.html` +
  `src/minimal-harness.ts`) importing `Room`/`ExternalE2EEKeyProvider`
  directly from `livekit-client` — no `@ayureze/telehealth-web` import at
  all, driven by a standalone Playwright script
  (`minimal-repro-driver.mjs`, not part of the committed test suite).

**Result**: identical failure. The native participant published real
audio (confirmed via LiveKit's own `ready`/`done` events); the Web page
received real ciphertext (**61,224 bytes** of real audio over the wire,
confirmed via `RTCRtpReceiver.getStats()`), saw the remote participant as
`isEncrypted: true`, and every frame failed decryption with the exact
same signature as every other test in this investigation:
`RoomEvent.EncryptionError` → `"InvalidKey: Decryption failed:
OperationError"`, six times over an 8-second observation window.

**This is the most conclusive evidence in the investigation.** With
every single piece of AyurEze-specific code removed from the chain —
key generation, key storage, key transport, token minting, room
creation, and both SDKs' wrapper code — the Web↔native mismatch persists
identically. This rules out an AyurEze integration bug (classification
B) with high confidence: there is no AyurEze code left in this
reproduction that could be the root cause. The mismatch is inherent to
how `livekit-client` (Web) and the native `livekit` SDK's shared
Rust/C++ core derive/apply keys from identical raw input, independent of
any application built on top of them.

None of the artifacts from this pass (`minimal-repro.html`,
`src/minimal-harness.ts`, `tests/helpers/minimal_repro_setup.py`,
`tests/helpers/minimal_native_runner.py`, `minimal-repro-driver.mjs`)
touch or alter any production code path; they are standalone
investigation tooling kept alongside the suite for reproducibility, not
wired into `npm test`/`playwright test`'s default run.

**Current state left in the codebase**: `sdk/web/src/client.ts` uses
`new ExternalE2EEKeyProvider({ keySize: 256 })` + `setKey(base64Text)` —
PBKDF2 path (LiveKit's own documented "recommended for maximum
compatibility" choice), ASCII-safe input (avoids the UTF-8-mangling bug
found in candidate 2), and a 256-bit output size matching this system's
32-byte session keys and the AES-256 selection rule from finding 5 above
— the most defensible combination available given everything tried, but
**explicitly not claimed to work cross-platform**.
`apps/e2e-harness/tests/kdf-compat.spec.ts` is left in the suite as a
permanent, real regression trip-wire: it currently fails (correctly —
that's the accurate signal), and should go green automatically the
moment a working configuration is found or LiveKit resolves the upstream
ambiguity, without anyone needing to remember to re-check it.

The `apps/ai-agent` service is kept on `livekit==1.1.7` (upgraded from
1.0.7 during the third pass) going forward regardless of this finding:
it is a real, current, independently-justified fix (see changelog note
above) unrelated to whether it resolves cross-platform E2EE, and it was
re-verified safe on its own terms — the full `apps/ai-agent` unit suite
(22/22) and the real `test_agent_integration.py::
test_ai_agent_full_lifecycle` integration test both pass against it.

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

### Fail-closed: E2EE initialization failure never becomes silent plaintext

A gap was found and fixed while re-auditing `joinSession()` for exactly
this property: `room.setE2EEEnabled(true)` resolving does **not** itself
guarantee the E2EE worker has acknowledged the enable message —
`room.isE2EEEnabled` is only flipped by an async
`RoomEvent.ParticipantEncryptionStatusChanged` event that call doesn't
wait for. A slow or failed worker handshake could previously have left
`joinSession()` returning "success" without encryption actually
confirmed active — the same *class* of bug as Bug 2 above, at a
different layer.

**Fix**: `joinSession()` now waits (`waitForE2EEConfirmed`, 8s timeout)
for `room.isE2EEEnabled` to actually become true after calling
`setE2EEEnabled(true)`, and on any failure in that chain — the call
throwing, or the confirmation never arriving — disconnects, clears
`this.room`, and throws `ConnectionError("Secure connection could not be
established. Please retry. (...)")` rather than returning.

**Verified for real** (`apps/e2e-harness/tests/fail-closed.spec.ts`): a
deliberately dead `Worker` (loads, runs, never acknowledges any message —
the realistic shape of a real-world E2EE worker failure) causes
`joinSession()` to reject with exactly that error after the 8s timeout,
and leaves the connection state `disconnected`, not `connected` — no
silent plaintext fallback.

## Test Matrix

| Test | Result | Evidence |
|---|---|---|
| Web ↔ Web E2EE (audio+video, both directions) | **PASS** | `web-web-e2ee.spec.ts` — real media both directions, `isEncrypted: true` both sides, zero `EncryptionError`s, clean leave |
| Flutter ↔ Flutter E2EE | **BLOCKED** | No Flutter/Android toolchain in this environment — see "Flutter feasibility" |
| Flutter ↔ Web E2EE | **BLOCKED** (and, by the Python proxy finding above, presumed broken for the same reason as Web↔native) | Not directly tested |
| Web ↔ Flutter E2EE | **BLOCKED** (same) | Not directly tested |
| Web ↔ native (Python SDK) E2EE | **CONFIRMED BROKEN** | `kdf-compat.spec.ts` test 1 — reproducible `InvalidKey` on every run, 5 parameter combinations tried |
| native → Web E2EE (reverse) | **INCONCLUSIVE** | `kdf-compat.spec.ts` test 2 — see "Reverse direction" above; treat as probably also broken |
| E2EE initialization failure (dead worker) | **FAIL CLOSED (correct)** | `fail-closed.spec.ts` — `joinSession()` rejects with a clear error, connection left `disconnected`, never silently unencrypted |
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
| E2EE-FINDING-3 | Critical, **confirmed upstream LiveKit limitation (classification C)** | Web SDK (JS/WASM key derivation) vs. native LiveKit stack (Rust/C++ core, shared by Flutter + Python) derive different keys from the same raw bytes; eight candidate fixes/configurations tried across three sessions, plus a fourth-pass minimal reproduction with zero AyurEze code in the chain — all fail identically; no officially supported version combination found that works; matches an unresolved, maintainer-uncommented upstream LiveKit issue; AyurEze integration bug (classification B) ruled out with high confidence by the minimal reproduction | Web ↔ (Flutter \| AI agent \| any native SDK) | None found across any pass — none applicable, this is not an AyurEze bug | `apps/e2e-harness/tests/kdf-compat.spec.ts` (left red intentionally, as a trip-wire) |
| E2EE-BUG-4 | High | `joinSession()` didn't wait for/verify E2EE-enable confirmation — a slow or failed worker handshake could return "success" before encryption was actually active | Web SDK, any real browser | `waitForE2EEConfirmed()`: wait for `room.isE2EEEnabled`, fail closed (disconnect + throw) on timeout/failure | `apps/e2e-harness/tests/fail-closed.spec.ts` |

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
- Fail-closed behavior on E2EE initialization failure: **VERIFIED** — a
  real dead-worker scenario correctly rejects `joinSession()` rather than
  silently connecting unencrypted (see "Fail-closed" above).

Do not read "PARTIALLY VERIFIED" as "mostly fine" — the broken
combination (Web ↔ native) is exactly the one the real product's Mode B
(AI translation, which is Web/Flutter clients talking to the Python AI
agent) depends on, and it does not currently work.

**Second-pass note**: a follow-up session specifically targeted resolving
E2EE-FINDING-3, using external research (LiveKit's own GitHub issues,
confirming the AES-128/256-by-key-length behavior) and a direct FFI-level
key-export probe, and tried one further untested parameter combination
(candidates 5 and 6 above). None of it resolved the mismatch. This is
reported honestly rather than re-framed as progress: the finding remains
open. Further black-box testing (trying more parameter permutations
without source-level visibility into the native frame-crypto core) has
diminishing odds of success — the next productive step is almost
certainly external (LiveKit maintainer input, or a controlled experiment
with a debug build of the native core), not more guessing from this
codebase alone. CI/CD readiness should wait on this — see the final
report this document was produced alongside.

**Third-pass note**: a dedicated compatibility investigation (not a fix
attempt) re-checked whether a different, *officially supported*
Server/Web/native version combination — as opposed to a different
client-side parameter — resolves E2EE-FINDING-3. Re-confirmed
issue #4247 is still open and uncommented by LiveKit maintainers. Found
and tested the one concrete version-specific lead available (Python SDK
1.1.7's new explicit `key_derivation_function` field, candidates 7 and 8
above), including an explicit HKDF-matched-on-both-sides test that had
never been tried before. Both failed identically to every prior attempt.
This is a **definitive negative result**: it rules out "KDF algorithm
choice" as the root cause with certainty (both algorithms tested,
explicitly matched, both fail), which prior passes could not fully rule
out (prior passes always left the native side on its implicit default).
No version combination of LiveKit server (`v1.13.7`), Web SDK (`2.22.3`),
or native/Python SDK (`1.0.7` or `1.1.7`) tested in this investigation
achieves real cross-platform E2EE interoperability. Given three full
passes, eight total parameter/version combinations, and no access to the
native frame-crypto core's C++ source, this is now classified as an
**upstream LiveKit limitation** (see the final report this document was
produced alongside) rather than an AyurEze integration bug — further
in-repo experimentation has no remaining credible hypotheses to test.

**Fourth-pass note**: a follow-up pass built a "minimal reproduction,
independent of AyurEze business logic" (see the "Fourth pass" subsection
above) — a standalone Web↔native E2EE test using LiveKit's own
`RoomService.CreateRoom`, hand-minted JWTs, a freshly-generated random
key, and raw `livekit-client`/`livekit` (Python) SDK calls, with **no
AyurEze code anywhere in the chain** (no Go API, no `internal/e2ee`, no
`internal/token`, no `sdk/web`'s `AyurezeTelehealthClient`). It failed
identically (`InvalidKey: Decryption failed: OperationError`, 61,224
bytes of real audio received, remote `isEncrypted: true`). This is the
strongest evidence yet against an AyurEze-side root cause: with every
line of AyurEze-authored code removed from the reproduction, the
mismatch persists exactly as before. **Classification upgraded from
"probable" to confirmed: C — LiveKit upstream limitation**, not an
AyurEze integration bug (ruling out classification B with high
confidence) and not an AyurEze misconfiguration.

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
- **The fail-closed timeout (8s) is an untuned first guess** — long
  enough not to false-positive-fail a normal connection (never observed
  to in this pass's ~25+ successful joins), but not validated against
  real-world slow-network conditions where E2EE setup might legitimately
  take longer. Worth revisiting with real network telemetry before
  treating 8s as a permanent constant.
- **A transient WebRTC ICE connection flake** was observed once (of
  ~4 full-suite runs across both passes) on a test unrelated to any code
  changed this pass, in a combined run of 13 tests in one browser/worker
  process; it did not reproduce in isolation or on a subsequent full
  rerun. Consistent with resource contention under this sandbox's load
  rather than a real bug, but worth watching if it recurs in CI.

## Git — first pass (`35fd53a`)

- **Branch**: `claude/ayureze-telehealth-build-vaf7sr`
- **Files changed**: `sdk/web/src/client.ts`, `sdk/web/src/types.ts`,
  `sdk/web/src/apiClient.ts`, `sdk/web/test/apiClient.test.ts`, plus a new
  `apps/e2e-harness/` (Playwright suite: `web-web-e2ee.spec.ts`,
  `kdf-compat.spec.ts`, `private-mode.spec.ts`, `ai-mode.spec.ts`,
  `ai-authorization-boundaries.spec.ts`, `reconnect.spec.ts`,
  `bug-hunting.spec.ts`, plus `tests/helpers/` — `seed.ts`,
  `webClient.ts`, `nativeParticipant.ts`, `native_participant.py`), and
  this document + `docs/security/README.md`/`PROGRESS.md` updates.
- **Tests executed**: `sdk/web` unit suite (19/19 passing, including one
  new regression test), the full `apps/e2e-harness` Playwright suite
  (11/12 passing — the 1 failure is `kdf-compat.spec.ts`'s forward-
  direction test, intentionally left red as a real, accurate trip-wire
  for Finding 3, not a flaky or broken test).

## Git — second pass (this commit)

- **Branch**: `claude/ayureze-telehealth-build-vaf7sr`
- **Files changed**: `sdk/web/src/client.ts` (fail-closed confirmation +
  the `keySize: 256` candidate fix attempt), `apps/e2e-harness/tests/
  fail-closed.spec.ts` (new), `apps/e2e-harness/tests/helpers/
  native_participant.py` (unchanged behavior, re-verified), this document.
- **Tests executed**: `sdk/web` unit suite (19/19), Go unit + integration
  suite (`go test ./...` and `go test -tags integration
  ./test/integration/...`, all passing, unaffected by this pass since no
  Go code changed), Python AI agent suite (22/22 fast tests passing,
  unaffected), full `apps/e2e-harness` Playwright suite twice
  (12/13 passing both times — the 1 failure is `kdf-compat.spec.ts`'s
  forward-direction test, still intentionally red; a transient WebRTC ICE
  flake was observed once on an unrelated test during a combined run,
  confirmed non-reproducing when re-run in isolation and on a full clean
  rerun, not a real regression).

## Git — third pass (this commit)

- **Branch**: `claude/ayureze-telehealth-build-vaf7sr`
- **Purpose**: a compatibility *investigation* (per explicit instruction —
  not a fix attempt, no arbitrary version changes, no production code
  touched except the one independently-justified dependency bump below,
  kept only after it was proven not to resolve E2EE-FINDING-3).
- **Files changed**: `apps/ai-agent/requirements.txt` (`livekit` 1.0.7 →
  1.1.7 — kept for its own documented bug fix, not because it resolves
  cross-platform E2EE; it does not), this document.
- **Files touched then fully reverted, nothing left uncommitted**:
  `sdk/web/src/client.ts` was temporarily changed to test an explicit-HKDF
  configuration (candidate 8 above), then restored via `git checkout --`
  to its exact previously-committed content before any commit was made —
  confirmed via `git status`/`git diff` showing zero changes to that file
  in this pass's diff.
- **Note on the running `ai-agent` Docker service**: the container
  currently running in this sandbox's `docker compose` stack still runs
  `livekit==1.0.7` — rebuilding its image to pick up the `requirements.txt`
  bump failed in this sandboxed environment (the Docker build step cannot
  reach PyPI through this session's outbound proxy without additional
  build-time proxy/CA configuration, which was out of scope for an
  investigation task). This does not affect this pass's findings: the
  KDF-compatibility tests run the native participant directly via
  `apps/ai-agent/.venv/bin/python3` (already upgraded in-place and used
  for every test in this pass), not via the Docker container. The image
  should be rebuilt as ordinary follow-up maintenance whenever this
  environment (or CI) has full PyPI egress.
- **Tests executed** (final confirmation, after all investigation and
  before committing): `apps/ai-agent` unit suite (22/22, against the
  upgraded 1.1.7 venv), `sdk/web` unit suite (19/19, confirming
  `client.ts` is back to its clean committed state), Go unit suite
  (`go test ./...`, all passing, unaffected — no Go code changed), full
  `apps/e2e-harness` Playwright suite (12/13 passing — the 1 failure is
  `kdf-compat.spec.ts`'s forward-direction test, still intentionally red,
  still failing with the exact same `InvalidKey: Decryption failed:
  OperationError` signature, now reconfirmed against the upgraded native
  SDK: 38KB of real audio bytes received, remote `isEncrypted: true`).
- **Conclusion**: no code change was needed or made to resolve
  E2EE-FINDING-3, because none of the three passes' combined eight
  parameter/version combinations found a working one. See the final
  report delivered alongside this commit for the full classification.
