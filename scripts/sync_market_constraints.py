#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.sources.sync_delta import sync_market_constraints


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync adjustment factors, limit prices and suspensions.")
    parser.add_argument("--provider", choices=["csv", "akshare"], default="csv")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--raw-root", default="raw")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    parser.add_argument("--csv-security-master", default="raw/samples/security_master.csv")
    parser.add_argument("--csv-calendar", default="raw/samples/trading_calendar.csv")
    parser.add_argument("--csv-daily-bar", default="raw/samples/daily_bar.csv")
    parser.add_argument("--akshare-adjust", default="")
    parser.add_argument("--akshare-lookup-names", action="store_true")
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None
    result = sync_market_constraints(
        provider_name=args.provider,
        trade_date=args.trade_date,
        symbols=symbols,
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        raw_root=args.raw_root,
        dry_run=args.dry_run,
        provider_kwargs=_provider_config(args),
    )
    bundle = result["bundle"]
    print(
        f"provider={args.provider} date={args.trade_date} ingested={result['ingested']} "
        f"securities={len(bundle.securities)} factors={len(bundle.adjustment_factors)} "
        f"limits={len(bundle.limit_prices)} suspensions={len(bundle.suspensions)}"
    )
    print(f"paths={result['paths']}")
    return 0


def _provider_config(args) -> dict:
    if args.provider == "csv":
        return {
            "security_master_path": args.csv_security_master,
            "trading_calendar_path": args.csv_calendar,
            "daily_bar_path": args.csv_daily_bar,
        }
    return {
        "adjust": args.akshare_adjust,
        "lookup_names": args.akshare_lookup_names,
        "allow_full_market": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
