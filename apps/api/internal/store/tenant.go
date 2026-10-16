// Package store is the data-access layer: parameterized SQL queries against
// Postgres, scoped by tenant wherever the underlying table is
// tenant-owned. No caller outside this package writes raw SQL.
package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ayureze/telehealth/api/internal/domain"
)

type TenantStore struct{ pool *pgxpool.Pool }

func NewTenantStore(pool *pgxpool.Pool) *TenantStore { return &TenantStore{pool: pool} }

func (s *TenantStore) GetByID(ctx context.Context, id string) (*domain.Tenant, error) {
	row := s.pool.QueryRow(ctx, `SELECT id, name, created_at FROM tenants WHERE id = $1`, id)
	var t domain.Tenant
	if err := row.Scan(&t.ID, &t.Name, &t.CreatedAt); err != nil {
		if err == pgx.ErrNoRows {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("get tenant: %w", err)
	}
	return &t, nil
}

func (s *TenantStore) GetByName(ctx context.Context, name string) (*domain.Tenant, error) {
	row := s.pool.QueryRow(ctx, `SELECT id, name, created_at FROM tenants WHERE name = $1`, name)
	var t domain.Tenant
	if err := row.Scan(&t.ID, &t.Name, &t.CreatedAt); err != nil {
		if err == pgx.ErrNoRows {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("get tenant by name: %w", err)
	}
	return &t, nil
}

// EnsureByName creates the tenant if it doesn't exist, or returns the
// existing one. Used by the dev seed command only.
func (s *TenantStore) EnsureByName(ctx context.Context, name string) (*domain.Tenant, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO tenants (name) VALUES ($1)
		ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
		RETURNING id, name, created_at`, name)
	var t domain.Tenant
	if err := row.Scan(&t.ID, &t.Name, &t.CreatedAt); err != nil {
		return nil, fmt.Errorf("ensure tenant: %w", err)
	}
	return &t, nil
}
