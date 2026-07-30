#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client
from qdata.ingest.models import TradableUniverseRecord
from qdata.loaders import SqlDailyBundleLoader


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and persist a daily tradable A-share universe.")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--base-universe", default="")
    parser.add_argument("--universe-code", default="tradable_a_share")
    parser.add_argument("--universe-name", default="每日可交易 A 股")
    parser.add_argument("--min-list-days", type=int, default=30)
    parser.add_argument("--include-st", action="store_true")
    parser.add_argument("--include-suspended", action="store_true")
    parser.add_argument("--include-new-listing", action="store_true")
    parser.add_argument("--include-delisting-period", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None
    with Client(
        backend="sql",
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        default_format="records",
    ) as client:
        rows = client.get_tradable_universe(
            asof_date=args.trade_date,
            symbols=symbols,
            universe=args.base_universe or None,
            exclude_st=not args.include_st,
            exclude_suspended=not args.include_suspended,
            exclude_new_listing=not args.include_new_listing,
            exclude_delisting_period=not args.include_delisting_period,
            min_list_days=args.min_list_days,
        )
    records = [
        TradableUniverseRecord(symbol=row["symbol"], trade_date=args.trade_date)
        for row in rows
    ]
    if not args.dry_run:
        with SqlDailyBundleLoader(args.postgres_dsn, args.clickhouse_dsn, source_code="qdata") as loader:
            loader.load_tradable_universe(args.universe_code, args.universe_name, args.trade_date, records)
    print(
        f"universe={args.universe_code} date={args.trade_date} dry_run={args.dry_run} "
        f"members={len(records)} symbols={[record.symbol for record in records[:20]]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
