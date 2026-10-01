#!/usr/bin/env bash
# Verify that every core service in the AyurEze Telehealth dev stack is up
# and healthy. Exits non-zero (and prints which check failed) if not.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

fail=0
check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "OK    $name"
  else
    echo "FAIL  $name"
    fail=1
  fi
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

echo "== Container status =="
compose ps

echo ""
echo "== Health checks =="
check "postgres accepting connections"   compose exec -T postgres pg_isready -U "${POSTGRES_USER:-ayureze}" -d "${POSTGRES_DB:-ayureze_telehealth}"
check "redis PING"                       compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" ping
check "livekit HTTP root"                curl -fsS "http://localhost:${LIVEKIT_HTTP_PORT:-7880}/"
check "prometheus healthy"               curl -fsS "http://localhost:${PROMETHEUS_HTTP_PORT:-9090}/-/healthy"
check "loki ready"                       curl -fsS "http://localhost:${LOKI_HTTP_PORT:-3100}/ready"
check "grafana healthy"                  curl -fsS "http://localhost:${GRAFANA_HTTP_PORT:-3001}/api/health"
check "coturn TCP port open"             bash -c "echo > /dev/tcp/127.0.0.1/${TURN_LISTEN_PORT:-3478}"

echo ""
if [[ "$fail" -eq 0 ]]; then
  echo "All health checks passed."
else
  echo "One or more health checks FAILED. See above." >&2
fi
exit "$fail"
