#!/usr/bin/env bash
# Run database migrations and insert local-dev-only tenant/user accounts
# (apps/api/cmd/seed) so the login flow has something to authenticate
# against. Refuses to run with ENVIRONMENT=production.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Run scripts/dev-up.sh first (it documents how to create .env)." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Host-side overrides: these hostnames only resolve inside the
# docker-compose network. When apps/api runs on the host (as it does in
# local dev today, ahead of a Day-7 Dockerfile), it needs localhost.
export DATABASE_URL="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB}?sslmode=disable"
export REDIS_HOST=localhost
export LIVEKIT_URL="ws://localhost:${LIVEKIT_HTTP_PORT:-7880}"

cd "$ROOT_DIR/apps/api"
go run ./cmd/seed "$@"
