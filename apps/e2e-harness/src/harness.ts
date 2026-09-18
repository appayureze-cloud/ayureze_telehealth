import { AyurezeTelehealthClient } from "@ayureze/telehealth-web";
import type {
  AyurezeEncryptionDiagnostics,
  AyurezeEncryptionError,
  AyurezeParticipant,
  AyurezeSessionState,
} from "@ayureze/telehealth-web";

// Exposes a window-level driver so Playwright can operate the REAL Web SDK
// (imported as actual TS source, not a mock — see vite.config.ts) from
// outside the page context. One harness instance = one participant.
export interface AyurezeHarness {
  client: AyurezeTelehealthClient;
  encryptionErrors: AyurezeEncryptionError[];
  initialize(apiBaseUrl: string, livekitUrl: string): void;
  authenticate(tenant: string, email: string, password: string): Promise<unknown>;
  createSession(patientEmail: string): Promise<AyurezeSessionState>;
  joinSession(sessionId: string): Promise<AyurezeSessionState>;
  leaveSession(): Promise<void>;
  endSession(): Promise<AyurezeSessionState>;
  enableMicrophone(): Promise<void>;
  enableCamera(): Promise<void>;
  enableAITranslation(): Promise<void>;
  disableAITranslation(): Promise<void>;
  getConnectionState(): string;
  getParticipants(): AyurezeParticipant[];
  getEncryptionDiagnostics(): AyurezeEncryptionDiagnostics;
  getEncryptionErrors(): AyurezeEncryptionError[];
  getRemoteMediaStats(): Promise<{ audioBytesReceived: number; videoBytesReceived: number }>;
}

declare global {
  interface Window {
    Ayureze?: AyurezeHarness;
  }
}

function makeHarness(): AyurezeHarness {
  let client: AyurezeTelehealthClient | null = null;
  const encryptionErrors: AyurezeEncryptionError[] = [];
  let detachMedia: (() => void) | null = null;

  const ensure = () => {
    if (!client) throw new Error("call initialize() first");
    return client;
  };

  return {
    get client() {
      return ensure();
    },
    encryptionErrors,
    initialize(apiBaseUrl: string, livekitUrl: string) {
      client = new AyurezeTelehealthClient({ apiBaseUrl, livekitUrl });
      client.onEncryptionError((e) => {
        encryptionErrors.push(e);
        // eslint-disable-next-line no-console
        console.error("[ayureze-e2ee-error]", JSON.stringify(e));
      });
    },
    async authenticate(tenant, email, password) {
      await ensure().initialize();
      return ensure().authenticate(tenant, email, password);
    },
    async createSession(patientEmail) {
      return ensure().createSession(patientEmail);
    },
    async joinSession(sessionId) {
      // The real bundler-specific Worker instantiation this SDK requires —
      // see sdk/web/README.md.
      const e2eeWorker = new Worker(new URL("livekit-client/e2ee-worker", import.meta.url), {
        type: "module",
      });
      const result = await ensure().joinSession(sessionId, { e2eeWorker });
      detachMedia?.();
      detachMedia = ensure().attachRemoteMedia({
        video: document.getElementById("remote-video") as HTMLVideoElement,
        audio: document.getElementById("remote-audio") as HTMLAudioElement,
      });
      return result;
    },
    async leaveSession() {
      detachMedia?.();
      detachMedia = null;
      await ensure().leaveSession();
    },
    async endSession() {
      return ensure().endSession();
    },
    async enableMicrophone() {
      await ensure().enableMicrophone();
    },
    async enableCamera() {
      await ensure().enableCamera();
    },
    async enableAITranslation() {
      await ensure().enableAITranslation();
    },
    async disableAITranslation() {
      await ensure().disableAITranslation();
    },
    getConnectionState() {
      return ensure().getConnectionState();
    },
    getParticipants() {
      return ensure().getParticipants();
    },
    getEncryptionDiagnostics() {
      return ensure().getEncryptionDiagnostics();
    },
    getEncryptionErrors() {
      return encryptionErrors;
    },
    async getRemoteMediaStats() {
      // Ground-truth proof that media is actually flowing over the wire
      // (not just that the SDK's abstractions say so): raw WebRTC receiver
      // stats. Reaches into the underlying Room's peer connections, which
      // is legitimate for a validation harness even though the SDK itself
      // doesn't expose this (apps shouldn't normally need it).
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const room = (ensure() as any).room;
      let audioBytesReceived = 0;
      let videoBytesReceived = 0;
      if (!room) return { audioBytesReceived, videoBytesReceived };
      for (const participant of room.remoteParticipants.values()) {
        for (const pub of participant.trackPublications.values()) {
          const track = pub.track;
          if (!track?.receiver) continue;
          const stats: RTCStatsReport = await track.receiver.getStats();
          stats.forEach((report) => {
            if (report.type === "inbound-rtp") {
              if (report.kind === "audio") audioBytesReceived += report.bytesReceived ?? 0;
              if (report.kind === "video") videoBytesReceived += report.bytesReceived ?? 0;
            }
          });
        }
      }
      return { audioBytesReceived, videoBytesReceived };
    },
  };
}

window.Ayureze = makeHarness();
document.getElementById("status")!.textContent = "ready";
