#!/usr/bin/env python3
from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test synced daily market data through the SDK.")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--symbols", default="600519.SH,000001.SZ")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    with Client(
        backend="sql",
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        default_format="records",
    ) as client:
        prices = client.get_price(
            symbols=symbols,
            start_date=args.trade_date,
            end_date=args.trade_date,
            adjust="forward",
        )
        constraints = client.get_trading_constraints(
            symbols=symbols,
            start_date=args.trade_date,
            end_date=args.trade_date,
        )
        health = client.get_dataset_health(
            dataset_code="daily_bar",
            start_date=args.trade_date,
            end_date=args.trade_date,
        )
    print(f"prices_count={len(prices)} {prices}")
    print(f"constraints_count={len(constraints)} {constraints}")
    print(f"health_count={len(health)} {health}")
    return 0 if len(prices) == len(symbols) and health else 1


if __name__ == "__main__":
    raise SystemExit(main())
