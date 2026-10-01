import { Room, RoomEvent, ConnectionState, RemoteTrack, RemoteParticipant, Track } from "livekit-client";

// Manual/automated test client. Not a product surface — see apps/playground
// README and docs/deployment/local-development.md. Reads role/room/identity
// from the URL query string so a single build serves both the "patient" and
// "doctor" side of a Day 2 connectivity test.

const params = new URLSearchParams(window.location.search);
const role = (params.get("role") ?? "patient") as "patient" | "doctor";
const room = params.get("room") ?? "dev-room";
const identity = params.get("identity") ?? `${role}-${Math.random().toString(36).slice(2, 8)}`;
const displayName = params.get("name") ?? identity;
const apiUrl = params.get("apiUrl") ?? "http://localhost:8080";
const livekitUrl = params.get("livekitUrl") ?? "ws://localhost:7880";
const autoconnect = params.get("autoconnect") !== "false";
// Allows tests to inject a pre-minted (e.g. expired/tampered) token instead
// of fetching a fresh one from the API, to exercise rejection paths.
const overrideToken = params.get("token");

const statusEl = document.getElementById("status")!;
const videosEl = document.getElementById("videos")!;
document.getElementById("title")!.textContent = `AyurEze Playground — ${role} (${identity}) in ${room}`;

type State = {
  phase: "idle" | "fetching_token" | "connecting" | "connected" | "disconnected" | "reconnecting" | "failed";
  error: string | null;
  connectionState: string;
  remoteParticipants: string[];
  localTracksPublished: string[];
  remoteTracksSubscribed: string[];
};

const state: State = {
  phase: "idle",
  error: null,
  connectionState: "disconnected",
  remoteParticipants: [],
  remoteTracksSubscribed: [],
  localTracksPublished: [],
};

function render() {
  statusEl.textContent = JSON.stringify(state, null, 2);
}

async function fetchToken(): Promise<string> {
  if (overrideToken) return overrideToken;
  const res = await fetch(`${apiUrl}/v1/dev/session-tokens`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room, identity, display_name: displayName, role }),
  });
  if (!res.ok) {
    throw new Error(`token request failed: ${res.status} ${await res.text()}`);
  }
  const data = await res.json();
  return data.access_token as string;
}

const lkRoom = new Room({ adaptiveStream: false, dynacast: false });

function attachTrack(track: RemoteTrack, participant: RemoteParticipant) {
  if (track.kind !== Track.Kind.Video && track.kind !== Track.Kind.Audio) return;
  const el = track.attach();
  el.id = `track-${participant.identity}-${track.sid}`;
  el.setAttribute("data-participant", participant.identity);
  el.setAttribute("data-kind", track.kind);
  const tile = document.createElement("div");
  tile.className = "tile";
  tile.appendChild(el);
  const label = document.createElement("div");
  label.textContent = `${participant.identity} (${track.kind})`;
  tile.appendChild(label);
  videosEl.appendChild(tile);
}

function refreshParticipants() {
  state.remoteParticipants = Array.from(lkRoom.remoteParticipants.values()).map((p) => p.identity);
  render();
}

lkRoom
  .on(RoomEvent.ConnectionStateChanged, (cs: ConnectionState) => {
    state.connectionState = cs;
    render();
  })
  .on(RoomEvent.ParticipantConnected, () => refreshParticipants())
  .on(RoomEvent.ParticipantDisconnected, () => refreshParticipants())
  .on(RoomEvent.TrackSubscribed, (track, _pub, participant) => {
    state.remoteTracksSubscribed.push(`${participant.identity}:${track.kind}`);
    attachTrack(track, participant);
    render();
  })
  .on(RoomEvent.Disconnected, (reason) => {
    state.phase = "disconnected";
    state.error = reason ? String(reason) : null;
    render();
  })
  .on(RoomEvent.Reconnecting, () => {
    state.phase = "reconnecting";
    render();
  })
  .on(RoomEvent.Reconnected, () => {
    state.phase = "connected";
    render();
  });

async function connect() {
  state.phase = "fetching_token";
  state.error = null;
  render();
  try {
    const token = await fetchToken();
    state.phase = "connecting";
    render();
    await lkRoom.connect(livekitUrl, token);
    await lkRoom.localParticipant.setCameraEnabled(true);
    await lkRoom.localParticipant.setMicrophoneEnabled(true);
    state.localTracksPublished = Array.from(lkRoom.localParticipant.trackPublications.values()).map(
      (p) => p.kind as string,
    );
    state.phase = "connected";
    refreshParticipants();
  } catch (err) {
    state.phase = "failed";
    state.error = err instanceof Error ? err.message : String(err);
    render();
    throw err;
  }
}

async function disconnect() {
  await lkRoom.disconnect();
  state.phase = "disconnected";
  render();
}

// Exposed for Playwright-driven E2E tests (scripts under apps/playground/tests).
(window as any).__ayureze = {
  connect,
  disconnect,
  getState: () => state,
  room: lkRoom,
};

render();
if (autoconnect) {
  connect().catch(() => {
    /* surfaced via state.error / state.phase for tests to observe */
  });
}
