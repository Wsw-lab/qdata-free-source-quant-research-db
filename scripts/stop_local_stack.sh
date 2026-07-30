#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.docker/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

docker compose down

echo "Local qdata stack stopped."
