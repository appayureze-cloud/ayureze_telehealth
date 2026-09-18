// Package sessionsvc implements session create/join/end, participant
// authorization, and consent — the authenticated replacement for the Day 2
// dev-token endpoint. Join-authorization is enforced against the
// participants table (who was explicitly authorized when the session was
// created), never merely against "presented a syntactically valid token".
package sessionsvc

import (
	"context"
	"encoding/base64"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/ayureze/telehealth/api/internal/apperr"
	"github.com/ayureze/telehealth/api/internal/domain"
	"github.com/ayureze/telehealth/api/internal/e2ee"
	"github.com/ayureze/telehealth/api/internal/metrics"
	"github.com/ayureze/telehealth/api/internal/roomsvc"
	"github.com/ayureze/telehealth/api/internal/store"
	"github.com/ayureze/telehealth/api/internal/token"
)

type Service struct {
	sessions     *store.SessionStore
	participants *store.ParticipantStore
	consents     *store.ConsentStore
	users        *store.UserStore
	audit        *store.AuditStore
	events       *store.EventStore
	minter       *token.Minter
	rooms        *roomsvc.Service
	keys         *e2ee.KeyManager
	joinTokenTTL time.Duration
}

func New(sessions *store.SessionStore, participants *store.ParticipantStore, consents *store.ConsentStore, users *store.UserStore, audit *store.AuditStore, events *store.EventStore, minter *token.Minter, rooms *roomsvc.Service, keys *e2ee.KeyManager, joinTokenTTL time.Duration) *Service {
	return &Service{sessions: sessions, participants: participants, consents: consents, users: users, audit: audit, events: events, minter: minter, rooms: rooms, keys: keys, joinTokenTTL: joinTokenTTL}
}

type Caller struct {
	UserID   string
	TenantID string
	Role     domain.Role
}

// Create authorizes exactly the doctor and patient named in the request as
// this session's participants — nobody else, including other users in the
// same tenant, can ever join it (see Join).
func (s *Service) Create(ctx context.Context, caller Caller, patientEmail string, ip string) (*domain.Session, error) {
	if caller.Role != domain.RoleDoctor && caller.Role != domain.RoleAdmin {
		s.deny(ctx, caller, "session.create", "session", "", ip, "role_not_permitted")
		return nil, apperr.Forbidden("only a doctor or admin may create a session")
	}

	patient, err := s.users.GetByEmail(ctx, caller.TenantID, patientEmail)
	if err != nil {
		return nil, apperr.NotFound("patient not found in this tenant")
	}
	if patient.Role != domain.RolePatient {
		return nil, apperr.Invalid("target user is not a patient")
	}

	doctorID := caller.UserID
	if caller.Role == domain.RoleAdmin {
		return nil, apperr.Invalid("admin-created sessions must specify a doctor (not yet supported)")
	}

	// Generate this session's E2EE media key now, envelope-encrypted before
	// it ever touches the database. The plaintext is discarded here and
	// only re-derived (by decrypting the stored ciphertext) at the moment
	// an authorized participant joins — see Join below.
	_, encryptedKey, err := s.keys.GenerateSessionKey()
	if err != nil {
		return nil, apperr.Internal(err)
	}

	roomName := fmt.Sprintf("session-%s", uuid.NewString())
	sess, err := s.sessions.Create(ctx, caller.TenantID, roomName, caller.UserID, doctorID, patient.ID, encryptedKey)
	if err != nil {
		return nil, apperr.Internal(err)
	}

	if err := s.rooms.EnsureRoom(ctx, roomName, 300); err != nil {
		return nil, apperr.Internal(err)
	}

	doctorUser, _ := s.users.GetByID(ctx, caller.TenantID, doctorID)
	if _, err := s.participants.Authorize(ctx, sess.ID, &doctorID, domain.ParticipantDoctor, identityFor(doctorUser)); err != nil {
		return nil, apperr.Internal(err)
	}
	if _, err := s.participants.Authorize(ctx, sess.ID, &patient.ID, domain.ParticipantPatient, identityFor(patient)); err != nil {
		return nil, apperr.Internal(err)
	}

	_ = s.events.Insert(ctx, sess.ID, "session_created", map[string]any{"room_name": roomName})
	s.allow(ctx, caller, "session.create", "session", sess.ID, ip, nil)
	metrics.SessionsCreatedTotal.Inc()

	return sess, nil
}

func identityFor(u *domain.User) string {
	if u == nil {
		return ""
	}
	return u.ID
}

type JoinResult struct {
	Session     *domain.Session
	AccessToken string
	Room        string
	ExpiresAt   time.Time
	// E2EEKeyBase64 is the session's media-encryption key, decrypted only
	// for this response. Only ever returned over the authenticated,
	// TLS-protected join response to a participant who just passed the
	// authorization checks above — never logged (see internal/logging's
	// redaction) and never included in any GET/list response.
	E2EEKeyBase64 string
}

