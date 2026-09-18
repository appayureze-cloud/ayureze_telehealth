"""Prometheus metrics for the AI agent service. Scraped by
observability/prometheus/prometheus.yml's ayureze-ai-agent job (Day 1).
"""

from prometheus_client import Counter, Gauge

AI_AGENT_AUTHORIZE_TOTAL = Counter(
    "ai_agent_authorize_total", "AI agent authorization attempts", ["outcome"]
)
AI_AGENT_JOIN_TOTAL = Counter(
    "ai_agent_join_total", "AI agent LiveKit join attempts", ["outcome"]
)
AI_AGENT_ACTIVE_SESSIONS = Gauge(
    "ai_agent_active_sessions", "Number of AI agent instances not yet in a terminal state"
)
AI_AGENT_STATE_TRANSITIONS_TOTAL = Counter(
    "ai_agent_state_transitions_total", "AI agent lifecycle state transitions", ["state"]
)
