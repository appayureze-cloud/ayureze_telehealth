import {
  ConnectionState as LKConnectionState,
  type CryptorError,
  DataPacket_Kind,
  ExternalE2EEKeyProvider,
  RemoteTrack,
  RemoteTrackPublication,
  Room,
  RoomEvent,
  Track,
  type LocalParticipant,
  type Participant,
  type RemoteParticipant,
} from "livekit-client";

import { ApiClient, type AuthResult } from "./apiClient";
import { ConnectionError, NotInitializedError } from "./exceptions";
import {
  type AyurezeCaption,
  type AyurezeConnectionState,
  type AyurezeEncryptionDiagnostics,
  type AyurezeEncryptionError,
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
  private readonly encryptionErrorListeners = new Set<(e: AyurezeEncryptionError) => void>();

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

    // IMPORTANT — see docs/e2ee/VALIDATION.md's key-derivation finding
    // before changing this.
    //
    // 1. Input bytes: ExternalE2EEKeyProvider.setKey(string) UTF-8-encodes
    //    the string then runs PBKDF2 (salt "LKFrameEncryptionKey", 100000
    //    iterations, SHA-256) over those bytes. We pass the base64 *text*
    //    itself (pure ASCII, so UTF-8-encoding it is lossless) — the
    //    native/Flutter side must do the same (feed the base64 text's raw
    //    bytes into its shared_key, not the base64-decoded bytes) or the
    //    two platforms derive unrelated keys from the same secret.
    //
    // 2. Key size: do NOT pass `keySize`. The native SDKs' key derivation
    //    (ParticipantKeyHandler::SetKeyFromMaterial, in LiveKit's WebRTC
    //    fork's api/crypto/frame_crypto_transformer.h) hardcodes a
    //    128-bit derived key with no configuration knob to change it —
    //    confirmed by reading that source directly. This SDK's own
    //    ExternalE2EEKeyProvider defaults to `keySize: 128` for exactly
    //    this reason ("recommended for maximum compatibility across
    //    SDKs" per its setKey() doc comment). An earlier version of this
    //    client explicitly overrode that default to 256, which silently
    //    produced a native-incompatible AES-256-GCM key while native
    //    always derives AES-128-GCM — a structural mismatch that alone
    //    guarantees "InvalidKey: Decryption failed: OperationError"
    //    regardless of whether the KDF input bytes match. Leave this at
    //    the SDK default.
    //
    // See apps/e2e-harness/tests/kdf-compat.spec.ts for the real,
    // end-to-end verification of both fixes above (actual encrypted audio
    // crossing the Web<->native boundary, not just matching derived-key
    // bytes in isolation).
    const keyProvider = new ExternalE2EEKeyProvider();
    await keyProvider.setKey(joinResult.e2eeKeyBase64);

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

    // CRITICAL — found via real cross-browser testing
    // (apps/e2e-harness/tests/web-web-e2ee.spec.ts), not by inspection:
    // passing `e2ee: { keyProvider, worker }` to the Room constructor
    // only wires up the *decryption* path for incoming tracks — it does
    // NOT itself mark this participant's own outgoing tracks as
    // encrypted. That requires an explicit `room.setE2EEEnabled(true)`
    // call (LiveKit's own public API for this, see
    // LocalParticipant.setE2EEEnabled). Without it, this SDK was
    // publishing every local track as `encryption: NONE` — real,
    // unencrypted media — while still claiming "E2EE is on by default,
    // no way to join without it." LiveKit's own diagnostics
    // (Participant.isEncrypted, backed by server-reported track
    // metadata, not client-side state) caught this: both sides reported
    // isEncrypted:false with zero EncryptionErrors, because nothing was
    // ever actually encrypted, so nothing ever failed to decrypt either.
    //
    // FAIL-CLOSED REQUIREMENT: a call must never silently downgrade to
    // plaintext. `room.setE2EEEnabled(true)` throws synchronously if e2ee
    // wasn't configured on the Room at all (e.g. an unsupported browser),
    // which already fails closed — but its resolution does NOT itself
    // guarantee encryption is confirmed active: `room.isE2EEEnabled` is
    // only flipped by an async `ParticipantEncryptionStatusChanged` event
    // fired once the E2EE worker acknowledges the enable message, which
    // this call does not wait for. Without an explicit wait+verify step
    // here, a slow/failed worker handshake could leave this method
    // returning "success" while the room is not actually confirmed
    // encrypted — exactly the same class of silent-plaintext bug as the
    // missing setE2EEEnabled() call above, just at a different layer. So:
    // enable, then wait for confirmation, then verify; disconnect and
    // throw rather than return on any failure of that chain.
    try {
      await room.setE2EEEnabled(true);
      const confirmed = await waitForE2EEConfirmed(room, 8000);
      if (!confirmed) {
        throw new Error("E2EE was not confirmed active within 8s");
      }
    } catch (e) {
      await room.disconnect();
      this.room = null;
      throw new ConnectionError(`Secure connection could not be established. Please retry. (${String(e)})`);
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

  /**
   * Synchronous, technically-meaningful E2EE status — backed by LiveKit's
   * own `Room.isE2EEEnabled` and per-participant `Participant.isEncrypted`
   * (each true only once that participant has an active encrypted track),
   * never by "did we call setKey()". A UI that shows "E2EE: ON" should
   * read this, not just whether `joinSession()` resolved.
   */
  getEncryptionDiagnostics(): AyurezeEncryptionDiagnostics {
    const room = this.room;
    if (!room) return { e2eeEnabledForRoom: false, participants: [] };
    const participants: AyurezeEncryptionDiagnostics["participants"] = [];
    if (room.localParticipant) {
      participants.push({
        identity: room.localParticipant.identity,
        isLocal: true,
        isEncrypted: room.localParticipant.isEncrypted,
      });
    }
    for (const p of room.remoteParticipants.values()) {
      participants.push({ identity: p.identity, isLocal: false, isEncrypted: p.isEncrypted });
    }
    return { e2eeEnabledForRoom: room.isE2EEEnabled, participants };
  }

  onCaption(listener: (caption: AyurezeCaption) => void): () => void {
    this.captionListeners.add(listener);
    return () => this.captionListeners.delete(listener);
  }

  /**
   * Fires on every LiveKit frame-decryption failure (wrong/incompatible
   * key, missing key, or an internal cryptor error) for any participant in
   * the room — see {@link AyurezeEncryptionError}.
   */
  onEncryptionError(listener: (error: AyurezeEncryptionError) => void): () => void {
    this.encryptionErrorListeners.add(listener);
    return () => this.encryptionErrorListeners.delete(listener);
  }

  /**
   * Auto-attaches subscribed remote audio/video tracks to the given media
   * elements (decrypted output, since LiveKit decrypts in the E2EE worker
   * before handing off to the media pipeline) — the common boilerplate
   * every consuming app needs to actually render a call. Returns an
   * unsubscribe function.
   */
  attachRemoteMedia(elements: { video?: HTMLVideoElement; audio?: HTMLAudioElement }): () => void {
    const onSubscribed = (track: RemoteTrack, _pub: RemoteTrackPublication, _participant: RemoteParticipant) => {
      if (track.kind === Track.Kind.Video && elements.video) track.attach(elements.video);
      if (track.kind === Track.Kind.Audio && elements.audio) track.attach(elements.audio);
    };
    const onUnsubscribed = (track: RemoteTrack) => track.detach();
    const room = this.room;
    if (!room) return () => {};
    room.on(RoomEvent.TrackSubscribed, onSubscribed).on(RoomEvent.TrackUnsubscribed, onUnsubscribed);
    return () => {
      room.off(RoomEvent.TrackSubscribed, onSubscribed).off(RoomEvent.TrackUnsubscribed, onUnsubscribed);
    };
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
      .on(RoomEvent.EncryptionError, (error: Error | CryptorError, participant?: Participant) => {
        const reasonMap: Record<number, AyurezeEncryptionError["reason"]> = {
          0: "invalid_key",
          1: "missing_key",
          2: "internal_error",
        };
        const reason = "reason" in error ? (reasonMap[error.reason] ?? "internal_error") : "internal_error";
        for (const listener of this.encryptionErrorListeners) {
          listener({
            reason,
            participantIdentity: participant?.identity,
            message: error.message ?? String(error),
          });
        }
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

/**
 * Resolves true once `room.isE2EEEnabled` is confirmed (either already
 * true, or flipped true by a `RoomEvent.ParticipantEncryptionStatusChanged`
 * event for the local participant within `timeoutMs`), false on timeout.
 * Exists because `Room.setE2EEEnabled()` resolving does not itself
 * guarantee the E2EE worker has acknowledged the enable message — see the
 * fail-closed comment in `joinSession()`.
 */
function waitForE2EEConfirmed(room: Room, timeoutMs: number): Promise<boolean> {
  if (room.isE2EEEnabled) return Promise.resolve(true);
  return new Promise((resolve) => {
    const onChange = (enabled: boolean, participant?: Participant) => {
      if (participant?.isLocal && enabled) {
        cleanup();
        resolve(true);
      }
    };
    const timer = setTimeout(() => {
      cleanup();
      resolve(false);
    }, timeoutMs);
    const cleanup = () => {
      clearTimeout(timer);
      room.off(RoomEvent.ParticipantEncryptionStatusChanged, onChange);
    };
    room.on(RoomEvent.ParticipantEncryptionStatusChanged, onChange);
  });
}
