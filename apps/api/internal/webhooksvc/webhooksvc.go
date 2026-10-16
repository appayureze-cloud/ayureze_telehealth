// Package webhooksvc consumes LiveKit's signed room/participant lifecycle
// webhooks to keep Postgres (participant status) and Redis (presence) in
// sync with what's actually happening on the SFU. It never receives media
// or E2EE keys — LiveKit's webhooks carry only room/participant metadata.
package webhooksvc

import (
	"context"
	"log/slog"

	"github.com/livekit/protocol/livekit"

	"github.com/ayureze/telehealth/api/internal/redisstate"
	"github.com/ayureze/telehealth/api/internal/store"
)

type Service struct {
	sessions     *store.SessionStore
	participants *store.ParticipantStore
	events       *store.EventStore
	presence     *redisstate.PresenceStore
	logger       *slog.Logger
}

func New(sessions *store.SessionStore, participants *store.ParticipantStore, events *store.EventStore, presence *redisstate.PresenceStore, logger *slog.Logger) *Service {
	return &Service{sessions: sessions, participants: participants, events: events, presence: presence, logger: logger}
}

func (s *Service) Handle(ctx context.Context, evt *livekit.WebhookEvent) {
	room := evt.GetRoom()
	if room == nil {
		return
	}
	sess, err := s.sessions.GetByRoomName(ctx, room.GetName())
	if err != nil {
		// Room not tracked by us (shouldn't happen since auto_create is
		// disabled and we always create rooms via EnsureRoom) — ignore.
		return
	}

	switch evt.Event {
	case "participant_joined":
		identity := evt.GetParticipant().GetIdentity()
		_ = s.participants.MarkJoined(ctx, sess.ID, identity)
		_ = s.presence.MarkJoined(ctx, room.GetName(), identity)
		_ = s.events.Insert(ctx, sess.ID, "participant_joined", map[string]any{"identity": identity})

	case "participant_left":
		identity := evt.GetParticipant().GetIdentity()
		_ = s.participants.MarkLeft(ctx, sess.ID, identity)
		_ = s.presence.MarkLeft(ctx, room.GetName(), identity)
		_ = s.events.Insert(ctx, sess.ID, "participant_left", map[string]any{"identity": identity})

	case "room_finished":
		_ = s.events.Insert(ctx, sess.ID, "room_finished", nil)

	default:
		// track_published/unpublished, egress/ingress events etc. are
		// logged for observability but don't drive state transitions.
	}

	s.logger.Info("livekit_webhook",
		slog.String("event_type", "livekit_webhook"),
		slog.String("webhook_event", evt.Event),
		slog.String("session_id", sess.ID),
		slog.String("room", room.GetName()),
	)
}
