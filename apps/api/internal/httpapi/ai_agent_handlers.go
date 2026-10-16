package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/ayureze/telehealth/api/internal/sessionsvc"
)

func (s *Server) WithAIAgentAuth(serviceSecret string, sessions *sessionsvc.Service) *Server {
	s.aiAgentServiceSecret = serviceSecret
	s.aiAgentSessions = sessions
	return s
}

// RequireAIAgentServiceSecret authenticates the AI agent process itself —
// a trusted backend service, not a human user — via a static shared
// secret rather than the login/JWT flow. This is deliberately separate
// from httpapi.RequireAuth: the AI agent has no tenant/user identity of
// its own to put in a JWT.
func RequireAIAgentServiceSecret(secret string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			presented := r.Header.Get("X-AI-Agent-Secret")
			if presented == "" || presented != secret {
				writeError(w, http.StatusUnauthorized, "invalid_service_secret", "missing or invalid AI agent service credential")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

type aiAgentAuthorizeRequest struct {
	TenantID string `json:"tenant_id"`
}

// AIAgentAuthorize is called by the AI agent (Day 5) to request access to
// a session. It is the HTTP entry point to sessionsvc.AuthorizeAIAgent,
// which enforces that access is refused unless AI-translation consent is
// currently granted for this exact session.
func (s *Server) AIAgentAuthorize(w http.ResponseWriter, r *http.Request) {
	sessionID := chi.URLParam(r, "id")
	var req aiAgentAuthorizeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.TenantID == "" {
		writeError(w, http.StatusBadRequest, "invalid_body", "tenant_id is required")
		return
	}

	result, err := s.aiAgentSessions.AuthorizeAIAgent(r.Context(), req.TenantID, sessionID, ClientIP(r))
	if err != nil {
		writeAppError(w, err)
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"access_token": result.AccessToken,
		"room":         result.Room,
		"identity":     result.Identity,
		"e2ee_key":     result.E2EEKeyBase64,
		"expires_at":   result.ExpiresAt.Format(rfc3339),
	})
}
