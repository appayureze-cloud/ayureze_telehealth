// Package tracing wires up application-level OpenTelemetry spans, closing
// the gap documented in docs/monitoring/README.md's "known limitation":
// this API previously emitted Prometheus metrics and structured logs but
// no distributed trace spans, so a single request's path (HTTP handler ->
// session service -> LiveKit RoomService call) could not be followed as
// one trace. Exports via OTLP/gRPC to the otel-collector already deployed
// in infrastructure/docker/docker-compose.yml (OTEL_EXPORTER_OTLP_ENDPOINT).
//
// What this intentionally does NOT do: put any medical/session content —
// patient/doctor identity strings, emails, room names beyond their opaque
// UUID suffix — into a span attribute. Span attributes here are limited to
// the same opaque-ID/enum/outcome vocabulary the existing Prometheus
// metrics and structured logs already use (see docs/monitoring/privacy.md).
package tracing

import (
	"context"
	"fmt"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
	"go.opentelemetry.io/otel/trace"
)

// Shutdown flushes and stops the trace provider; callers should defer it
// from main().
type Shutdown func(context.Context) error

// Init sets up the global TracerProvider. If otlpEndpoint is empty,
// tracing is a no-op (spans are created but never exported) — this keeps
// local `go test`/dev-without-the-full-stack runs working without needing
// a live otel-collector.
func Init(ctx context.Context, serviceName, otlpEndpoint string) (Shutdown, error) {
	if otlpEndpoint == "" {
		otel.SetTracerProvider(sdktrace.NewTracerProvider())
		return func(context.Context) error { return nil }, nil
	}

	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpointURL(otlpEndpoint),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, fmt.Errorf("init otlp trace exporter: %w", err)
	}

	res, err := resource.Merge(resource.Default(), resource.NewSchemaless(
		semconv.ServiceNameKey.String(serviceName),
	))
	if err != nil {
		return nil, fmt.Errorf("build otel resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter, sdktrace.WithBatchTimeout(2*time.Second)),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	return tp.Shutdown, nil
}

// Tracer returns the named tracer — call once per package, package-level,
// same pattern as Go's log/slog loggers.
func Tracer(name string) trace.Tracer {
	return otel.Tracer(name)
}

// RequestIDAttribute is the one correlation identifier every span in this
// API attaches — the same request_id already in every structured log line
// (internal/logging), so a trace and a log line for the same request can
// be joined without inventing a second ID scheme.
func RequestIDAttribute(requestID string) attribute.KeyValue {
	return attribute.String("ayureze.request_id", requestID)
}
