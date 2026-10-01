import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    launchOptions: {
      // See apps/e2e-harness/playwright.config.ts's comment: no hardcoded
      // fallback path here — that's one specific sandbox's own Chromium
      // location, not something `playwright install` sets up elsewhere.
      ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}),
      args: [
        // Chromium's built-in synthetic camera (moving test pattern) + mic
        // (a tone), so WebRTC media flows without real hardware/a display.
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
  },
  webServer: {
    command: "npm run preview",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
