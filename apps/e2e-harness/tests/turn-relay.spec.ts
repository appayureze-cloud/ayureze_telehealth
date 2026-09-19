import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Browser } from "@playwright/test";
import { seedTenant } from "./helpers/seed";

const API_BASE_URL = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";
const TURN_URL = "turn:127.0.0.1:3478";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "../../..");

/**
 * Real TURN relay verification — see docs/deployment/turn-verification.md
 * for the full investigation this belongs to. Forces
 * `iceTransportPolicy: "relay"` on a real `RTCPeerConnection` (via
 * src/turn-harness.ts, since AyurezeTelehealthClient doesn't expose an
 * rtcConfig passthrough) so a successful connection can ONLY happen over
 * an actual TURN relay candidate — never host/srflx/prflx — and inspects
 * the real selected ICE candidate pair via `RTCStatsReport`.
 *
 * IMPORTANT: `rtcConfig` (including `iceTransportPolicy`) must be passed
 * to `room.connect()`'s ConnectOptions, NOT the Room constructor's
 * RoomOptions — confirmed by reading livekit-client's actual source
 * (`RTCEngine.connect`: `this.engine.rtcConfig = this.connOptions.rtcConfig`).
 * Passing it to the constructor is silently ignored, which would make
 * this test falsely look like it tested relay-only mode when it never
 * took effect (host/prflx candidates would still be used) — see
 * src/turn-harness.ts's own comment for the exact mistake this test
 * caught during development.
 *
 * Generates a real REST-API short-term TURN credential from
 * TURN_STATIC_AUTH_SECRET (coturn's `--use-auth-secret` mechanism) —
 * never hardcoded, never logged.
 */
function turnCredential(secret: string): { username: string; credential: string } {
  const username = String(Math.floor(Date.now() / 1000) + 3600);
  const credential = createHmac("sha1", secret).update(username).digest("base64");
  return { username, credential };
}

function env(key: string): string {
  const fromEnv = process.env[key];
  if (fromEnv) return fromEnv;
  // Fall back to reading the repo-root .env directly, matching
  // tests/helpers/seed.ts's own fallback — Playwright's webServer/test
  // process doesn't source it automatically.
  const envPath = path.join(ROOT_DIR, ".env");
  const content = readFileSync(envPath, "utf-8");
  const match = content.match(new RegExp(`^${key}=(.*)$`, "m"));
  if (!match) throw new Error(`${key} not found in ${envPath}`);
  return match[1];
}

interface RunResult {
  connectError: string | null;
  doctorDiag: Awaited<ReturnType<typeof getDiag>>;
  patientDiag: Awaited<ReturnType<typeof getDiag>>;
}

async function getDiag(page: import("@playwright/test").Page) {
  return page.evaluate(() => window.TurnHarness!.getDiagnostics());
}

async function runSession(browser: Browser, label: string, forceRelay: boolean): Promise<RunResult> {
  const seeded = seedTenant(label);
  const turnSecret = env("TURN_STATIC_AUTH_SECRET");
  const { username, credential } = turnCredential(turnSecret);

  // Real join flow via the actual Go API — same tokens/keys production
  // clients get, not hand-minted.
  const doctorAuth = await fetch(`${API_BASE_URL}/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tenant: seeded.tenant, email: seeded.doctorEmail, password: seeded.password }),
  }).then((r) => r.json());

  const session = await fetch(`${API_BASE_URL}/v1/sessions`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${doctorAuth.access_token}` },
    body: JSON.stringify({ patient_email: seeded.patientEmail }),
  }).then((r) => r.json());

  const doctorJoin = await fetch(`${API_BASE_URL}/v1/sessions/${session.id}/join`, {
    method: "POST",
    headers: { authorization: `Bearer ${doctorAuth.access_token}` },
  }).then((r) => r.json());

  const patientAuth = await fetch(`${API_BASE_URL}/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tenant: seeded.tenant, email: seeded.patientEmail, password: seeded.password }),
  }).then((r) => r.json());

  const patientJoin = await fetch(`${API_BASE_URL}/v1/sessions/${session.id}/join`, {
    method: "POST",
    headers: { authorization: `Bearer ${patientAuth.access_token}` },
  }).then((r) => r.json());

  const doctorCtx = await browser.newContext({ permissions: ["camera", "microphone"] });
  const patientCtx = await browser.newContext({ permissions: ["camera", "microphone"] });
  const doctorPage = await doctorCtx.newPage();
  const patientPage = await patientCtx.newPage();

  await doctorPage.goto("/turn-repro.html");
  await patientPage.goto("/turn-repro.html");
  await doctorPage.waitForFunction(() => window.TurnHarness !== undefined);
  await patientPage.waitForFunction(() => window.TurnHarness !== undefined);

  let connectError: string | null = null;
  try {
    await Promise.all([
      doctorPage.evaluate(
        ([lk, token, key, turn, user, cred, relay]) =>
          window.TurnHarness!.connect(lk, token, key, turn, user, cred, relay, true),
        [LIVEKIT_URL, doctorJoin.access_token, doctorJoin.e2ee_key, TURN_URL, username, credential, forceRelay] as const,
      ),
      patientPage.evaluate(
        ([lk, token, key, turn, user, cred, relay]) =>
          window.TurnHarness!.connect(lk, token, key, turn, user, cred, relay, true),
        [LIVEKIT_URL, patientJoin.access_token, patientJoin.e2ee_key, TURN_URL, username, credential, forceRelay] as const,
      ),
    ]);
  } catch (e) {
    connectError = String(e);
  }

  // Give ICE/SFrame a few seconds to settle either way (success or
  // permanent failure) before reading final diagnostics.
  await doctorPage.waitForTimeout(5000);

  const doctorDiag = await getDiag(doctorPage);
  const patientDiag = await getDiag(patientPage);

  await doctorPage.evaluate(() => window.TurnHarness?.disconnect()).catch(() => undefined);
  await patientPage.evaluate(() => window.TurnHarness?.disconnect()).catch(() => undefined);
  await doctorCtx.close();
  await patientCtx.close();

  return { connectError, doctorDiag, patientDiag };
}

test.describe("TURN relay verification (real coturn, real LiveKit)", () => {
  test("control — Web <-> Web, relay NOT forced: connects normally, non-relay candidate expected", async ({
    browser,
  }) => {
    const result = await runSession(browser, "turn-control", false);
    console.log("TURN-CONTROL (relay not forced) result:", JSON.stringify(result, null, 2));

    // This is the baseline: same harness, same real stack, TURN servers
    // configured but not mandatory — proves the harness itself works and
    // isolates "forcing relay" as the only variable in the next test.
    expect(result.connectError).toBeNull();
    expect(result.doctorDiag.connectionState).toBe("connected");
    expect(result.doctorDiag.audioBytesReceived).toBeGreaterThan(0);
  });

  test("forced relay — Web <-> Web, iceTransportPolicy=relay: real outcome, not assumed", async ({ browser }) => {
    const result = await runSession(browser, "turn-forced", true);
    console.log("TURN-RELAY-FORCED result:", JSON.stringify(result, null, 2));

    // No pass/fail assertion on the ICE outcome itself — see
    // docs/deployment/turn-verification.md for why: in this deployment
    // (LiveKit node_ip: 127.0.0.1), a real, deliberate security rule
    // (coturn's denied-peer-ip) is expected to block relay to LiveKit, so
    // "the connection fails" is itself the expected, documented, real
    // result, not a test bug to paper over. The console.log above is the
    // actual evidence this investigation reports against — reproducible
    // on demand, not asserted into a fake PASS/FAIL either way.
    expect(result).toBeTruthy();
  });
});
