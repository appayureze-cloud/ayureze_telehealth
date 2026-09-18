import {
  ConnectionState as LKConnectionState,
  DataPacket_Kind,
  ExternalE2EEKeyProvider,
  Room,
  RoomEvent,
  type LocalParticipant,
  type Participant,
} from "livekit-client";

import { ApiClient, type AuthResult } from "./apiClient";
import { ConnectionError, NotInitializedError } from "./exceptions";
import {
  type AyurezeCaption,
  type AyurezeConnectionState,
  type AyurezeParticipant,
  type AyurezeSessionState,
  type AyurezeUser,
  captionFromJson,
  participantRoleFromAttribute,
} from "./types";

export * from "./exceptions";
export * from "./types";
export type { AuthResult, JoinResult } from "./apiClient";

const CAPTIONS_TOPIC = "ayureze.captions";

export interface AyurezeTelehealthClientOptions {
  apiBaseUrl: string;
  livekitUrl: string;
  fetchImpl?: typeof fetch;
}

/**
 * Options for {@link AyurezeTelehealthClient.joinSession}. `e2eeWorker` is
 * required: LiveKit's Web E2EE implementation runs frame encryption in a
 * dedicated Worker, and how a Worker is instantiated is bundler-specific
 * (Vite's `new Worker(new URL(..., import.meta.url), { type: "module" })`,
 * webpack's `new Worker(new URL(...))`, etc.) — a headless library cannot
 * pick that for every consumer, so the caller supplies the Worker
 * instance. This SDK deliberately does not offer a way to join *without*
 * one: every session is encrypted, by default, with no silent downgrade
 * path. See README.md for exact snippets per bundler.
 */
export interface JoinSessionOptions {
  e2eeWorker: Worker;
}

function mapConnectionState(state: LKConnectionState): AyurezeConnectionState {
  switch (state) {
    case LKConnectionState.Connected:
      return "connected";
    case LKConnectionState.Connecting:
      return "connecting";
    case LKConnectionState.Reconnecting:
    case LKConnectionState.SignalReconnecting:
      return "reconnecting";
    default:
      return "disconnected";
  }
}

function toAyurezeParticipant(p: Participant, isLocal: boolean): AyurezeParticipant {
  return {
    identity: p.identity,
    role: participantRoleFromAttribute(p.attributes?.role),
    audioEnabled: p.isMicrophoneEnabled,
    videoEnabled: p.isCameraEnabled,
    isLocal,
  };
}

/**
 * Headless Web SDK for the AyurEze Patient and Doctor web apps. Wraps the
 * Go session API and LiveKit's Web client behind a single interface —
 * consuming apps never import `livekit-client` directly.
 */
export class AyurezeTelehealthClient {
  private readonly api: ApiClient;
  private readonly livekitUrl: string;

  private initialized = false;
  private auth: AuthResult | null = null;
  private sessionState: AyurezeSessionState | null = null;
  private room: Room | null = null;
  private preferredLanguageCode = "en";

  private readonly captionListeners = new Set<(c: AyurezeCaption) => void>();
  private readonly connectionStateListeners = new Set<(s: AyurezeConnectionState) => void>();

  constructor(options: AyurezeTelehealthClientOptions) {
    this.api = new ApiClient(options.apiBaseUrl, options.fetchImpl);
    this.livekitUrl = options.livekitUrl;
  }

  /** Must be called once before any other method. */
  async initialize(): Promise<void> {
    this.initialized = true;
  }

  async authenticate(tenant: string, email: string, password: string): Promise<AyurezeUser> {
    this.ensureInitialized();
    const result = await this.api.login(tenant, email, password);
    this.auth = result;
    return result.user;
  }

  /** Doctor/admin only — the Go API enforces this (see docs/security/README.md). */
  async createSession(patientEmail: string): Promise<AyurezeSessionState> {
    const auth = this.ensureAuthenticated();
    const session = await this.api.createSession(auth.accessToken, patientEmail);
    this.sessionState = session;
    return session;
  }

  /**
   * Joins the session's encrypted LiveKit room. Applies the session's
   * real E2EE key (delivered only in this call's response — see
   * docs/e2ee/README.md) via a `Worker`-backed key provider before
   * connecting, so SFrame encryption is active from the first published
   * frame. See {@link JoinSessionOptions} for why `e2eeWorker` is
   * required rather than optional.
   */
  async joinSession(sessionId: string, options: JoinSessionOptions): Promise<AyurezeSessionState> {
    const auth = this.ensureAuthenticated();
    const joinResult = await this.api.joinSession(auth.accessToken, sessionId);
    this.sessionState = joinResult.session;

    const keyProvider = new ExternalE2EEKeyProvider();
    // IMPORTANT: pass the raw key *bytes* (ArrayBuffer), not the base64
    // text. ExternalE2EEKeyProvider.setKey(string) runs PBKDF2 over the
    // string; setKey(ArrayBuffer) uses HKDF directly on the bytes — the
    // correct path for an already cryptographically-random key. The Go
    // API and Python AI agent both use the session's raw key bytes
    // directly (internal/e2ee; rtc.KeyProviderOptions(shared_key=...)),
    // so passing the base64 *text* here would derive a different, wrong
    // key and this client would fail to decrypt/encrypt compatibly with
    // the other participants.
    const rawKeyBytes = base64ToArrayBuffer(joinResult.e2eeKeyBase64);
    await keyProvider.setKey(rawKeyBytes);

    const room = new Room({
      adaptiveStream: true,
      dynacast: true,
      e2ee: { keyProvider, worker: options.e2eeWorker },
    });
    this.room = room;
    this.wireRoomListeners(room);

    try {
      await room.connect(this.livekitUrl, joinResult.livekitAccessToken);
    } catch (e) {
      this.room = null;
      throw new ConnectionError(`failed to connect to LiveKit room: ${String(e)}`);
    }

    return joinResult.session;
  }

