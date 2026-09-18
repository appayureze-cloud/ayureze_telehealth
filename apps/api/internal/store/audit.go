package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ayureze/telehealth/api/internal/domain"
)

type AuditStore struct{ pool *pgxpool.Pool }

func NewAuditStore(pool *pgxpool.Pool) *AuditStore { return &AuditStore{pool: pool} }

type AuditRecord struct {
	TenantID     *string
	ActorUserID  *string
	Action       string
	ResourceType string
	ResourceID   string
	Outcome      domain.AuditOutcome
	Metadata     map[string]any
	IPAddress    string
}

// Insert never stores request/response bodies, tokens, or medical content —
// only the identifying/decision metadata listed in AuditRecord. See
// docs/monitoring/privacy.md.
func (s *AuditStore) Insert(ctx context.Context, r AuditRecord) error {
	var ip any
	if r.IPAddress != "" {
		ip = r.IPAddress
	}
	metadata := r.Metadata
	if metadata == nil {
		metadata = map[string]any{}
	}
	_, err := s.pool.Exec(ctx, `
		INSERT INTO audit_events (tenant_id, actor_user_id, action, resource_type, resource_id, outcome, metadata, ip_address)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
		r.TenantID, r.ActorUserID, r.Action, r.ResourceType, nullableString(r.ResourceID), r.Outcome, metadata, ip)
	if err != nil {
		return fmt.Errorf("insert audit event: %w", err)
	}
	return nil
}

func nullableString(s string) any {
	if s == "" {
		return nil
	}
	return s
}
