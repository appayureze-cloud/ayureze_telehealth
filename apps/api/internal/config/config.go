// Package config loads process configuration from environment variables.
// No defaults are provided for secrets: missing required values fail fast
// at startup rather than silently running with an insecure default.
package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

type Config struct {
	HTTPPort string

	LiveKitURL       string
	LiveKitAPIKey    string
	LiveKitAPISecret string

	// DevTokenTTL bounds how long a Day-2 "dev login" token may live. This
	// endpoint is a stand-in for the real authenticated login flow built on
	// Day 3 and is intentionally short-lived and role-restricted.
	DevTokenTTL time.Duration

	Environment string
}

func Load() (*Config, error) {
	cfg := &Config{
		HTTPPort:    getEnvDefault("API_HTTP_PORT", "8080"),
		Environment: getEnvDefault("ENVIRONMENT", "development"),
	}

	var err error
	cfg.LiveKitURL, err = requireEnv("LIVEKIT_URL")
	if err != nil {
		return nil, err
	}
	cfg.LiveKitAPIKey, err = requireEnv("LIVEKIT_API_KEY")
	if err != nil {
		return nil, err
	}
	cfg.LiveKitAPISecret, err = requireEnv("LIVEKIT_API_SECRET")
	if err != nil {
		return nil, err
	}

	ttlSeconds := getEnvDefault("API_ACCESS_TOKEN_TTL_SECONDS", "300")
	seconds, err := strconv.Atoi(ttlSeconds)
	if err != nil {
		return nil, fmt.Errorf("invalid API_ACCESS_TOKEN_TTL_SECONDS: %w", err)
	}
	cfg.DevTokenTTL = time.Duration(seconds) * time.Second

	return cfg, nil
}

func requireEnv(key string) (string, error) {
	v := os.Getenv(key)
	if v == "" {
		return "", fmt.Errorf("required environment variable %s is not set", key)
	}
	return v, nil
}

func getEnvDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
