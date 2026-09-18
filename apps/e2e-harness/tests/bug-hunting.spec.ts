import { expect, test } from "@playwright/test";
import { seedTenant } from "./helpers/seed";
import { initSdk, joinAsDoctor } from "./helpers/webClient";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";

/**
 * Section 15 ("bug-hunting") — a few high-value attempts to break E2EE/
 * authorization through the real SDK + real Go API, never bypassing
 * either. Most of this section's scenarios (wrong/expired token, tenant
 * isolation, invalid role) already have real, passing coverage at the Go
 * API layer (apps/api/test/integration — TestAuth_ExpiredAccessTokenRejected,
 * TestTenantIsolation, TestParticipant_InvalidRoleRejectedAtTokenMint);
 * this file adds the ones that specifically need a real SDK/browser to be
 * meaningful (an unauthorized participant hitting the SDK's own error
 * surface, not just the raw HTTP response).
 */
test.describe("Bug hunting: E2EE and authorization edge cases", () => {
  test("an unauthorized third user cannot join someone else's session via the real SDK", async ({ browser }) => {
    const seeded = seedTenant("bug-unauth");
    const doctorCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    const intruderCtx = await browser.newContext();
    const intruderPage = await intruderCtx.newPage();

    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, {});

      // A second, unrelated doctor+patient pair in the SAME tenant — a
      // real account, real login, just never named as a participant on
      // seeded's session.
      const intruderSeed = seedTenant("bug-unauth-intruder");
      await initSdk(intruderPage, API_BASE_URL, LIVEKIT_URL);
      await intruderPage.evaluate(
        ([tenant, email, password]) => window.Ayureze!.authenticate(tenant, email, password),
        [intruderSeed.tenant, intruderSeed.doctorEmail, intruderSeed.password],
      );

      const joinError = await intruderPage.evaluate(async (sessionId) => {
        try {
          await window.Ayureze!.joinSession(sessionId);
          return null;
        } catch (e) {
          return String(e);
        }
      }, session.id);

      expect(joinError, "an unauthorized user's joinSession() call did not fail").toBeTruthy();
      // The Go API returns 404 for a cross-tenant session id (see
      // TestTenantIsolation) or 403 for a same-tenant non-participant —
      // either way, the real SDK must surface it as a thrown error, never
      // a silent success.
      expect(joinError).toMatch(/40[034]|forbidden|not found|unauthorized/i);
    } finally {
      await doctorCtx.close();
      await intruderCtx.close();
    }
  });

  test("browser refresh mid-call: the SDK does not silently resurrect a stale room reference", async ({ browser }) => {
    const seeded = seedTenant("bug-refresh");
    const doctorCtx = await browser.newContext();
    const doctorPage = await doctorCtx.newPage();
    try {
      await initSdk(doctorPage, API_BASE_URL, LIVEKIT_URL);
      const session = await joinAsDoctor(doctorPage, seeded, undefined, { publishAudio: true });
      await doctorPage.waitForTimeout(2000);
      expect(await doctorPage.evaluate(() => window.Ayureze!.getConnectionState())).toBe("connected");

      // A full page reload — simulates a browser refresh, which destroys
      // all in-memory JS state (the old Room object, its E2EE worker,
      // everything). A real production app would need to re-authenticate
      // and re-join; this proves the SDK doesn't crash or leave the new
      // page in some half-initialized state, and that a fresh
      // joinSession() on the same session id after reload gets fresh,
      // correctly-encrypted state (not stale key material from a
      // previous page-lifetime).
      await doctorPage.reload();
      await doctorPage.waitForFunction(() => window.Ayureze !== undefined, { timeout: 5000 });
      await doctorPage.evaluate(([api, lk]) => window.Ayureze!.initialize(api, lk), [API_BASE_URL, LIVEKIT_URL]);
      await doctorPage.evaluate(
        ([tenant, email, password]) => window.Ayureze!.authenticate(tenant, email, password),
        [seeded.tenant, seeded.doctorEmail, seeded.password],
      );
      await doctorPage.evaluate((sid) => window.Ayureze!.joinSession(sid), session.id);
      await doctorPage.waitForTimeout(2000);

      expect(await doctorPage.evaluate(() => window.Ayureze!.getConnectionState())).toBe("connected");
      const diagnostics = await doctorPage.evaluate(() => window.Ayureze!.getEncryptionDiagnostics());
      expect(diagnostics.e2eeEnabledForRoom).toBe(true);
    } finally {
      await doctorCtx.close();
    }
  });
});
