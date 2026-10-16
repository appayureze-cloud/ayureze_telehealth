"""Application-level OpenTelemetry tracing for the AI pipeline, closing
the gap docs/monitoring/README.md documents as a known limitation: the
agent previously emitted Prometheus metrics and structured logs per stage
but no distributed trace spans, so one segment's path through
VAD -> STT -> language ID -> terminology -> translation -> safety -> TTS
could not be followed as a single trace.

Exports via OTLP/gRPC to the otel-collector already deployed in
infrastructure/docker/docker-compose.yml (OTEL_EXPORTER_OTLP_ENDPOINT). If
that env var is unset, spans are created but never exported — the same
safe no-op default as apps/api's internal/tracing, so unit tests and any
run without a live collector are unaffected.

Never put transcript/translation text, or any other patient-spoken
content, into a span attribute — only stage name, duration (already also
in Prometheus via metrics.py), language codes, and the safety verdict
boolean. See docs/monitoring/privacy.md.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized = False


def init() -> None:
    """Idempotent — safe to call multiple times (e.g. once from main.py,
    once from a test fixture)."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    service_name = os.environ.get("OTEL_SERVICE_NAME", "ayureze-ai-agent")

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def tracer() -> trace.Tracer:
    if not _initialized:
        init()
    return trace.get_tracer("ayureze.ai-agent.pipeline")
