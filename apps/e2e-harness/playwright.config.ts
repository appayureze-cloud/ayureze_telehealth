import { defineConfig } from "@playwright/test";

// Real cross-platform E2EE acceptance tests — see docs/e2ee/VALIDATION.md.
// Runs the ACTUAL sdk/web source against the real docker-compose stack
// (Go API, LiveKit, Postgres, Redis). No mocked LiveKit or Go API here —
// mocks belong only in sdk/web's own unit tests (vitest).
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4174",
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || "/opt/pw-browsers/chromium",
      args: [
        // Chromium's synthetic camera (moving test pattern) + tone
        // generator, so real WebRTC media capture/encode/E2EE-encrypt/
        // transport/decrypt/decode happens without physical hardware.
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:4174",
    reuseExistingServer: true,
    // 30s wasn't enough on this job's first real CI run (ci.yml's
    // e2ee-harness job, gated behind go/python/web passing, had never
    // completed a full run before) — Playwright reported a plain timeout,
    // no crash. A local cold `vite` start here took ~1-2s, so the CI
    // runner's slower disk/CPU closing the gap to 30s is the most likely
    // explanation, but that's not fully confirmed. Bumped to 90s for
    // headroom, and piping stdout/stderr below so a repeat failure shows
    // vite's actual output in the job log instead of nothing.
    timeout: 90_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
