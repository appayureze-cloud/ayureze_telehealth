package httpapi

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"

	"github.com/ayureze/telehealth/api/internal/metrics"
	"github.com/ayureze/telehealth/api/internal/tracing"
)

type ctxKey string

const requestIDKey ctxKey = "request_id"

func RequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-Id")
		if id == "" {
			id = uuid.NewString()
		}
		w.Header().Set("X-Request-Id", id)
		ctx := context.WithValue(r.Context(), requestIDKey, id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func RequestIDFromContext(ctx context.Context) string {
	if v, ok := ctx.Value(requestIDKey).(string); ok {
		return v
	}
	return ""
}

// TraceSpan starts one root span per HTTP request — the "API request"
// entry point of the trace docs/monitoring/README.md's tracing section
// describes (API request -> session service -> LiveKit interaction). Named
// after the chi route pattern, never the raw path (same unbounded-
// cardinality reasoning as AccessLog's Prometheus labels below), and
// carries only the request_id correlation attribute plus method/status —
// no request/response body, no header values, nothing session-content-
// shaped. internal/sessionsvc/internal/roomsvc add their own child spans
// from the context this middleware puts in place.
func TraceSpan(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		route := r.URL.Path
		if rctx := chi.RouteContext(r.Context()); rctx != nil {
			if pattern := rctx.RoutePattern(); pattern != "" {
				route = pattern
			}
		}
		ctx, span := tracing.Tracer("ayureze.api").Start(r.Context(), fmt.Sprintf("%s %s", r.Method, route))
		defer span.End()
		span.SetAttributes(
			tracing.RequestIDAttribute(RequestIDFromContext(ctx)),
			attribute.String("http.method", r.Method),
			attribute.String("http.route", route),
		)

		sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(sw, r.WithContext(ctx))

		span.SetAttributes(attribute.Int("http.status_code", sw.status))
		if sw.status >= 500 {
			span.SetStatus(codes.Error, fmt.Sprintf("http %d", sw.status))
		}
	})
}

// AccessLog emits one structured JSON log line per request and records
// Prometheus request-count/latency metrics. It never logs request/response
// bodies (which could contain tokens) — only metadata. Metrics are labeled
// by the chi *route pattern* (e.g. "/v1/sessions/{id}/join"), never the raw
// path — using raw paths (which contain session/resource IDs) as a label
// would give Prometheus unbounded cardinality, a classic production
// observability mistake this deliberately avoids.
func AccessLog(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(sw, r)
			elapsed := time.Since(start)

			route := r.URL.Path
			if rctx := chi.RouteContext(r.Context()); rctx != nil {
				if pattern := rctx.RoutePattern(); pattern != "" {
					route = pattern
				}
			}
			statusClass := fmt.Sprintf("%dxx", sw.status/100)
			metrics.HTTPRequestsTotal.WithLabelValues(r.Method, route, statusClass).Inc()
			metrics.HTTPRequestDuration.WithLabelValues(r.Method, route).Observe(elapsed.Seconds())

			logger.Info("http_request",
				slog.String("event_type", "http_request"),
				slog.String("request_id", RequestIDFromContext(r.Context())),
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Int("status", sw.status),
				slog.Int64("latency_ms", elapsed.Milliseconds()),
			)
		})
	}
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(code int) {
	w.status = code
	w.ResponseWriter.WriteHeader(code)
}

func Recover(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if err := recover(); err != nil {
					logger.Error("panic_recovered",
						slog.String("event_type", "panic_recovered"),
						slog.String("request_id", RequestIDFromContext(r.Context())),
						slog.Any("error", err),
					)
					http.Error(w, `{"error":"internal_server_error"}`, http.StatusInternalServerError)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

// CORS restricts browser access to an explicit allow-list read from
// API_CORS_ALLOWED_ORIGINS. It never reflects "*" with credentials.
func CORS(allowedOrigins map[string]struct{}) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := r.Header.Get("Origin")
			if _, ok := allowedOrigins[origin]; ok {
				w.Header().Set("Access-Control-Allow-Origin", origin)
				w.Header().Set("Vary", "Origin")
				w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
				w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
			}
			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// SecurityHeaders sets baseline defensive headers on every response.
func SecurityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		next.ServeHTTP(w, r)
	})
}
