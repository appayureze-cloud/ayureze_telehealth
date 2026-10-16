//go:build integration

// Package integration exercises the Day 3 session platform against the
// real Postgres/Redis/LiveKit stack started by scripts/dev-up.sh — no
// mocks. Run with:
//
//	cp .env.example .env   # if not already done
//	./scripts/dev-up.sh
//	cd apps/api && go test -tags integration ./test/integration/...
package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/uuid"

	"github.com/ayureze/telehealth/api/internal/appwire"
	"github.com/ayureze/telehealth/api/internal/authn"
	"github.com/ayureze/telehealth/api/internal/config"
	"github.com/ayureze/telehealth/api/internal/domain"
)

type testApp struct {
	server *httptest.Server
	app    *appwire.App
}

func newTestApp(t *testing.T) *testApp {
	t.Helper()
	if err := loadRootEnv(); err != nil {
		t.Fatalf("load root .env: %v", err)
	}
	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("config.Load: %v", err)
	}
	app, err := appwire.Build(context.Background(), cfg)
	if err != nil {
		t.Fatalf("appwire.Build: %v", err)
	}
	server := httptest.NewServer(app.Handler)
	t.Cleanup(func() {
		server.Close()
		app.Close()
	})
	return &testApp{server: server, app: app}
}

// seedTenant creates a fresh tenant + doctor + patient with unique
// emails/tenant name per call, so tests never collide with each other or
// with apps/api/cmd/seed's fixed dev accounts.
func (ta *testApp) seedTenant(t *testing.T) (tenantName, doctorEmail, patientEmail, password string) {
	t.Helper()
	suffix := uuid.NewString()[:8]
	tenantName = "it-tenant-" + suffix
	doctorEmail = "doctor-" + suffix + "@it.test"
	patientEmail = "patient-" + suffix + "@it.test"
	password = "integration-test-password"

	ctx := context.Background()
	tenant, err := ta.app.Stores.Tenants.EnsureByName(ctx, tenantName)
	if err != nil {
		t.Fatalf("ensure tenant: %v", err)
	}
	hash, err := authn.HashPassword(password)
	if err != nil {
		t.Fatalf("hash password: %v", err)
	}
	if _, err := ta.app.Stores.Users.Create(ctx, domain.User{TenantID: tenant.ID, Email: doctorEmail, PasswordHash: hash, Role: domain.RoleDoctor, DisplayName: "IT Doctor"}); err != nil {
		t.Fatalf("create doctor: %v", err)
	}
	if _, err := ta.app.Stores.Users.Create(ctx, domain.User{TenantID: tenant.ID, Email: patientEmail, PasswordHash: hash, Role: domain.RolePatient, DisplayName: "IT Patient"}); err != nil {
		t.Fatalf("create patient: %v", err)
	}
	return tenantName, doctorEmail, patientEmail, password
}

func (ta *testApp) do(t *testing.T, method, path, token string, body any) (int, map[string]any) {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal body: %v", err)
		}
		reader = bytes.NewReader(b)
	} else {
		reader = bytes.NewReader(nil)
	}
	req, err := http.NewRequest(method, ta.server.URL+path, reader)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("do request: %v", err)
	}
	defer resp.Body.Close()

	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out
}

func (ta *testApp) login(t *testing.T, tenant, email, password string) string {
	t.Helper()
	status, body := ta.do(t, http.MethodPost, "/v1/auth/login", "", map[string]string{
		"tenant": tenant, "email": email, "password": password,
	})
	if status != http.StatusOK {
		t.Fatalf("login failed: status=%d body=%v", status, body)
	}
	return body["access_token"].(string)
}

func TestLogin_SuccessAndFailureModes(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, _, password := ta.seedTenant(t)

	status, body := ta.do(t, http.MethodPost, "/v1/auth/login", "", map[string]string{
		"tenant": tenant, "email": doctorEmail, "password": password,
	})
	if status != http.StatusOK {
		t.Fatalf("expected 200, got %d: %v", status, body)
	}
	if body["access_token"] == "" || body["refresh_token"] == "" {
		t.Fatalf("expected access+refresh tokens, got %v", body)
	}

	cases := []struct {
		name     string
		tenant   string
		email    string
		password string
	}{
		{"wrong password", tenant, doctorEmail, "wrong-password"},
		{"unknown email", tenant, "nobody@it.test", password},
		{"unknown tenant", "no-such-tenant", doctorEmail, password},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			status, body := ta.do(t, http.MethodPost, "/v1/auth/login", "", map[string]string{
				"tenant": c.tenant, "email": c.email, "password": c.password,
			})
			if status != http.StatusUnauthorized {
				t.Fatalf("expected 401, got %d: %v", status, body)
			}
		})
	}
}

func TestRefreshToken_RotatesAndSingleUse(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, _, password := ta.seedTenant(t)

	_, loginBody := ta.do(t, http.MethodPost, "/v1/auth/login", "", map[string]string{
		"tenant": tenant, "email": doctorEmail, "password": password,
	})
	refreshToken := loginBody["refresh_token"].(string)

	status, refreshed := ta.do(t, http.MethodPost, "/v1/auth/refresh", "", map[string]string{"refresh_token": refreshToken})
	if status != http.StatusOK {
		t.Fatalf("expected 200, got %d: %v", status, refreshed)
	}
	if refreshed["access_token"] == loginBody["access_token"] {
		t.Fatal("expected a new access token on refresh")
	}

	// Reusing the same (already-redeemed) refresh token must fail.
	status, _ = ta.do(t, http.MethodPost, "/v1/auth/refresh", "", map[string]string{"refresh_token": refreshToken})
	if status != http.StatusUnauthorized {
		t.Fatalf("expected reused refresh token to be rejected, got %d", status)
	}
}

