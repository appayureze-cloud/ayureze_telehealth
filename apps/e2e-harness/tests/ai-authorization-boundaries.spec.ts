import { expect, test } from "@playwright/test";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor } from "./helpers/webClient";

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
 * Section 11 ("AI E2EE test") + section 10's "AI must never join merely
 * because the room exists" — the AI's authorization boundary, tested
 * against the real Go API and real AI agent service, never mocked.
 */
test.describe("AI authorization boundaries", () => {
  test("AI cannot join without consent (real 403 from the Go API)", async ({ browser }) => {
    const seeded = seedTenant("ai-no-consent");
    const doctorCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, {});
      // No enableAITranslation() call — consent was never granted.

      const startResp = await doctorPage.request.post(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}/start`, {
        data: { tenant_id: seeded.tenantId },
      });
      // The agent itself accepts the start request (202) and transitions
      // asynchronously — real rejection happens one level down, at the Go
      // API's AuthorizeAIAgent call, which the agent's own lifecycle
      // surfaces as a FAILED state. Assert on that real state, not the
      // HTTP status of the fire-and-forget /start call.
      expect(startResp.status()).toBe(202);

      const reachedFailed = await waitFor(async () => {
        const statusResp = await doctorPage.request.get(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}`);
        if (!statusResp.ok()) return false;
        const body = await statusResp.json();
        return body.current_state === "FAILED";
      }, 10_000);
      expect(reachedFailed, "AI agent never reached FAILED state after starting with no consent").toBe(true);

      const statusResp = await doctorPage.request.get(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}`);
      const body = await statusResp.json();
      const lastTransition = body.history?.[body.history.length - 1];
      expect(String(lastTransition?.detail ?? JSON.stringify(body))).toMatch(/403|authoriz/i);

      // And it never actually appears as a LiveKit participant.
      const participants = await doctorPage.evaluate(() => window.Ayureze!.getParticipants());
      expect(participants.some((p) => p.role === "ai_agent")).toBe(false);
    } finally {
      await doctorCtx.close();
    }
  });

  test("revoking consent force-removes an already-joined AI agent", async ({ browser }) => {
    const seeded = seedTenant("ai-revoke");
    const doctorCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, {});
      await doctorPage.evaluate(() => window.Ayureze!.enableAITranslation());

      const startResp = await doctorPage.request.post(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}/start`, {
        data: { tenant_id: seeded.tenantId },
      });
      expect(startResp.status()).toBe(202);

      const aiJoined = await waitFor(async () => {
        const participants = await doctorPage.evaluate(() => window.Ayureze!.getParticipants());
        return participants.some((p) => p.role === "ai_agent");
      }, 20_000);
      expect(aiJoined, "AI agent never joined before the revocation part of this test").toBe(true);

      // The real revoke call — internal_consentsvc.Revoke enforces
      // removal via roomsvc.RemoveParticipant as part of this same call.
      await doctorPage.evaluate(() => window.Ayureze!.disableAITranslation());

      const aiRemoved = await waitFor(async () => {
        const participants = await doctorPage.evaluate(() => window.Ayureze!.getParticipants());
        return !participants.some((p) => p.role === "ai_agent");
      }, 15_000);
      expect(aiRemoved, "AI agent was not removed from the room within 15s of consent revocation").toBe(true);
    } finally {
      await doctorCtx.close();
    }
  });

  test("ending the session stops the AI agent (room deleted, participant force-disconnected)", async ({ browser }) => {
    const seeded = seedTenant("ai-session-end");
    const doctorCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, {});
      await doctorPage.evaluate(() => window.Ayureze!.enableAITranslation());

      const startResp = await doctorPage.request.post(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}/start`, {
        data: { tenant_id: seeded.tenantId },
      });
      expect(startResp.status()).toBe(202);

      const aiJoined = await waitFor(async () => {
        const participants = await doctorPage.evaluate(() => window.Ayureze!.getParticipants());
        return participants.some((p) => p.role === "ai_agent");
      }, 20_000);
      expect(aiJoined).toBe(true);

      await doctorPage.evaluate(() => window.Ayureze!.endSession());

      const disconnected = await waitFor(async () => {
        const state = await doctorPage.evaluate(() => window.Ayureze!.getConnectionState());
        return state === "disconnected";
      }, 10_000);
      expect(disconnected, "doctor's own connection was not torn down after endSession()").toBe(true);

      // Server-side confirmation the agent itself observed the
      // disconnection and reached a terminal lifecycle state (not just
      // that our own client disconnected).
      const agentStopped = await waitFor(async () => {
        const statusResp = await doctorPage.request.get(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}`);
        if (!statusResp.ok()) return true; // 404 = registry already cleared it, also acceptable
        const body = await statusResp.json();
        return ["DISCONNECTED", "REVOKED", "FAILED"].includes(body.current_state);
      }, 15_000);
      expect(agentStopped, "AI agent never reached a terminal state after the session ended").toBe(true);
    } finally {
      await doctorCtx.close();
    }
  });

  test("AI cannot be authorized for another tenant's session (cross-tenant rejection)", async ({ browser }) => {
    const seededA = seedTenant("ai-tenant-a");
    const seededB = seedTenant("ai-tenant-b");
    const doctorCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seededA, undefined, {});
      await doctorPage.evaluate(() => window.Ayureze!.enableAITranslation());

      // Ask the AI agent to authorize itself for tenant A's session but
      // claiming tenant B's tenant id — the Go API's AuthorizeAIAgent
      // looks the session up scoped by tenant_id, so this must fail
      // exactly like the tenant-isolation guarantee for human callers.
      const startResp = await doctorPage.request.post(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}/start`, {
        data: { tenant_id: seededB.tenantId },
      });
      expect(startResp.status()).toBe(202);

      const reachedFailed = await waitFor(async () => {
        const statusResp = await doctorPage.request.get(`${AI_AGENT_URL}/v1/agent/sessions/${session.id}`);
        if (!statusResp.ok()) return false;
        const body = await statusResp.json();
        return body.current_state === "FAILED";
      }, 10_000);
      expect(reachedFailed, "cross-tenant AI authorization was not rejected").toBe(true);

      const participants = await doctorPage.evaluate(() => window.Ayureze!.getParticipants());
      expect(participants.some((p) => p.role === "ai_agent")).toBe(false);
    } finally {
      await doctorCtx.close();
    }
  });
});
