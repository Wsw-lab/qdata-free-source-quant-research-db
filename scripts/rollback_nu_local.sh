#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.docker/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DROP_NU_METADATA=0
for arg in "$@"; do
  case "$arg" in
    --drop-nu-metadata)
      DROP_NU_METADATA=1
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

echo "Stopping Nu app/scheduler services..."
docker compose --profile app --profile scheduler stop qdata-api mu-scheduler >/dev/null 2>&1 || true

if [[ "$DROP_NU_METADATA" == "1" ]]; then
  echo "Dropping Nu deployment metadata tables..."
  docker compose exec -T postgres psql -U qdata -d qdata -v ON_ERROR_STOP=1 < db/rollback/0014_postgresql_ops_nu_drop.sql
else
  echo "Nu metadata preserved. Pass --drop-nu-metadata to remove only 0014 Nu tables."
fi

echo "Nu rollback step completed."
