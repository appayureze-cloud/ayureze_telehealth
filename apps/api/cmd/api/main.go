// Command api is the AyurEze Telehealth Go session/auth platform.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ayureze/telehealth/api/internal/appwire"
	"github.com/ayureze/telehealth/api/internal/config"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		slog.Default().Error("config_load_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}

	ctx := context.Background()
	app, err := appwire.Build(ctx, cfg)
	if err != nil {
		slog.Default().Error("app_build_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer app.Close()

	logger := app.Logger

	httpServer := &http.Server{
		Addr:              ":" + cfg.HTTPPort,
		Handler:           app.Handler,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info("http_server_starting", slog.String("event_type", "startup"), slog.String("port", cfg.HTTPPort))
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("http_server_failed", slog.String("error", err.Error()))
			os.Exit(1)
		}
	}()

	stopCtx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	<-stopCtx.Done()

	logger.Info("http_server_stopping", slog.String("event_type", "shutdown"))
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		logger.Error("http_server_shutdown_error", slog.String("error", err.Error()))
	}
}
