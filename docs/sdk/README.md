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
`livekit-client` types) and `vitest run` (19/19 passing), plus
`npm run build` producing a clean ESM + `.d.ts` `dist/`.

**Two real bugs found and fixed via a real-browser test harness** (see
`docs/e2ee/VALIDATION.md` for the full investigation) — neither was
visible from source inspection or from unit tests with a mocked `fetch`/
`Room`:
1. `ApiClient`'s default `fetch` was called unbound (`this.fetchImpl(...)`
   sets `this` to the `ApiClient` instance), which native browser `fetch`
   rejects with `TypeError: ... Illegal invocation`. Fixed:
   `fetch.bind(globalThis)`.
2. `joinSession()` never called LiveKit's `room.setE2EEEnabled(true)` —
   every session published via this SDK was sending **real, unencrypted
   media** despite the SDK's own "E2EE is on by default" claim. Only real
   LiveKit server-reported track metadata (`Participant.isEncrypted`)
   surfaced this; a mocked Room would never catch it. Fixed: the SDK now
   explicitly enables E2EE on the room right after connecting.

## Real cross-platform E2EE validation — see `docs/e2ee/VALIDATION.md`

A dedicated Playwright-based harness (`apps/e2e-harness/`) exercises both
of the bugs above out of existence and then goes further: real Web↔Web
(now **PASS**, both bugs fixed), real Private Mode and AI Translation
Mode acceptance tests (**PASS**), real AI authorization-boundary tests —
no consent, cross-tenant, revocation, session end (all **correctly
rejected/stopped**), a real network-loss/reconnect test (**PASS**), and a
real cross-platform key-derivation test between the Web SDK and a native
LiveKit participant (Python, sharing Flutter's compiled frame-crypto
core) — this one is **CONFIRMED BROKEN**: the Web SDK and the native
LiveKit stack (Flutter, the Python AI agent) derive different encryption
keys from the same raw session key, and every attempted fix in this pass
failed to resolve it. This matches an unresolved upstream LiveKit report.
**Do not mix Web clients with Flutter/native clients (including the AI
agent) in the same encrypted room in production until this is resolved.**
Flutter itself remains entirely unverified in real conditions — this
sandbox has no Flutter SDK or Android emulator/device. Full detail,
evidence, and the exact fixes attempted are in `docs/e2ee/VALIDATION.md`;
this section is a summary, not a substitute for reading it.
