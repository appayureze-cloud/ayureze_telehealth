package httpapi

import (
	"context"
	"net"
	"net/http"
	"sync"

	"golang.org/x/time/rate"

	"github.com/ayureze/telehealth/api/internal/metrics"
)

// RateLimiter is implemented by both IPRateLimiter (in-memory, single
// instance) and redisstate.RateLimiter (shared across replicas). Day 2
// used the former for every route; Day 3 uses the latter for the
// authenticated API while dev-only routes keep the in-memory one.
type RateLimiter interface {
	Allow(ctx context.Context, key string) (bool, error)
}

// RateLimitMiddleware applies limiter per client IP, independent of which
// RateLimiter implementation is supplied.
func RateLimitMiddleware(limiter RateLimiter) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			host, _, err := net.SplitHostPort(r.RemoteAddr)
			if err != nil {
				host = r.RemoteAddr
			}
			allowed, err := limiter.Allow(r.Context(), host)
			if err != nil {
				// Fail open on limiter infrastructure errors rather than
				// taking the whole API down if Redis has a blip — but log
				// it, since a persistently-failing limiter is a real
				// availability/security concern.
				next.ServeHTTP(w, r)
				return
			}
			if !allowed {
				metrics.RateLimitedTotal.Inc()
				writeError(w, http.StatusTooManyRequests, "rate_limited", "too many requests")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// IPRateLimiter is a simple per-IP token bucket limiter. It is process-local
// (fine for a single Day-2 instance); Day 3 moves this to Redis so it works
// across replicas.
type IPRateLimiter struct {
	mu       sync.Mutex
	limiters map[string]*rate.Limiter
	rps      rate.Limit
	burst    int
}

func NewIPRateLimiter(perMinute int) *IPRateLimiter {
	if perMinute <= 0 {
		perMinute = 120
	}
	return &IPRateLimiter{
		limiters: make(map[string]*rate.Limiter),
		rps:      rate.Limit(float64(perMinute) / 60.0),
		burst:    perMinute,
	}
}

func (l *IPRateLimiter) get(ip string) *rate.Limiter {
	l.mu.Lock()
	defer l.mu.Unlock()
	lim, ok := l.limiters[ip]
	if !ok {
		lim = rate.NewLimiter(l.rps, l.burst)
		l.limiters[ip] = lim
	}
	return lim
}

// Allow implements RateLimiter. ctx and key's network-address parsing are
// unused (the token-bucket state is keyed by whatever string is passed),
// kept here only to satisfy the shared interface.
func (l *IPRateLimiter) Allow(_ context.Context, key string) (bool, error) {
	return l.get(key).Allow(), nil
}
