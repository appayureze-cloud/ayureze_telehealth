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

# Streaming pipeline (build spec section 24). Distinct from the existing
# PIPELINE_STAGE_LATENCY_SECONDS histogram above (which times the
# whole-utterance pipeline's stages) — these time the NEW streaming
# pipeline's own stage boundaries specifically. Not yet emitted by any
# live code path in this pass (streaming_pipeline.py is unit-tested but
# not wired into the live LiveKit audio path yet — see
# docs/ai/streaming.md); defined now so that wiring is a call-site change,
# not a metrics-design change.
STREAMING_ASR_FIRST_PARTIAL_MS = Histogram(
    "ayureze_asr_first_partial_ms", "Time from utterance start to the first ASR partial transcript",
    buckets=(50, 100, 200, 300, 500, 800, 1200, 2000, 5000),
)
STREAMING_ASR_COMMIT_MS = Histogram(
    "ayureze_asr_commit_ms", "Time from a word stabilizing to CommitPolicy flushing its phrase",
    buckets=(50, 100, 200, 500, 1000, 2000, 5000),
)
STREAMING_TRANSLATION_FIRST_TOKEN_MS = Histogram(
    "ayureze_translation_first_token_ms", "Translation first-token latency (batch providers report total time here — see docs/ai/streaming.md)",
    buckets=(50, 100, 250, 500, 1000, 2000, 5000),
)
STREAMING_TRANSLATION_TOTAL_MS = Histogram(
    "ayureze_translation_total_ms", "Translation completion latency, streaming pipeline",
    buckets=(50, 100, 250, 500, 1000, 2000, 5000),
)
STREAMING_SAFETY_MS = Histogram(
    "ayureze_safety_ms", "SafetyCommitPolicy evaluation latency, streaming pipeline",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 25, 50),
)
STREAMING_TTS_FIRST_AUDIO_MS = Histogram(
    "ayureze_tts_first_audio_ms", "Time to the first streamed TTS audio chunk",
    buckets=(50, 100, 250, 500, 1000, 2000, 5000),
)
STREAMING_TTS_TOTAL_MS = Histogram(
    "ayureze_tts_total_ms", "TTS completion latency (all chunks), streaming pipeline",
    buckets=(50, 100, 250, 500, 1000, 2000, 5000),
)
STREAMING_FIRST_TRANSLATED_AUDIO_MS = Histogram(
    "ayureze_first_translated_audio_ms", "End of source utterance to first translated audio chunk delivered",
    buckets=(200, 500, 1000, 1500, 2000, 3000, 5000, 10000),
)
STREAMING_FINAL_UTTERANCE_MS = Histogram(
    "ayureze_final_utterance_ms", "End of source utterance to final translated audio chunk delivered",
    buckets=(200, 500, 1000, 2000, 3000, 5000, 10000, 20000),
)
STREAMING_MODEL_REQUESTS_TOTAL = Counter(
    "ayureze_model_requests_total", "Streaming pipeline model provider invocations", ["provider_id", "stage"],
)
STREAMING_MODEL_FAILURES_TOTAL = Counter(
    "ayureze_model_failures_total", "Streaming pipeline model provider failures", ["provider_id", "stage"],
)
STREAMING_MODEL_FALLBACK_TOTAL = Counter(
    "ayureze_model_fallback_total", "Router fallback-provider selections (primary unavailable)", ["stage", "from_provider_id", "to_provider_id"],
)
STREAMING_SAFETY_BLOCKS_TOTAL = Counter(
    "ayureze_safety_blocks_total", "Streaming pipeline phrases blocked by SafetyCommitPolicy",
)
STREAMING_BARGE_IN_TOTAL = Counter(
    "ayureze_barge_in_total", "Utterances that cancelled a still-playing previous utterance's audio",
)
STREAMING_QUEUE_DEPTH = Gauge(
    "ayureze_queue_depth", "Current depth of a streaming pipeline bounded queue", ["queue"],
)

# Declared per build spec section 24's required metric list, but NEVER
# observed/set anywhere in this codebase: there is no GPU in this build's
# environment and no GPU-resident model actually running (Qwen3-ASR/
# MADLAD-400/Qwen3-TTS/CosyVoice3 are none of them downloaded — see
# docs/MODEL_LICENSE_MATRIX.md). Wiring these to a real value (e.g. via
# pynvml or an NVIDIA DCGM exporter) is real future work once GPU
# infrastructure exists; shipping them now as always-zero/absent gauges
# would be misleading, so they are defined (satisfying "the metric
# exists") but deliberately left unpopulated rather than faked.
STREAMING_GPU_UTILIZATION = Gauge("ayureze_gpu_utilization", "GPU utilization percent, per device", ["device"])
STREAMING_GPU_MEMORY_USED = Gauge("ayureze_gpu_memory_used", "GPU memory used in bytes, per device", ["device"])
