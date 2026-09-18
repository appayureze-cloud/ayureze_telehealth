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
  server: { port: 4174, strictPort: true },
  preview: { port: 4174, strictPort: true },
});
