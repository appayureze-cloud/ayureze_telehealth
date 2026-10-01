import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

export interface SeededTenant {
  tenant: string;
  tenantId: string;
  doctorEmail: string;
  patientEmail: string;
  password: string;
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const API_DIR = path.resolve(__dirname, "../../../api");
const ROOT_DIR = path.resolve(__dirname, "../../../..");

/**
 * Seeds a fresh, uniquely-named tenant + doctor + patient directly via
 * `go run ./cmd/seed` (the same dev-seed command scripts/db-seed.sh uses)
 * against the real Postgres — no mocks, no direct DB writes from the test
 * itself. Unique per call so parallel/repeated test runs never collide on
 * an existing session between the same two users.
 */
export function seedTenant(label: string): SeededTenant {
  const suffix = randomUUID().slice(0, 8);
  const tenant = `e2ee-${label}-${suffix}`;
  const doctorEmail = `doctor-${suffix}@e2ee-test.local`;
  const patientEmail = `patient-${suffix}@e2ee-test.local`;
  const password = "dev-password-only-12345";

  const output = execFileSync("go", ["run", "./cmd/seed"], {
    cwd: API_DIR,
    env: {
      ...process.env,
      DATABASE_URL: `postgres://${env("POSTGRES_USER", "ayureze")}:${env("POSTGRES_PASSWORD")}@localhost:${env("POSTGRES_PORT", "5432")}/${env("POSTGRES_DB", "ayureze_telehealth")}?sslmode=disable`,
      SEED_TENANT_NAME: tenant,
      SEED_DOCTOR_EMAIL: doctorEmail,
      SEED_PATIENT_EMAIL: patientEmail,
      SEED_PASSWORD: password,
      ENVIRONMENT: "development",
    },
    stdio: "pipe",
  }).toString();

  // cmd/seed prints: Seeded tenant "name" (uuid)
  const tenantIdMatch = output.match(/Seeded tenant "[^"]+" \(([0-9a-f-]{36})\)/);
  if (!tenantIdMatch) {
    throw new Error(`could not parse tenant id from cmd/seed output:\n${output}`);
  }

  return { tenant, tenantId: tenantIdMatch[1], doctorEmail, patientEmail, password };
}

function env(key: string, fallback?: string): string {
  const fromEnv = process.env[key];
  if (fromEnv) return fromEnv;
  if (fallback !== undefined) return fallback;
  // Fall back to reading the repo-root .env directly (Playwright's
  // webServer/test process doesn't source it automatically).
  const envPath = path.join(ROOT_DIR, ".env");
  const content = readFileSync(envPath, "utf-8");
  const match = content.match(new RegExp(`^${key}=(.*)$`, "m"));
  if (!match) throw new Error(`${key} not found in ${envPath}`);
  return match[1];
}
