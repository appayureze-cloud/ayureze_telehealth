package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ayureze/telehealth/api/internal/domain"
)

type ParticipantStore struct{ pool *pgxpool.Pool }

func NewParticipantStore(pool *pgxpool.Pool) *ParticipantStore { return &ParticipantStore{pool: pool} }

func scanParticipant(row pgx.Row) (*domain.Participant, error) {
	var p domain.Participant
	if err := row.Scan(&p.ID, &p.SessionID, &p.UserID, &p.Role, &p.Identity, &p.Status, &p.JoinedAt, &p.LeftAt, &p.CreatedAt); err != nil {
		if err == pgx.ErrNoRows {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("scan participant: %w", err)
	}
	return &p, nil
}

const participantColumns = `id, session_id, user_id, role, identity, status, joined_at, left_at, created_at`

// Authorize records that userID/identity is allowed into sessionID with the
// given role. This is the row join-authorization checks against — a valid
// LiveKit token alone is never sufficient (see internal/sessionsvc).
func (s *ParticipantStore) Authorize(ctx context.Context, sessionID string, userID *string, role domain.ParticipantRole, identity string) (*domain.Participant, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO participants (session_id, user_id, role, identity, status)
		VALUES ($1, $2, $3, $4, 'authorized')
		ON CONFLICT (session_id, identity) DO UPDATE SET role = EXCLUDED.role
		RETURNING `+participantColumns,
		sessionID, userID, role, identity)
	return scanParticipant(row)
}

func (s *ParticipantStore) GetBySessionAndIdentity(ctx context.Context, sessionID, identity string) (*domain.Participant, error) {
	row := s.pool.QueryRow(ctx, `SELECT `+participantColumns+` FROM participants WHERE session_id = $1 AND identity = $2`, sessionID, identity)
	return scanParticipant(row)
}

func (s *ParticipantStore) MarkJoined(ctx context.Context, sessionID, identity string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE participants SET status = 'joined', joined_at = now()
		WHERE session_id = $1 AND identity = $2`, sessionID, identity)
	if err != nil {
		return fmt.Errorf("mark participant joined: %w", err)
	}
	return nil
}

func (s *ParticipantStore) MarkLeft(ctx context.Context, sessionID, identity string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE participants SET status = 'left', left_at = now()
		WHERE session_id = $1 AND identity = $2`, sessionID, identity)
	if err != nil {
		return fmt.Errorf("mark participant left: %w", err)
	}
	return nil
}

func (s *ParticipantStore) Revoke(ctx context.Context, sessionID, identity string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE participants SET status = 'revoked'
		WHERE session_id = $1 AND identity = $2`, sessionID, identity)
	if err != nil {
		return fmt.Errorf("revoke participant: %w", err)
	}
	return nil
}

func (s *ParticipantStore) ListBySession(ctx context.Context, sessionID string) ([]domain.Participant, error) {
	rows, err := s.pool.Query(ctx, `SELECT `+participantColumns+` FROM participants WHERE session_id = $1 ORDER BY created_at`, sessionID)
	if err != nil {
		return nil, fmt.Errorf("list participants: %w", err)
	}
	defer rows.Close()

	var out []domain.Participant
	for rows.Next() {
		p, err := scanParticipant(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *p)
	}
	return out, rows.Err()
}