// Join is the authorization boundary: it checks the caller against the
// session's own tenant, doctor_id/patient_id (or admin), and non-ended
// status — all four must hold before a LiveKit token is ever minted. This
// is what makes "wrong session", "wrong tenant", and "ended session" all
// fail closed rather than relying on token possession alone.
func (s *Service) Join(ctx context.Context, caller Caller, sessionID, ip string) (*JoinResult, error) {
	sess, err := s.sessions.GetByID(ctx, caller.TenantID, sessionID)
	if err != nil {
		s.deny(ctx, caller, "session.join", "session", sessionID, ip, "not_found_or_wrong_tenant")
		return nil, apperr.NotFound("session not found")
	}

	if sess.Status == domain.SessionEnded {
		s.deny(ctx, caller, "session.join", "session", sessionID, ip, "session_ended")
		return nil, apperr.Conflict("session has ended")
	}

	var role domain.ParticipantRole
	switch {
	case caller.Role == domain.RoleAdmin:
		role = domain.ParticipantDoctor // admin observes with doctor-equivalent grants
	case caller.UserID == sess.DoctorID:
		role = domain.ParticipantDoctor
	case caller.UserID == sess.PatientID:
		role = domain.ParticipantPatient
	default:
		s.deny(ctx, caller, "session.join", "session", sessionID, ip, "not_a_participant")
		return nil, apperr.Forbidden("you are not a participant in this session")
	}

	identity := caller.UserID
	participant, err := s.participants.GetBySessionAndIdentity(ctx, sess.ID, identity)
	if err != nil || participant.Status == domain.ParticipantRevoked {
		s.deny(ctx, caller, "session.join", "session", sessionID, ip, "not_authorized_participant")
		return nil, apperr.Forbidden("not authorized to join this session")
	}

	if sess.Status == domain.SessionCreated {
		sess, err = s.sessions.SetStatus(ctx, sess.ID, domain.SessionActive, true, false)
		if err != nil {
			return nil, apperr.Internal(err)
		}
		_ = s.events.Insert(ctx, sess.ID, "session_started", nil)
	}

	minted, err := s.minter.Mint(token.MintRequest{
		Room:     sess.RoomName,
		Identity: identity,
		Name:     identity,
		Role:     token.Role(role),
		TTL:      s.joinTokenTTL,
	})
	if err != nil {
		return nil, apperr.Internal(err)
	}

	plainKey, err := s.keys.Decrypt(sess.E2EEKeyEncrypted)
	if err != nil {
		return nil, apperr.Internal(fmt.Errorf("decrypt session e2ee key: %w", err))
	}

	_ = s.events.Insert(ctx, sess.ID, "join_authorized", map[string]any{"identity": identity, "role": string(role)})
	s.allow(ctx, caller, "session.join", "session", sess.ID, ip, map[string]any{"role": string(role)})
	metrics.SessionsJoinedTotal.WithLabelValues(string(role), "success").Inc()

	return &JoinResult{
		Session:       sess,
		AccessToken:   minted.AccessToken,
		Room:          minted.Room,
		ExpiresAt:     minted.ExpiresAt,
		E2EEKeyBase64: base64.StdEncoding.EncodeToString(plainKey),
	}, nil
}

// End is restricted to the session's own doctor or an admin — a patient
// cannot unilaterally end a consultation.
func (s *Service) End(ctx context.Context, caller Caller, sessionID, ip string) (*domain.Session, error) {
	sess, err := s.sessions.GetByID(ctx, caller.TenantID, sessionID)
	if err != nil {
		return nil, apperr.NotFound("session not found")
	}
	if caller.Role != domain.RoleAdmin && caller.UserID != sess.DoctorID {
		s.deny(ctx, caller, "session.end", "session", sessionID, ip, "not_permitted")
		return nil, apperr.Forbidden("only the session's doctor or an admin may end it")
	}
	if sess.Status == domain.SessionEnded {
		return sess, nil
	}

	sess, err = s.sessions.SetStatus(ctx, sess.ID, domain.SessionEnded, false, true)
	if err != nil {
		return nil, apperr.Internal(err)
	}
	if err := s.rooms.DeleteRoom(ctx, sess.RoomName); err != nil {
		// Room may already be gone (e.g. empty_timeout fired first) — this
		// is not a reason to fail ending the session in our system of
		// record.
		_ = err
	}
	_ = s.events.Insert(ctx, sess.ID, "session_ended", nil)
	s.allow(ctx, caller, "session.end", "session", sess.ID, ip, nil)
	metrics.SessionsEndedTotal.Inc()
	return sess, nil
}

func (s *Service) Get(ctx context.Context, caller Caller, sessionID string) (*domain.Session, []domain.Participant, error) {
	sess, err := s.sessions.GetByID(ctx, caller.TenantID, sessionID)
	if err != nil {
		return nil, nil, apperr.NotFound("session not found")
	}
	if caller.Role != domain.RoleAdmin && caller.UserID != sess.DoctorID && caller.UserID != sess.PatientID {
		return nil, nil, apperr.Forbidden("not a participant in this session")
	}
	participants, err := s.participants.ListBySession(ctx, sess.ID)
	if err != nil {
		return nil, nil, apperr.Internal(err)
	}
	return sess, participants, nil
}

