"""AyurEze Terminology Engine — standalone FastAPI app.

Phase 1 isolation, restated here where it matters most: this app has NO
import of, or dependency on, the AyurEze AI pipeline, Qwen3-ASR,
translation models, Qwen3-TTS, the Safety Validator, or LiveKit. It never
calls an LLM. It is a deterministic lookup/search service over the
concept registry built by ingestion/ — see docs/ARCHITECTURE.md and
README.md.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.routes import router
from config.settings import get_settings

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("terminology-engine")

app = FastAPI(
    title="AyurEze Terminology Engine",
    description="Standalone Ayurveda + biomedical terminology registry, search, and resolution API. Phase 1 — no AI, no diagnosis, no patient data.",
    version="0.1.0",
)

app.include_router(router)


@app.middleware("http")
async def log_request_latency(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "request",
        extra={"path": request.url.path, "method": request.method, "status_code": response.status_code, "duration_ms": round(elapsed_ms, 2)},
    )
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals (stack traces, DB connection strings, etc.) in
    # a response body — spec section 23: "never expose raw secrets."
    logger.exception("unhandled_exception", extra={"path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
