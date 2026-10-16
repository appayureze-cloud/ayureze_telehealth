package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ayureze/telehealth/api/internal/domain"
)

type UserStore struct{ pool *pgxpool.Pool }

func NewUserStore(pool *pgxpool.Pool) *UserStore { return &UserStore{pool: pool} }

func scanUser(row pgx.Row) (*domain.User, error) {
	var u domain.User
	if err := row.Scan(&u.ID, &u.TenantID, &u.Email, &u.PasswordHash, &u.Role, &u.DisplayName, &u.CreatedAt); err != nil {
		if err == pgx.ErrNoRows {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("scan user: %w", err)
	}
	return &u, nil
}

// GetByEmail looks up a user by email *within a tenant*. Login always
// requires a tenant to be known first (see internal/authn) — there is
// deliberately no cross-tenant "find by email alone" query, since that
// would let one tenant's login path leak whether an email exists in
// another tenant.
func (s *UserStore) GetByEmail(ctx context.Context, tenantID, email string) (*domain.User, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, tenant_id, email, password_hash, role, display_name, created_at
		FROM users WHERE tenant_id = $1 AND email = $2`, tenantID, email)
	return scanUser(row)
}

func (s *UserStore) GetByID(ctx context.Context, tenantID, id string) (*domain.User, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, tenant_id, email, password_hash, role, display_name, created_at
		FROM users WHERE tenant_id = $1 AND id = $2`, tenantID, id)
	return scanUser(row)
}

// Create inserts a user. Only used by the dev seed command today — real
// provisioning (from the main AyurEze platform) is a future integration.
func (s *UserStore) Create(ctx context.Context, u domain.User) (*domain.User, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO users (tenant_id, email, password_hash, role, display_name)
		VALUES ($1, $2, $3, $4, $5)
		ON CONFLICT (tenant_id, email) DO UPDATE SET
			password_hash = EXCLUDED.password_hash,
			role = EXCLUDED.role,
			display_name = EXCLUDED.display_name
		RETURNING id, tenant_id, email, password_hash, role, display_name, created_at`,
		u.TenantID, u.Email, u.PasswordHash, u.Role, u.DisplayName)
	return scanUser(row)
}
