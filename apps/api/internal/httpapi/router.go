package httpapi

import (
	"log/slog"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func NewRouter(srv *Server, logger *slog.Logger, corsOrigins string, rateLimitPerMinute int) http.Handler {
	r := chi.NewRouter()

	origins := map[string]struct{}{}
	for _, o := range strings.Split(corsOrigins, ",") {
		if o = strings.TrimSpace(o); o != "" {
			origins[o] = struct{}{}
		}
	}
	limiter := NewIPRateLimiter(rateLimitPerMinute)

	r.Use(RequestID)
	r.Use(Recover(logger))
	r.Use(AccessLog(logger))
	r.Use(SecurityHeaders)
	r.Use(CORS(origins))
	r.Use(limiter.Middleware)

	r.Get("/health", srv.Health)
	r.Get("/ready", srv.Ready)
	r.Handle("/metrics", promhttp.Handler())

	r.Route("/v1", func(r chi.Router) {
		r.Post("/dev/session-tokens", srv.DevSessionToken)
	})

	return r
}
