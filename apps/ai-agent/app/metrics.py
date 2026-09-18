"""Prometheus metrics for the AI agent service. Scraped by
observability/prometheus/prometheus.yml's ayureze-ai-agent job (Day 1).
"""

from prometheus_client import Counter, Gauge, Histogram

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

# Translation pipeline per-stage latency (build spec section 13's AI
# category: "VAD latency, STT latency, language detection latency,
# translation latency, terminology latency, safety validation latency, TTS
# latency, total translation latency"). Buckets are seconds, sized for
# CPU-bound model inference (tens of ms to a few seconds), not HTTP-request
# scale. Never labeled with session/tenant/user IDs or any call content —
# see docs/monitoring/privacy.md.
PIPELINE_STAGE_LATENCY_SECONDS = Histogram(
    "ayureze_ai_pipeline_stage_latency_seconds",
    "Translation pipeline per-stage processing latency",
    ["stage"],  # vad | stt | language_id | terminology | translation | safety_validation | tts | total
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
PIPELINE_SEGMENTS_PROCESSED_TOTAL = Counter(
    "ayureze_ai_pipeline_segments_processed_total", "VAD-delimited speech segments run through the pipeline"
)
PIPELINE_SEGMENTS_BLOCKED_TOTAL = Counter(
    "ayureze_ai_pipeline_segments_blocked_total",
    "Segments whose translation the safety validator blocked",
)
