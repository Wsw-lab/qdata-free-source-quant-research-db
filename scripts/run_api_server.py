#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.api import run_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the qdata REST API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--backend", choices=["auto", "mock", "sql"], default=os.getenv("QDATA_API_BACKEND", "auto"))
    parser.add_argument("--tokens", default=os.getenv("QDATA_API_TOKENS", ""))
    parser.add_argument("--token-scopes", default=os.getenv("QDATA_API_TOKEN_SCOPES", "read"))
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    tokens = [item.strip() for item in args.tokens.split(",") if item.strip()]
    token_scopes = [item.strip() for item in args.token_scopes.split(",") if item.strip()]
    run_server(
        host=args.host,
        port=args.port,
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        tokens=tokens,
        token_scopes=token_scopes,
        default_backend=args.backend,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
