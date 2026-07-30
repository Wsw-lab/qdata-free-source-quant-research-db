#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.docker/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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

echo "Local qdata stack is ready."
echo "PostgreSQL:  postgresql://qdata:qdata@localhost:15432/qdata"
echo "ClickHouse:  http://qdata:qdata@localhost:18123/default"
