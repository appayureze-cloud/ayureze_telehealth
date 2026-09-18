package httpapi

import (
	"net"
	"net/http"
	"sync"

	"golang.org/x/time/rate"
)

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

func (l *IPRateLimiter) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := net.SplitHostPort(r.RemoteAddr)
		if err != nil {
			host = r.RemoteAddr
		}
		if !l.get(host).Allow() {
			writeError(w, http.StatusTooManyRequests, "rate_limited", "too many requests")
			return
		}
		next.ServeHTTP(w, r)
	})
}
