"""Live end-to-end test of the Day 6 pipeline wired into the Day 5 agent:
real LiveKit room, real E2EE, real streamed speech audio (synthesized via
TTS to stand in for a doctor's microphone), real VAD segmentation, real
STT/translation/safety/TTS, and a real translated-caption data message
received back — the full chain, no mocks.

Separate from tests/test_agent_integration.py (which validates the Day 5
lifecycle in isolation, pipeline disabled, for speed) because this test
needs AI_AGENT_ENABLE_PIPELINE=true and pays the full model-loading cost.

Run with:
  pytest -m integration -v tests/test_pipeline_live_integration.py
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os

import numpy as np
import pytest
from livekit import rtc

from tests.test_agent_integration import GoAPI, decode_jwt_claims, seed_tenant

pytestmark = pytest.mark.integration


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return samples
    duration = len(samples) / src_rate
    dst_len = int(duration * dst_rate)
    x_old = np.linspace(0, 1, len(samples))
    x_new = np.linspace(0, 1, dst_len)
    return np.interp(x_new, x_old, samples).astype(np.float32)


async def publish_speech(room: rtc.Room, text: str) -> rtc.AudioSource:
    """Synthesizes `text` via the English TTS model and streams it into
    the room at real-time pace (10ms frames), standing in for a doctor
    speaking into a microphone."""
    from app.pipeline.tts import MmsTTSProvider

    tts = MmsTTSProvider()
    audio = tts.synthesize(text, "en")
    pcm = _resample(audio.samples, audio.sample_rate, 16000)
    pcm16 = np.clip(pcm * 32767.0, -32768, 32767).astype(np.int16)

    source = rtc.AudioSource(sample_rate=16000, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("doctor-mic", source)
    await room.local_participant.publish_track(track)

    frame_len = 160  # 10ms @ 16kHz
    for start in range(0, len(pcm16), frame_len):
        chunk = pcm16[start : start + frame_len]
        if len(chunk) < frame_len:
            chunk = np.pad(chunk, (0, frame_len - len(chunk)))
        frame = rtc.AudioFrame.create(sample_rate=16000, num_channels=1, samples_per_channel=frame_len)
        np.frombuffer(frame.data, dtype=np.int16)[:] = chunk
        await source.capture_frame(frame)
        await asyncio.sleep(0.01)

    # Trailing silence so the agent's VAD hangover actually fires and
    # closes out the turn (see app/pipeline/vad.py TurnSegmenter).
    silence = np.zeros(frame_len, dtype=np.int16)
    for _ in range(40):  # ~400ms
        frame = rtc.AudioFrame.create(sample_rate=16000, num_channels=1, samples_per_channel=frame_len)
        np.frombuffer(frame.data, dtype=np.int16)[:] = silence
        await source.capture_frame(frame)
        await asyncio.sleep(0.01)

    return source


async def test_live_translation_pipeline_produces_captions():
    os.environ["AI_AGENT_ENABLE_PIPELINE"] = "true"
    import app.config as config_module
    import app.main as main_module

    importlib.reload(config_module)
    importlib.reload(main_module)
    from app.main import app as agent_app

    go_api = GoAPI()
    creds = seed_tenant()
    doctor_token = go_api.login(creds["tenant"], creds["doctor_email"], creds["password"])
    patient_token = go_api.login(creds["tenant"], creds["patient_email"], creds["password"])
    tenant_id = decode_jwt_claims(doctor_token)["tid"]

    sess = go_api.create_session(doctor_token, creds["patient_email"])
    session_id = sess["id"]
    go_api.grant_consent(patient_token, session_id)

    join_resp = go_api.join(doctor_token, session_id)

    doctor_room = rtc.Room()
    key_bytes = base64.b64decode(join_resp["e2ee_key"])
    await doctor_room.connect(
        os.environ["LIVEKIT_URL"],
        join_resp["access_token"],
        options=rtc.RoomOptions(
            auto_subscribe=False,
            e2ee=rtc.E2EEOptions(key_provider_options=rtc.KeyProviderOptions(shared_key=key_bytes)),
        ),
    )

    captions_received: list[dict] = []

    def on_data(data_packet):
        if data_packet.topic == "ayureze.captions":
            captions_received.append(json.loads(bytes(data_packet.data)))

    doctor_room.on("data_received", on_data)

    import httpx

    transport = httpx.ASGITransport(app=agent_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://agent-under-test") as client:
        r = await client.post(f"/v1/agent/sessions/{session_id}/start", json={"tenant_id": tenant_id})
        assert r.status_code == 202

        # Wait for the agent to actually connect before speaking, so its
        # track_subscribed handler is registered in time.
        deadline = asyncio.get_event_loop().time() + 30
        while asyncio.get_event_loop().time() < deadline:
            s = await client.get(f"/v1/agent/sessions/{session_id}")
            if s.json()["current_state"] in ("CONNECTED", "PROCESSING"):
                break
            await asyncio.sleep(0.5)
        else:
            pytest.fail("AI agent never reached CONNECTED (pipeline load likely still in progress)")

        try:
            await publish_speech(doctor_room, "Take two tablets twice daily for seven days.")

            deadline = asyncio.get_event_loop().time() + 20
            while asyncio.get_event_loop().time() < deadline and not captions_received:
                await asyncio.sleep(0.5)
        finally:
            if doctor_room.isconnected:
                await doctor_room.disconnect()
            await client.post(f"/v1/agent/sessions/{session_id}/stop")

    assert captions_received, "expected at least one caption data message from the AI agent"
    caption = captions_received[0]
    assert caption["source_lang"] == "en"
    assert caption["target_lang"] == "ta"
    assert caption["original_text"].strip() != ""
    assert caption["blocked"] is False
    assert caption["translated_text"].strip() != ""
    assert "stt_ms" in caption["timings_ms"]
    assert "translation_ms" in caption["timings_ms"]
    assert "tts_ms" in caption["timings_ms"]
