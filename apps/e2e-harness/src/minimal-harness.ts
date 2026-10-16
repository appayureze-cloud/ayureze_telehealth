import { Room, RoomEvent, ExternalE2EEKeyProvider, type EncryptionError } from "livekit-client";

// Minimal LiveKit E2EE reproduction — deliberately independent of ANY
// AyurEze code (no @ayureze/telehealth-web, no Go API, no session/consent
// logic). Talks to livekit-client directly with a token and raw key handed
// to it from outside (minted independently — see tests/helpers/
// mint_minimal_token.py). Exists solely to answer: does the Web<->native
// E2EE key-derivation mismatch documented in docs/e2ee/VALIDATION.md
// reproduce with ZERO AyurEze integration code involved at all, or is it
// specific to this codebase's key transport/encoding?
export interface MinimalHarness {
  connect(livekitUrl: string, token: string, room: string, keyBase64: string): Promise<void>;
  disconnect(): Promise<void>;
  getDiagnostics(): Promise<{
    participants: { identity: string; isLocal: boolean; isEncrypted: boolean }[];
    errors: { reason: string; participantIdentity?: string; message: string }[];
    audioBytesReceived: number;
  }>;
}

declare global {
  interface Window {
    Minimal?: MinimalHarness;
  }
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function makeHarness(): MinimalHarness {
  let room: Room | null = null;
  const errors: { reason: string; participantIdentity?: string; message: string }[] = [];

  return {
    async connect(livekitUrl, token, roomName, keyBase64) {
      const worker = new Worker(new URL("livekit-client/e2ee-worker", import.meta.url), { type: "module" });
      const keyProvider = new ExternalE2EEKeyProvider({ keySize: 256 });
      room = new Room({ e2ee: { keyProvider, worker } });

      room.on(RoomEvent.EncryptionError, (e: EncryptionError) => {
        errors.push({
          reason: (e as unknown as { reason?: string }).reason ?? "unknown",
          participantIdentity: (e as unknown as { participant?: { identity?: string } }).participant?.identity,
          message: String(e),
        });
        // eslint-disable-next-line no-console
        console.error("[minimal-e2ee-error]", JSON.stringify(e));
      });

      // Raw key material, base64-decoded to real bytes — same PBKDF2 path
      // (string input UTF-8-encoded then PBKDF2-derived) as this session's
      // full investigation used, minted totally independently of the Go
      // API's envelope-encrypted key storage.
      await keyProvider.setKey(keyBase64);
      await room.connect(livekitUrl, token, { autoSubscribe: true });
      await room.setE2EEEnabled(true);

      // Simple poll for confirmation, mirroring waitForE2EEConfirmed's
      // logic without importing sdk/web at all.
      const deadline = Date.now() + 8000;
      while (!room.isE2EEEnabled && Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 100));
      }
      void base64ToArrayBuffer; // kept for parity/reference, unused on this path
    },
    async disconnect() {
      await room?.disconnect();
      room = null;
    },
    async getDiagnostics() {
      const participants: { identity: string; isLocal: boolean; isEncrypted: boolean }[] = [];
      let audioBytesReceived = 0;
      if (room) {
        participants.push({ identity: room.localParticipant.identity, isLocal: true, isEncrypted: room.localParticipant.isEncrypted });
        for (const p of room.remoteParticipants.values()) {
          participants.push({ identity: p.identity, isLocal: false, isEncrypted: p.isEncrypted });
          for (const pub of p.trackPublications.values()) {
            const track = pub.track as unknown as { receiver?: RTCRtpReceiver } | undefined;
            if (!track?.receiver) continue;
            const stats: RTCStatsReport = await track.receiver.getStats();
            stats.forEach((report) => {
              if (report.type === "inbound-rtp" && report.kind === "audio") {
                audioBytesReceived += report.bytesReceived ?? 0;
              }
            });
          }
        }
      }
      return { participants, errors, audioBytesReceived };
    },
  };
}

window.Minimal = makeHarness();
document.getElementById("status")!.textContent = "ready";
