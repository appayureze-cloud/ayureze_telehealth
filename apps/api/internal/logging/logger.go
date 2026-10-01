// Package logging provides a structured JSON logger. Every log line must
// go through this package so the fields required by docs/monitoring/ are
// consistent, and so secret-shaped fields are never accidentally attached
// (see New's ReplaceAttr).
package logging

import (
	"log/slog"
	"os"
	"strings"
)

// sensitiveKeys are field names that must never appear in a log record.
// This is a defense-in-depth backstop — callers must not pass these in the
// first place. See docs/monitoring/privacy.md.
var sensitiveKeys = map[string]struct{}{
	"password":     {},
	"secret":       {},
	"token":        {},
	"access_token": {},
	"api_key":      {},
	"e2ee_key":     {},
	"private_key":  {},
}

func New(service, environment string) *slog.Logger {
	level := slog.LevelInfo
	if lvl := strings.ToLower(os.Getenv("LOG_LEVEL")); lvl == "debug" {
		level = slog.LevelDebug
	}

	handler := slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: level,
		ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
			if _, blocked := sensitiveKeys[strings.ToLower(a.Key)]; blocked {
				return slog.String(a.Key, "[REDACTED]")
			}
			return a
		},
	})

	return slog.New(handler).With(
		slog.String("service", service),
		slog.String("environment", environment),
	)
}
