// Package token mints short-lived, role-scoped LiveKit access tokens
// server-side. Clients never see LIVEKIT_API_KEY/LIVEKIT_API_SECRET and can
// never mint their own privileged tokens — every join to a room happens
// through this package.
package token

import (
	"errors"
	"fmt"
	"time"

	"github.com/livekit/protocol/auth"
)

type Role string

const (
	RolePatient Role = "patient"
	RoleDoctor  Role = "doctor"
	RoleAIAgent Role = "ai_agent"
)

func (r Role) Valid() bool {
	switch r {
	case RolePatient, RoleDoctor, RoleAIAgent:
		return true
	default:
		return false
	}
}

var ErrInvalidRole = errors.New("invalid role")

type Minter struct {
	apiKey    string
	apiSecret string
}

func NewMinter(apiKey, apiSecret string) *Minter {
	return &Minter{apiKey: apiKey, apiSecret: apiSecret}
}

type MintRequest struct {
	Room     string
	Identity string
	Name     string
	Role     Role
	TTL      time.Duration
}

type MintedToken struct {
	AccessToken string    `json:"access_token"`
	Identity    string    `json:"identity"`
	Room        string    `json:"room"`
	Role        Role      `json:"role"`
	ExpiresAt   time.Time `json:"expires_at"`
}

// Mint issues a room-scoped, role-scoped, time-bounded LiveKit JWT.
//
// Role scoping (least privilege):
//   - patient/doctor: can publish and subscribe to audio/video/data within
//     the single room they were granted, nothing else.
//   - ai_agent: same room-scoped publish/subscribe, but is never issued
//     unless the caller has already verified authorization/consent — see
//     apps/api/internal/consent (added Day 4). This package only knows how
//     to mint a token; it enforces no policy of its own.
func (m *Minter) Mint(req MintRequest) (*MintedToken, error) {
	if req.Room == "" {
		return nil, fmt.Errorf("room is required")
	}
	if req.Identity == "" {
		return nil, fmt.Errorf("identity is required")
	}
	if !req.Role.Valid() {
		return nil, ErrInvalidRole
	}
	if req.TTL <= 0 || req.TTL > 10*time.Minute {
		return nil, fmt.Errorf("ttl must be > 0 and <= 10m, got %s", req.TTL)
	}

	canPublish := true
	canSubscribe := true
	canPublishData := true
	// Only the doctor/patient/ai_agent roles ever reach this point (Valid()
	// above rejects anything else); all three get symmetric publish/
	// subscribe rights within their single assigned room. Visibility across
	// tenants/rooms is enforced by never minting a token for a room the
	// caller isn't authorized for (apps/api/internal/session, Day 3) — this
	// package has no notion of "all rooms".
	grant := &auth.VideoGrant{
		RoomJoin:       true,
		Room:           req.Room,
		CanPublish:     &canPublish,
		CanSubscribe:   &canSubscribe,
		CanPublishData: &canPublishData,
	}

	at := auth.NewAccessToken(m.apiKey, m.apiSecret).
		SetIdentity(req.Identity).
		SetName(req.Name).
		SetValidFor(req.TTL).
		SetVideoGrant(grant).
		SetAttributes(map[string]string{"role": string(req.Role)})

	jwtStr, err := at.ToJWT()
	if err != nil {
		return nil, fmt.Errorf("signing token: %w", err)
	}

	return &MintedToken{
		AccessToken: jwtStr,
		Identity:    req.Identity,
		Room:        req.Room,
		Role:        req.Role,
		ExpiresAt:   time.Now().Add(req.TTL),
	}, nil
}
