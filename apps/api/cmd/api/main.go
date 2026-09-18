// Command api is the AyurEze Telehealth Go session/auth platform.
// Day 2 scope: health/ready endpoints + a dev-only, role-scoped LiveKit
// token minting endpoint used by apps/playground. Day 3 replaces the dev
// token endpoint with full authenticated session management.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/ayureze/telehealth/api/internal/config"
	"github.com/ayureze/telehealth/api/internal/httpapi"
	"github.com/ayureze/telehealth/api/internal/logging"
	"github.com/ayureze/telehealth/api/internal/roomsvc"
	"github.com/ayureze/telehealth/api/internal/token"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		slog.Default().Error("config_load_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}

	logger := logging.New("ayureze-api", cfg.Environment)

	minter := token.NewMinter(cfg.LiveKitAPIKey, cfg.LiveKitAPISecret)
	rooms := roomsvc.New(cfg.LiveKitURL, cfg.LiveKitAPIKey, cfg.LiveKitAPISecret)
	srv := httpapi.NewServer(logger, minter, rooms, cfg.DevTokenTTL, cfg.Environment)

	corsOrigins := os.Getenv("API_CORS_ALLOWED_ORIGINS")
	rateLimit := 120
	if v := os.Getenv("API_RATE_LIMIT_PER_MINUTE"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil {
			rateLimit = parsed
		}
	}

	handler := httpapi.NewRouter(srv, logger, corsOrigins, rateLimit)

	httpServer := &http.Server{
		Addr:              ":" + cfg.HTTPPort,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info("http_server_starting", slog.String("event_type", "startup"), slog.String("port", cfg.HTTPPort))
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("http_server_failed", slog.String("error", err.Error()))
			os.Exit(1)
		}
	}()

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	<-ctx.Done()

	logger.Info("http_server_stopping", slog.String("event_type", "shutdown"))
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		logger.Error("http_server_shutdown_error", slog.String("error", err.Error()))
	}
}
