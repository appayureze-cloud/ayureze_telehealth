// Package appwire constructs the fully-wired HTTP server from config. It
// exists so cmd/api and the integration test suite (apps/api/test/integration)
// build the exact same object graph rather than the test suite hand-rolling
// its own wiring that could drift from what actually runs in production.
package appwire

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/jackc/pgx/v5/pgxpool"
	lkauth "github.com/livekit/protocol/auth"
	"github.com/redis/go-redis/v9"

	"github.com/ayureze/telehealth/api/internal/authn"
	"github.com/ayureze/telehealth/api/internal/authsvc"
	"github.com/ayureze/telehealth/api/internal/config"
	"github.com/ayureze/telehealth/api/internal/consentsvc"
	"github.com/ayureze/telehealth/api/internal/db"
	"github.com/ayureze/telehealth/api/internal/e2ee"
	"github.com/ayureze/telehealth/api/internal/httpapi"
	"github.com/ayureze/telehealth/api/internal/logging"
	"github.com/ayureze/telehealth/api/internal/redisstate"
	"github.com/ayureze/telehealth/api/internal/roomsvc"
	"github.com/ayureze/telehealth/api/internal/sessionsvc"
	"github.com/ayureze/telehealth/api/internal/store"
	"github.com/ayureze/telehealth/api/internal/token"
	"github.com/ayureze/telehealth/api/internal/webhooksvc"
)

type App struct {
	Server  *httpapi.Server
	Handler http.Handler
	Logger  *slog.Logger
	Pool    *pgxpool.Pool
	Redis   *redis.Client
	Stores  Stores
}

type Stores struct {
	Tenants      *store.TenantStore
	Users        *store.UserStore
	Sessions     *store.SessionStore
	Participants *store.ParticipantStore
	Consents     *store.ConsentStore
	Audit        *store.AuditStore
	Events       *store.EventStore
}

func Build(ctx context.Context, cfg *config.Config) (*App, error) {
	if err := db.Migrate(cfg.DatabaseURL); err != nil {
		return nil, err
	}
	pool, err := db.NewPool(ctx, cfg.DatabaseURL)
	if err != nil {
		return nil, err
	}
	redisClient, err := redisstate.NewClient(cfg.RedisAddr, cfg.RedisPassword, cfg.RedisDB)
	if err != nil {
		pool.Close()
		return nil, err
	}

	logger := logging.New("ayureze-api", cfg.Environment)

	keys, err := e2ee.NewKeyManager(cfg.E2EEMasterKeyHex)
	if err != nil {
		pool.Close()
		_ = redisClient.Close()
		return nil, err
	}

	minter := token.NewMinter(cfg.LiveKitAPIKey, cfg.LiveKitAPISecret)
	rooms := roomsvc.New(cfg.LiveKitURL, cfg.LiveKitAPIKey, cfg.LiveKitAPISecret)

	stores := Stores{
		Tenants:      store.NewTenantStore(pool),
		Users:        store.NewUserStore(pool),
		Sessions:     store.NewSessionStore(pool),
		Participants: store.NewParticipantStore(pool),
		Consents:     store.NewConsentStore(pool),
		Audit:        store.NewAuditStore(pool),
		Events:       store.NewEventStore(pool),
	}

	refreshStore := redisstate.NewRefreshTokenStore(redisClient)
	presenceStore := redisstate.NewPresenceStore(redisClient)
	rateLimiter := redisstate.NewRateLimiter(redisClient, cfg.RateLimitPerMinute)

	issuer := authn.NewIssuer(cfg.JWTSigningSecret)
	authService := authsvc.New(stores.Tenants, stores.Users, stores.Audit, issuer, refreshStore, cfg.AccessTokenTTL, cfg.RefreshTokenTTL)
	sessionService := sessionsvc.New(stores.Sessions, stores.Participants, stores.Consents, stores.Users, stores.Audit, stores.Events, minter, rooms, keys, cfg.JoinTokenTTL)
	consentService := consentsvc.New(stores.Sessions, stores.Consents, stores.Participants, stores.Audit, stores.Events, rooms, logger)

	webhookKeyProvider := lkauth.NewSimpleKeyProvider(cfg.LiveKitAPIKey, cfg.LiveKitAPISecret)
	webhookService := webhooksvc.New(stores.Sessions, stores.Participants, stores.Events, presenceStore, logger)

	srv := httpapi.NewServer(logger, minter, rooms, cfg.DevTokenTTL, cfg.Environment).
		WithAuthenticatedServices(issuer, authService, sessionService, consentService).
		WithWebhooks(webhookKeyProvider, webhookService).
		WithAIAgentAuth(cfg.AIAgentServiceSecret, sessionService).
		WithReadiness(
			func(ctx context.Context) error { return pool.Ping(ctx) },
			func(ctx context.Context) error { return redisClient.Ping(ctx).Err() },
		)

	handler := httpapi.NewRouter(srv, logger, cfg.CORSAllowedOrigins, rateLimiter)

	return &App{Server: srv, Handler: handler, Logger: logger, Pool: pool, Redis: redisClient, Stores: stores}, nil
}

// Close releases the database and Redis connections.
func (a *App) Close() {
	a.Pool.Close()
	_ = a.Redis.Close()
}
