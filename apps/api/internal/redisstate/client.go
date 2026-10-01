// Package redisstate holds everything the platform keeps in Redis:
// short-lived refresh-token state, participant presence per room, and
// distributed rate limiting. Nothing here is a system of record — Postgres
// (internal/store) is; Redis holds only transient/derived state.
package redisstate

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

func NewClient(addr, password string, db int) (*redis.Client, error) {
	client := redis.NewClient(&redis.Options{
		Addr:     addr,
		Password: password,
		DB:       db,
	})
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("ping redis: %w", err)
	}
	return client, nil
}
