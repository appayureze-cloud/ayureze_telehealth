import { expect, test } from "@playwright/test";
import { seedTenant } from "./helpers/seed";
import { initSdk } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";

/**
 * Step 13's requirement, tested for real: if E2EE cannot initialize, the
 * call must fail closed — never silently fall back to an unencrypted
 * session. This directly exercises the `waitForE2EEConfirmed` fail-closed
 * path added to `sdk/web/src/client.ts` (see the comment in
 * `joinSession()`), using a deliberately broken/dead Worker that never
 * acknowledges the E2EE 'enable' message, simulating a real-world
 * failure (e.g. the worker script failing to load, or the browser's E2EE
 * worker handshake never completing).
 */
test.describe("Fail-closed: E2EE initialization failure never becomes a silent plaintext session", () => {
  test("a dead/unresponsive E2EE worker causes joinSession() to reject, not silently succeed unencrypted", async ({
    page,
  }) => {
    const seeded = seedTenant("fail-closed");
    await initSdk(page, API_BASE_URL, LIVEKIT_URL);
    await page.evaluate(
      ([tenant, email, password]) => window.Ayureze!.authenticate(tenant, email, password),
      [seeded.tenant, seeded.doctorEmail, seeded.password],
    );
    const session = await page.evaluate((patientEmail) => window.Ayureze!.createSession(patientEmail), seeded.patientEmail);

    const result = await page.evaluate(async (sessionId) => {
      // Bypass the harness's joinSession() helper (which always
      // constructs a real, working Worker) by calling the real SDK
      // instance directly with a deliberately broken one.
      const client = window.Ayureze!.client;

      // A worker that never responds to any postMessage — the realistic
      // shape of "E2EE worker fails to initialize" (script loads, JS
      // runs, but the init handshake never completes).
      const deadWorkerSrc = "self.onmessage = () => {};";
      const blobUrl = URL.createObjectURL(new Blob([deadWorkerSrc], { type: "application/javascript" }));
      const deadWorker = new Worker(blobUrl, { type: "module" });

      let threw = false;
      let message = "";
      try {
        await client.joinSession(sessionId, { e2eeWorker: deadWorker });
      } catch (e) {
        threw = true;
        message = String(e);
      }
      return { threw, message, finalState: client.getConnectionState() };
    }, session.id);

    console.log("FAIL-CLOSED result:", JSON.stringify(result));

    expect(result.threw, "joinSession() with a dead E2EE worker resolved successfully instead of failing").toBe(true);
    expect(result.message).toMatch(/secure connection|e2ee/i);

    // The connection must not be left in "connected" — either the join
    // was rejected before ever reaching connected, or (if LiveKit's
    // signaling connected before the E2EE handshake timeout) this SDK's
    // fail-closed path must have disconnected it again.
    expect(result.finalState, "a dead E2EE worker left the session connected — silent plaintext fallback").not.toBe(
      "connected",
    );

    const diagnostics = await page.evaluate(() => window.Ayureze!.getEncryptionDiagnostics());
    expect(diagnostics.e2eeEnabledForRoom, "room reported E2EE enabled despite a dead worker").toBe(false);
  });
});
