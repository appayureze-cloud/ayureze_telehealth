import path from "node:path";
import { defineConfig } from "vite";

// Resolves @ayureze/telehealth-web directly to the real sdk/web TypeScript
// *source* (not a published/built package) so this harness always tests
// the actual SDK code under development, with zero build-step drift.
export default defineConfig({
  resolve: {
    alias: {
      "@ayureze/telehealth-web": path.resolve(__dirname, "../../sdk/web/src/index.ts"),
    },
  },
  // host: "127.0.0.1" is required, not cosmetic: without it Vite binds
  // whatever "localhost" resolves to on the runner, which on GitHub
  // Actions' Ubuntu 24.04 image resolves to IPv6 (::1) — so the server was
  // actually up (logged "ready" in ~100ms) but playwright.config.ts's
  // webServer.url (explicit 127.0.0.1) could never connect to it, timing
  // out the full 90s regardless of how long the timeout is.
  server: { host: "127.0.0.1", port: 4174, strictPort: true },
  preview: { host: "127.0.0.1", port: 4174, strictPort: true },
});
