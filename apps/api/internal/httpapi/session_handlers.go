package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/ayureze/telehealth/api/internal/domain"
	"github.com/ayureze/telehealth/api/internal/sessionsvc"
)

func (s *Server) callerFromContext(r *http.Request) (sessionsvc.Caller, bool) {
	claims, ok := ClaimsFromContext(r.Context())
	if !ok {
		return sessionsvc.Caller{}, false
	}
	return sessionsvc.Caller{UserID: claims.UserID, TenantID: claims.TenantID, Role: claims.Role}, true
}

type createSessionRequest struct {
	PatientEmail string `json:"patient_email"`
}

func (s *Server) CreateSession(w http.ResponseWriter, r *http.Request) {
	caller, ok := s.callerFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated", "missing caller identity")
		return
	}
	var req createSessionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.PatientEmail == "" {
		writeError(w, http.StatusBadRequest, "invalid_body", "patient_email is required")
		return
	}

	sess, err := s.sessions.Create(r.Context(), caller, req.PatientEmail, ClientIP(r))
	if err != nil {
		writeAppError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, sessionResponse(sess))
}

func (s *Server) JoinSession(w http.ResponseWriter, r *http.Request) {
	caller, ok := s.callerFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated", "missing caller identity")
		return
	}
	sessionID := chi.URLParam(r, "id")

	result, err := s.sessions.Join(r.Context(), caller, sessionID, ClientIP(r))
	if err != nil {
		writeAppError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"access_token": result.AccessToken,
		"room":         result.Room,
		"expires_at":   result.ExpiresAt.Format(rfc3339),
		// e2ee_key is this session's media-encryption key (see
		// internal/e2ee) delivered only here, only over this
		// authenticated response, to a caller who just passed
		// sessionsvc.Join's authorization checks. It is never included in
		// GetSession/CreateSession responses or logged.
		"e2ee_key": result.E2EEKeyBase64,
		"session":  sessionResponse(result.Session),
	})
}

func (s *Server) EndSession(w http.ResponseWriter, r *http.Request) {
	caller, ok := s.callerFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated", "missing caller identity")
		return
	}
	sessionID := chi.URLParam(r, "id")

	sess, err := s.sessions.End(r.Context(), caller, sessionID, ClientIP(r))
	if err != nil {
		writeAppError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, sessionResponse(sess))
}

func (s *Server) GetSession(w http.ResponseWriter, r *http.Request) {
	caller, ok := s.callerFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated", "missing caller identity")
		return
	}
	sessionID := chi.URLParam(r, "id")

	sess, participants, err := s.sessions.Get(r.Context(), caller, sessionID)
	if err != nil {
		writeAppError(w, err)
		return
	}

	participantsResp := make([]map[string]any, 0, len(participants))
	for _, p := range participants {
		participantsResp = append(participantsResp, map[string]any{
			"identity": p.Identity,
			"role":     p.Role,
			"status":   p.Status,
		})
	}

	resp := sessionResponse(sess)
	resp["participants"] = participantsResp
	writeJSON(w, http.StatusOK, resp)
}

func sessionResponse(sess *domain.Session) map[string]any {
	resp := map[string]any{
		"id":                        sess.ID,
		"room":                      sess.RoomName,
		"status":                    sess.Status,
		"doctor_id":                 sess.DoctorID,
		"patient_id":                sess.PatientID,
		"ai_translation_authorized": sess.AITranslationAuthorized,
		"created_at":                sess.CreatedAt.Format(rfc3339),
	}
	if sess.StartedAt != nil {
		resp["started_at"] = sess.StartedAt.Format(rfc3339)
	}
	if sess.EndedAt != nil {
		resp["ended_at"] = sess.EndedAt.Format(rfc3339)
	}
	return resp
}