func TestRBAC_OnlyDoctorOrAdminCanCreateSession(t *testing.T) {
	ta := newTestApp(t)
	tenant, _, patientEmail, password := ta.seedTenant(t)
	patientToken := ta.login(t, tenant, patientEmail, password)

	status, body := ta.do(t, http.MethodPost, "/v1/sessions", patientToken, map[string]string{"patient_email": patientEmail})
	if status != http.StatusForbidden {
		t.Fatalf("expected 403 for patient creating a session, got %d: %v", status, body)
	}
}

func TestSessionLifecycle_CreateJoinConsentEnd(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, patientEmail, password := ta.seedTenant(t)
	doctorToken := ta.login(t, tenant, doctorEmail, password)
	patientToken := ta.login(t, tenant, patientEmail, password)

	status, sess := ta.do(t, http.MethodPost, "/v1/sessions", doctorToken, map[string]string{"patient_email": patientEmail})
	if status != http.StatusCreated {
		t.Fatalf("create session: expected 201, got %d: %v", status, sess)
	}
	sessionID := sess["id"].(string)
	if sess["status"] != "created" {
		t.Fatalf("expected status=created, got %v", sess["status"])
	}

	status, joinDoc := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), doctorToken, nil)
	if status != http.StatusOK {
		t.Fatalf("doctor join: expected 200, got %d: %v", status, joinDoc)
	}
	if joinDoc["access_token"] == "" {
		t.Fatal("expected a LiveKit access_token in join response")
	}

	status, joinPatient := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), patientToken, nil)
	if status != http.StatusOK {
		t.Fatalf("patient join: expected 200, got %d: %v", status, joinPatient)
	}

	// A user from a different tenant entirely must be refused (404, not
	// merely 403, so existence of the session is never confirmed to them).
	otherTenant, _, otherPatientEmail, otherPassword := ta.seedTenant(t)
	otherToken := ta.login(t, otherTenant, otherPatientEmail, otherPassword)
	status, _ = ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), otherToken, nil)
	if status != http.StatusNotFound {
		t.Fatalf("expected 404 for a different tenant's user joining, got %d", status)
	}

	status, grant := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/consent/ai-translation/grant", sessionID), patientToken, nil)
	if status != http.StatusOK || grant["status"] != "granted" {
		t.Fatalf("grant consent: expected 200/granted, got %d: %v", status, grant)
	}

	status, revoke := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/consent/ai-translation/revoke", sessionID), doctorToken, nil)
	if status != http.StatusOK || revoke["status"] != "revoked" {
		t.Fatalf("revoke consent: expected 200/revoked, got %d: %v", status, revoke)
	}

	// The patient may not end the session.
	status, _ = ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/end", sessionID), patientToken, nil)
	if status != http.StatusForbidden {
		t.Fatalf("expected 403 for patient ending session, got %d", status)
	}

	status, ended := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/end", sessionID), doctorToken, nil)
	if status != http.StatusOK || ended["status"] != "ended" {
		t.Fatalf("end session: expected 200/ended, got %d: %v", status, ended)
	}

	status, _ = ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), doctorToken, nil)
	if status != http.StatusConflict {
		t.Fatalf("expected 409 joining an ended session, got %d", status)
	}
}

func TestTenantIsolation(t *testing.T) {
	ta := newTestApp(t)
	tenantA, doctorA, patientA, passwordA := ta.seedTenant(t)
	tenantB, doctorB, _, passwordB := ta.seedTenant(t)

	doctorTokenA := ta.login(t, tenantA, doctorA, passwordA)
	doctorTokenB := ta.login(t, tenantB, doctorB, passwordB)

	_, sess := ta.do(t, http.MethodPost, "/v1/sessions", doctorTokenA, map[string]string{"patient_email": patientA})
	sessionID := sess["id"].(string)

	status, _ := ta.do(t, http.MethodGet, "/v1/sessions/"+sessionID, doctorTokenB, nil)
	if status != http.StatusNotFound {
		t.Fatalf("expected 404 for cross-tenant GET, got %d", status)
	}
	status, _ = ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), doctorTokenB, nil)
	if status != http.StatusNotFound {
		t.Fatalf("expected 404 for cross-tenant join, got %d", status)
	}
	status, body := ta.do(t, http.MethodPost, "/v1/sessions", doctorTokenB, map[string]string{"patient_email": patientA})
	if status != http.StatusNotFound {
		t.Fatalf("expected 404 creating a session against another tenant's patient email, got %d: %v", status, body)
	}
}

func TestAuth_MissingAndInvalidTokenRejected(t *testing.T) {
	ta := newTestApp(t)
	status, _ := ta.do(t, http.MethodGet, "/v1/sessions/"+uuid.NewString(), "", nil)
	if status != http.StatusUnauthorized {
		t.Fatalf("expected 401 with no token, got %d", status)
	}
	status, _ = ta.do(t, http.MethodGet, "/v1/sessions/"+uuid.NewString(), "not-a-real-token", nil)
	if status != http.StatusUnauthorized {
		t.Fatalf("expected 401 with a garbage token, got %d", status)
	}
}

// Sanity check that the process actually starts and readiness reflects
// real dependency health (this would fail if the compose stack were down,
// which is the point).
func TestReadiness(t *testing.T) {
	ta := newTestApp(t)
	req, _ := http.NewRequest(http.MethodGet, ta.server.URL+"/ready", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected /ready to return 200, got %d", resp.StatusCode)
	}
}
