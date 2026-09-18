package httpapi

import (
	"log/slog"
	"net/http"

	lkauth "github.com/livekit/protocol/auth"
	"github.com/livekit/protocol/webhook"

	"github.com/ayureze/telehealth/api/internal/webhooksvc"
)

func (s *Server) WithWebhooks(keyProvider *lkauth.SimpleKeyProvider, svc *webhooksvc.Service) *Server {
	s.webhookKeyProvider = keyProvider
	s.webhooks = svc
	return s
}

// LiveKitWebhook receives LiveKit's signed room/participant lifecycle
// events. webhook.ReceiveWebhookEvent verifies the request is signed with
// our own LIVEKIT_API_KEY/SECRET before we trust anything in the body —
// this endpoint is reachable from LiveKit's container on the compose
// network, not the public internet, but is verified regardless.
func (s *Server) LiveKitWebhook(w http.ResponseWriter, r *http.Request) {
	evt, err := webhook.ReceiveWebhookEvent(r, s.webhookKeyProvider)
	if err != nil {
		s.logger.Warn("livekit_webhook_rejected",
			slog.String("event_type", "livekit_webhook_rejected"),
			slog.String("request_id", RequestIDFromContext(r.Context())),
			slog.String("error", err.Error()),
		)
		writeError(w, http.StatusUnauthorized, "invalid_webhook_signature", "could not verify webhook signature")
		return
	}

	s.webhooks.Handle(r.Context(), evt)
	w.WriteHeader(http.StatusOK)
}
