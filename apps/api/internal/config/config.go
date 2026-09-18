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

	// JoinTokenTTL bounds how long a Day-3 authenticated session-join
	// LiveKit token may live.
	JoinTokenTTL time.Duration

	DatabaseURL string

	RedisAddr     string
	RedisPassword string
	RedisDB       int

	JWTSigningSecret string
	AccessTokenTTL   time.Duration
	RefreshTokenTTL  time.Duration

	CORSAllowedOrigins string
	RateLimitPerMinute int

	Environment string
}

func Load() (*Config, error) {
	cfg := &Config{
		HTTPPort:           getEnvDefault("API_HTTP_PORT", "8080"),
		Environment:        getEnvDefault("ENVIRONMENT", "development"),
		CORSAllowedOrigins: os.Getenv("API_CORS_ALLOWED_ORIGINS"),
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

	if cfg.DevTokenTTL, err = envSeconds("API_ACCESS_TOKEN_TTL_SECONDS", 300); err != nil {
		return nil, err
	}
	cfg.JoinTokenTTL = cfg.DevTokenTTL
	if cfg.AccessTokenTTL, err = envSeconds("API_ACCESS_TOKEN_TTL_SECONDS", 300); err != nil {
		return nil, err
	}
	if cfg.RefreshTokenTTL, err = envSeconds("API_REFRESH_TOKEN_TTL_SECONDS", 604800); err != nil {
		return nil, err
	}

	cfg.DatabaseURL, err = requireEnv("DATABASE_URL")
	if err != nil {
		return nil, err
	}

	redisHost, err := requireEnv("REDIS_HOST")
	if err != nil {
		return nil, err
	}
	redisPort := getEnvDefault("REDIS_PORT", "6379")
	cfg.RedisAddr = fmt.Sprintf("%s:%s", redisHost, redisPort)
	cfg.RedisPassword, err = requireEnv("REDIS_PASSWORD")
	if err != nil {
		return nil, err
	}
	redisDB, err := strconv.Atoi(getEnvDefault("REDIS_DB", "0"))
	if err != nil {
		return nil, fmt.Errorf("invalid REDIS_DB: %w", err)
	}
	cfg.RedisDB = redisDB

	cfg.JWTSigningSecret, err = requireEnv("API_JWT_SIGNING_SECRET")
	if err != nil {
		return nil, err
	}

	rateLimit, err := strconv.Atoi(getEnvDefault("API_RATE_LIMIT_PER_MINUTE", "120"))
	if err != nil {
		return nil, fmt.Errorf("invalid API_RATE_LIMIT_PER_MINUTE: %w", err)
	}
	cfg.RateLimitPerMinute = rateLimit

	return cfg, nil
}

func envSeconds(key string, def int) (time.Duration, error) {
	v := getEnvDefault(key, strconv.Itoa(def))
	seconds, err := strconv.Atoi(v)
	if err != nil {
		return 0, fmt.Errorf("invalid %s: %w", key, err)
	}
	return time.Duration(seconds) * time.Second, nil
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
