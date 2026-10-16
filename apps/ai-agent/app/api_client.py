"""Client for the Go session API's AI-agent authorization endpoint
(Day 4: POST /internal/ai-agent/sessions/{id}/authorize).

This is the *only* way the agent ever obtains a LiveKit token or the
session's E2EE key — it never mints its own credentials, matching "Never
allow clients to generate privileged tokens themselves" from the build
spec (the AI agent is a client of the Go API just as the patient/doctor
apps are, even though it's a backend service rather than a human user).
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel


class AuthorizationDenied(Exception):
    """Raised when the Go API refuses authorization — e.g. no active
    ai_translation consent, session not found/ended. Callers must treat
    this as "do not join," never retry-bypass it."""

    def __init__(self, status_code: int, body: str):
        super().__init__(f"AI agent authorization denied: {status_code} {body}")
        self.status_code = status_code
        self.body = body


class AIAgentGrant(BaseModel):
    access_token: str
    room: str
    identity: str
    e2ee_key: str
    expires_at: str


class APIClient:
    def __init__(self, base_url: str, service_secret: str, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._service_secret = service_secret
        self._timeout = timeout

    async def authorize_ai_agent(self, tenant_id: str, session_id: str) -> AIAgentGrant:
        url = f"{self._base_url}/internal/ai-agent/sessions/{session_id}/authorize"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                url,
                json={"tenant_id": tenant_id},
                headers={"X-AI-Agent-Secret": self._service_secret},
            )
        if resp.status_code != 200:
            raise AuthorizationDenied(resp.status_code, resp.text)
        return AIAgentGrant.model_validate(resp.json())
