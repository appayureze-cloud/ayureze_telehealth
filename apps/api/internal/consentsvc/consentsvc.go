// Package consentsvc provides the Day 3 schema/CRUD for session consent
// (currently just "ai_translation"). Day 4 wires this into the AI agent's
// join authorization; today, granting/revoking has no side effect beyond
// being recorded — there is no AI agent yet to gate.
package consentsvc

import (
	"context"

	"github.com/ayureze/telehealth/api/internal/apperr"
	"github.com/ayureze/telehealth/api/internal/domain"
	"github.com/ayureze/telehealth/api/internal/store"
)

type Service struct {
	sessions *store.SessionStore
	consents *store.ConsentStore
	audit    *store.AuditStore
	events   *store.EventStore
}

func New(sessions *store.SessionStore, consents *store.ConsentStore, audit *store.AuditStore, events *store.EventStore) *Service {
	return &Service{sessions: sessions, consents: consents, audit: audit, events: events}
}

type Caller struct {
	UserID   string
	TenantID string
	Role     domain.Role
}

func (s *Service) mustBeParticipant(ctx context.Context, caller Caller, sessionID string) (*domain.Session, error) {
	sess, err := s.sessions.GetByID(ctx, caller.TenantID, sessionID)
	if err != nil {
		return nil, apperr.NotFound("session not found")
	}
	if caller.Role != domain.RoleAdmin && caller.UserID != sess.DoctorID && caller.UserID != sess.PatientID {
		return nil, apperr.Forbidden("not a participant in this session")
	}
	return sess, nil
}

// Grant records consent to AI translation for a session. Either the
// doctor or the patient in that session may grant it — Day 4's
// authorization check for the AI agent additionally requires this to
// still be the *current* status (see store.ConsentStore.ActiveFor).
func (s *Service) Grant(ctx context.Context, caller Caller, sessionID, ip string) (*domain.Consent, error) {
	sess, err := s.mustBeParticipant(ctx, caller, sessionID)
	if err != nil {
		return nil, err
	}
	c, err := s.consents.Grant(ctx, sess.ID, domain.ConsentAITranslation, caller.UserID)
	if err != nil {
		return nil, apperr.Internal(err)
	}
	_ = s.events.Insert(ctx, sess.ID, "consent_granted", map[string]any{"subject": string(domain.ConsentAITranslation)})
	uid := caller.UserID
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &caller.TenantID, ActorUserID: &uid, Action: "consent.grant", ResourceType: "session", ResourceID: sess.ID,
		Outcome: domain.AuditSuccess, IPAddress: ip,
	})
	return c, nil
}

func (s *Service) Revoke(ctx context.Context, caller Caller, sessionID, ip string) error {
	sess, err := s.mustBeParticipant(ctx, caller, sessionID)
	if err != nil {
		return err
	}
	active, err := s.consents.ActiveFor(ctx, sess.ID, domain.ConsentAITranslation)
	if err != nil {
		return apperr.Conflict("no active consent to revoke")
	}
	if _, err := s.consents.Revoke(ctx, active.ID); err != nil {
		return apperr.Internal(err)
	}
	_ = s.events.Insert(ctx, sess.ID, "consent_revoked", map[string]any{"subject": string(domain.ConsentAITranslation)})
	uid := caller.UserID
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &caller.TenantID, ActorUserID: &uid, Action: "consent.revoke", ResourceType: "session", ResourceID: sess.ID,
		Outcome: domain.AuditSuccess, IPAddress: ip,
	})
	return nil
}
