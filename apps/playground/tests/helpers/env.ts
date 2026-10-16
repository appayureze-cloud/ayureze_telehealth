import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = dirname(fileURLToPath(import.meta.url));

/** Minimal .env parser — avoids pulling in a dependency for KEY=VALUE lines. */
export function loadRootEnv(): Record<string, string> {
  const path = resolve(currentDir, "../../../../.env");
  const out: Record<string, string> = {};
  const text = readFileSync(path, "utf-8");
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    out[line.slice(0, eq)] = line.slice(eq + 1);
  }
  return out;
}
