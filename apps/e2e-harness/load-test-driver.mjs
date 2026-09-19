// One-off load test driver — NOT part of the permanent suite. Spins up N
// concurrent real doctor+patient session pairs (real Go API, real
// LiveKit, real E2EE, audio-only to keep per-session CPU cost down),
// measures join success rate and join latency. Container CPU/RAM is
// sampled externally via `docker stats` by the caller. See
// docs/deployment/load-testing.md for results — this script produces raw
// data, not a target number decided in advance.
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const API_BASE = "http://localhost:8080";
const LIVEKIT_URL = "ws://localhost:7880";
const N = parseInt(process.argv[2] || "1", 10);

function seedTenant(label) {
  const suffix = Math.random().toString(36).slice(2, 10);
  const tenant = `load-${label}-${suffix}`;
  const doctorEmail = `doctor-${suffix}@load-test.local`;
  const patientEmail = `patient-${suffix}@load-test.local`;
  const password = "load-test-password-12345";
  const apiDir = path.resolve(__dirname, "../api");
  const out = execFileSync("go", ["run", "./cmd/seed"], {
    cwd: apiDir,
    env: {
      ...process.env,
      SEED_TENANT_NAME: tenant,
      SEED_DOCTOR_EMAIL: doctorEmail,
      SEED_PATIENT_EMAIL: patientEmail,
      SEED_PASSWORD: password,
      ENVIRONMENT: "development",
    },
  }).toString();
  const m = out.match(/Seeded tenant "[^"]+" \(([0-9a-f-]{36})\)/);
  if (!m) throw new Error(`seed failed: ${out}`);
  return { tenant, doctorEmail, patientEmail, password };
}

async function runOnePair(browser, idx) {
  const t0 = Date.now();
  const { tenant, doctorEmail, patientEmail, password } = seedTenant(String(idx));
  const seedMs = Date.now() - t0;

  const doctorPage = await browser.newPage();
  const patientPage = await browser.newPage();
  try {
    await doctorPage.goto("http://127.0.0.1:4174/index.html");
    await patientPage.goto("http://127.0.0.1:4174/index.html");
    await doctorPage.waitForFunction(() => window.Ayureze !== undefined);
    await patientPage.waitForFunction(() => window.Ayureze !== undefined);

    await doctorPage.evaluate(({ a, l }) => window.Ayureze.initialize(a, l), { a: API_BASE, l: LIVEKIT_URL });
    await patientPage.evaluate(({ a, l }) => window.Ayureze.initialize(a, l), { a: API_BASE, l: LIVEKIT_URL });

    await doctorPage.evaluate(({ tenant, email, password }) => window.Ayureze.authenticate(tenant, email, password), {
      tenant, email: doctorEmail, password,
    });
    await patientPage.evaluate(({ tenant, email, password }) => window.Ayureze.authenticate(tenant, email, password), {
      tenant, email: patientEmail, password,
    });

    const tSession = Date.now();
    const session = await doctorPage.evaluate((e) => window.Ayureze.createSession(e), patientEmail);

    const tJoin = Date.now();
    await doctorPage.evaluate((sid) => window.Ayureze.joinSession(sid), session.id);
    await patientPage.evaluate((sid) => window.Ayureze.joinSession(sid), session.id);
    const joinMs = Date.now() - tJoin;

    await doctorPage.evaluate(() => window.Ayureze.enableMicrophone());
    await patientPage.evaluate(() => window.Ayureze.enableMicrophone());

    await doctorPage.waitForTimeout(4000);

    const diag = await doctorPage.evaluate(() => window.Ayureze.getEncryptionDiagnostics());
    const stats = await doctorPage.evaluate(() => window.Ayureze.getRemoteMediaStats());

    await doctorPage.evaluate(() => window.Ayureze.leaveSession());
    await patientPage.evaluate(() => window.Ayureze.leaveSession());

    return {
      idx, ok: true, seedMs, joinMs, totalMs: Date.now() - t0,
      encrypted: diag.participants.every((p) => p.isEncrypted),
      audioBytesReceived: stats.audioBytesReceived,
    };
  } catch (e) {
    return { idx, ok: false, error: String(e).slice(0, 200), totalMs: Date.now() - t0 };
  } finally {
    await doctorPage.close().catch(() => {});
    await patientPage.close().catch(() => {});
  }
}

const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || "/opt/pw-browsers/chromium",
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
});

const results = await Promise.all(Array.from({ length: N }, (_, i) => runOnePair(browser, i)));
await browser.close();

const ok = results.filter((r) => r.ok);
const failed = results.filter((r) => !r.ok);
console.log("LOAD-TEST-RESULT:", JSON.stringify({
  n: N,
  succeeded: ok.length,
  failed: failed.length,
  errors: failed.map((f) => f.error),
  avgJoinMs: ok.length ? Math.round(ok.reduce((s, r) => s + r.joinMs, 0) / ok.length) : null,
  maxJoinMs: ok.length ? Math.max(...ok.map((r) => r.joinMs)) : null,
  avgTotalMs: ok.length ? Math.round(ok.reduce((s, r) => s + r.totalMs, 0) / ok.length) : null,
  allEncrypted: ok.every((r) => r.encrypted),
  allReceivedAudio: ok.every((r) => r.audioBytesReceived > 0),
}));
