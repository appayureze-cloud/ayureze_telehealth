"""AI agent connection lifecycle state machine.

States mirror the build spec exactly:
REQUESTED -> AUTHORIZED -> JOINING -> CONNECTED -> PROCESSING -> PUBLISHING
                                                          \\-> REVOKED
                                                          \\-> DISCONNECTED

PUBLISHING is only reached once Day 6's translation pipeline actually
publishes translated audio — Day 5 exercises every other transition against
a real LiveKit connection (see tests/test_agent_integration.py) but never
reaches PUBLISHING on its own, since there is nothing to publish yet.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class AgentState(str, enum.Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    JOINING = "JOINING"
    CONNECTED = "CONNECTED"
    PROCESSING = "PROCESSING"
    PUBLISHING = "PUBLISHING"
    REVOKED = "REVOKED"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"


# Terminal states: once reached, the agent instance is done and must not
# transition further (a fresh authorize/join cycle creates a new instance).
TERMINAL_STATES = frozenset({AgentState.REVOKED, AgentState.DISCONNECTED, AgentState.FAILED})

_ALLOWED_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.REQUESTED: frozenset({AgentState.AUTHORIZED, AgentState.FAILED}),
    AgentState.AUTHORIZED: frozenset({AgentState.JOINING, AgentState.FAILED}),
    AgentState.JOINING: frozenset({AgentState.CONNECTED, AgentState.FAILED, AgentState.DISCONNECTED}),
    AgentState.CONNECTED: frozenset({AgentState.PROCESSING, AgentState.REVOKED, AgentState.DISCONNECTED, AgentState.FAILED}),
    AgentState.PROCESSING: frozenset({AgentState.PUBLISHING, AgentState.REVOKED, AgentState.DISCONNECTED, AgentState.FAILED}),
    AgentState.PUBLISHING: frozenset({AgentState.PROCESSING, AgentState.REVOKED, AgentState.DISCONNECTED, AgentState.FAILED}),
    AgentState.REVOKED: frozenset(),
    AgentState.DISCONNECTED: frozenset(),
    AgentState.FAILED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, current: AgentState, target: AgentState):
        super().__init__(f"cannot transition from {current} to {target}")
        self.current = current
        self.target = target


@dataclass
class StateTransition:
    state: AgentState
    at: float = field(default_factory=time.time)
    detail: str | None = None


@dataclass
class LifecycleTracker:
    """Enforces the state machine above and keeps a full transition history
    (useful for both the /status endpoint and post-hoc audit/debugging —
    never contains media/key material, only state names and timestamps).
    """

    session_id: str
    history: list[StateTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.history.append(StateTransition(AgentState.REQUESTED))

    @property
    def current(self) -> AgentState:
        return self.history[-1].state

    @property
    def is_terminal(self) -> bool:
        return self.current in TERMINAL_STATES

    def transition(self, target: AgentState, detail: str | None = None) -> None:
        allowed = _ALLOWED_TRANSITIONS[self.current]
        if target not in allowed:
            raise InvalidTransition(self.current, target)
        self.history.append(StateTransition(target, detail=detail))

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "current_state": self.current.value,
            "history": [
                {"state": t.state.value, "at": t.at, "detail": t.detail} for t in self.history
            ],
        }
