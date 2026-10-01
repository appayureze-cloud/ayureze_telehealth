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
    // Root cause of the original 30s timeout (confirmed with stdout: "pipe"
    // below, added for exactly this diagnosis): Vite reported "ready" in
    // ~100ms and was genuinely listening — the health check itself could
    // never connect. Without an explicit host, Vite binds whatever
    // "localhost" resolves to, which on GitHub Actions' Ubuntu 24.04 image
    // is IPv6 (::1); this config's url is explicit IPv4 (127.0.0.1), so
    // every probe failed regardless of how long the timeout was. Fixed for
    // real in vite.config.ts (server/preview host: "127.0.0.1"). Left at
    // 60s rather than reverting to 30s as harmless extra headroom now that
    // the actual fix is elsewhere.
    timeout: 60_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
