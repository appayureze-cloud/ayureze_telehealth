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
`AyurezeCaption`, `AyurezeConnectionState`).

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
flutter test      # ApiClient (mocked HTTP, no network), model parsing, client guard rails
```

These run without a device/emulator (no camera/mic hardware, no platform
channels exercised) — they validate the SDK's own logic (HTTP request
shaping, response parsing, state-guard behavior) against the real
`livekit_client` and `http` package APIs (confirmed via `flutter analyze`
against the actual installed `livekit_client` version, not assumed
signatures). Full device-level integration (actual camera/mic capture,
rendering) is the consuming app's own testing responsibility — out of
scope for a headless SDK.