  /** Disconnects from the room without ending the session for others. */
  async leaveSession(): Promise<void> {
    await this.room?.disconnect();
    this.room = null;
    this.emitConnectionState("disconnected");
  }

  /** Doctor/admin only — ends the session for everyone, including the AI agent. */
  async endSession(): Promise<AyurezeSessionState> {
    const auth = this.ensureAuthenticated();
    const sessionId = this.ensureSessionId();
    const session = await this.api.endSession(auth.accessToken, sessionId);
    this.sessionState = session;
    return session;
  }

  async enableMicrophone(): Promise<void> {
    await this.ensureRoom().localParticipant.setMicrophoneEnabled(true);
  }

  async disableMicrophone(): Promise<void> {
    await this.ensureRoom().localParticipant.setMicrophoneEnabled(false);
  }

  async enableCamera(): Promise<void> {
    await this.ensureRoom().localParticipant.setCameraEnabled(true);
  }

  async disableCamera(): Promise<void> {
    await this.ensureRoom().localParticipant.setCameraEnabled(false);
  }

  /**
   * Grants AI-translation consent. Does not by itself make the AI agent
   * join — it only makes the agent's own Go-API authorization check
   * (consent-gated) succeed the next time it's triggered. The platform
   * never activates AI translation without this explicit call.
   */
  async enableAITranslation(): Promise<void> {
    const auth = this.ensureAuthenticated();
    const sessionId = this.ensureSessionId();
    await this.api.grantAiTranslationConsent(auth.accessToken, sessionId);
  }

  /**
   * Revokes AI-translation consent. The Go API immediately requests
   * force-removal of the AI agent from the room if it's currently
   * connected, as part of this same call.
   */
  async disableAITranslation(): Promise<void> {
    const auth = this.ensureAuthenticated();
    const sessionId = this.ensureSessionId();
    await this.api.revokeAiTranslationConsent(auth.accessToken, sessionId);
  }

  /** ISO 639-1 code, e.g. "en" | "ta" | "ml". Informational today. */
  setLanguage(languageCode: string): void {
    this.preferredLanguageCode = languageCode;
  }

  get preferredLanguage(): string {
    return this.preferredLanguageCode;
  }

  getConnectionState(): AyurezeConnectionState {
    if (!this.room) return "disconnected";
    return mapConnectionState(this.room.state);
  }

  getParticipants(): AyurezeParticipant[] {
    const room = this.room;
    if (!room) return [];
    const result: AyurezeParticipant[] = [];
    if (room.localParticipant) {
      result.push(toAyurezeParticipant(room.localParticipant as LocalParticipant, true));
    }
    for (const p of room.remoteParticipants.values()) {
      result.push(toAyurezeParticipant(p, false));
    }
    return result;
  }

  getSessionState(): AyurezeSessionState | null {
    return this.sessionState;
  }

  onCaption(listener: (caption: AyurezeCaption) => void): () => void {
    this.captionListeners.add(listener);
    return () => this.captionListeners.delete(listener);
  }

  onConnectionStateChange(listener: (state: AyurezeConnectionState) => void): () => void {
    this.connectionStateListeners.add(listener);
    return () => this.connectionStateListeners.delete(listener);
  }

  async dispose(): Promise<void> {
    await this.leaveSession();
    this.captionListeners.clear();
    this.connectionStateListeners.clear();
  }

  // -----------------------------------------------------------------
  // Internals
  // -----------------------------------------------------------------

  private wireRoomListeners(room: Room): void {
    room
      .on(RoomEvent.ConnectionStateChanged, (state: LKConnectionState) => {
        this.emitConnectionState(mapConnectionState(state));
      })
      .on(RoomEvent.DataReceived, (payload: Uint8Array, _participant?: Participant, _kind?: DataPacket_Kind, topic?: string) => {
        if (topic !== CAPTIONS_TOPIC) return;
        try {
          const json = JSON.parse(new TextDecoder().decode(payload)) as Record<string, unknown>;
          const caption = captionFromJson(json);
          for (const listener of this.captionListeners) listener(caption);
        } catch {
          // Malformed caption payload — drop it rather than throw inside
          // an event handler.
        }
      });
  }

  private emitConnectionState(state: AyurezeConnectionState): void {
    for (const listener of this.connectionStateListeners) listener(state);
  }

  private ensureInitialized(): void {
    if (!this.initialized) {
      throw new NotInitializedError("call initialize() before using the client");
    }
  }

  private ensureAuthenticated(): AuthResult {
    this.ensureInitialized();
    if (!this.auth) {
      throw new NotInitializedError("call authenticate() before this method");
    }
    return this.auth;
  }

  private ensureSessionId(): string {
    const id = this.sessionState?.id;
    if (!id) {
      throw new NotInitializedError("no active session — call createSession() or joinSession() first");
    }
    return id;
  }

  private ensureRoom(): Room {
    if (!this.room) {
      throw new ConnectionError("not connected to a session — call joinSession() first");
    }
    return this.room;
  }
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}
