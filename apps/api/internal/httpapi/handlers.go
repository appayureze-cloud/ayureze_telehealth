package httpapi

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	lkauth "github.com/livekit/protocol/auth"

	"github.com/ayureze/telehealth/api/internal/apperr"
	"github.com/ayureze/telehealth/api/internal/authn"
	"github.com/ayureze/telehealth/api/internal/authsvc"
	"github.com/ayureze/telehealth/api/internal/consentsvc"
	"github.com/ayureze/telehealth/api/internal/roomsvc"
	"github.com/ayureze/telehealth/api/internal/sessionsvc"
	"github.com/ayureze/telehealth/api/internal/token"
	"github.com/ayureze/telehealth/api/internal/webhooksvc"
)

type Server struct {
	logger      *slog.Logger
	minter      *token.Minter
	rooms       *roomsvc.Service
	devTokenTTL time.Duration
	environment string

	issuer   *authn.Issuer
	auth     *authsvc.Service
	sessions *sessionsvc.Service
	consents *consentsvc.Service

	webhookKeyProvider *lkauth.SimpleKeyProvider
	webhooks           *webhooksvc.Service

	dbPing    func(context.Context) error
	redisPing func(context.Context) error
}

func NewServer(logger *slog.Logger, minter *token.Minter, rooms *roomsvc.Service, devTokenTTL time.Duration, environment string) *Server {
	return &Server{logger: logger, minter: minter, rooms: rooms, devTokenTTL: devTokenTTL, environment: environment}
}

// WithAuthenticatedServices wires in the Day 3 authenticated login/session
// platform. Left unset, only the Day 2 dev-token endpoint and health checks
// are available (used by lightweight tests that don't need a database).
func (s *Server) WithAuthenticatedServices(issuer *authn.Issuer, auth *authsvc.Service, sessions *sessionsvc.Service, consents *consentsvc.Service) *Server {
	s.issuer = issuer
	s.auth = auth
	s.sessions = sessions
	s.consents = consents
	return s
}

func (s *Server) WithReadiness(dbPing, redisPing func(context.Context) error) *Server {
	s.dbPing = dbPing
	s.redisPing = redisPing
	return s
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]string{"error": code, "message": message})
}

// writeAppError maps internal/apperr kinds to HTTP status codes in one
// place, so authorization decisions made in the service layer are never
// re-interpreted (and potentially loosened) by a handler.
func writeAppError(w http.ResponseWriter, err error) {
	appErr, ok := apperr.As(err)
	if !ok {
		writeError(w, http.StatusInternalServerError, "internal_error", "an internal error occurred")
		return
	}
	status := http.StatusInternalServerError
	switch appErr.Kind {
	case apperr.KindNotFound:
		status = http.StatusNotFound
	case apperr.KindForbidden:
		status = http.StatusForbidden
	case apperr.KindUnauthorized:
		status = http.StatusUnauthorized
	case apperr.KindConflict:
		status = http.StatusConflict
	case apperr.KindInvalid:
		status = http.StatusBadRequest
	}
	writeError(w, status, string(appErr.Kind), appErr.Message)
}

func (s *Server) Health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) Ready(w http.ResponseWriter, r *http.Request) {
	checks := map[string]string{}
	healthy := true

	if s.dbPing != nil {
		if err := s.dbPing(r.Context()); err != nil {
			checks["database"] = "unhealthy"
			healthy = false
		} else {
			checks["database"] = "healthy"
		}
	}
	if s.redisPing != nil {
		if err := s.redisPing(r.Context()); err != nil {
			checks["redis"] = "unhealthy"
			healthy = false
		} else {
			checks["redis"] = "healthy"
		}
	}

	status := http.StatusOK
	statusText := "ready"
	if !healthy {
		status = http.StatusServiceUnavailable
		statusText = "not_ready"
	}
	writeJSON(w, status, map[string]any{"status": statusText, "checks": checks})
}

type devTokenRequest struct {
	Room        string `json:"room"`
	Identity    string `json:"identity"`
	DisplayName string `json:"display_name"`
	Role        string `json:"role"`
}

// DevSessionToken mints a short-lived, room-scoped LiveKit token for the
// patient/doctor test clients (apps/playground). This stands in for the
// real authenticated login + session-authorization flow built on Day 3; it
// is intentionally restricted to non-production environments, capped at a
// short TTL, and never issues the ai_agent role (which requires the
// authorization/consent checks added Day 4/5).
func (s *Server) DevSessionToken(w http.ResponseWriter, r *http.Request) {
	if s.environment == "production" {
		writeError(w, http.StatusForbidden, "dev_endpoint_disabled", "the dev token endpoint is disabled in production")
		return
	}

	var req devTokenRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", "request body must be valid JSON")
		return
	}

	role := token.Role(req.Role)
	if role != token.RolePatient && role != token.RoleDoctor {
		writeError(w, http.StatusForbidden, "role_not_allowed", "only 'patient' and 'doctor' may be minted by this endpoint")
		return
	}
	if req.Room == "" || req.Identity == "" {
		writeError(w, http.StatusBadRequest, "missing_fields", "room and identity are required")
		return
	}

	// Rooms are only ever created explicitly, server-side (LiveKit's
	// auto_create is disabled) — see internal/roomsvc.
	if err := s.rooms.EnsureRoom(r.Context(), req.Room, 300); err != nil {
		s.logger.Error("ensure_room_failed",
			slog.String("event_type", "ensure_room_failed"),
			slog.String("request_id", RequestIDFromContext(r.Context())),
			slog.String("room", req.Room),
			slog.String("error", err.Error()),
		)
		writeError(w, http.StatusInternalServerError, "room_setup_failed", "failed to prepare room")
		return
	}

	minted, err := s.minter.Mint(token.MintRequest{
		Room:     req.Room,
		Identity: req.Identity,
		Name:     req.DisplayName,
		Role:     role,
		TTL:      s.devTokenTTL,
	})
	if err != nil {
		s.logger.Error("token_mint_failed",
			slog.String("event_type", "token_mint_failed"),
			slog.String("request_id", RequestIDFromContext(r.Context())),
			slog.String("error", err.Error()),
		)
		writeError(w, http.StatusInternalServerError, "mint_failed", "failed to mint access token")
		return
	}

	s.logger.Info("token_minted",
		slog.String("event_type", "token_minted"),
		slog.String("request_id", RequestIDFromContext(r.Context())),
		slog.String("room", minted.Room),
		slog.String("identity", minted.Identity),
		slog.String("role", string(minted.Role)),
	)

	writeJSON(w, http.StatusOK, minted)
}
