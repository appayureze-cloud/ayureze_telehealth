// Package consentsvc provides the Day 3 schema/CRUD for session consent
// (currently just "ai_translation"). Day 4 wires this into the AI agent's
// join authorization; today, granting/revoking has no side effect beyond
// being recorded — there is no AI agent yet to gate.
package consentsvc

import (
	"context"
	"log/slog"

	"github.com/ayureze/telehealth/api/internal/apperr"
	"github.com/ayureze/telehealth/api/internal/domain"
	"github.com/ayureze/telehealth/api/internal/metrics"
	"github.com/ayureze/telehealth/api/internal/roomsvc"
	"github.com/ayureze/telehealth/api/internal/store"
)

type Service struct {
	sessions     *store.SessionStore
	consents     *store.ConsentStore
	participants *store.ParticipantStore
	audit        *store.AuditStore
	events       *store.EventStore
	rooms        *roomsvc.Service
	logger       *slog.Logger
}

func New(sessions *store.SessionStore, consents *store.ConsentStore, participants *store.ParticipantStore, audit *store.AuditStore, events *store.EventStore, rooms *roomsvc.Service, logger *slog.Logger) *Service {
	return &Service{sessions: sessions, consents: consents, participants: participants, audit: audit, events: events, rooms: rooms, logger: logger}
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
	metrics.AIConsentTotal.WithLabelValues("grant").Inc()
	return c, nil
}

// Revoke immediately enforces the revocation, not merely records it: if the
// AI agent is currently a joined participant in this session's room, it is
// forcibly disconnected via LiveKit before this call returns. Patient and
// doctor continue their call unaffected — only the AI agent identity is
// removed.
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
	metrics.AIConsentTotal.WithLabelValues("revoke").Inc()

	s.enforceAIAgentRemoval(ctx, sess, ip)
	return nil
}

func (s *Service) enforceAIAgentRemoval(ctx context.Context, sess *domain.Session, ip string) {
	identity := "ai-agent-" + sess.ID
	participant, err := s.participants.GetBySessionAndIdentity(ctx, sess.ID, identity)
	if err != nil {
		return // AI agent was never authorized in this session — nothing to remove.
	}
	if participant.Status != domain.ParticipantJoined && participant.Status != domain.ParticipantAuthorized {
		return
	}

	removeErr := s.rooms.RemoveParticipant(ctx, sess.RoomName, identity)
	if err := s.participants.Revoke(ctx, sess.ID, identity); err != nil {
		s.logger.Error("ai_agent_participant_revoke_failed", slog.String("session_id", sess.ID), slog.String("error", err.Error()))
	}

	outcome := domain.AuditSuccess
	metadata := map[string]any{}
	if removeErr != nil {
		// Not fatal to the revoke call: the agent may already have left
		// (e.g. LiveKit's own disconnect raced this), or never actually
		// connected despite being "authorized". The participants-table
		// revocation above is what future join/authorize checks rely on
		// regardless.
		outcome = domain.AuditError
		metadata["remove_participant_error"] = removeErr.Error()
	}
	_ = s.events.Insert(ctx, sess.ID, "ai_agent_access_revoked", nil)
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &sess.TenantID, Action: "ai_agent.access_revoked", ResourceType: "session", ResourceID: sess.ID,
		Outcome: outcome, IPAddress: ip, Metadata: metadata,
	})
}
