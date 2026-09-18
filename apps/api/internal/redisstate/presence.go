package redisstate

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

// PresenceStore tracks who is currently connected to a room, fed by
// LiveKit participant_joined/participant_left webhooks (internal/webhooks).
// This is operational/observability state, not an authorization source —
// the participants table in Postgres remains authoritative for "is this
// identity allowed here".
type PresenceStore struct {
	client *redis.Client
}

func NewPresenceStore(client *redis.Client) *PresenceStore {
	return &PresenceStore{client: client}
}

func presenceKey(room string) string { return "presence:" + room }

func (s *PresenceStore) MarkJoined(ctx context.Context, room, identity string) error {
	k := presenceKey(room)
	if err := s.client.SAdd(ctx, k, identity).Err(); err != nil {
		return fmt.Errorf("mark presence joined: %w", err)
	}
	// Presence keys expire on their own if a room is abandoned without a
	// clean "left" event, so stale entries don't accumulate forever.
	return s.client.Expire(ctx, k, 24*time.Hour).Err()
}

func (s *PresenceStore) MarkLeft(ctx context.Context, room, identity string) error {
	if err := s.client.SRem(ctx, presenceKey(room), identity).Err(); err != nil {
		return fmt.Errorf("mark presence left: %w", err)
	}
	return nil
}

func (s *PresenceStore) ListPresent(ctx context.Context, room string) ([]string, error) {
	members, err := s.client.SMembers(ctx, presenceKey(room)).Result()
	if err != nil {
		return nil, fmt.Errorf("list presence: %w", err)
	}
	return members, nil
}
