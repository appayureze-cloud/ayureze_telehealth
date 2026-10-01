/**
 * Public data models returned by AyurezeTelehealthClient. Kept free of any
 * `livekit-client` types so consuming apps never need to import that
 * package directly.
 */

export type AyurezeUserRole = "patient" | "doctor" | "admin";

export function userRoleFromString(value: string): AyurezeUserRole {
  return value === "doctor" || value === "admin" ? value : "patient";
}

export interface AyurezeUser {
  id: string;
  email: string;
  role: AyurezeUserRole;
  displayName: string;
}

export type AyurezeSessionStatus = "created" | "active" | "ended";

export function sessionStatusFromString(value: string): AyurezeSessionStatus {
  return value === "active" || value === "ended" ? value : "created";
}

export interface AyurezeSessionState {
  id: string;
  room: string;
  status: AyurezeSessionStatus;
  aiTranslationAuthorized: boolean;
}

export type AyurezeConnectionState = "disconnected" | "connecting" | "connected" | "reconnecting";

export type AyurezeParticipantRole = "patient" | "doctor" | "ai_agent" | "unknown";

export function participantRoleFromAttribute(value: string | undefined): AyurezeParticipantRole {
  if (value === "patient" || value === "doctor" || value === "ai_agent") return value;
  return "unknown";
}

export interface AyurezeParticipant {
  identity: string;
  role: AyurezeParticipantRole;
  audioEnabled: boolean;
  videoEnabled: boolean;
  isLocal: boolean;
}

/**
 * A LiveKit frame-decryption failure — e.g. an incompatible or wrong key
 * for a given participant. Surfaced so a consuming app's "E2EE: ON"
 * indicator can be backed by something more meaningful than a static
 * flag: an app should treat any of these as E2EE NOT actually working for
 * that participant, regardless of what `joinSession()` returned. See
 * `docs/e2ee/VALIDATION.md`.
 */
export type AyurezeEncryptionErrorReason = "invalid_key" | "missing_key" | "internal_error";

export interface AyurezeEncryptionError {
  reason: AyurezeEncryptionErrorReason;
  participantIdentity: string | undefined;
  message: string;
}

/**
 * Per-participant encryption diagnostics, queried synchronously. Backed by
 * LiveKit's own `Room.isE2EEEnabled` / `Participant.isEncrypted` — never
 * derived from application state alone.
 */
export interface AyurezeEncryptionDiagnostics {
  e2eeEnabledForRoom: boolean;
  participants: { identity: string; isLocal: boolean; isEncrypted: boolean }[];
}

/**
 * A live or translated caption delivered over the AI agent's data channel
 * (`ayureze.captions` topic — see apps/ai-agent/app/pipeline/streaming.py).
 */
export interface AyurezeCaption {
  speakerIdentity: string;
  sourceLanguage: string;
  targetLanguage: string;
  originalText: string;
  translatedText: string | null;
  blocked: boolean;
  timingsMs: Record<string, number>;
  at: Date;
}

export function captionFromJson(json: Record<string, unknown>): AyurezeCaption {
  const timingsRaw = (json.timings_ms as Record<string, number>) ?? {};
  return {
    speakerIdentity: (json.speaker_identity as string) ?? "",
    sourceLanguage: (json.source_lang as string) ?? "",
    targetLanguage: (json.target_lang as string) ?? "",
    originalText: (json.original_text as string) ?? "",
    translatedText: (json.translated_text as string | null) ?? null,
    blocked: (json.blocked as boolean) ?? false,
    timingsMs: { ...timingsRaw },
    at: new Date((((json.at as number) ?? 0) as number) * 1000),
  };
}
