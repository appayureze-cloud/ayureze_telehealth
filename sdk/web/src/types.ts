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
