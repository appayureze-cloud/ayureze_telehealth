"""Process configuration for the terminology engine — isolated from the
existing telehealth repo's root .env: its own prefix (TERMINOLOGY_*), its
own database, no shared required variables. See docs/ARCHITECTURE.md
section 3 for why this is deliberately separate.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TERMINOLOGY_", extra="ignore")

    environment: str = "development"
    log_level: str = "info"

    http_port: int = 8100

    # A separate Postgres instance/database from the existing telehealth
    # stack's shared "ayureze_telehealth" DB — see docs/ARCHITECTURE.md.
    database_url: str = "postgresql+psycopg://terminology:terminology@localhost:5433/ayureze_terminology"

    # Search query length limit (section 23: "limit query lengths").
    max_query_length: int = 200

    # Basic rate limiting (section 23: "implement basic request rate
    # limiting if practical") — requests per minute per client IP.
    rate_limit_per_minute: int = 120


def get_settings() -> Settings:
    return Settings()
