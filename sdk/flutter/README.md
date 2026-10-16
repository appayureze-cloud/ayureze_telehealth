# ayureze_telehealth (Flutter SDK)

Headless Flutter SDK for the AyurEze Patient and Doctor apps. Wraps the Go
session API (`docs/api/README.md`) and LiveKit's Flutter client behind a
single API surface — consuming apps never import `livekit_client` or call
the Go API directly.

## Install (within this monorepo)

```yaml
dependencies:
  ayureze_telehealth:
    path: ../../sdk/flutter   # adjust relative to your app
```

## API surface

```dart
final client = AyurezeTelehealthClient(
  apiBaseUrl: 'https://api.ayureze.example',
  livekitUrl: 'wss://livekit.ayureze.example',
);

await client.initialize();
final user = await client.authenticate(tenant: 'clinic-1', email: '...', password: '...');

// Doctor: create + join
final session = await client.createSession(patientEmail: 'patient@example.com');
await client.joinSession(session.id);

// Patient: join an existing session
await client.joinSession(sessionId);

await client.enableMicrophone();
await client.enableCamera();

// AI translation (Mode B) — either participant may grant/revoke
await client.enableAITranslation();
client.captions.listen((c) => print('${c.sourceLanguage} -> ${c.targetLanguage}: ${c.translatedText}'));
await client.disableAITranslation();

client.setLanguage('ta');
final state = client.getConnectionState();
final participants = client.getParticipants();
final sessionState = client.getSessionState();

await client.leaveSession();   // or client.endSession() to end for everyone
await client.dispose();
```

See `lib/src/ayureze_client.dart` for full method-level documentation and
`lib/src/models/models.dart` for the returned data types
(`AyurezeUser`, `AyurezeSessionState`, `AyurezeParticipant`,
`AyurezeCaption`, `AyurezeConnectionState`, `AyurezeE2EETrackState`).

## E2EE diagnostics

`joinSession()` enabling E2EE and the room connecting successfully do
**not** by themselves mean a specific participant's media can actually be
decrypted — see `docs/e2ee/VALIDATION.md`. Use the diagnostic surface
below to observe real, per-track E2EE state, sourced entirely from
LiveKit's own `TrackE2EEStateEvent`:

```dart
// Live updates, any time a track's E2EE state changes:
client.e2eeStateChanges.listen((s) {
  if (!s.state.isSecure) {
    // e.g. s.state == AyurezeE2EEState.missingKey / decryptionFailed /
    // encryptionFailed / internalError / pending (not yet confirmed) —
    // treat the track as NOT currently usable, never as "probably fine."
  }
});

// Synchronous snapshot of every currently-known track:
final states = client.getE2EETrackStates();
```

`AyurezeE2EEState` mirrors `livekit_client`'s own `E2EEState` 1:1 (`kNew`
renamed to `pending` since `new` is a Dart keyword), plus an `unknown`
fallback. **Fail-closed semantics**: `AyurezeE2EEState.isSecure` is `true`
only for `ok` and `keyRatcheted` — every other state, including `pending`
(not yet confirmed) and `unknown` (unrecognized), is treated as NOT
secure. A track is never inferred secure from connection success alone,
and never silently reset to secure without LiveKit itself reporting `ok`/
`keyRatcheted` again.

`AyurezeE2EETrackState` carries only `participantIdentity`, `trackSid`,
`kind` (`audio`/`video`/`data`), `state`, and a timestamp — never
encryption keys, ciphertext, plaintext, raw media, access tokens, or
other session secrets. It is safe to log or display as-is.

This diagnostic state has no effect on AI-translation authorization,
which remains entirely server-side (Go API consent checks) — it exists
only so a consuming app can tell "this participant's track cannot
currently be decrypted" instead of assuming success from a connected
room. See `lib/src/e2ee_diagnostics.dart` for the implementation and
`test/e2ee_diagnostics_test.dart` for its test coverage.

