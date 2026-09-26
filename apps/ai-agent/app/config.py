"""Process configuration. No secret defaults — missing required values
fail fast at startup, matching apps/api/internal/config's convention.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    environment: str = "development"
    log_level: str = "info"

    ai_agent_http_port: int = 8090

    # The Go session API — this is what AuthorizeAIAgent (Day 4) is called
    # against. Never the LiveKit URL directly for authorization purposes;
    # the agent must go through the Go API's consent check every time.
    api_base_url: str = "http://localhost:8080"
    ai_agent_service_secret: str

    livekit_url: str

    # Day 6: when true, the agent loads the real VAD/STT/translation/TTS
    # pipeline (several GB of model weights, seconds to load) and actually
    # processes/publishes translated audio. When false (default — matches
    # Day 5 behavior), the agent still authorizes/joins/subscribes for
    # real, but only tracks lifecycle state off the encrypted media path
    # without running the pipeline — useful for lifecycle-only tests and
    # environments that haven't provisioned the pipeline's model weights.
    ai_agent_enable_pipeline: bool = False
    ai_agent_whisper_model_size: str = "tiny"

    # build_default_pipeline()'s actual backend selection (app/pipeline/
    # factory.py). Deploy-time choice, not a code change — neither backend
    # is removed from the codebase by selecting the other:
    #   translation: "opus-mt" (default) — Helsinki-NLP/opus-mt-en-dra/
    #     -dra-en, Apache-2.0, small enough for real CPU inference; this
    #     is what actually runs on a CPU-only VPS today.
    #     "madlad" — MADLAD-400 3B, Apache-2.0 but GPU-only per its own
    #     docs (not downloaded unless ai_allow_model_download=true AND a
    #     GPU is present) — set this once real GPU infrastructure exists.
    #   tts: "none" (default) — captions-only.
    #     "qwen3-tts" — GPU-only, also needs a reference voice clip per
    #     language (see ai_tts_reference_audio_path/ai_tts_reference_text
    #     below).
    #     "indic-parler-tts" — ai4bharat/indic-parler-tts, Apache-2.0
    #     (confirmed commercial-clean), confirmed Tamil support, has a
    #     documented CPU fallback (0.9B params — expect multi-second
    #     latency per utterance on CPU, not benchmarked).
    #     "piper" — invoked via CLI subprocess only, genuinely CPU-fast.
    #     REAL UNRESOLVED GAP: the specific Tamil voice checkpoint's
    #     dataset license could not be verified — see
    #     docs/MODEL_LICENSE_MATRIX.md before enabling in production.
    #     Needs ai_tts_piper_checkpoint_path (a local .onnx file) and the
    #     `piper` executable on PATH.
    ai_translation_backend: str = "opus-mt"  # "opus-mt" | "madlad"
    ai_tts_backend: str = "none"  # "none" | "qwen3-tts" | "indic-parler-tts" | "piper"
    ai_tts_reference_audio_path: str | None = None
    ai_tts_reference_text: str | None = None
    ai_tts_piper_checkpoint_path: str | None = None

    # Streaming pipeline (this pass's addition — see app/pipeline/
    # streaming_pipeline.py). Opt-in and OFF by default: the existing,
    # live-verified whole-utterance pipeline above remains the default
    # path. Not yet wired into the live LiveKit audio path — see
    # docs/ai/streaming.md's "What has not been verified."
    ai_agent_streaming_pipeline_enabled: bool = False

    ai_stt_primary: str = "qwen3-asr-1.7b"
    ai_stt_fallback: str = "whisper-tiny"

    ai_translation_primary: str = "madlad400-3b"
    ai_translation_high_quality: str = "madlad400-7b"

    ai_tts_primary: str = "qwen3-tts"
    ai_tts_streaming: str = "cosyvoice3"

    ai_asr_chunk_ms: float = 600.0
    ai_asr_overlap_ms: float = 150.0

    ai_tts_chunk_ms: float = 500.0

    ai_max_translation_buffer_ms: float = 2000.0

    # New model weights are never downloaded implicitly (build spec: work
    # incrementally, don't make large speculative changes) — see
    # ModelNotAvailableError in app/pipeline/model_lifecycle.py. Setting
    # this true also requires the relevant optional package
    # (qwen_asr/qwen_tts/cosyvoice/transformers' Marian/T5 classes) and,
    # for the GPU-only models, an actual CUDA device.
    ai_allow_model_download: bool = False

    # Bounded queue sizes (build spec section 16's own example limits).
    ai_translation_queue_size: int = 20
    ai_safety_queue_size: int = 20
    ai_tts_queue_size: int = 20
    ai_audio_output_max_out_of_order_wait: int = 5


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env
