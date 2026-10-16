#!/usr/bin/env bash
# Run apps/api against the local docker-compose infrastructure stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Run scripts/dev-up.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export DATABASE_URL="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB}?sslmode=disable"
export REDIS_HOST=localhost
export LIVEKIT_URL="ws://localhost:${LIVEKIT_HTTP_PORT:-7880}"

cd "$ROOT_DIR/apps/api"
go run ./cmd/api
