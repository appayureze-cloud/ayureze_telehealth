import type { Page } from "@playwright/test";
import type { AyurezeHarness } from "../../src/harness";
import type { SeededTenant } from "./seed";

declare global {
  interface Window {
    Ayureze?: AyurezeHarness;
  }
}

export async function initSdk(page: Page, apiBaseUrl: string, livekitUrl: string): Promise<void> {
  await page.goto("/");
  await page.waitForFunction(() => window.Ayureze !== undefined, { timeout: 5000 });
  await page.evaluate(([api, lk]) => window.Ayureze!.initialize(api, lk), [apiBaseUrl, livekitUrl]);
}

export interface JoinOpts {
  publishAudio?: boolean;
  publishVideo?: boolean;
}

/** Doctor creates a session (if sessionId not given) and joins it. Returns the session state (id/room). */
export async function joinAsDoctor(
  page: Page,
  seeded: SeededTenant,
  sessionId: string | undefined,
  opts: JoinOpts = {},
): Promise<{ id: string; room: string }> {
  await page.evaluate(
    ([tenant, email, password]) => window.Ayureze!.authenticate(tenant, email, password),
    [seeded.tenant, seeded.doctorEmail, seeded.password],
  );
  let id = sessionId;
  if (!id) {
    const session = await page.evaluate((patientEmail) => window.Ayureze!.createSession(patientEmail), seeded.patientEmail);
    id = session.id;
  }
  const joined = await page.evaluate((sid) => window.Ayureze!.joinSession(sid), id);
  if (opts.publishAudio) await page.evaluate(() => window.Ayureze!.enableMicrophone());
  if (opts.publishVideo) await page.evaluate(() => window.Ayureze!.enableCamera());
  return joined;
}

export async function joinAsPatient(
  page: Page,
  seeded: SeededTenant,
  sessionId: string,
  opts: JoinOpts = {},
): Promise<{ id: string; room: string }> {
  await page.evaluate(
    ([tenant, email, password]) => window.Ayureze!.authenticate(tenant, email, password),
    [seeded.tenant, seeded.patientEmail, seeded.password],
  );
  const joined = await page.evaluate((sid) => window.Ayureze!.joinSession(sid), sessionId);
  if (opts.publishAudio) await page.evaluate(() => window.Ayureze!.enableMicrophone());
  if (opts.publishVideo) await page.evaluate(() => window.Ayureze!.enableCamera());
  return joined;
}
