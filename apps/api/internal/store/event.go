package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

type EventStore struct{ pool *pgxpool.Pool }

func NewEventStore(pool *pgxpool.Pool) *EventStore { return &EventStore{pool: pool} }

func (s *EventStore) Insert(ctx context.Context, sessionID, eventType string, payload map[string]any) error {
	if payload == nil {
		payload = map[string]any{}
	}
	_, err := s.pool.Exec(ctx, `
		INSERT INTO session_events (session_id, event_type, payload)
		VALUES ($1, $2, $3)`, sessionID, eventType, payload)
	if err != nil {
		return fmt.Errorf("insert session event: %w", err)
	}
	return nil
}