**Real Flutter Android device E2EE interoperability has NOT yet been
verified.** The key-derivation and key-size fixes in
`docs/e2ee/VALIDATION.md`'s "Fifth pass" were applied to this SDK by the
same source-level reasoning verified end-to-end for Web ↔ native
(Python), and this diagnostic surface is code-level verified (`flutter
analyze` clean, `flutter test` passing against synthetic/mocked state —
no LiveKit room or real device involved). Neither confirms real encrypted
media crossing a real Android device boundary. No Android SDK, `adb`,
emulator, physical device, or `/dev/kvm` has been available in any
sandbox pass to date — do not claim Flutter E2EE is production-verified
until a real device/emulator test proves it.

## External E2EE device test harness

This repo's own sandbox has no Android SDK, `adb`, emulator, physical
device, or `/dev/kvm` (true in every pass to date — see
`docs/e2ee/VALIDATION.md`), so real Flutter Android E2EE interoperability
cannot be tested here. `example/` is a small, real Flutter app — built
with the actual `AyurezeTelehealthClient` from this package, no second
E2EE implementation — for an external developer with a real Android
device/emulator to run these tests and read the results directly off the
`e2eeStateChanges`/`getE2EETrackStates()` diagnostics on screen.

**Flutter E2EE is code-level verified but has not yet been verified on a
real Android device/emulator in the current development environment.**
It is not production-ready and not fully verified until someone runs the
procedure below and it passes.

### What's in `example/`

A single-screen app (`example/lib/main.dart`) with:

- Config fields (API base URL, LiveKit URL, tenant, email, password) and
  a session-id field for joining an existing session.
- **Authenticate**, **Create + Join + Publish**, **Join Existing**, mic
  toggle, and **Leave** buttons — each calling the real
  `AyurezeTelehealthClient` methods a production app would.
- A live, scrolling **E2EE track states** list, backed by
  `client.e2eeStateChanges` and `client.getE2EETrackStates()` — the
  screen a tester actually reads to judge PASS/FAIL.
- A structured **event log** (connection state changes, E2EE state
  changes, errors) using the event names in "Logging" below.

It never displays an E2EE key, access token, ciphertext, or patient
data — only what `AyurezeE2EETrackState`/`AyurezeParticipant` already
expose (identifiers + state) and the synthetic test credentials the
tester types in. **Use only against a synthetic/dev tenant, never a real
patient session.**

Run it from a real Android device/emulator:

```bash
cd sdk/flutter/example
flutter pub get
flutter run   # pick your connected Android device/emulator
```

### Test procedure

