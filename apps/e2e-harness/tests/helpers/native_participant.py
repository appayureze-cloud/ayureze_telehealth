#!/usr/bin/env python3
"""Real LiveKit participant using the native (Rust/C++ core) livekit SDK —
the same underlying frame-crypto engine flutter_webrtc uses (see
docs/e2ee/VALIDATION.md's key-derivation audit). Used two ways by the
Playwright E2EE tests:

  1. As a stand-in for a *second native-SDK client* (Flutter, in this
     sandbox where no Android emulator/device is available — see
     VALIDATION.md's "Flutter feasibility" section for why this is an
     honest, evidence-backed substitute for that specific narrow claim
     "does the Web SDK's key derivation match the native path", not a
     substitute for testing Flutter's own Dart code, UI, or permissions
     handling, which this script does not exercise).
  2. As the "doctor" or "patient" side of a real session, driven through
     the exact same Go API endpoints a real client uses (login, create,
     join) — never a shortcut/mocked token.

Usage:
  native_participant.py create-and-join --tenant T --doctor-email E --doctor-password P \
      --patient-email E2 --api-base-url URL --livekit-url URL --role doctor|patient \
      --duration-seconds 15 [--publish-audio] [--json]

  native_participant.py join --tenant T --email E --password P --session-id ID \
      --api-base-url URL --livekit-url URL --duration-seconds 15 [--publish-audio] [--json]

Prints newline-delimited JSON to stdout (flushed immediately, so a caller
can act on "ready" before this process's own duration-seconds sleep ends):
  {"event": "ready", "session_id": ..., "room": ..., "identity": ...}
  {"event": "done", "encryption_errors": [...], "published": true}
On any failure, prints {"event": "error", "error": "..."} and exits 1.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
import numpy as np
from livekit import rtc


async def api_login(client: httpx.AsyncClient, base_url: str, tenant: str, email: str, password: str) -> dict:
    resp = await client.post(f"{base_url}/v1/auth/login", json={"tenant": tenant, "email": email, "password": password})
    resp.raise_for_status()
    return resp.json()


async def api_create_session(client: httpx.AsyncClient, base_url: str, access_token: str, patient_email: str) -> dict:
    resp = await client.post(
        f"{base_url}/v1/sessions",
        json={"patient_email": patient_email},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json()


async def api_join_session(client: httpx.AsyncClient, base_url: str, access_token: str, session_id: str) -> dict:
    resp = await client.post(
        f"{base_url}/v1/sessions/{session_id}/join",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json()


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


async def run_participant(
    livekit_url: str,
    lk_access_token: str,
    e2ee_key_b64: str,
    duration_seconds: float,
    publish_audio: bool,
    ready_extra: dict,
) -> None:
    import base64

    # Matches apps/ai-agent/app/agent.py's real production behavior
    # exactly (base64.b64decode -> raw bytes) — this script exists to
    # test against production code paths, not a hypothesis. See
    # docs/e2ee/VALIDATION.md for the key-derivation investigation this
    # was used for.
    key_bytes = base64.b64decode(e2ee_key_b64)
    encryption_errors: list[dict] = []

    room = rtc.Room()

    @room.on("track_subscription_failed")
    def _on_sub_failed(participant_identity, track_sid, error):  # noqa: ANN001
        encryption_errors.append({"event": "track_subscription_failed", "participant": participant_identity, "error": str(error)})

    await room.connect(
        livekit_url,
        lk_access_token,
        options=rtc.RoomOptions(
            auto_subscribe=True,
            # The exact same "shared key, raw bytes" path used by
            # apps/ai-agent/app/agent.py in production — see
            # docs/e2ee/README.md.
            e2ee=rtc.E2EEOptions(key_provider_options=rtc.KeyProviderOptions(shared_key=key_bytes)),
        ),
    )

    published = False
    if publish_audio:
        source = rtc.AudioSource(sample_rate=16000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("native-test-mic", source)
        await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        published = True

        async def pump_tone():
            frame_samples = 160  # 10ms @ 16kHz
            t = 0
            while True:
                frame = rtc.AudioFrame.create(sample_rate=16000, num_channels=1, samples_per_channel=frame_samples)
                tone = (np.sin(2 * np.pi * 440 * (np.arange(frame_samples) + t) / 16000) * 8000).astype(np.int16)
                np.frombuffer(frame.data, dtype=np.int16)[:] = tone
                await source.capture_frame(frame)
                t += frame_samples
                await asyncio.sleep(0.01)

        pump_task = asyncio.create_task(pump_tone())
    else:
        pump_task = None

    emit({"event": "ready", "identity": room.local_participant.identity, "published": published, **ready_extra})

    await asyncio.sleep(duration_seconds)

    if pump_task:
        pump_task.cancel()
    await room.disconnect()

    emit({"event": "done", "encryption_errors": encryption_errors})


async def main_async(args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        if args.mode == "create-and-join":
            doctor_auth = await api_login(client, args.api_base_url, args.tenant, args.doctor_email, args.doctor_password)
            session = await api_create_session(client, args.api_base_url, doctor_auth["access_token"], args.patient_email)
            session_id = session["id"]

            if args.role == "doctor":
                join_auth_token = doctor_auth["access_token"]
            else:
                patient_auth = await api_login(client, args.api_base_url, args.tenant, args.patient_email, args.doctor_password)
                join_auth_token = patient_auth["access_token"]

            join_result = await api_join_session(client, args.api_base_url, join_auth_token, session_id)
        elif args.mode == "join":
            auth = await api_login(client, args.api_base_url, args.tenant, args.email, args.password)
            session_id = args.session_id
            join_result = await api_join_session(client, args.api_base_url, auth["access_token"], session_id)
        else:
            raise ValueError(f"unknown mode {args.mode}")

    await run_participant(
        args.livekit_url,
        join_result["access_token"],
        join_result["e2ee_key"],
        args.duration_seconds,
        args.publish_audio,
        ready_extra={"session_id": session_id, "room": join_result["room"]},
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    p1 = sub.add_parser("create-and-join")
    p1.add_argument("--tenant", required=True)
    p1.add_argument("--doctor-email", required=True)
    p1.add_argument("--doctor-password", required=True)
    p1.add_argument("--patient-email", required=True)
    p1.add_argument("--role", choices=["doctor", "patient"], default="patient")
    for p in (p1,):
        p.add_argument("--api-base-url", required=True)
        p.add_argument("--livekit-url", required=True)
        p.add_argument("--duration-seconds", type=float, default=10.0)
        p.add_argument("--publish-audio", action="store_true")

    p2 = sub.add_parser("join")
    p2.add_argument("--tenant", required=True)
    p2.add_argument("--email", required=True)
    p2.add_argument("--password", required=True)
    p2.add_argument("--session-id", required=True)
    p2.add_argument("--api-base-url", required=True)
    p2.add_argument("--livekit-url", required=True)
    p2.add_argument("--duration-seconds", type=float, default=10.0)
    p2.add_argument("--publish-audio", action="store_true")

    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except Exception as e:  # noqa: BLE001
        emit({"event": "error", "error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
