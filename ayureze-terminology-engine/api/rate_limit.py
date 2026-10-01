"""Basic in-memory, per-client-IP sliding-window rate limiting (spec
section 23: "implement basic request rate limiting if practical").
Deliberately in-process, not Redis-backed — this is a single-process
Phase 1 MVP (see docs/ARCHITECTURE.md's decision not to add Redis without
a demonstrated need); a multi-replica deployment would need a shared store
instead, documented as a known limitation, not silently pretended away.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self._limit = requests_per_minute
        self._window_seconds = 60.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client_key: str) -> None:
        now = time.monotonic()
        window = self._hits[client_key]
        while window and now - window[0] > self._window_seconds:
            window.popleft()
        if len(window) >= self._limit:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        window.append(now)


def client_key(request: Request) -> str:
    """The real client IP where a proxy sets one, falling back to the
    direct connection — never trusted for authorization, only for rate
    limiting fairness."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
