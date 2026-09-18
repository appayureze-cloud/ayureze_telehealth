"""Process configuration. No secret defaults — missing required values
fail fast at startup, matching apps/api/internal/config's convention.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    environment: str = "development"
    log_level: str = "info"

    ai_agent_http_port: int = 8090

    # The Go session API — this is what AuthorizeAIAgent (Day 4) is called
    # against. Never the LiveKit URL directly for authorization purposes;
    # the agent must go through the Go API's consent check every time.
    api_base_url: str = "http://localhost:8080"
    ai_agent_service_secret: str

    livekit_url: str


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env
