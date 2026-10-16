from app.lifecycle import (
    TERMINAL_STATES,
    AgentState,
    InvalidTransition,
    LifecycleTracker,
)


def test_starts_in_requested():
    t = LifecycleTracker(session_id="s1")
    assert t.current == AgentState.REQUESTED
    assert not t.is_terminal


def test_happy_path_transitions():
    t = LifecycleTracker(session_id="s1")
    t.transition(AgentState.AUTHORIZED)
    t.transition(AgentState.JOINING)
    t.transition(AgentState.CONNECTED)
    t.transition(AgentState.PROCESSING)
    t.transition(AgentState.PUBLISHING)
    assert t.current == AgentState.PUBLISHING
    assert not t.is_terminal


def test_revoked_from_connected():
    t = LifecycleTracker(session_id="s1")
    t.transition(AgentState.AUTHORIZED)
    t.transition(AgentState.JOINING)
    t.transition(AgentState.CONNECTED)
    t.transition(AgentState.REVOKED)
    assert t.current == AgentState.REVOKED
    assert t.is_terminal


def test_revoked_from_processing_and_publishing():
    for target_before_revoke in (AgentState.PROCESSING, AgentState.PUBLISHING):
        t = LifecycleTracker(session_id="s1")
        t.transition(AgentState.AUTHORIZED)
        t.transition(AgentState.JOINING)
        t.transition(AgentState.CONNECTED)
        t.transition(AgentState.PROCESSING)
        if target_before_revoke == AgentState.PUBLISHING:
            t.transition(AgentState.PUBLISHING)
        t.transition(AgentState.REVOKED)
        assert t.current == AgentState.REVOKED


def test_cannot_skip_states():
    t = LifecycleTracker(session_id="s1")
    try:
        t.transition(AgentState.CONNECTED)
        assert False, "expected InvalidTransition"
    except InvalidTransition as e:
        assert e.current == AgentState.REQUESTED
        assert e.target == AgentState.CONNECTED


def test_cannot_transition_out_of_terminal_state():
    t = LifecycleTracker(session_id="s1")
    t.transition(AgentState.AUTHORIZED)
    t.transition(AgentState.JOINING)
    t.transition(AgentState.DISCONNECTED)
    assert t.current in TERMINAL_STATES
    try:
        t.transition(AgentState.CONNECTED)
        assert False, "expected InvalidTransition"
    except InvalidTransition:
        pass


def test_failed_reachable_from_every_non_terminal_state():
    for start_states in (
        [],
        [AgentState.AUTHORIZED],
        [AgentState.AUTHORIZED, AgentState.JOINING],
        [AgentState.AUTHORIZED, AgentState.JOINING, AgentState.CONNECTED],
    ):
        t = LifecycleTracker(session_id="s1")
        for s in start_states:
            t.transition(s)
        t.transition(AgentState.FAILED)
        assert t.current == AgentState.FAILED


def test_history_records_every_transition():
    t = LifecycleTracker(session_id="s1")
    t.transition(AgentState.AUTHORIZED, detail="ok")
    t.transition(AgentState.FAILED, detail="join_error")
    d = t.as_dict()
    assert d["session_id"] == "s1"
    assert d["current_state"] == "FAILED"
    assert [h["state"] for h in d["history"]] == ["REQUESTED", "AUTHORIZED", "FAILED"]
    assert d["history"][-1]["detail"] == "join_error"
