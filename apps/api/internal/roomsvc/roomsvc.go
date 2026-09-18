// Package roomsvc wraps LiveKit's RoomServiceClient so that rooms are only
// ever created explicitly by this service (LiveKit's own auto_create is
// disabled — see infrastructure/livekit/livekit.yaml) rather than implicitly
// whenever a client happens to connect with a valid-looking token.
package roomsvc

import (
	"context"
	"fmt"
	"time"

	"github.com/livekit/protocol/livekit"
	lksdk "github.com/livekit/server-sdk-go/v2"
)

type Service struct {
	client *lksdk.RoomServiceClient
}

func New(url, apiKey, apiSecret string) *Service {
	return &Service{client: lksdk.NewRoomServiceClient(url, apiKey, apiSecret)}
}

// EnsureRoom creates the room if it doesn't already exist. CreateRoom is
// idempotent on the LiveKit server side (calling it for an already-existing
// room returns that room rather than erroring), so this is safe to call on
// every join attempt.
func (s *Service) EnsureRoom(ctx context.Context, roomName string, emptyTimeoutSeconds uint32) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err := s.client.CreateRoom(ctx, &livekit.CreateRoomRequest{
		Name:         roomName,
		EmptyTimeout: emptyTimeoutSeconds,
	})
	if err != nil {
		return fmt.Errorf("ensure room %q: %w", roomName, err)
	}
	return nil
}

// DeleteRoom disconnects everyone and removes the room. Called when a
// session is explicitly ended rather than left to LiveKit's empty_timeout.
func (s *Service) DeleteRoom(ctx context.Context, roomName string) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err := s.client.DeleteRoom(ctx, &livekit.DeleteRoomRequest{Room: roomName})
	if err != nil {
		return fmt.Errorf("delete room %q: %w", roomName, err)
	}
	return nil
}

// RemoveParticipant forcibly disconnects a single participant without
// affecting the rest of the room. Used to immediately enforce AI-agent
// consent revocation (Day 4) — a patient or doctor revoking consent must
// not leave the AI agent connected until it happens to notice.
func (s *Service) RemoveParticipant(ctx context.Context, roomName, identity string) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err := s.client.RemoveParticipant(ctx, &livekit.RoomParticipantIdentity{Room: roomName, Identity: identity})
	if err != nil {
		return fmt.Errorf("remove participant %q from room %q: %w", identity, roomName, err)
	}
	return nil
}
