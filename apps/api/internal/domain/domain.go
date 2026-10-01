// Package domain holds the core data types shared across the session
// platform's storage, authorization, and HTTP layers.
package domain

import "time"

type Role string

const (
	RoleAdmin   Role = "admin"
	RoleDoctor  Role = "doctor"
	RolePatient Role = "patient"
)

func (r Role) Valid() bool {
	switch r {
	case RoleAdmin, RoleDoctor, RolePatient:
		return true
	}
	return false
}

type ParticipantRole string

const (
	ParticipantPatient ParticipantRole = "patient"
	ParticipantDoctor  ParticipantRole = "doctor"
	ParticipantAIAgent ParticipantRole = "ai_agent"
)

type SessionStatus string

const (
	SessionCreated SessionStatus = "created"
	SessionActive  SessionStatus = "active"
	SessionEnded   SessionStatus = "ended"
)

type ParticipantStatus string

const (
	ParticipantAuthorized ParticipantStatus = "authorized"
	ParticipantJoined     ParticipantStatus = "joined"
	ParticipantLeft       ParticipantStatus = "left"
	ParticipantRevoked    ParticipantStatus = "revoked"
)

type ConsentSubject string

const ConsentAITranslation ConsentSubject = "ai_translation"

type ConsentStatus string

const (
	ConsentGranted ConsentStatus = "granted"
	ConsentRevoked ConsentStatus = "revoked"
)

type AuditOutcome string

const (
	AuditSuccess AuditOutcome = "success"
	AuditDenied  AuditOutcome = "denied"
	AuditError   AuditOutcome = "error"
)

type Tenant struct {
	ID        string
	Name      string
	CreatedAt time.Time
}

type User struct {
	ID           string
	TenantID     string
	Email        string
	PasswordHash string
	Role         Role
	DisplayName  string
	CreatedAt    time.Time
}

type Session struct {
	ID                      string
	TenantID                string
	RoomName                string
	Status                  SessionStatus
	CreatedBy               string
	DoctorID                string
	PatientID               string
	AITranslationAuthorized bool
	// E2EEKeyEncrypted is the envelope-encrypted (never plaintext)
	// per-session media key. It must never be marshaled into an API
	// response or log line — see internal/e2ee and internal/sessionsvc,
	// which decrypt it only at the point of handing it to an authorized,
	// just-joined participant.
	E2EEKeyEncrypted []byte
	CreatedAt        time.Time
	StartedAt        *time.Time
	EndedAt          *time.Time
}

type Participant struct {
	ID        string
	SessionID string
	UserID    *string
	Role      ParticipantRole
	Identity  string
	Status    ParticipantStatus
	JoinedAt  *time.Time
	LeftAt    *time.Time
	CreatedAt time.Time
}

type Consent struct {
	ID              string
	SessionID       string
	Subject         ConsentSubject
	Status          ConsentStatus
	GrantedByUserID string
	GrantedAt       *time.Time
	RevokedAt       *time.Time
	CreatedAt       time.Time
}
