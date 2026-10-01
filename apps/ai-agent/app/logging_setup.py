"""Structured JSON logging, mirroring apps/api/internal/logging's
conventions (service/environment/event_type fields, secret redaction) so
Loki queries and dashboards work uniformly across both services.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_REDACTED_KEYS = {
    "password",
    "secret",
    "token",
    "access_token",
    "api_key",
    "e2ee_key",
    "private_key",
    "ai_agent_service_secret",
}


class JSONFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str):
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "msg": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                payload[key] = "[REDACTED]" if key.lower() in _REDACTED_KEYS else value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service: str, environment: str, level: str = "info") -> logging.Logger:
    logger = logging.getLogger(service)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(service, environment))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    logger.log(level, msg, extra={"fields": fields})
