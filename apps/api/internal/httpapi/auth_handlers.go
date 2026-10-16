package httpapi

import (
	"encoding/json"
	"net/http"
)

type loginRequest struct {
	Tenant   string `json:"tenant"`
	Email    string `json:"email"`
	Password string `json:"password"`
}

type tokenPairResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresAt    string `json:"expires_at"`
	User         struct {
		ID          string `json:"id"`
		Email       string `json:"email"`
		Role        string `json:"role"`
		DisplayName string `json:"display_name"`
	} `json:"user"`
}

func (s *Server) Login(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", "request body must be valid JSON")
		return
	}
	if req.Tenant == "" || req.Email == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "missing_fields", "tenant, email, and password are required")
		return
	}

	pair, err := s.auth.Login(r.Context(), req.Tenant, req.Email, req.Password, ClientIP(r))
	if err != nil {
		writeAppError(w, err)
		return
	}

	var resp tokenPairResponse
	resp.AccessToken = pair.AccessToken
	resp.RefreshToken = pair.RefreshToken
	resp.ExpiresAt = pair.ExpiresAt.Format(rfc3339)
	resp.User.ID = pair.User.ID
	resp.User.Email = pair.User.Email
	resp.User.Role = string(pair.User.Role)
	resp.User.DisplayName = pair.User.DisplayName

	writeJSON(w, http.StatusOK, resp)
}

type refreshRequest struct {
	RefreshToken string `json:"refresh_token"`
}

func (s *Server) Refresh(w http.ResponseWriter, r *http.Request) {
	var req refreshRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.RefreshToken == "" {
		writeError(w, http.StatusBadRequest, "invalid_body", "refresh_token is required")
		return
	}

	pair, err := s.auth.Refresh(r.Context(), req.RefreshToken, ClientIP(r))
	if err != nil {
		writeAppError(w, err)
		return
	}

	var resp tokenPairResponse
	resp.AccessToken = pair.AccessToken
	resp.RefreshToken = pair.RefreshToken
	resp.ExpiresAt = pair.ExpiresAt.Format(rfc3339)
	resp.User.ID = pair.User.ID
	resp.User.Email = pair.User.Email
	resp.User.Role = string(pair.User.Role)
	resp.User.DisplayName = pair.User.DisplayName

	writeJSON(w, http.StatusOK, resp)
}

func (s *Server) Logout(w http.ResponseWriter, r *http.Request) {
	var req refreshRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.RefreshToken == "" {
		writeError(w, http.StatusBadRequest, "invalid_body", "refresh_token is required")
		return
	}
	if err := s.auth.Logout(r.Context(), req.RefreshToken); err != nil {
		writeError(w, http.StatusInternalServerError, "logout_failed", "failed to revoke refresh token")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "logged_out"})
}

const rfc3339 = "2006-01-02T15:04:05.999999999Z07:00"
