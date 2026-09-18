package httpapi

import (
	"log/slog"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// NewRouter wires all HTTP routes. limiter is the rate limiter to apply
// globally — pass a redisstate.RateLimiter in production (shared across
// replicas) or an *IPRateLimiter for a single dev instance.
func NewRouter(srv *Server, logger *slog.Logger, corsOrigins string, limiter RateLimiter) http.Handler {
	r := chi.NewRouter()

	origins := map[string]struct{}{}
	for _, o := range strings.Split(corsOrigins, ",") {
		if o = strings.TrimSpace(o); o != "" {
			origins[o] = struct{}{}
		}
	}

	r.Use(RequestID)
	r.Use(Recover(logger))
	r.Use(AccessLog(logger))
	r.Use(SecurityHeaders)
	r.Use(CORS(origins))
	r.Use(RateLimitMiddleware(limiter))

	r.Get("/health", srv.Health)
	r.Get("/ready", srv.Ready)
	r.Handle("/metrics", promhttp.Handler())

	if srv.webhooks != nil {
		r.Post("/internal/webhooks/livekit", srv.LiveKitWebhook)
	}

	if srv.aiAgentSessions != nil {
		r.Group(func(r chi.Router) {
			r.Use(RequireAIAgentServiceSecret(srv.aiAgentServiceSecret))
			r.Post("/internal/ai-agent/sessions/{id}/authorize", srv.AIAgentAuthorize)
		})
	}

	r.Route("/v1", func(r chi.Router) {
		r.Post("/dev/session-tokens", srv.DevSessionToken)

		if srv.auth != nil {
			r.Post("/auth/login", srv.Login)
			r.Post("/auth/refresh", srv.Refresh)
			r.Post("/auth/logout", srv.Logout)
		}

		if srv.sessions != nil {
			r.Group(func(r chi.Router) {
				r.Use(RequireAuth(srv.issuer))
				r.Post("/sessions", srv.CreateSession)
				r.Get("/sessions/{id}", srv.GetSession)
				r.Post("/sessions/{id}/join", srv.JoinSession)
				r.Post("/sessions/{id}/end", srv.EndSession)
				r.Post("/sessions/{id}/consent/ai-translation/grant", srv.GrantAIConsent)
				r.Post("/sessions/{id}/consent/ai-translation/revoke", srv.RevokeAIConsent)
			})
		}
	})

	return r
}
