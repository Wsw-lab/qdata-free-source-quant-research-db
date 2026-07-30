#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.docker/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENVIRONMENT="${QDATA_NU_ENVIRONMENT:-local}"
RELEASE_CODE="${QDATA_NU_RELEASE_CODE:-nu-local-$(date +%Y%m%d%H%M%S)}"
POSTGRES_DSN="${QDATA_POSTGRES_DSN:-postgresql://qdata:qdata@localhost:15432/qdata}"
CLICKHOUSE_DSN="${QDATA_CLICKHOUSE_DSN:-http://qdata:qdata@localhost:18123/default}"
API_BASE_URL="${QDATA_API_BASE_URL:-http://127.0.0.1:18080}"
API_TOKEN="${QDATA_API_TOKEN:-devtoken}"

START_APP=1
START_SCHEDULER=1
for arg in "$@"; do
  case "$arg" in
    --no-app)
      START_APP=0
      ;;
    --no-scheduler)
      START_SCHEDULER=0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

echo "Nu deploy release_code=$RELEASE_CODE environment=$ENVIRONMENT"
docker compose up -d postgres clickhouse

echo "Waiting for qdata-postgres..."
until docker compose exec -T postgres pg_isready -U qdata -d qdata >/dev/null 2>&1; do
  sleep 1
done

echo "Waiting for qdata-clickhouse..."
until docker compose exec -T clickhouse clickhouse-client --user qdata --password qdata --query "SELECT 1" >/dev/null 2>&1; do
  sleep 1
done

"$ROOT_DIR/scripts/apply_postgres_migrations.sh"

if [[ "$START_APP" == "1" ]]; then
  docker compose --profile app up -d qdata-api
  echo "Waiting for qdata-api..."
  deadline=$((SECONDS + 120))
  until QDATA_NU_API_BASE_URL="$API_BASE_URL" python3 - <<'PY' >/dev/null 2>&1
from urllib.request import urlopen
import os

health_url = os.environ["QDATA_NU_API_BASE_URL"].rstrip("/") + "/health"
with urlopen(health_url, timeout=3) as response:
    raise SystemExit(0 if 200 <= response.status < 300 else 1)
PY
  do
    if (( SECONDS >= deadline )); then
      echo "qdata-api did not become ready at $API_BASE_URL/health" >&2
      docker compose --profile app logs --tail=80 qdata-api >&2 || true
      exit 1
    fi
    sleep 2
  done
fi

if [[ "$START_SCHEDULER" == "1" ]]; then
  docker compose --profile scheduler up -d mu-scheduler
fi

python3 scripts/check_nu_health.py \
  --environment "$ENVIRONMENT" \
  --release-code "$RELEASE_CODE" \
  --postgres-dsn "$POSTGRES_DSN" \
  --clickhouse-dsn "$CLICKHOUSE_DSN" \
  --api-base-url "$API_BASE_URL" \
  --api-token "$API_TOKEN" \
  --write-db

echo "Nu local deployment is ready."
echo "API:        $API_BASE_URL"
echo "PostgreSQL: $POSTGRES_DSN"
echo "ClickHouse: $CLICKHOUSE_DSN"
