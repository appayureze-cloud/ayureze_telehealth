//go:build integration

package integration

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"testing"
	"time"

	"github.com/livekit/protocol/livekit"

	"github.com/ayureze/telehealth/api/internal/authn"
)

func (ta *testApp) aiAgentAuthorize(t *testing.T, tenantID, sessionID string) (int, map[string]any) {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"tenant_id": tenantID})
	req, err := http.NewRequest(http.MethodPost,
		fmt.Sprintf("%s/internal/ai-agent/sessions/%s/authorize", ta.server.URL, sessionID),
		bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-AI-Agent-Secret", os.Getenv("AI_AGENT_SERVICE_SECRET"))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out
}

// TestE2EE_JoinReturnsUsableSessionKey verifies the join response carries
// a 32-byte E2EE key and that a fresh session gets a distinct key (the key
// is never reused/hardcoded).
func TestE2EE_JoinReturnsUsableSessionKey(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, patientEmail, password := ta.seedTenant(t)
	doctorToken := ta.login(t, tenant, doctorEmail, password)

	_, sessA := ta.do(t, http.MethodPost, "/v1/sessions", doctorToken, map[string]string{"patient_email": patientEmail})
	_, joinA := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessA["id"]), doctorToken, nil)
	keyA, ok := joinA["e2ee_key"].(string)
	if !ok || keyA == "" {
		t.Fatalf("expected a non-empty e2ee_key in join response, got %v", joinA)
	}
	decodedA, err := base64.StdEncoding.DecodeString(keyA)
	if err != nil || len(decodedA) != 32 {
		t.Fatalf("expected a base64-encoded 32-byte key, got %d bytes (err=%v)", len(decodedA), err)
	}

	_, sessB := ta.do(t, http.MethodPost, "/v1/sessions", doctorToken, map[string]string{"patient_email": patientEmail})
	_, joinB := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessB["id"]), doctorToken, nil)
	keyB := joinB["e2ee_key"].(string)
	if keyA == keyB {
		t.Fatal("expected distinct sessions to have distinct E2EE keys")
	}

	// The key must never appear in GetSession (only in the join response).
	_, getResp := ta.do(t, http.MethodGet, "/v1/sessions/"+sessA["id"].(string), doctorToken, nil)
	if _, present := getResp["e2ee_key"]; present {
		t.Fatal("GetSession response must never include the E2EE key")
	}
}

// TestAIAgent_RequiresActiveConsent covers the two security scenarios
// explicitly called out in the build spec: "AI without consent" and "AI
// after consent revoked" must both be refused.
func TestAIAgent_RequiresActiveConsent(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, patientEmail, password := ta.seedTenant(t)
	doctorToken := ta.login(t, tenant, doctorEmail, password)
	patientToken := ta.login(t, tenant, patientEmail, password)

	_, sess := ta.do(t, http.MethodPost, "/v1/sessions", doctorToken, map[string]string{"patient_email": patientEmail})
	sessionID := sess["id"].(string)
	tenantID := ""
	{
		// Resolve the tenant id the same way sessionsvc does: from the
		// doctor's own claims, by decoding the access token.
		claims, err := authn.NewIssuer(os.Getenv("API_JWT_SIGNING_SECRET")).Parse(doctorToken)
		if err != nil {
			t.Fatalf("parse doctor token: %v", err)
		}
		tenantID = claims.TenantID
	}

	ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), doctorToken, nil)
	ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), patientToken, nil)

	// 1. AI without consent: must be refused.
	status, body := ta.aiAgentAuthorize(t, tenantID, sessionID)
	if status != http.StatusForbidden {
		t.Fatalf("expected 403 for AI authorization without consent, got %d: %v", status, body)
	}

	// Consent is granted...
	status, _ = ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/consent/ai-translation/grant", sessionID), patientToken, nil)
	if status != http.StatusOK {
		t.Fatalf("grant consent: expected 200, got %d", status)
	}

	// 2. ...now the AI agent is authorized, joins, and receives the same
	// session E2EE key (so it can actually decrypt media once connected —
	// see docs/e2ee/README.md on why the agent necessarily holds the key
	// once authorized).
	status, aiJoin := ta.aiAgentAuthorize(t, tenantID, sessionID)
	if status != http.StatusOK {
		t.Fatalf("expected 200 for AI authorization with active consent, got %d: %v", status, aiJoin)
	}
	if aiJoin["access_token"] == "" || aiJoin["e2ee_key"] == "" {
		t.Fatalf("expected access_token and e2ee_key in AI authorization response, got %v", aiJoin)
	}

	_, doctorJoin := ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/join", sessionID), doctorToken, nil)
	if doctorJoin["e2ee_key"] != aiJoin["e2ee_key"] {
		t.Fatal("expected the AI agent to receive the same session E2EE key as the doctor/patient")
	}

	// Simulate the AI agent actually having connected (normally driven by
	// a real LiveKit participant_joined webhook — Day 5).
	roomName := sess["room"].(string)
	status = ta.sendSignedWebhook(t, &livekit.WebhookEvent{
		Event:       "participant_joined",
		Room:        &livekit.Room{Name: roomName},
		Participant: &livekit.ParticipantInfo{Identity: aiJoin["identity"].(string)},
	})
	if status != http.StatusOK {
		t.Fatalf("expected 200 simulating AI agent join webhook, got %d", status)
	}

	// 3. Consent is revoked while the AI agent is connected: access must
	// be enforced immediately (the participant is force-removed), and any
	// subsequent authorization attempt must fail again.
	status, _ = ta.do(t, http.MethodPost, fmt.Sprintf("/v1/sessions/%s/consent/ai-translation/revoke", sessionID), doctorToken, nil)
	if status != http.StatusOK {
		t.Fatalf("revoke consent: expected 200, got %d", status)
	}

	status, body = ta.aiAgentAuthorize(t, tenantID, sessionID)
	if status != http.StatusForbidden {
		t.Fatalf("expected 403 for AI authorization after consent revoked, got %d: %v", status, body)
	}

	_, getResp := ta.do(t, http.MethodGet, "/v1/sessions/"+sessionID, doctorToken, nil)
	found := false
	for _, p := range getResp["participants"].([]any) {
		pm := p.(map[string]any)
		if pm["role"] == "ai_agent" {
			found = true
			if pm["status"] != "revoked" {
				t.Fatalf("expected ai_agent participant status=revoked after consent revocation, got %v", pm)
			}
		}
	}
	if !found {
		t.Fatal("expected an ai_agent participant row to exist after it was authorized once")
	}
}

