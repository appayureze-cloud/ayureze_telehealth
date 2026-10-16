# @ayureze/telehealth-web

Headless Web SDK for the AyurEze Patient and Doctor web apps. Wraps the
Go session API (`docs/api/README.md`) and `livekit-client` behind a
single API surface — consuming apps never import `livekit-client`
directly.

## Install (within this monorepo)

```json
{
  "dependencies": {
    "@ayureze/telehealth-web": "file:../../sdk/web"
  }
}
```

## API surface

```ts
import { AyurezeTelehealthClient } from "@ayureze/telehealth-web";

const client = new AyurezeTelehealthClient({
  apiBaseUrl: "https://api.ayureze.example",
  livekitUrl: "wss://livekit.ayureze.example",
});

await client.initialize();
const user = await client.authenticate("clinic-1", "doctor@example.com", "...");

// Doctor: create + join
const session = await client.createSession("patient@example.com");

// E2EE requires a Worker instance — see "Why e2eeWorker is required" below.
const e2eeWorker = new Worker(new URL("livekit-client/e2ee-worker", import.meta.url), {
  type: "module",
});
await client.joinSession(session.id, { e2eeWorker });

await client.enableMicrophone();
await client.enableCamera();

// AI translation (Mode B) — either participant may grant/revoke
await client.enableAITranslation();
const unsubscribe = client.onCaption((c) => console.log(`${c.sourceLanguage} -> ${c.targetLanguage}: ${c.translatedText}`));
await client.disableAITranslation();

client.setLanguage("ta");
const state = client.getConnectionState();
const participants = client.getParticipants();
const sessionState = client.getSessionState();

await client.leaveSession(); // or client.endSession() to end for everyone
await client.dispose();
```

See `src/client.ts` for full method-level documentation and `src/types.ts`
for the returned data types (`AyurezeUser`, `AyurezeSessionState`,
`AyurezeParticipant`, `AyurezeCaption`, `AyurezeConnectionState`).

## Why `e2eeWorker` is required

LiveKit's Web E2EE implementation runs SFrame encryption/decryption in a
dedicated Web Worker. *How* a Worker is instantiated is bundler-specific:

```ts
// Vite
const e2eeWorker = new Worker(new URL("livekit-client/e2ee-worker", import.meta.url), { type: "module" });

// webpack 5
const e2eeWorker = new Worker(new URL("livekit-client/e2ee-worker", import.meta.url));
```

A headless library cannot make that choice for every consumer's bundler,
so `joinSession()` takes the Worker instance as a required parameter
rather than trying to instantiate one internally. This is a deliberate
design choice, not an oversight: **there is no way to call `joinSession()`
without E2EE** — every session is encrypted by default, with no silent
downgrade path.

## Design notes

- **The session's real E2EE key bytes are used directly** (`ExternalE2EEKeyProvider.setKey(ArrayBuffer)`,
  the HKDF-over-random-bytes path), matching how the Go API and Python AI
  agent use the same raw key — see the comment in `src/client.ts`'s
  `joinSession()` for why the base64 *text* must never be passed to
  `setKey()` as a string (a different, incompatible derivation path).
- **Every method that can fail rejects through its returned `Promise`**,
  consistent with the Flutter SDK's equivalent guarantee.
- Typed errors (`NotInitializedError`, `ApiError`, `ConnectionError`) let
  callers distinguish "you forgot a setup step" from "the server rejected
  this" from "the room connection failed."

## Tests

```bash
npm install
npx tsc --noEmit   # typecheck against the real livekit-client API — 0 errors
npx vitest run     # ApiClient (mocked fetch), type/caption parsing, client guard rails — 18/18 passing
npm run build      # produces dist/ (ESM + .d.ts)
```

These run in Node without a browser/DOM — they validate the SDK's own
logic (HTTP request shaping, response parsing, state-guard behavior, and
that the code typechecks against the real installed `livekit-client`
types) rather than guessed signatures. Full browser-level integration
(actual camera/mic capture, rendering, and Worker-based E2EE running in a
real browser) is the consuming app's own testing responsibility — out of
scope for a headless SDK. See `apps/playground` for a working example of
driving real LiveKit connectivity from a browser (without this SDK's E2EE
wrapper, which was added after that playground was built for Day 2).
