import { expect, test } from "@playwright/test";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor, joinAsPatient } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";

/**
 * Private Mode acceptance test (master prompt section 9): patient +
 * doctor only, real encrypted audio/video, and — critically — the AI
 * agent is never triggered and never appears as a room participant. The
 * platform must never activate AI translation just because a room exists.
 */
test.describe("Private Mode (AI absent) acceptance test", () => {
  test("patient <-> doctor E2EE call with no AI consent granted: AI never joins", async ({ browser }) => {
    const seeded = seedTenant("private-mode");

    const doctorCtx = await browser.newContext();
    const patientCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    const patientPage = await patientCtx.newPage();

    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, { publishAudio: true, publishVideo: true });

      await initSdk(patientPage, API_BASE_URL, LIVEKIT_URL);
      await joinAsPatient(patientPage, seeded, session.id, { publishAudio: true, publishVideo: true });

      await doctorPage.waitForTimeout(4000);

      // 1. E2EE audio/video works (reuses the same proof points as the
      // Web<->Web test — kept here too since Private Mode is its own
      // acceptance scenario per the spec, not just a subset).
      const [doctorStats, patientStats] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getRemoteMediaStats()),
        patientPage.evaluate(() => window.Ayureze!.getRemoteMediaStats()),
      ]);
      expect(doctorStats.audioBytesReceived).toBeGreaterThan(0);
      expect(patientStats.audioBytesReceived).toBeGreaterThan(0);

      const [doctorDiag, patientDiag] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getEncryptionDiagnostics()),
        patientPage.evaluate(() => window.Ayureze!.getEncryptionDiagnostics()),
      ]);
      expect(doctorDiag.participants.find((p) => !p.isLocal)?.isEncrypted).toBe(true);
      expect(patientDiag.participants.find((p) => !p.isLocal)?.isEncrypted).toBe(true);

      // 2. AI absent: exactly 2 participants in the room (never a 3rd,
      // AI-agent-identity one) from the Web SDK's own view.
      const [doctorParticipants, patientParticipants] = await Promise.all([
        doctorPage.evaluate(() => window.Ayureze!.getParticipants()),
        patientPage.evaluate(() => window.Ayureze!.getParticipants()),
      ]);
      expect(doctorParticipants).toHaveLength(2);
      expect(patientParticipants).toHaveLength(2);
      expect(doctorParticipants.some((p) => p.role === "ai_agent")).toBe(false);
      expect(patientParticipants.some((p) => p.role === "ai_agent")).toBe(false);

      // 3. Ground truth from the Go API itself (server-authoritative, part
      // of the real join response, not client-side state): the session's
      // own ai_translation_authorized flag was never set, because
      // enableAITranslation() (consent grant) was never called anywhere
      // in this test.
      expect((session as { aiTranslationAuthorized?: boolean }).aiTranslationAuthorized).toBe(false);

      await patientPage.evaluate(() => window.Ayureze!.leaveSession());
      await doctorPage.evaluate(() => window.Ayureze!.leaveSession());
    } finally {
      await doctorCtx.close();
      await patientCtx.close();
    }
  });
});
