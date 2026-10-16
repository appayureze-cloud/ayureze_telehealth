"""Loads the repo root .env (with host-friendly overrides) into the process
environment *before* app.config.Settings is instantiated at import time —
pytest conftest files run before test collection, so this happens ahead of
any `from app.main import app` in test modules.
"""

from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env.example").exists():
            return parent
    raise RuntimeError("could not locate repo root (.env.example not found)")


def _load_env() -> None:
    root = _repo_root()
    env_path = root / ".env"
    if not env_path.exists():
        raise RuntimeError(f".env not found at {env_path} — copy .env.example first")

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key, value)

    # Host-side overrides — these hostnames only resolve inside the
    # docker-compose network.
    os.environ["LIVEKIT_URL"] = "ws://localhost:7880"
    os.environ["API_BASE_URL"] = "http://localhost:8080"
    os.environ["_REPO_ROOT"] = str(root)


_load_env()
