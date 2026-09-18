"""AI Agent service — FastAPI control surface.

The AI agent never joins a room merely because it exists. It joins only
when explicitly triggered via POST /v1/agent/sessions/{id}/start, which
itself only succeeds through the full chain: Go API verifies an active
ai_translation consent (Day 4) -> mints a room-scoped token + hands over
the E2EE key -> this service connects to LiveKit as an encrypted
participant (Day 5).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from .agent import AIAgent
from .api_client import APIClient
from .config import load_settings
from .lifecycle import AgentState
from .logging_setup import configure_logging, log
from .metrics import AI_AGENT_ACTIVE_SESSIONS
from .registry import AgentRegistry

settings = load_settings()
logger = configure_logging("ayureze-ai-agent", settings.environment, settings.log_level)
api_client = APIClient(settings.api_base_url, settings.ai_agent_service_secret)
registry = AgentRegistry()

_pipeline = None  # built lazily on first use — see _get_pipeline()


def _get_pipeline():
    """Loads the Day 6 ML pipeline on first use (several GB of model
    weights, several seconds) rather than at import time, so `/health`
    and lifecycle-only operation never pay this cost when
    AI_AGENT_ENABLE_PIPELINE=false."""
    global _pipeline
    if _pipeline is None:
        from .pipeline.factory import build_default_pipeline

        log(logger, logging.INFO, "loading_translation_pipeline", event_type="loading_translation_pipeline")
        _pipeline = build_default_pipeline(whisper_model_size=settings.ai_agent_whisper_model_size)
        log(logger, logging.INFO, "translation_pipeline_loaded", event_type="translation_pipeline_loaded")
    return _pipeline

app = FastAPI(title="AyurEze AI Translation Agent")


class StartRequest(BaseModel):
    tenant_id: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    AI_AGENT_ACTIVE_SESSIONS.set(registry.active_count())
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/agent/sessions/{session_id}/start", status_code=202)
async def start_agent(session_id: str, req: StartRequest):
    pipeline = None
    if settings.ai_agent_enable_pipeline:
        # First call loads several GB of model weights (seconds) — never
        # block the event loop (and every other in-flight request,
        # including /health) on that.
        loop = asyncio.get_event_loop()
        pipeline = await loop.run_in_executor(None, _get_pipeline)
    agent = AIAgent(
        session_id=session_id,
        tenant_id=req.tenant_id,
        livekit_url=settings.livekit_url,
        api_client=api_client,
        logger=logger,
        pipeline=pipeline,
    )
    try:
        await registry.start(agent)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    log(
        logger,
        logging.INFO,
        "ai_agent_start_requested",
        event_type="ai_agent_start_requested",
        session_id=session_id,
        tenant_id=req.tenant_id,
    )
    return agent.lifecycle.as_dict()


@app.post("/v1/agent/sessions/{session_id}/stop")
async def stop_agent(session_id: str):
    stopped = await registry.stop(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="no active agent for this session")
    agent = registry.get(session_id)
    return agent.lifecycle.as_dict() if agent else {"status": "stopped"}


@app.get("/v1/agent/sessions/{session_id}")
async def get_agent_status(session_id: str):
    agent = registry.get(session_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="no agent found for this session")
    return agent.lifecycle.as_dict()


# Re-exported for tests / potential future use.
__all__ = ["AgentState", "app"]
