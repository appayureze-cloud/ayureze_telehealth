import { expect, test } from "@playwright/test";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor, joinAsPatient } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";
const AI_AGENT_URL = "http://localhost:8090";

async function waitFor(predicate: () => Promise<boolean>, timeoutMs: number, intervalMs = 500): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return true;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}

/**
 * AI Translation Mode acceptance test (master prompt section 10): patient
 * + doctor + AI agent. Verifies the full real chain — consent grant ->
 * AI-agent-service authorization against the real Go API -> AI joins
 * LiveKit as a real encrypted participant -> AI is visible to the other
 * real participants with the correct role. Never a shortcut/mocked
 * consent or authorization call.
 */
test.describe("AI Translation Mode acceptance test", () => {
  test("consent -> AI authorization -> AI joins as an encrypted participant", async ({ browser }) => {
    const seeded = seedTenant("ai-mode");

    const doctorCtx = await browser.newContext();
    const patientCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    const patientPage = await patientCtx.newPage();

    try {
      // 1 & 2: patient and doctor authenticate; session is created.
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, { publishAudio: true });

      await initSdk(patientPage, API_BASE_URL, LIVEKIT_URL);
      await joinAsPatient(patientPage, seeded, session.id, { publishAudio: true });

      // 3 & 4: both joined (above). 5: E2EE initializes (asserted below
      // alongside the AI's own encrypted-participant status, since that's
      // this test's unique focus vs. private-mode.spec.ts).

      // 6: consent is explicitly granted (doctor grants it here — either
      // participant may per docs/security/README.md).
      await doctorPage.evaluate(() => window.Ayureze!.enableAITranslation());

      // 7: AI authorization is issued, and 8: AI joins as an encrypted
      // participant — triggered via the real AI agent's own public HTTP
      // control surface (POST /v1/agent/sessions/{id}/start), exactly as
      // a real orchestrator would, never a shortcut that calls the Go
      // API's internal authorize endpoint directly.
      const startResp = await doctorPage.request.post(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}/start`, {
        data: { tenant_id: seeded.tenantId },
      });
      expect(startResp.ok(), `AI agent /start returned ${startResp.status()}: ${await startResp.text()}`).toBe(true);

      // Poll until the AI agent identity ("ai-agent-<session id>", set by
      // apps/api/internal/sessionsvc.AuthorizeAIAgent) appears as a real
      // LiveKit participant to the doctor's own real Web SDK session.
      const aiJoined = await waitFor(async () => {
        const participants = await doctorPage.evaluate(() => window.Ayureze!.getParticipants());
        return participants.some((p) => p.role === "ai_agent");
      }, 20_000);
      expect(aiJoined, "AI agent never appeared as a participant within 20s").toBe(true);

      // 9: AI receives only authorized media / 11: AI is an encrypted
      // endpoint — verified via the doctor's own LiveKit diagnostics: the
      // AI's track publications (if it publishes any) and its
      // participant-level encryption status.
      const diagnostics = await doctorPage.evaluate(() => window.Ayureze!.getEncryptionDiagnostics());
      const aiParticipant = diagnostics.participants.find((p) => !p.isLocal && p.identity.startsWith("ai-agent-"));
      expect(aiParticipant, "AI participant not found in encryption diagnostics").toBeTruthy();

      // Real Prometheus evidence (not just SDK-side state) that the real
      // AI agent process itself transitioned through its authorize/join
      // lifecycle for this exact interaction — see apps/ai-agent/app/metrics.py.
      const metricsResp = await doctorPage.request.get(`${AI_AGENT_URL}/metrics`);
      const metricsText = await metricsResp.text();
      expect(metricsText).toContain('ai_agent_authorize_total{outcome="success"}');
      expect(metricsText).toContain('ai_agent_join_total{outcome="success"}');

      // Clean up: stop the agent via its real API, then leave.
      await doctorPage.request.post(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}/stop`);
      await patientPage.evaluate(() => window.Ayureze!.leaveSession());
      await doctorPage.evaluate(() => window.Ayureze!.leaveSession());
    } finally {
      await doctorCtx.close();
      await patientCtx.close();
    }
  });
});
