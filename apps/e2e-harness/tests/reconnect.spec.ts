import { expect, test } from "@playwright/test";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor, joinAsPatient } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";

/**
 * Network failure/reconnect test (master prompt section 14): drops the
 * browser's network mid-call, restores it, and verifies the real LiveKit
 * client reconnects and E2EE remains functional afterward (not just that
 * the socket reopens). Uses Playwright's real network-condition
 * emulation (CDP-backed, actually blocks traffic), not an application-
 * level simulation.
 */
test.describe("Network failure / reconnect", () => {
  test("temporary network loss during an active encrypted call: reconnects and E2EE keeps working", async ({ browser }) => {
    const seeded = seedTenant("reconnect");

    const doctorCtx = await browser.newContext();
    const patientCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    const patientPage = await patientCtx.newPage();

    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, { publishAudio: true });
      await initSdk(patientPage, API_BASE_URL, LIVEKIT_URL);
      await joinAsPatient(patientPage, seeded, session.id, { publishAudio: true });

      await doctorPage.waitForTimeout(3000);
      expect(await doctorPage.evaluate(() => window.Ayureze!.getConnectionState())).toBe("connected");

      // Real network loss: Playwright's context-level offline mode cuts
      // all traffic at the browser/CDP level, not an app-level mock.
      await doctorCtx.setOffline(true);
      await doctorPage.waitForTimeout(3000);

      // Restore, then wait for LiveKit's own reconnection logic.
      await doctorCtx.setOffline(false);

      const reconnected = await (async () => {
        const deadline = Date.now() + 30_000;
        while (Date.now() < deadline) {
          const state = await doctorPage.evaluate(() => window.Ayureze!.getConnectionState());
          if (state === "connected") return true;
          await new Promise((r) => setTimeout(r, 1000));
        }
        return false;
      })();
      expect(reconnected, "doctor never reached 'connected' again within 30s of network restoration").toBe(true);

      // E2EE remains functional post-reconnect: fresh media stats show
      // continued (non-stale) byte growth, and diagnostics still report
      // no encryption errors and an encrypted remote participant.
      const statsBefore = await doctorPage.evaluate(() => window.Ayureze!.getRemoteMediaStats());
      await doctorPage.waitForTimeout(4000);
      const statsAfter = await doctorPage.evaluate(() => window.Ayureze!.getRemoteMediaStats());
      expect(statsAfter.audioBytesReceived, "no new audio bytes arrived after reconnect").toBeGreaterThan(
        statsBefore.audioBytesReceived,
      );

      const diagnostics = await doctorPage.evaluate(() => window.Ayureze!.getEncryptionDiagnostics());
      const errors = await doctorPage.evaluate(() => window.Ayureze!.getEncryptionErrors());
      expect(errors).toEqual([]);
      expect(diagnostics.participants.find((p) => !p.isLocal)?.isEncrypted).toBe(true);
    } finally {
      await doctorCtx.close();
      await patientCtx.close();
    }
  });
});
