// One-off investigation driver — NOT part of the permanent test suite.
// Drives minimal-repro.html (raw livekit-client, zero AyurEze code) as the
// Web-side participant of the "minimal reproduction independent of
// AyurEze business logic" experiment. See docs/e2ee/VALIDATION.md.
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));

const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || "/opt/pw-browsers/chromium",
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
});
const page = await browser.newPage();
page.on("console", (msg) => {
  if (msg.type() === "error" || msg.text().includes("minimal-e2ee-error")) {
    console.log("[browser]", msg.text());
  }
});

await page.goto("http://127.0.0.1:4174/minimal-repro.html");
await page.waitForFunction(() => window.Minimal !== undefined, { timeout: 10000 });

await page.evaluate(
  async ({ livekitUrl, token, room, keyB64 }) => {
    await window.Minimal.connect(livekitUrl, token, room, keyB64);
  },
  { livekitUrl: cfg.livekit_url, token: cfg.web_token, room: cfg.room, keyB64: cfg.key_b64 },
);

// Let frames accumulate for a few seconds so decrypt attempts happen.
await page.waitForTimeout(8000);

const diagnostics = await page.evaluate(() => window.Minimal.getDiagnostics());
console.log("MINIMAL-REPRO-DIAGNOSTICS:", JSON.stringify(diagnostics));

await page.evaluate(async () => {
  await window.Minimal.disconnect();
});
await browser.close();
