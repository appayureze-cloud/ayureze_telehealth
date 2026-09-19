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
