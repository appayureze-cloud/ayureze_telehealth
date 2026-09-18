//go:build integration

package integration

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// loadRootEnv reads the repo root .env (the same file scripts/dev-up.sh
// uses) and applies host-friendly overrides for the services this test
// reaches from outside the docker-compose network (Postgres/Redis/LiveKit
// are addressed as "localhost" here rather than their compose service
// names). It does not overwrite variables already set in the process
// environment, so CI can override via real env vars instead.
func loadRootEnv() error {
	root, err := repoRoot()
	if err != nil {
		return err
	}
	f, err := os.Open(filepath.Join(root, ".env"))
	if err != nil {
		return fmt.Errorf(".env not found at repo root (%s) — copy .env.example first: %w", root, err)
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		eq := strings.Index(line, "=")
		if eq == -1 {
			continue
		}
		key, val := line[:eq], line[eq+1:]
		if os.Getenv(key) == "" {
			_ = os.Setenv(key, val)
		}
	}

	// Host-side overrides: the docker-compose service names below only
	// resolve inside the compose network.
	_ = os.Setenv("REDIS_HOST", "localhost")
	_ = os.Setenv("LIVEKIT_URL", "ws://localhost:7880")
	dbURL := fmt.Sprintf("postgres://%s:%s@localhost:5432/%s?sslmode=disable",
		os.Getenv("POSTGRES_USER"), os.Getenv("POSTGRES_PASSWORD"), os.Getenv("POSTGRES_DB"))
	_ = os.Setenv("DATABASE_URL", dbURL)

	return scanner.Err()
}

func repoRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, ".env.example")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("could not locate repo root (.env.example not found)")
		}
		dir = parent
	}
}
