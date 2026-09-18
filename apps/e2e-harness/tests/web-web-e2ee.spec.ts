import { expect, test } from "@playwright/test";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor, joinAsPatient } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";

/**
 * Full real acceptance test per master prompt section 3/6: two real
 * browser contexts, the real Web SDK, real Go API auth/session/join, real
 * LiveKit room, real E2EE, real synthetic audio+video (Chromium's fake
 * media devices — genuine capture/encode/encrypt/transport/decrypt/decode,
 * only the physical camera/mic is synthetic), verified received on both
 * sides, then a clean leave.
 */
test.describe("Web <-> Web E2EE acceptance test", () => {
  test("doctor and patient join, exchange encrypted audio+video, both directions verified", async ({ browser }) => {
    const seeded = seedTenant("web-web");

    const doctorCtx = await browser.newContext();
    const patientCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    const patientPage = await patientCtx.newPage();
    doctorPage.on("console", (m) => console.log("[doctor console]", m.type(), m.text()));
    doctorPage.on("pageerror", (e) => console.log("[doctor pageerror]", e.message));
    patientPage.on("console", (m) => console.log("[patient console]", m.type(), m.text()));
    patientPage.on("pageerror", (e) => console.log("[patient pageerror]", e.message));

    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, { publishAudio: true, publishVideo: true });

      await initSdk(patientPage, API_BASE_URL, LIVEKIT_URL);
      await joinAsPatient(patientPage, seeded, session.id, { publishAudio: true, publishVideo: true });

      // Give SFrame + subscription + media negotiation time to settle.
      await doctorPage.waitForTimeout(6000);

      const [doctorState, patientState] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getConnectionState()),
        patientPage.evaluate(() => window.Ayureze!.getConnectionState()),
      ]);
      expect(doctorState, "doctor never reached connected").toBe("connected");
      expect(patientState, "patient never reached connected").toBe("connected");

      const [doctorDiag, patientDiag] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getEncryptionDiagnostics()),
        patientPage.evaluate(() => window.Ayureze!.getEncryptionDiagnostics()),
      ]);
      const [doctorErrors, patientErrors] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getEncryptionErrors()),
        patientPage.evaluate(() => window.Ayureze!.getEncryptionErrors()),
      ]);
      const [doctorStats, patientStats] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getRemoteMediaStats()),
        patientPage.evaluate(() => window.Ayureze!.getRemoteMediaStats()),
      ]);

      console.log("WEB-WEB doctor:", JSON.stringify({ doctorDiag, doctorErrors, doctorStats }));
      console.log("WEB-WEB patient:", JSON.stringify({ patientDiag, patientErrors, patientStats }));

      // Ground truth: real media bytes crossed in both directions.
      expect(doctorStats.audioBytesReceived, "doctor received no audio from patient").toBeGreaterThan(0);
      expect(doctorStats.videoBytesReceived, "doctor received no video from patient").toBeGreaterThan(0);
      expect(patientStats.audioBytesReceived, "patient received no audio from doctor").toBeGreaterThan(0);
      expect(patientStats.videoBytesReceived, "patient received no video from doctor").toBeGreaterThan(0);

      // Ground truth: LiveKit's own E2EE diagnostics, not a UI flag.
      expect(doctorErrors, "doctor observed encryption errors").toEqual([]);
      expect(patientErrors, "patient observed encryption errors").toEqual([]);
      const doctorSeesPatientEncrypted = doctorDiag.participants.find((p) => !p.isLocal)?.isEncrypted;
      const patientSeesDoctorEncrypted = patientDiag.participants.find((p) => !p.isLocal)?.isEncrypted;
      expect(doctorSeesPatientEncrypted, "doctor's view of patient's track was never encrypted").toBe(true);
      expect(patientSeesDoctorEncrypted, "patient's view of doctor's track was never encrypted").toBe(true);

      // Clean leave — both directions.
      await patientPage.evaluate(() => window.Ayureze!.leaveSession());
      await doctorPage.evaluate(() => window.Ayureze!.leaveSession());
      const [doctorAfterLeave, patientAfterLeave] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getConnectionState()),
        patientPage.evaluate(() => window.Ayureze!.getConnectionState()),
      ]);
      expect(doctorAfterLeave).toBe("disconnected");
      expect(patientAfterLeave).toBe("disconnected");
    } finally {
      await doctorCtx.close();
      await patientCtx.close();
    }
  });
});
