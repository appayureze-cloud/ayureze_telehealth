//go:build integration

package integration

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"net/http"
	"os"
	"testing"
	"time"

	lkauth "github.com/livekit/protocol/auth"
	"github.com/livekit/protocol/livekit"
	"google.golang.org/protobuf/encoding/protojson"
)

// sendSignedWebhook builds and sends a LiveKit-shaped webhook request the
// same way the real LiveKit server would: the body is a protojson-encoded
// WebhookEvent, and the Authorization header is an API token whose Sha256
// claim commits to that exact body. This directly exercises our
// signature-verification + state-update code (internal/webhooksvc),
// independent of whether the LiveKit container in this dev environment can
// reach the host-run API process over the docker network.
func (ta *testApp) sendSignedWebhook(t *testing.T, evt *livekit.WebhookEvent) int {
	t.Helper()
	body, err := protojson.Marshal(evt)
	if err != nil {
		t.Fatalf("marshal webhook event: %v", err)
	}
	sum := sha256.Sum256(body)
	hash := base64.StdEncoding.EncodeToString(sum[:])

	at := lkauth.NewAccessToken(os.Getenv("LIVEKIT_API_KEY"), os.Getenv("LIVEKIT_API_SECRET")).
		SetSha256(hash).
		SetValidFor(time.Minute)
	signed, err := at.ToJWT()
	if err != nil {
		t.Fatalf("sign webhook token: %v", err)
	}

	req, err := http.NewRequest(http.MethodPost, ta.server.URL+"/internal/webhooks/livekit", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Authorization", signed)
	req.Header.Set("Content-Type", "application/webhook+json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("do request: %v", err)
	}
	defer resp.Body.Close()
	return resp.StatusCode
}

func TestWebhook_RejectsUnsignedRequest(t *testing.T) {
	ta := newTestApp(t)
	req, _ := http.NewRequest(http.MethodPost, ta.server.URL+"/internal/webhooks/livekit", bytes.NewReader([]byte(`{}`)))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 for an unsigned webhook request, got %d", resp.StatusCode)
	}
}

func TestWebhook_ParticipantJoinedAndLeftUpdateParticipantStatus(t *testing.T) {
	ta := newTestApp(t)
	tenant, doctorEmail, patientEmail, password := ta.seedTenant(t)
	doctorToken := ta.login(t, tenant, doctorEmail, password)

	_, sess := ta.do(t, http.MethodPost, "/v1/sessions", doctorToken, map[string]string{"patient_email": patientEmail})
	sessionID := sess["id"].(string)
	roomName := sess["room"].(string)

	_, getResp := ta.do(t, http.MethodGet, "/v1/sessions/"+sessionID, doctorToken, nil)
	participants, _ := getResp["participants"].([]any)
	if len(participants) != 2 {
		t.Fatalf("expected 2 authorized participants before any join, got %v", getResp)
	}
	for _, p := range participants {
		pm := p.(map[string]any)
		if pm["status"] != "authorized" {
			t.Fatalf("expected status=authorized pre-webhook, got %v", pm)
		}
	}
	doctorIdentity := participants[0].(map[string]any)["identity"].(string)

	status := ta.sendSignedWebhook(t, &livekit.WebhookEvent{
		Event:       "participant_joined",
		Room:        &livekit.Room{Name: roomName},
		Participant: &livekit.ParticipantInfo{Identity: doctorIdentity},
	})
	if status != http.StatusOK {
		t.Fatalf("expected 200 from webhook endpoint, got %d", status)
	}

	_, getResp = ta.do(t, http.MethodGet, "/v1/sessions/"+sessionID, doctorToken, nil)
	found := false
	for _, p := range getResp["participants"].([]any) {
		pm := p.(map[string]any)
		if pm["identity"] == doctorIdentity {
			found = true
			if pm["status"] != "joined" {
				t.Fatalf("expected participant status=joined after participant_joined webhook, got %v", pm)
			}
		}
	}
	if !found {
		t.Fatal("doctor participant not found after webhook")
	}

	status = ta.sendSignedWebhook(t, &livekit.WebhookEvent{
		Event:       "participant_left",
		Room:        &livekit.Room{Name: roomName},
		Participant: &livekit.ParticipantInfo{Identity: doctorIdentity},
	})
	if status != http.StatusOK {
		t.Fatalf("expected 200 from webhook endpoint, got %d", status)
	}

	_, getResp = ta.do(t, http.MethodGet, "/v1/sessions/"+sessionID, doctorToken, nil)
	for _, p := range getResp["participants"].([]any) {
		pm := p.(map[string]any)
		if pm["identity"] == doctorIdentity && pm["status"] != "left" {
			t.Fatalf("expected participant status=left after participant_left webhook, got %v", pm)
		}
	}

	fmt.Println("webhook-driven participant lifecycle verified for room", roomName)
}
