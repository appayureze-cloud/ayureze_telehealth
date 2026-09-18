import { expect, test } from "@playwright/test";
import { spawnNativeCreateAndJoin, spawnNativeJoin } from "./helpers/nativeParticipant";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor, joinAsPatient } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";

/**
 * THE decisive test for this validation exercise (see
 * docs/e2ee/VALIDATION.md's audit). Static analysis of the installed
 * packages found the Web SDK's key derivation (HKDF, via
 * ExternalE2EEKeyProvider.setKey(ArrayBuffer)) differs from the native
 * LiveKit stack's key derivation (PBKDF2, confirmed via `strings` on both
 * flutter_webrtc's bundled libwebrtc.so and livekit-python's
 * liblivekit_ffi.so — the same compiled frame-crypto core Flutter's
 * plugin uses). This proves it empirically: a real native LiveKit
 * participant (Python's livekit SDK) publishes real encrypted audio into
 * a real room; the real Web SDK, in a real browser, subscribes and
 * reports LiveKit's own E2EE diagnostics — never a UI flag.
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
    // NOTE: this direction cannot currently produce a trustworthy PASS/FAIL
    // verdict. Python's livekit rtc.Room only exposes
    // "track_subscription_failed" (a subscription-level event) — there is
    // no equivalent of the JS SDK's per-frame CryptorError/EncryptionError
    // for AES-GCM tag-verification failures. Given the forward direction
    // (this file's other test) proves a real, reproducible KDF mismatch
    // using the SAME two endpoints, a clean "0 errors" result here is far
    // more likely a false negative (frames silently fail to decrypt to
    // garbage audio with no event fired) than genuine compatibility. Kept
    // as a documented, always-inconclusive data point — never assert a
    // pass/fail verdict on `encryption_errors` here until a native-side
    // per-frame decrypt diagnostic is available.
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
        "Given the forward direction confirms a real KDF mismatch, treat this direction as PROBABLY ALSO BROKEN, not verified.",
    });

    // Only assert the mechanical parts (native connected + ran to
    // completion) — never a crypto-correctness verdict, per the note
    // above.
    expect(native.identity).toBeTruthy();
  });
});
