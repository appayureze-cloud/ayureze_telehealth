/**
 * Headless Web SDK for AyurEze Telehealth.
 *
 * This package deliberately does not re-export anything from
 * `livekit-client` — consuming apps interact only with these types.
 */
export {
  AyurezeTelehealthClient,
  type AyurezeTelehealthClientOptions,
  type JoinSessionOptions,
} from "./client";
export * from "./types";
export * from "./exceptions";
export type { AuthResult, JoinResult } from "./apiClient";
