#!/usr/bin/env bash
# Stop the AyurEze Telehealth local development stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down "$@"
