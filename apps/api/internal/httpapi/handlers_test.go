package httpapi

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/ayureze/telehealth/api/internal/token"
)

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(bytes.NewBuffer(nil), nil))
}

func TestDevSessionToken_RejectsAIAgentRole(t *testing.T) {
	// rooms is intentionally nil: role validation must reject before ever
	// touching LiveKit, so this must not panic on a nil roomsvc.
	srv := NewServer(testLogger(), token.NewMinter("k", "s"), nil, 5*time.Minute, "development")

	body, _ := json.Marshal(map[string]string{"room": "r", "identity": "id", "role": "ai_agent"})
	req := httptest.NewRequest("POST", "/v1/dev/session-tokens", bytes.NewReader(body))
	rec := httptest.NewRecorder()

	srv.DevSessionToken(rec, req)

	if rec.Code != 403 {
		t.Fatalf("expected 403 for ai_agent role, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestDevSessionToken_DisabledInProduction(t *testing.T) {
	srv := NewServer(testLogger(), token.NewMinter("k", "s"), nil, 5*time.Minute, "production")

	body, _ := json.Marshal(map[string]string{"room": "r", "identity": "id", "role": "patient"})
	req := httptest.NewRequest("POST", "/v1/dev/session-tokens", bytes.NewReader(body))
	rec := httptest.NewRecorder()

	srv.DevSessionToken(rec, req)

	if rec.Code != 403 {
		t.Fatalf("expected 403 in production environment, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestDevSessionToken_RejectsMissingFields(t *testing.T) {
	srv := NewServer(testLogger(), token.NewMinter("k", "s"), nil, 5*time.Minute, "development")

	body, _ := json.Marshal(map[string]string{"role": "patient"})
	req := httptest.NewRequest("POST", "/v1/dev/session-tokens", bytes.NewReader(body))
	rec := httptest.NewRecorder()

	srv.DevSessionToken(rec, req)

	if rec.Code != 400 {
		t.Fatalf("expected 400 for missing room/identity, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestHealth(t *testing.T) {
	srv := NewServer(testLogger(), token.NewMinter("k", "s"), nil, 5*time.Minute, "development")
	req := httptest.NewRequest("GET", "/health", nil)
	rec := httptest.NewRecorder()
	srv.Health(rec, req)
	if rec.Code != 200 {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
}
