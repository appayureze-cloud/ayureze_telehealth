package token

import (
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const (
	testAPIKey    = "test_key"
	testAPISecret = "test_secret_at_least_32_bytes_long"
)

func TestMint_ValidRequest(t *testing.T) {
	m := NewMinter(testAPIKey, testAPISecret)
	got, err := m.Mint(MintRequest{
		Room:     "room-1",
		Identity: "patient-1",
		Name:     "Test Patient",
		Role:     RolePatient,
		TTL:      5 * time.Minute,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.AccessToken == "" {
		t.Fatal("expected non-empty access token")
	}
	if got.Room != "room-1" || got.Identity != "patient-1" || got.Role != RolePatient {
		t.Fatalf("unexpected minted token fields: %+v", got)
	}

	claims := jwt.MapClaims{}
	parsed, err := jwt.ParseWithClaims(got.AccessToken, claims, func(t *jwt.Token) (interface{}, error) {
		return []byte(testAPISecret), nil
	})
	if err != nil || !parsed.Valid {
		t.Fatalf("token did not verify against the signing secret: %v", err)
	}
	video, ok := claims["video"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected video grant in claims, got: %+v", claims)
	}
	if video["room"] != "room-1" {
		t.Fatalf("expected grant scoped to room-1, got %v", video["room"])
	}
	if video["roomJoin"] != true {
		t.Fatalf("expected roomJoin=true, got %v", video["roomJoin"])
	}
}

func TestMint_RejectsInvalidRole(t *testing.T) {
	m := NewMinter(testAPIKey, testAPISecret)
	_, err := m.Mint(MintRequest{Room: "r", Identity: "id", Role: Role("superadmin"), TTL: time.Minute})
	if err != ErrInvalidRole {
		t.Fatalf("expected ErrInvalidRole, got %v", err)
	}
}

func TestMint_RejectsMissingRoom(t *testing.T) {
	m := NewMinter(testAPIKey, testAPISecret)
	_, err := m.Mint(MintRequest{Identity: "id", Role: RolePatient, TTL: time.Minute})
	if err == nil {
		t.Fatal("expected error for missing room")
	}
}

func TestMint_RejectsMissingIdentity(t *testing.T) {
	m := NewMinter(testAPIKey, testAPISecret)
	_, err := m.Mint(MintRequest{Room: "r", Role: RolePatient, TTL: time.Minute})
	if err == nil {
		t.Fatal("expected error for missing identity")
	}
}

func TestMint_RejectsExcessiveTTL(t *testing.T) {
	m := NewMinter(testAPIKey, testAPISecret)
	_, err := m.Mint(MintRequest{Room: "r", Identity: "id", Role: RolePatient, TTL: time.Hour})
	if err == nil {
		t.Fatal("expected error for TTL exceeding the 10-minute cap")
	}
}

func TestMint_RejectsZeroTTL(t *testing.T) {
	m := NewMinter(testAPIKey, testAPISecret)
	_, err := m.Mint(MintRequest{Room: "r", Identity: "id", Role: RolePatient, TTL: 0})
	if err == nil {
		t.Fatal("expected error for zero TTL")
	}
}

func TestMint_DifferentRoomsProduceIsolatedGrants(t *testing.T) {
	m := NewMinter(testAPIKey, testAPISecret)
	a, err := m.Mint(MintRequest{Room: "room-a", Identity: "x", Role: RoleDoctor, TTL: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	b, err := m.Mint(MintRequest{Room: "room-b", Identity: "x", Role: RoleDoctor, TTL: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if a.AccessToken == b.AccessToken {
		t.Fatal("tokens for different rooms must not be identical")
	}
	if a.Room == b.Room {
		t.Fatal("expected different rooms in minted tokens")
	}
}
