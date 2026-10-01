"""End-to-end AI agent lifecycle test against the real stack — no mocks.

Requires:
  ./scripts/dev-up.sh                     (Postgres/Redis/LiveKit running)
  cd apps/api && go run ./cmd/api &       (or scripts/run-api.sh)

Run with:
  cd apps/ai-agent
  source .venv/bin/activate
  pytest -m integration -v tests/test_agent_integration.py

This test seeds its own tenant/doctor/patient (via the Go seed command, a
subprocess call — the same mechanism a human developer would use), drives
the real Go API over HTTP (login, create/join session, grant/revoke
consent), connects a real second LiveKit participant (standing in for the
doctor's browser) that publishes a synthetic encrypted audio track using
the session's actual E2EE key, and drives the actual AI agent FastAPI app
in-process (so its asyncio background tasks share this test's event loop)
through authorize -> join -> CONNECTED -> PROCESSING -> REVOKED.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import uuid

import httpx
import pytest
from livekit import rtc

pytestmark = pytest.mark.integration


def _repo_root() -> str:
    return os.environ["_REPO_ROOT"]


def seed_tenant() -> dict:
    suffix = uuid.uuid4().hex[:8]
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": (
                f"postgres://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
                f"@localhost:5432/{env['POSTGRES_DB']}?sslmode=disable"
            ),
            "REDIS_HOST": "localhost",
            "SEED_TENANT_NAME": f"pytest-tenant-{suffix}",
            "SEED_DOCTOR_EMAIL": f"doctor-{suffix}@pytest.test",
            "SEED_PATIENT_EMAIL": f"patient-{suffix}@pytest.test",
            "SEED_PASSWORD": "pytest-integration-password",
        }
    )
    result = subprocess.run(
        ["go", "run", "./cmd/seed"],
        cwd=os.path.join(_repo_root(), "apps", "api"),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"seed failed: {result.stdout}\n{result.stderr}"
    return {
        "tenant": env["SEED_TENANT_NAME"],
        "doctor_email": env["SEED_DOCTOR_EMAIL"],
        "patient_email": env["SEED_PATIENT_EMAIL"],
        "password": env["SEED_PASSWORD"],
    }


def decode_jwt_claims(token: str) -> dict:
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class GoAPI:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=10.0)

    def login(self, tenant: str, email: str, password: str) -> str:
        r = self.client.post("/v1/auth/login", json={"tenant": tenant, "email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    def create_session(self, doctor_token: str, patient_email: str) -> dict:
        r = self.client.post(
            "/v1/sessions",
            json={"patient_email": patient_email},
            headers={"Authorization": f"Bearer {doctor_token}"},
        )
        assert r.status_code == 201, r.text
        return r.json()

    def join(self, token: str, session_id: str) -> dict:
        r = self.client.post(
            f"/v1/sessions/{session_id}/join",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        return r.json()

    def grant_consent(self, token: str, session_id: str) -> None:
        r = self.client.post(
            f"/v1/sessions/{session_id}/consent/ai-translation/grant",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text

    def revoke_consent(self, token: str, session_id: str) -> None:
        r = self.client.post(
            f"/v1/sessions/{session_id}/consent/ai-translation/revoke",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text


async def connect_test_publisher(livekit_url: str, access_token: str, e2ee_key_b64: str) -> rtc.Room:
    """Stands in for the doctor's browser: joins the same room with the
    same session E2EE key and continuously publishes a synthetic audio
    track, so the AI agent has real encrypted media to subscribe to."""
    room = rtc.Room()
    key_bytes = base64.b64decode(e2ee_key_b64)
    await room.connect(
        livekit_url,
        access_token,
        options=rtc.RoomOptions(
            auto_subscribe=False,
            e2ee=rtc.E2EEOptions(key_provider_options=rtc.KeyProviderOptions(shared_key=key_bytes)),
        ),
    )

    source = rtc.AudioSource(sample_rate=16000, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("doctor-mic", source)
    await room.local_participant.publish_track(track)

    async def _pump_silence():
        frame = rtc.AudioFrame.create(sample_rate=16000, num_channels=1, samples_per_channel=160)
        while room.isconnected:
            try:
                await source.capture_frame(frame)
            except Exception:
                break
            await asyncio.sleep(0.01)

    room._pump_task = asyncio.create_task(_pump_silence())
    return room


@pytest.fixture
def go_api():
    return GoAPI()


async def wait_for_state(client: httpx.AsyncClient, session_id: str, target_states: set[str], timeout: float = 15.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    last = None
    while loop.time() < deadline:
        r = await client.get(f"/v1/agent/sessions/{session_id}")
        if r.status_code == 200:
            last = r.json()
            if last["current_state"] in target_states:
                return last
        await asyncio.sleep(0.2)
    raise AssertionError(f"timed out waiting for state in {target_states}, last={last}")


async def test_ai_agent_full_lifecycle(go_api):
    from app.main import app as agent_app

    creds = seed_tenant()
    doctor_token = go_api.login(creds["tenant"], creds["doctor_email"], creds["password"])
    patient_token = go_api.login(creds["tenant"], creds["patient_email"], creds["password"])
    tenant_id = decode_jwt_claims(doctor_token)["tid"]

    sess = go_api.create_session(doctor_token, creds["patient_email"])
    session_id = sess["id"]

    join_resp = go_api.join(doctor_token, session_id)
    publisher_room = await connect_test_publisher(
        os.environ["LIVEKIT_URL"], join_resp["access_token"], join_resp["e2ee_key"]
    )

    try:
        # AI must not be reachable without consent (re-verifies Day 4's
        # enforcement from within the same lifecycle this test exercises).
        transport = httpx.ASGITransport(app=agent_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://agent-under-test") as client:
            r = await client.post(
                f"/v1/agent/sessions/{session_id}/start", json={"tenant_id": tenant_id}
            )
            assert r.status_code == 202
            failed = await wait_for_state(client, session_id, {"FAILED"})
            assert failed["history"][-1]["detail"].startswith("authorization_denied")

            # Grant consent, then start a *new* agent run for the same
            # session (the previous instance is terminal/FAILED).
            go_api.grant_consent(patient_token, session_id)

            r = await client.post(
                f"/v1/agent/sessions/{session_id}/start", json={"tenant_id": tenant_id}
            )
            assert r.status_code == 202

            connected = await wait_for_state(client, session_id, {"CONNECTED", "PROCESSING"})
            assert connected["current_state"] in ("CONNECTED", "PROCESSING")

            processing = await wait_for_state(client, session_id, {"PROCESSING"}, timeout=10.0)
            assert processing["current_state"] == "PROCESSING"
            assert "audio_track_from" in processing["history"][-1]["detail"]

            # Revoke consent while the agent is connected: it must be
            # force-disconnected (REVOKED), not merely blocked from a
            # future join.
            go_api.revoke_consent(doctor_token, session_id)
            revoked = await wait_for_state(client, session_id, {"REVOKED", "DISCONNECTED"}, timeout=10.0)
            assert revoked["current_state"] == "REVOKED", (
                f"expected REVOKED (participant force-removed), got {revoked}"
            )
    finally:
        publisher_room._pump_task.cancel()
        if publisher_room.isconnected:
            await publisher_room.disconnect()
