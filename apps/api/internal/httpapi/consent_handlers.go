package httpapi

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/ayureze/telehealth/api/internal/consentsvc"
)

func (s *Server) consentCallerFromContext(r *http.Request) (consentsvc.Caller, bool) {
	claims, ok := ClaimsFromContext(r.Context())
	if !ok {
		return consentsvc.Caller{}, false
	}
	return consentsvc.Caller{UserID: claims.UserID, TenantID: claims.TenantID, Role: claims.Role}, true
}

func (s *Server) GrantAIConsent(w http.ResponseWriter, r *http.Request) {
	caller, ok := s.consentCallerFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated", "missing caller identity")
		return
	}
	sessionID := chi.URLParam(r, "id")

	c, err := s.consents.Grant(r.Context(), caller, sessionID, ClientIP(r))
	if err != nil {
		writeAppError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": c.ID, "subject": c.Subject, "status": c.Status})
}

func (s *Server) RevokeAIConsent(w http.ResponseWriter, r *http.Request) {
	caller, ok := s.consentCallerFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated", "missing caller identity")
		return
	}
	sessionID := chi.URLParam(r, "id")

	if err := s.consents.Revoke(r.Context(), caller, sessionID, ClientIP(r)); err != nil {
		writeAppError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "revoked"})
}
