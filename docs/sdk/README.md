# SDK Usage

Both SDKs expose the same headless API surface (build spec section 12) so
the Patient/Doctor apps can be built against either platform consistently:
`initialize`, `authenticate`, `createSession`, `joinSession`,
`leaveSession`, `endSession`, `enableMicrophone`/`disableMicrophone`,
`enableCamera`/`disableCamera`, `enableAITranslation`/`disableAITranslation`,
`setLanguage`, `getConnectionState`, `getParticipants`, `getSessionState`,
plus a caption stream/callback for AI-translated captions.

## Flutter — `sdk/flutter`

```dart
final client = AyurezeTelehealthClient(apiBaseUrl: '...', livekitUrl: '...');
await client.initialize();
await client.authenticate(tenant: 'clinic-1', email: '...', password: '...');
```

E2EE is on by default for every `joinSession()` call — no way to join
without it. See `sdk/flutter/README.md` for the full API and a documented
real bug this SDK's own tests caught during development (a synchronous
throw that would have broken callers' `try`/`await`/`catch` pattern).

**Validated in this build:** `flutter analyze` (0 issues) and `flutter
test` (18/18 passing — `ApiClient` against a mocked HTTP client, caption/
model parsing, and client guard-rail behavior), all against the real
`livekit_client` package API (not assumed signatures — confirmed by
reading its installed source during development, which is also how the
E2EE key-encoding bug below was caught).

**Real bug found and fixed during development:** `livekit_client`'s
`BaseKeyProvider.setSharedKey(String)` uses the string's UTF-16 code units
as the raw key bytes directly — it does **not** base64-decode. Passing the
join response's base64 key text directly would have derived a completely
different (wrong) key than the one the Go API and Python AI agent use,
silently breaking cross-participant decryption. Fixed by base64-decoding
first, then round-tripping through `String.fromCharCodes` — see the
comment in `sdk/flutter/lib/src/ayureze_client.dart`.

## Web — `sdk/web`

```ts
const client = new AyurezeTelehealthClient({ apiBaseUrl: "...", livekitUrl: "..." });
await client.initialize();
await client.authenticate("clinic-1", "...", "...");
```

`joinSession()` requires an `e2eeWorker: Worker` argument — LiveKit's Web
E2EE runs in a dedicated Worker, and Worker instantiation is
bundler-specific, so this SDK never picks one silently (and never offers
a way to join without E2EE at all). See `sdk/web/README.md` for exact
Vite/webpack snippets.

**Validated in this build:** `tsc --noEmit` (0 errors against the real
`livekit-client` types) and `vitest run` (18/18 passing — same coverage
shape as the Flutter SDK), plus `npm run build` producing a clean
ESM + `.d.ts` `dist/`.

## What has *not* been validated

Neither SDK has been exercised in a real browser/device against the live
Go API + LiveKit + AI agent stack end-to-end (that would require a UI
harness beyond a headless library's own test suite — `apps/playground`
does this for raw LiveKit connectivity, but predates this SDK layer).
Cross-SDK E2EE interop (a Flutter or Web client's media actually being
decrypted by the Python AI agent using the same session key, or vice
versa) is architecturally sound — all three follow LiveKit's standardized
shared-key SFrame derivation — but has only been directly verified
Python-to-Python (`apps/ai-agent/tests/test_pipeline_live_integration.py`).
Marked here rather than silently assumed, per the project's "never report
an untested feature as working" rule.