Two people (or two terminals/devices) are needed for A and B; C needs two
Android runtimes (two emulators, or one emulator + one physical device).
For all three, first bring up the real stack (`docker compose up` from
the repo root, or point the harness's URL fields at a real deployment).

#### Test A — Web → Flutter (Flutter subscribes)

1. Open a Web client (e.g. `apps/e2e-harness`'s `webClient.ts` helper, or
   any app built on `sdk/web`) and create+join a session as the doctor,
   publishing audio.
2. Note the session id the Web side created.
3. On the Flutter harness: fill in **Session id to join**, tap
   **Authenticate** (as the patient), then **2b. Join Existing**.
4. Watch **E2EE track states** for the Web participant's audio track.

#### Test B — Flutter → Web (Flutter publishes)

1. On the Flutter harness: **Authenticate** (as the doctor), then
   **2a. Create + Join + Publish**. Note the printed session id.
2. Open a Web client and join that same session id as the patient
   (subscribe-only is fine).
3. On the Web side, check its own E2EE diagnostics
   (`getEncryptionDiagnostics()`/`onEncryptionError()` — see
   `sdk/web/README.md`) for the Flutter participant's track.

#### Test C — Flutter ↔ Flutter

1. Run the harness on device/emulator A: **Authenticate** (doctor),
   **2a. Create + Join + Publish**. Note the session id.
2. Run the harness on device/emulator B: **Authenticate** (patient),
   fill in that session id, **2b. Join Existing**, then **Enable mic**
   to publish from B too (tests both directions in one session).
3. Watch **E2EE track states** on *both* devices for the other's track.

#### Test D — Flutter video (only if required at this stage)

The harness doesn't currently have a camera toggle button, but
`AyurezeTelehealthClient.enableCamera()` exists and uses the same
`e2eeOptions` as audio — the same `TrackE2EEStateEvent` path applies with
`kind == AyurezeTrackKind.video`. Add a temporary button calling
`client.enableCamera()` to exercise this, or drive it from `flutter
attach`'s Dart VM console. Treat this as optional/not-yet-required unless
the product needs encrypted video before audio-only Flutter E2EE is
verified — report clearly whether it was tested, don't skip reporting it
silently.

### Pass/fail criteria

A test is **PASS** only if **all** of the following hold — connecting
alone, or `TrackSubscribed` alone, is **not** a pass:

1. Both participants connect successfully (`getConnectionState() ==
   connected` on each side).
2. Encrypted media is actually transmitted (LiveKit reports non-zero
   bytes received on the subscribing side — Web:
   `RTCRtpReceiver.getStats()`/the existing Playwright helpers; Flutter:
   audible audio, or inspect `flutter_webrtc`'s stats API).
3. The subscriber receives the track (`TrackSubscribed`/participant
   appears with the track).
4. The **E2EE diagnostic state reaches `ok` or `keyRatcheted`**
   (`s.state.isSecure == true`) for that track on the harness's own
   screen.
5. Media is actually rendered/consumed — for audio, audible sound (or a
   non-silent waveform if using a synthetic tone, matching
   `kdf-compat.spec.ts`'s approach on the Web/native side).
6. **No** `missingKey`, `decryptionFailed`, `encryptionFailed`, or
   `internalError` state occurs for that track.
7. No plaintext fallback occurred (there is none to fall back to in this
   codebase — this is a sanity re-check, not a real risk path).

Record: exact states observed and their order, whether audio was
actually heard, and the full event log from the harness's log panel.

### Reconnect test

1. Establish an encrypted call (any of Tests A–C).
2. Confirm `ok` in **E2EE track states**.
3. Disable the Android device/emulator's network (airplane mode, or kill
   Wi-Fi) for 10–15s.
4. Restore network.
5. Confirm `connectionStateChanges` shows `reconnecting` then
   `connected` again (visible in the harness's status card and log).
6. Confirm E2EE track state returns to `ok`/`keyRatcheted` — not stuck
   on a stale `ok` from before the interruption (check the event log's
   timestamps: a fresh `ok` event should appear after reconnect, not just
   the old one still displayed).
7. Confirm encrypted media resumes (audio audible again / bytes flowing
   again on the other side).

Any silent downgrade (media resumes but the state stays `missingKey`/
`decryptionFailed`/etc., or reconnects without ever re-confirming `ok`)
is a **FAIL**.

### Fail-closed test

Demonstrate that a broken E2EE key produces `missingKey`/
`decryptionFailed`, and that `isSecure == false` for it — **without**
weakening any production code to make this observable:

1. On the Flutter harness, join a session normally (any test above) so a
   healthy `ok` state is showing.
2. On the *other* participant's side, deliberately break the shared
   secret they're publishing with — e.g. in a throwaway build of the Web
   test client, patch its call site to pass a different (garbage) string
   to `keyProvider.setKey(...)` before connecting, publish from that
   broken build.
3. On the Flutter harness, confirm the corresponding track's state
   becomes `missingKey` or `decryptionFailed`, and that the on-screen
   icon/text shows **not secure** (`isSecure == false`).
4. Confirm the harness never displays that track as `ok`/secure while
   this state persists, and that no audio is intelligible from that
   track (frames aren't silently passed through unencrypted — there is
   no plaintext-fallback code path to accidentally exercise here).

Do this against a disposable throwaway build/branch — never commit a
deliberately-broken key as a code change to `sdk/web` or `sdk/flutter`.

### Version manifest

Exact versions in this repo as of commit `e882e48` — do not substitute
assumed versions:

| Component | Version | Source |
|---|---|---|
| Flutter SDK | 3.27.1 (stable channel) | `flutter --version` in this dev environment |
| Dart SDK | 3.6.0 | `flutter --version` |
| `livekit_client` (Dart/pub.dev) | 2.4.3 (constraint `^2.4.1`) | `sdk/flutter/pubspec.lock` |
| `flutter_webrtc` (transitive) | 0.13.1+hotfix.1 | `sdk/flutter/pubspec.lock` |
| `livekit-client` (Web/npm) | 2.22.3 (constraint `^2.7.5`) | `apps/e2e-harness/node_modules/livekit-client/package.json` |
| `livekit` (Python) | 1.1.7 | `apps/ai-agent/requirements.txt` |
| LiveKit Server | `v1.13.7` (Docker image `livekit/livekit-server:v1.13.7`) | `infrastructure/docker/docker-compose.yml` |
| Android `compileSdk`/`targetSdk` | 35 (Flutter 3.27.1's built-in default) | Flutter SDK's own `flutter.groovy`; `example/android` doesn't override it |
| Android `minSdk` | 21 (Flutter 3.27.1's built-in default) | same |
| Android device/emulator API level | **Not yet chosen — pick any device/emulator between API 21 and 35** and record the exact one used in your test report | n/a (no device tested yet) |

If the external tester's Flutter/Dart/Android toolchain differs from the
above, record the actual versions used in the test report — don't
silently assume they match.

### Network requirements

The harness needs to reach, from the Android device/emulator:

| Endpoint | Default port | Protocol | Purpose |
|---|---|---|---|
| API base URL | `8080` | HTTP(S) | Go API — auth, session create/join |
| LiveKit URL | `7880` | WS(S) | LiveKit signaling |
| LiveKit RTC (TCP fallback) | `7881` | TCP | Media, when UDP is blocked |
| LiveKit RTC (UDP) | `50000`–`50100` | UDP | Media (preferred path) |
| Coturn (TURN, if used) | `3478` | TCP+UDP | NAT traversal when direct/UDP fails |
| Coturn relay range | `49160`–`49200` | UDP | Relayed media via TURN |

- **Android emulator reaching a host machine's `localhost` stack**: use
  `10.0.2.2` instead of `localhost`/`127.0.0.1` (the harness's default
  config fields already use this) — that's the emulator's special alias
  for the host loopback interface.
- **A real physical device**: it can't reach `10.0.2.2` or the host's
  `localhost` at all — use the host machine's real LAN IP (and make sure
  the host's firewall allows the ports above from the device's subnet),
  or point at a real non-local deployment.
- **No secrets belong in this repo for this test.** Use the same
  synthetic dev credentials/tenant `docs/e2ee/VALIDATION.md`'s existing
  passes use, entered directly into the harness's config fields at
  runtime — never hardcoded into `example/lib/main.dart` or committed
  anywhere.

## Design notes

- **E2EE is on by default for every join.** `joinSession()` fetches the
  session's real E2EE key from the Go API (only ever delivered in that
  one response — see `docs/e2ee/README.md`) and configures LiveKit's
  SFrame key provider with it before connecting.
- **Every method that can fail throws through its returned `Future`**,
  never synchronously at call time — callers can uniformly
  `try { await client.foo(); } catch (e) { ... }` (see
  `test/ayureze_client_test.dart`, which caught a real bug of this kind
  during development).
- **`AyurezeException` subtypes** (`NotInitializedException`,
  `ApiException`, `ConnectionException`) let callers distinguish "you
  forgot a setup step" from "the server rejected this" from "the network/
  room connection failed."

## Tests

```bash
flutter analyze   # 0 issues
flutter test      # ApiClient (mocked HTTP, no network), model parsing, client guard rails,
                   # E2EE diagnostics state management + fail-closed classification
```

These run without a device/emulator (no camera/mic hardware, no platform
channels exercised) — they validate the SDK's own logic (HTTP request
shaping, response parsing, state-guard behavior) against the real
`livekit_client` and `http` package APIs (confirmed via `flutter analyze`
against the actual installed `livekit_client` version, not assumed
signatures). Full device-level integration (actual camera/mic capture,
rendering) is the consuming app's own testing responsibility — out of
scope for a headless SDK.
