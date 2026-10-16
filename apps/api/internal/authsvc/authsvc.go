// Package authsvc implements the login/refresh/logout flow: the real
// authenticated entry point the Day 2 dev-token endpoint stood in for.
package authsvc

import (
	"context"
	"time"

	"github.com/ayureze/telehealth/api/internal/apperr"
	"github.com/ayureze/telehealth/api/internal/authn"
	"github.com/ayureze/telehealth/api/internal/domain"
	"github.com/ayureze/telehealth/api/internal/metrics"
	"github.com/ayureze/telehealth/api/internal/redisstate"
	"github.com/ayureze/telehealth/api/internal/store"
)

type Service struct {
	tenants    *store.TenantStore
	users      *store.UserStore
	audit      *store.AuditStore
	issuer     *authn.Issuer
	refresh    *redisstate.RefreshTokenStore
	accessTTL  time.Duration
	refreshTTL time.Duration
}

func New(tenants *store.TenantStore, users *store.UserStore, audit *store.AuditStore, issuer *authn.Issuer, refresh *redisstate.RefreshTokenStore, accessTTL, refreshTTL time.Duration) *Service {
	return &Service{tenants: tenants, users: users, audit: audit, issuer: issuer, refresh: refresh, accessTTL: accessTTL, refreshTTL: refreshTTL}
}

type TokenPair struct {
	AccessToken  string
	RefreshToken string
	ExpiresAt    time.Time
	User         domain.User
}

// Login never distinguishes "unknown tenant", "unknown email", and "wrong
// password" in its returned error — all three collapse to the same
// apperr.Unauthorized so the API cannot be used to enumerate valid
// tenants/emails. Every attempt (success or failure) is audited.
func (s *Service) Login(ctx context.Context, tenantName, email, password, ip string) (*TokenPair, error) {
	const genericFailure = "invalid credentials"

	tenant, err := s.tenants.GetByName(ctx, tenantName)
	if err != nil {
		s.auditLoginFailure(ctx, nil, email, ip, "tenant_not_found")
		return nil, apperr.Unauthorized(genericFailure)
	}

	user, err := s.users.GetByEmail(ctx, tenant.ID, email)
	if err != nil {
		s.auditLoginFailure(ctx, &tenant.ID, email, ip, "user_not_found")
		return nil, apperr.Unauthorized(genericFailure)
	}

	if !authn.VerifyPassword(user.PasswordHash, password) {
		s.auditLoginFailure(ctx, &tenant.ID, email, ip, "bad_password")
		return nil, apperr.Unauthorized(genericFailure)
	}

	access, exp, err := s.issuer.IssueAccessToken(*user, s.accessTTL)
	if err != nil {
		return nil, apperr.Internal(err)
	}
	refreshTok, err := s.refresh.Issue(ctx, redisstate.RefreshTokenData{UserID: user.ID, TenantID: user.TenantID}, s.refreshTTL)
	if err != nil {
		return nil, apperr.Internal(err)
	}

	uid := user.ID
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &tenant.ID, ActorUserID: &uid, Action: "auth.login", ResourceType: "user", ResourceID: user.ID,
		Outcome: domain.AuditSuccess, IPAddress: ip,
	})
	metrics.AuthLoginTotal.WithLabelValues("success").Inc()

	return &TokenPair{AccessToken: access, RefreshToken: refreshTok, ExpiresAt: exp, User: *user}, nil
}

func (s *Service) auditLoginFailure(ctx context.Context, tenantID *string, email, ip, reason string) {
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: tenantID, Action: "auth.login", ResourceType: "user", ResourceID: email,
		Outcome: domain.AuditDenied, IPAddress: ip, Metadata: map[string]any{"reason": reason},
	})
	metrics.AuthLoginTotal.WithLabelValues("denied").Inc()
}

func (s *Service) Refresh(ctx context.Context, refreshToken, ip string) (*TokenPair, error) {
	data, err := s.refresh.Redeem(ctx, refreshToken)
	if err != nil {
		metrics.AuthRefreshTotal.WithLabelValues("denied").Inc()
		return nil, apperr.Unauthorized("invalid or expired refresh token")
	}

	user, err := s.users.GetByID(ctx, data.TenantID, data.UserID)
	if err != nil {
		metrics.AuthRefreshTotal.WithLabelValues("denied").Inc()
		return nil, apperr.Unauthorized("user no longer exists")
	}

	access, exp, err := s.issuer.IssueAccessToken(*user, s.accessTTL)
	if err != nil {
		return nil, apperr.Internal(err)
	}
	newRefresh, err := s.refresh.Issue(ctx, redisstate.RefreshTokenData{UserID: user.ID, TenantID: user.TenantID}, s.refreshTTL)
	if err != nil {
		return nil, apperr.Internal(err)
	}

	uid := user.ID
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &user.TenantID, ActorUserID: &uid, Action: "auth.refresh", ResourceType: "user", ResourceID: user.ID,
		Outcome: domain.AuditSuccess, IPAddress: ip,
	})
	metrics.AuthRefreshTotal.WithLabelValues("success").Inc()

	return &TokenPair{AccessToken: access, RefreshToken: newRefresh, ExpiresAt: exp, User: *user}, nil
}

func (s *Service) Logout(ctx context.Context, refreshToken string) error {
	return s.refresh.Revoke(ctx, refreshToken)
}
