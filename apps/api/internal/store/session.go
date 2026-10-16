package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ayureze/telehealth/api/internal/domain"
)

type SessionStore struct{ pool *pgxpool.Pool }

func NewSessionStore(pool *pgxpool.Pool) *SessionStore { return &SessionStore{pool: pool} }

func scanSession(row pgx.Row) (*domain.Session, error) {
	var s domain.Session
	if err := row.Scan(
		&s.ID, &s.TenantID, &s.RoomName, &s.Status, &s.CreatedBy, &s.DoctorID, &s.PatientID,
		&s.AITranslationAuthorized, &s.E2EEKeyEncrypted, &s.CreatedAt, &s.StartedAt, &s.EndedAt,
	); err != nil {
		if err == pgx.ErrNoRows {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("scan session: %w", err)
	}
	return &s, nil
}

const sessionColumns = `id, tenant_id, room_name, status, created_by, doctor_id, patient_id,
	ai_translation_authorized, e2ee_key_encrypted, created_at, started_at, ended_at`

func (s *SessionStore) Create(ctx context.Context, tenantID, roomName, createdBy, doctorID, patientID string, e2eeKeyEncrypted []byte) (*domain.Session, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO sessions (tenant_id, room_name, status, created_by, doctor_id, patient_id, e2ee_key_encrypted)
		VALUES ($1, $2, 'created', $3, $4, $5, $6)
		RETURNING `+sessionColumns,
		tenantID, roomName, createdBy, doctorID, patientID, e2eeKeyEncrypted)
	return scanSession(row)
}

// GetByID scopes the lookup to tenantID — the mechanism by which a session
// in one tenant is never visible to a caller from another, regardless of
// whether the caller knows or guesses the session ID.
func (s *SessionStore) GetByID(ctx context.Context, tenantID, id string) (*domain.Session, error) {
	row := s.pool.QueryRow(ctx, `SELECT `+sessionColumns+` FROM sessions WHERE tenant_id = $1 AND id = $2`, tenantID, id)
	return scanSession(row)
}

// GetByRoomName is unscoped by tenant because it's only ever called from
// the LiveKit webhook handler, which learns the room name from LiveKit
// itself (a trusted, signature-verified source) rather than from a
// tenant-scoped caller.
func (s *SessionStore) GetByRoomName(ctx context.Context, roomName string) (*domain.Session, error) {
	row := s.pool.QueryRow(ctx, `SELECT `+sessionColumns+` FROM sessions WHERE room_name = $1`, roomName)
	return scanSession(row)
}

func (s *SessionStore) SetStatus(ctx context.Context, id string, status domain.SessionStatus, setStartedAt, setEndedAt bool) (*domain.Session, error) {
	var query string
	switch {
	case setStartedAt:
		query = `UPDATE sessions SET status = $2, started_at = now() WHERE id = $1 RETURNING ` + sessionColumns
	case setEndedAt:
		query = `UPDATE sessions SET status = $2, ended_at = now() WHERE id = $1 RETURNING ` + sessionColumns
	default:
		query = `UPDATE sessions SET status = $2 WHERE id = $1 RETURNING ` + sessionColumns
	}
	row := s.pool.QueryRow(ctx, query, id, status)
	return scanSession(row)
}

func (s *SessionStore) SetAITranslationAuthorized(ctx context.Context, id string, authorized bool) (*domain.Session, error) {
	row := s.pool.QueryRow(ctx, `
		UPDATE sessions SET ai_translation_authorized = $2 WHERE id = $1
		RETURNING `+sessionColumns, id, authorized)
	return scanSession(row)
}
