package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ayureze/telehealth/api/internal/domain"
)

type ConsentStore struct{ pool *pgxpool.Pool }

func NewConsentStore(pool *pgxpool.Pool) *ConsentStore { return &ConsentStore{pool: pool} }

const consentColumns = `id, session_id, subject, status, granted_by_user_id, granted_at, revoked_at, created_at`

func scanConsent(row pgx.Row) (*domain.Consent, error) {
	var c domain.Consent
	if err := row.Scan(&c.ID, &c.SessionID, &c.Subject, &c.Status, &c.GrantedByUserID, &c.GrantedAt, &c.RevokedAt, &c.CreatedAt); err != nil {
		if err == pgx.ErrNoRows {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("scan consent: %w", err)
	}
	return &c, nil
}

func (s *ConsentStore) Grant(ctx context.Context, sessionID string, subject domain.ConsentSubject, grantedByUserID string) (*domain.Consent, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO consents (session_id, subject, status, granted_by_user_id, granted_at)
		VALUES ($1, $2, 'granted', $3, now())
		RETURNING `+consentColumns,
		sessionID, subject, grantedByUserID)
	return scanConsent(row)
}

func (s *ConsentStore) Revoke(ctx context.Context, id string) (*domain.Consent, error) {
	row := s.pool.QueryRow(ctx, `
		UPDATE consents SET status = 'revoked', revoked_at = now() WHERE id = $1
		RETURNING `+consentColumns, id)
	return scanConsent(row)
}

// ActiveFor returns the most recent consent row for (sessionID, subject) if
// its status is currently 'granted', or ErrNotFound otherwise. This is the
// single source of truth Day 4's AI-join authorization check reads from.
func (s *ConsentStore) ActiveFor(ctx context.Context, sessionID string, subject domain.ConsentSubject) (*domain.Consent, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT `+consentColumns+` FROM consents
		WHERE session_id = $1 AND subject = $2 AND status = 'granted'
		ORDER BY created_at DESC LIMIT 1`, sessionID, subject)
	return scanConsent(row)
}

func (s *ConsentStore) ListBySession(ctx context.Context, sessionID string) ([]domain.Consent, error) {
	rows, err := s.pool.Query(ctx, `SELECT `+consentColumns+` FROM consents WHERE session_id = $1 ORDER BY created_at`, sessionID)
	if err != nil {
		return nil, fmt.Errorf("list consents: %w", err)
	}
	defer rows.Close()
	var out []domain.Consent
	for rows.Next() {
		c, err := scanConsent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *c)
	}
	return out, rows.Err()
}
