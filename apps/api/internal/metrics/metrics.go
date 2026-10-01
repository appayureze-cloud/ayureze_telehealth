// Package metrics defines the Go API's Prometheus metrics in one place so
// both internal/httpapi (HTTP-layer metrics) and the service layer
// (internal/sessionsvc, internal/consentsvc — security/business-event
// metrics) can record to them without an import cycle.
package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Prometheus metrics for the Go API — scraped by
// observability/prometheus/prometheus.yml's ayureze-api job (Day 1).
// Never labeled with anything that could identify a person or reveal
// call content (tenant/session/user IDs are opaque UUIDs, never emails or
// names) — see docs/monitoring/privacy.md.
var (
	HTTPRequestsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "ayureze_api_http_requests_total", Help: "HTTP requests by route and status class"},
		[]string{"method", "route", "status_class"},
	)
	HTTPRequestDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "ayureze_api_http_request_duration_seconds",
			Help:    "HTTP request latency by route",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"method", "route"},
	)

	AuthLoginTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "ayureze_api_auth_login_total", Help: "Login attempts by outcome"},
		[]string{"outcome"}, // success | denied
	)
	AuthRefreshTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "ayureze_api_auth_refresh_total", Help: "Refresh-token exchanges by outcome"},
		[]string{"outcome"},
	)

	SessionsCreatedTotal = promauto.NewCounter(
		prometheus.CounterOpts{Name: "ayureze_api_sessions_created_total", Help: "Sessions created"},
	)
	SessionsJoinedTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "ayureze_api_sessions_joined_total", Help: "Session join attempts by role and outcome"},
		[]string{"role", "outcome"}, // outcome: success | denied
	)
	SessionsEndedTotal = promauto.NewCounter(
		prometheus.CounterOpts{Name: "ayureze_api_sessions_ended_total", Help: "Sessions ended"},
	)

	// SecurityDeniedTotal covers every authorization decision the build
	// spec's security-events list calls out by name: unauthorized
	// participant, wrong room, wrong tenant, expired/invalid token, AI
	// without/after-revoked consent, invalid role, ended-session access —
	// each is one of these reasons at one of these actions.
	SecurityDeniedTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "ayureze_api_security_denied_total", Help: "Authorization decisions that were denied, by action and reason"},
		[]string{"action", "reason"},
	)

	RateLimitedTotal = promauto.NewCounter(
		prometheus.CounterOpts{Name: "ayureze_api_rate_limited_total", Help: "Requests rejected by the rate limiter"},
	)

	AIConsentTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "ayureze_api_ai_consent_total", Help: "AI-translation consent grant/revoke calls"},
		[]string{"action"}, // grant | revoke
	)
)