func TestAIAgent_RejectsMissingOrWrongServiceSecret(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, patientEmail, password := ta.seedTenant(t)
	doctorToken := ta.login(t, tenant, doctorEmail, password)
	_, sess := ta.do(t, http.MethodPost, "/v1/sessions", doctorToken, map[string]string{"patient_email": patientEmail})

	req, _ := http.NewRequest(http.MethodPost,
		fmt.Sprintf("%s/internal/ai-agent/sessions/%s/authorize", ta.server.URL, sess["id"]),
		bytes.NewReader([]byte(`{"tenant_id":"x"}`)))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 with no service secret, got %d", resp.StatusCode)
	}

	req2, _ := http.NewRequest(http.MethodPost,
		fmt.Sprintf("%s/internal/ai-agent/sessions/%s/authorize", ta.server.URL, sess["id"]),
		bytes.NewReader([]byte(`{"tenant_id":"x"}`)))
	req2.Header.Set("X-AI-Agent-Secret", "definitely-wrong")
	resp2, err := http.DefaultClient.Do(req2)
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	if resp2.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 with a wrong service secret, got %d", resp2.StatusCode)
	}
}

// TestAuth_ExpiredAccessTokenRejected covers "expired authorization" at
// the application-JWT layer (distinct from Day 2's LiveKit-token-level
// expiry test).
func TestAuth_ExpiredAccessTokenRejected(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, _, password := ta.seedTenant(t)
	_ = ta.login(t, tenant, doctorEmail, password) // sanity: credentials are valid

	issuer := authn.NewIssuer(os.Getenv("API_JWT_SIGNING_SECRET"))
	ctx := t.Context()
	tenantRow, err := ta.app.Stores.Tenants.GetByName(ctx, tenant)
	if err != nil {
		t.Fatal(err)
	}
	user, err := ta.app.Stores.Users.GetByEmail(ctx, tenantRow.ID, doctorEmail)
	if err != nil {
		t.Fatal(err)
	}

	expired, _, err := issuer.IssueAccessToken(*user, -1*time.Minute)
	if err != nil {
		t.Fatal(err)
	}

	status, _ := ta.do(t, http.MethodGet, "/v1/sessions/00000000-0000-0000-0000-000000000000", expired, nil)
	if status != http.StatusUnauthorized {
		t.Fatalf("expected 401 for an expired access token, got %d", status)
	}
}

// TestParticipant_InvalidRoleRejectedAtTokenMint covers "invalid
// participant role" — the LiveKit token minter (internal/token, used by
// both sessionsvc.Join and AuthorizeAIAgent) refuses anything outside
// patient/doctor/ai_agent.
func TestParticipant_InvalidRoleRejectedAtTokenMint(t *testing.T) {
	// This is exercised directly against internal/token in
	// apps/api/internal/token/token_test.go (TestMint_RejectsInvalidRole);
	// here we confirm the HTTP surface never lets an unvalidated role
	// value reach it: DevSessionToken already restricts to patient/doctor
	// (see handlers_test.go), and the authenticated session endpoints
	// derive the role internally from the session's own doctor_id/
	// patient_id — there is no request field a client can set to request
	// an arbitrary role.
	ta := newTestApp(t)
	tenant, doctorEmail, patientEmail, password := ta.seedTenant(t)
	doctorToken := ta.login(t, tenant, doctorEmail, password)
	status, body := ta.do(t, http.MethodPost, "/v1/dev/session-tokens", "", map[string]string{
		"room": "x", "identity": "y", "role": "admin",
	})
	if status != http.StatusForbidden {
		t.Fatalf("expected 403 for an invalid/disallowed role on the dev endpoint, got %d: %v", status, body)
	}
	_ = doctorToken
	_ = patientEmail
}
