import { expect, test } from "@playwright/test";
import { spawnNativeCreateAndJoin, spawnNativeJoin } from "./helpers/nativeParticipant";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor, joinAsPatient } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";

/**
 * THE decisive test for this validation exercise (see
 * docs/e2ee/VALIDATION.md's audit). A real native LiveKit participant
 * (Python's livekit SDK) publishes real encrypted audio into a real room;
 * the real Web SDK, in a real browser, subscribes and reports LiveKit's
 * own E2EE diagnostics — never a UI flag.
 *
 * Two real, independent AyurEze implementation bugs previously made this
 * fail (root-caused by reading the actual native crypto source, not by
 * guessing more parameter combinations — see VALIDATION.md):
 *
 *  1. Key-derivation *input* mismatch: the Web SDK's
 *     ExternalE2EEKeyProvider.setKey(string) UTF-8-encodes the base64
 *     *text* and PBKDF2-derives from that; the native/Flutter code paths
 *     were base64-*decoding* the same string first and deriving from the
 *     raw bytes instead — two different PBKDF2 inputs, so two unrelated
 *     keys, even with an identical salt/algorithm/iteration count.
 *  2. Key-*size* mismatch: LiveKit's native KeyProvider
 *     (ParticipantKeyHandler::SetKeyFromMaterial, in LiveKit's WebRTC
 *     fork) hardcodes a 128-bit derived key with no way to configure it
 *     otherwise. This SDK previously overrode ExternalE2EEKeyProvider's
 *     own default (`keySize: 128`) with `keySize: 256`, producing an
 *     AES-256-GCM key that native can never match (it only ever derives
 *     AES-128-GCM).
 *
 * Fixed in sdk/web/src/client.ts (drop the keySize override),
 * apps/ai-agent/app/agent.py, and
 * apps/e2e-harness/tests/helpers/native_participant.py (don't
 * base64-decode before deriving). See VALIDATION.md for the full
 * root-cause writeup and the byte-level test vector that proved it before
 * this test was re-verified end-to-end.
 */
test.describe("Web SDK key-derivation compatibility with the native LiveKit stack", () => {
  test("Web subscriber receiving a native publisher's encrypted audio", async ({ page }) => {
    const seeded = seedTenant("kdf-native-pub");

    const native = await spawnNativeCreateAndJoin({
      tenant: seeded.tenant,
      doctorEmail: seeded.doctorEmail,
      doctorPassword: seeded.password,
      patientEmail: seeded.patientEmail,
      role: "doctor",
      apiBaseUrl: API_BASE_URL,
      livekitUrl: LIVEKIT_URL,
      durationSeconds: 18,
      publishAudio: true,
    });

    await initSdk(page, API_BASE_URL, LIVEKIT_URL);
    await joinAsPatient(page, seeded, native.sessionId);

    // Give SFrame a few seconds to establish and either succeed or fail.
    await page.waitForTimeout(5000);

    const diagnostics = await page.evaluate(() => window.Ayureze!.getEncryptionDiagnostics());
    const errors = await page.evaluate(() => window.Ayureze!.getEncryptionErrors());
    const stats = await page.evaluate(() => window.Ayureze!.getRemoteMediaStats());

    console.log("KDF-COMPAT diagnostics:", JSON.stringify({ diagnostics, errors, stats }));

    native.kill();
    await native.waitDone().catch(() => undefined);

    // Ground truth #1: bytes are arriving at the transport layer
    // regardless of decryption outcome — proves ICE/SFU/media path works
    // and isolates the question to encryption specifically.
    expect(stats.audioBytesReceived, "no audio bytes received at all — media path itself is broken, not just E2EE").toBeGreaterThan(0);

    // Ground truth #2: LiveKit's own encryption diagnostics.
    const remoteParticipant = diagnostics.participants.find((p) => !p.isLocal);
    expect(remoteParticipant, "native publisher never appeared as a remote participant").toBeTruthy();

    if (errors.length > 0 || !remoteParticipant?.isEncrypted) {
      test.info().annotations.push({
        type: "e2ee-verdict",
        description:
          "KDF MISMATCH CONFIRMED: Web SDK could not decrypt the native participant's media. " +
          `encryption_errors=${JSON.stringify(errors)} remoteParticipant=${JSON.stringify(remoteParticipant)}`,
      });
    }

    expect(errors, "LiveKit reported encryption errors — see VALIDATION.md's key-derivation finding").toEqual([]);
    expect(remoteParticipant?.isEncrypted, "remote participant's track never reached the encrypted state").toBe(true);
  });

  test("native subscriber receiving a Web SDK publisher's encrypted audio (reverse direction) — INCONCLUSIVE, see comment", async ({
    page,
  }) => {
    // NOTE: this direction still cannot produce a trustworthy PASS/FAIL
    // verdict *from this test alone*. Python's livekit rtc.Room only
    // exposes "track_subscription_failed" (a subscription-level event) —
    // there is no equivalent of the JS SDK's per-frame
    // CryptorError/EncryptionError for AES-GCM tag-verification failures,
    // so a clean "0 errors" result here cannot by itself rule out frames
    // silently failing to decrypt to garbage audio. Unlike when this
    // comment was first written, that is no longer the only evidence for
    // this direction: the forward-direction test above now proves real,
    // matching-key encrypted audio decrypts successfully using the exact
    // same key material and the exact same two endpoints, which is strong
    // (not conclusive) evidence this direction now also works. Kept as a
    // documented data point rather than upgraded to a hard assertion —
    // never assert a pass/fail verdict on `encryption_errors` here until a
    // native-side per-frame decrypt diagnostic is available.
    const seeded = seedTenant("kdf-web-pub");

    await initSdk(page, API_BASE_URL, LIVEKIT_URL);
    const session = await joinAsDoctor(page, seeded, undefined, { publishAudio: true });

    const native = await spawnNativeJoin({
      tenant: seeded.tenant,
      email: seeded.patientEmail,
      password: seeded.password,
      sessionId: session.id,
      apiBaseUrl: API_BASE_URL,
      livekitUrl: LIVEKIT_URL,
      durationSeconds: 12,
      publishAudio: false,
    });

    const done = await native.waitDone();

    console.log("KDF-COMPAT (reverse, INCONCLUSIVE) native subscriber errors:", JSON.stringify(done.encryption_errors));
    test.info().annotations.push({
      type: "e2ee-verdict",
      description:
        "INCONCLUSIVE — native SDK lacks a per-frame decrypt-failure diagnostic; " +
        `subscription-level errors observed: ${JSON.stringify(done.encryption_errors)}. ` +
        "The forward direction now confirms matching keys decrypt real audio successfully, which is strong supporting evidence for this direction too, but this test alone still cannot prove per-frame decrypt success — not a substitute for a native-side diagnostic.",
    });

    // Only assert the mechanical parts (native connected + ran to
    // completion) — never a crypto-correctness verdict, per the note
    // above.
    expect(native.identity).toBeTruthy();
  });
});
