package httpapi

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/ayureze/telehealth/api/internal/roomsvc"
	"github.com/ayureze/telehealth/api/internal/token"
)

type Server struct {
	logger      *slog.Logger
	minter      *token.Minter
	rooms       *roomsvc.Service
	devTokenTTL time.Duration
	environment string
}

func NewServer(logger *slog.Logger, minter *token.Minter, rooms *roomsvc.Service, devTokenTTL time.Duration, environment string) *Server {
	return &Server{logger: logger, minter: minter, rooms: rooms, devTokenTTL: devTokenTTL, environment: environment}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]string{"error": code, "message": message})
}

func (s *Server) Health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) Ready(w http.ResponseWriter, r *http.Request) {
	// Day 2: no external dependencies to check yet beyond process health.
	// Day 3 extends this to verify Postgres/Redis connectivity.
	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
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
