"""In-memory registry of active agent instances, keyed by session_id. A
single process instance is sufficient for this build (Kubernetes-ready
scaling would shard by session_id across replicas — out of scope here).
"""

from __future__ import annotations

import asyncio

from .agent import AIAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AIAgent] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def start(self, agent: AIAgent) -> None:
        async with self._lock:
            existing = self._agents.get(agent.session_id)
            if existing is not None and not existing.lifecycle.is_terminal:
                raise ValueError(f"an active agent already exists for session {agent.session_id}")
            self._agents[agent.session_id] = agent
            self._tasks[agent.session_id] = asyncio.create_task(agent.run())

    def get(self, session_id: str) -> AIAgent | None:
        return self._agents.get(session_id)

    async def stop(self, session_id: str) -> bool:
        agent = self._agents.get(session_id)
        if agent is None:
            return False
        await agent.stop()
        return True

    def active_count(self) -> int:
        return sum(1 for a in self._agents.values() if not a.lifecycle.is_terminal)
