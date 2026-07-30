#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.docker/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export QDATA_BACKEND="${QDATA_BACKEND:-sql}"
export QDATA_POSTGRES_DSN="${QDATA_POSTGRES_DSN:-postgresql://qdata:qdata@localhost:15432/qdata}"
export QDATA_CLICKHOUSE_DSN="${QDATA_CLICKHOUSE_DSN:-http://qdata:qdata@localhost:18123/default}"

python3 examples/sql_backend_smoke.py
