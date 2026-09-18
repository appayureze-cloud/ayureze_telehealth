#!/usr/bin/env bash
# Start the AyurEze Telehealth local development stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found." >&2
  echo "Copy .env.example to .env and fill in real values before starting the stack:" >&2
  echo "  cp .env.example .env" >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d "$@"

echo ""
echo "Stack starting. Run scripts/health-check.sh to verify readiness."
