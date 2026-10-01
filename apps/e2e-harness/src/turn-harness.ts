import { Room, RoomEvent, ExternalE2EEKeyProvider, type EncryptionError } from "livekit-client";

// TURN relay verification harness — deliberately independent of
// AyurezeTelehealthClient (which doesn't expose an rtcConfig/iceServers
// passthrough today) so this can force `iceTransportPolicy: 'relay'` and
// inspect the actual selected ICE candidate pair. Talks to livekit-client
// directly, using a token minted through the real Go API (see
// tests/turn-relay.spec.ts) and the SAME E2EE key-handling fix already
// verified in sdk/web/src/client.ts (no keySize override — see
// docs/e2ee/VALIDATION.md's "Fifth pass") so this also confirms E2EE
// stays active over a forced TURN relay path, not just that media flows.
//
// This file exists purely for docs/deployment/turn-verification.md's
// real-relay test; it is not wired into the AyurEze SDK build.
export interface TurnHarness {
  connect(
    livekitUrl: string,
    token: string,
    keyBase64: string,
    turnUrl: string,
    turnUsername: string,
    turnCredential: string,
    forceRelay: boolean,
    publishAudio: boolean,
  ): Promise<void>;
  disconnect(): Promise<void>;
  getDiagnostics(): Promise<{
    connectionState: string;
    isE2EEEnabled: boolean;
    participants: { identity: string; isLocal: boolean; isEncrypted: boolean }[];
    errors: { reason: string; participantIdentity?: string; message: string }[];
    audioBytesReceived: number;
    selectedCandidatePair: { localType?: string; remoteType?: string; transport?: string } | null;
  }>;
}

declare global {
  interface Window {
    TurnHarness?: TurnHarness;
  }
}

function makeHarness(): TurnHarness {
  let room: Room | null = null;
  const errors: { reason: string; participantIdentity?: string; message: string }[] = [];

  return {
    async connect(livekitUrl, token, keyBase64, turnUrl, turnUsername, turnCredential, forceRelay, publishAudio) {
      const worker = new Worker(new URL("livekit-client/e2ee-worker", import.meta.url), { type: "module" });
      const keyProvider = new ExternalE2EEKeyProvider();
      room = new Room({ e2ee: { keyProvider, worker } });

      room.on(RoomEvent.EncryptionError, (e: EncryptionError) => {
        errors.push({
          reason: (e as unknown as { reason?: string }).reason ?? "unknown",
          participantIdentity: (e as unknown as { participant?: { identity?: string } }).participant?.identity,
          message: String(e),
        });
      });

      await keyProvider.setKey(keyBase64);
      // IMPORTANT: rtcConfig belongs to ConnectOptions (room.connect()'s
      // 3rd argument), NOT RoomOptions (the Room constructor) — confirmed
      // by reading livekit-client's actual source
      // (RTCEngine.connect: `this.engine.rtcConfig = this.connOptions.rtcConfig`).
      // Passing it to the constructor instead is silently ignored: the
      // connection still succeeds via host/prflx candidates, giving a
      // false impression that relay-only mode was tested when it never
      // took effect at all.
      await room.connect(livekitUrl, token, {
        autoSubscribe: true,
        rtcConfig: {
          iceServers: [{ urls: turnUrl, username: turnUsername, credential: turnCredential }],
          iceTransportPolicy: forceRelay ? "relay" : "all",
        } as RTCConfiguration,
      });
      await room.setE2EEEnabled(true);

      const deadline = Date.now() + 8000;
      while (!room.isE2EEEnabled && Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 100));
      }

      // Publishing (and, on the other side, subscribing) is what actually
      // drives ICE connectivity checks for media — without a track there
      // is nothing for the RTCPeerConnection to need a working candidate
      // pair for, and `room.connect()`'s promise resolving only reflects
      // the signaling WebSocket, not the media path.
      if (publishAudio) {
        await room.localParticipant.setMicrophoneEnabled(true);
      }
    },
    async disconnect() {
      await room?.disconnect();
      room = null;
    },
    async getDiagnostics() {
      const participants: { identity: string; isLocal: boolean; isEncrypted: boolean }[] = [];
      let audioBytesReceived = 0;
      let selectedCandidatePair: { localType?: string; remoteType?: string; transport?: string } | null = null;

      if (room) {
        participants.push({ identity: room.localParticipant.identity, isLocal: true, isEncrypted: room.localParticipant.isEncrypted });

        // Local (publishing) side: inspect the sender's candidate pair too
        // — the publishing side's own PeerConnection is where "did TURN
        // actually carry my outgoing media" is answered, independent of
        // whether anyone is currently subscribing to it.
        for (const pub of room.localParticipant.trackPublications.values()) {
          const track = pub.track as unknown as { sender?: RTCRtpSender } | undefined;
          if (!track?.sender) continue;
          const stats: RTCStatsReport = await track.sender.getStats();
          const byId = new Map<string, any>();
          stats.forEach((report) => byId.set(report.id, report));
          stats.forEach((report) => {
            if (report.type === "candidate-pair" && (report.state === "succeeded" || report.selected)) {
              const local = byId.get(report.localCandidateId);
              const remote = byId.get(report.remoteCandidateId);
              selectedCandidatePair = {
                localType: local?.candidateType,
                remoteType: remote?.candidateType,
                transport: local?.protocol ?? remote?.protocol,
              };
            }
          });
        }

        for (const p of room.remoteParticipants.values()) {
          participants.push({ identity: p.identity, isLocal: false, isEncrypted: p.isEncrypted });
          for (const pub of p.trackPublications.values()) {
            const track = pub.track as unknown as { receiver?: RTCRtpReceiver } | undefined;
            if (!track?.receiver) continue;
            const stats: RTCStatsReport = await track.receiver.getStats();
            const byId = new Map<string, any>();
            stats.forEach((report) => byId.set(report.id, report));
            stats.forEach((report) => {
              if (report.type === "inbound-rtp" && report.kind === "audio") {
                audioBytesReceived += report.bytesReceived ?? 0;
              }
              if (report.type === "candidate-pair" && (report.state === "succeeded" || report.selected)) {
                const local = byId.get(report.localCandidateId);
                const remote = byId.get(report.remoteCandidateId);
                selectedCandidatePair = {
                  localType: local?.candidateType,
                  remoteType: remote?.candidateType,
                  transport: local?.protocol ?? remote?.protocol,
                };
              }
            });
          }
        }
      }
      return {
        connectionState: room?.state ?? "disconnected",
        isE2EEEnabled: room?.isE2EEEnabled ?? false,
        participants,
        errors,
        audioBytesReceived,
        selectedCandidatePair,
      };
    },
  };
}

window.TurnHarness = makeHarness();
document.getElementById("status")!.textContent = "ready";