type AIAgentJoinResult struct {
	Session       *domain.Session
	AccessToken   string
	Room          string
	Identity      string
	ExpiresAt     time.Time
	E2EEKeyBase64 string
}

// AuthorizeAIAgent is the single enforcement point for "the AI agent may
// never join without explicit, currently-active consent" (see
// docs/e2ee/README.md, Mode B). It is called by the AI agent service
// itself (Day 5), authenticated separately via a service credential rather
// than a human login — see httpapi.WithAIAgentAuth. Every call, allowed or
// denied, is audited with no ActorUserID (there is no human caller) but a
// clear action name so "AI without consent" and "AI after consent
// revoked" are both distinguishable in the audit trail.
func (s *Service) AuthorizeAIAgent(ctx context.Context, tenantID, sessionID, ip string) (*AIAgentJoinResult, error) {
	sess, err := s.sessions.GetByID(ctx, tenantID, sessionID)
	if err != nil {
		s.auditSystem(ctx, tenantID, "ai_agent.authorize", sessionID, ip, domain.AuditDenied, "not_found_or_wrong_tenant")
		return nil, apperr.NotFound("session not found")
	}
	if sess.Status == domain.SessionEnded {
		s.auditSystem(ctx, tenantID, "ai_agent.authorize", sess.ID, ip, domain.AuditDenied, "session_ended")
		return nil, apperr.Conflict("session has ended")
	}

	consent, err := s.consents.ActiveFor(ctx, sess.ID, domain.ConsentAITranslation)
	if err != nil {
		s.auditSystem(ctx, tenantID, "ai_agent.authorize", sess.ID, ip, domain.AuditDenied, "no_active_consent")
		return nil, apperr.Forbidden("AI translation has not been authorized (or was revoked) for this session")
	}

	identity := "ai-agent-" + sess.ID
	if _, err := s.participants.Authorize(ctx, sess.ID, nil, domain.ParticipantAIAgent, identity); err != nil {
		return nil, apperr.Internal(err)
	}

	minted, err := s.minter.Mint(token.MintRequest{
		Room:     sess.RoomName,
		Identity: identity,
		Name:     "AI Translation Agent",
		Role:     token.RoleAIAgent,
		TTL:      s.joinTokenTTL,
	})
	if err != nil {
		return nil, apperr.Internal(err)
	}

	plainKey, err := s.keys.Decrypt(sess.E2EEKeyEncrypted)
	if err != nil {
		return nil, apperr.Internal(fmt.Errorf("decrypt session e2ee key: %w", err))
	}

	_ = s.events.Insert(ctx, sess.ID, "ai_agent_authorized", map[string]any{"consent_id": consent.ID})
	s.auditSystem(ctx, tenantID, "ai_agent.authorize", sess.ID, ip, domain.AuditSuccess, "")

	return &AIAgentJoinResult{
		Session:       sess,
		AccessToken:   minted.AccessToken,
		Room:          minted.Room,
		Identity:      identity,
		ExpiresAt:     minted.ExpiresAt,
		E2EEKeyBase64: base64.StdEncoding.EncodeToString(plainKey),
	}, nil
}

func (s *Service) auditSystem(ctx context.Context, tenantID, action, resourceID, ip string, outcome domain.AuditOutcome, reason string) {
	metadata := map[string]any{}
	if reason != "" {
		metadata["reason"] = reason
	}
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &tenantID, Action: action, ResourceType: "session", ResourceID: resourceID,
		Outcome: outcome, IPAddress: ip, Metadata: metadata,
	})
	if outcome == domain.AuditDenied {
		metrics.SecurityDeniedTotal.WithLabelValues(action, reason).Inc()
	}
}

func (s *Service) deny(ctx context.Context, caller Caller, action, resourceType, resourceID, ip, reason string) {
	uid := caller.UserID
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &caller.TenantID, ActorUserID: &uid, Action: action, ResourceType: resourceType, ResourceID: resourceID,
		Outcome: domain.AuditDenied, IPAddress: ip, Metadata: map[string]any{"reason": reason},
	})
	metrics.SecurityDeniedTotal.WithLabelValues(action, reason).Inc()
}

func (s *Service) allow(ctx context.Context, caller Caller, action, resourceType, resourceID, ip string, metadata map[string]any) {
	uid := caller.UserID
	_ = s.audit.Insert(ctx, store.AuditRecord{
		TenantID: &caller.TenantID, ActorUserID: &uid, Action: action, ResourceType: resourceType, ResourceID: resourceID,
		Outcome: domain.AuditSuccess, IPAddress: ip, Metadata: metadata,
	})
}
