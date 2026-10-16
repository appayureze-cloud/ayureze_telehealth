package redisstate

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

// RateLimiter is a fixed-window counter shared across all API replicas via
// Redis (replacing the Day 2 in-memory, single-instance limiter).
type RateLimiter struct {
	client *redis.Client
	limit  int
	window time.Duration
}

func NewRateLimiter(client *redis.Client, perMinute int) *RateLimiter {
	if perMinute <= 0 {
		perMinute = 120
	}
	return &RateLimiter{client: client, limit: perMinute, window: time.Minute}
}

// Allow returns true if the caller identified by key has not exceeded the
// configured requests-per-window budget.
func (l *RateLimiter) Allow(ctx context.Context, key string) (bool, error) {
	k := "ratelimit:" + key
	count, err := l.client.Incr(ctx, k).Result()
	if err != nil {
		return false, fmt.Errorf("rate limit incr: %w", err)
	}
	if count == 1 {
		if err := l.client.Expire(ctx, k, l.window).Err(); err != nil {
			return false, fmt.Errorf("rate limit expire: %w", err)
		}
	}
	return count <= int64(l.limit), nil
}
