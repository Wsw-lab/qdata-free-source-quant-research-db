#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.iota import ensure_vendor_benchmark_schedule, run_vendor_benchmark_schedule


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or run Iota vendor benchmark schedule.")
    parser.add_argument("--schedule-code", default="daily_bar_vendor_fixture_schedule")
    parser.add_argument("--dataset-code", default="daily_bar")
    parser.add_argument("--primary-source-code", default="csv")
    parser.add_argument("--secondary-source-code", default="vendor_http")
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--target-trade-days", type=int, default=None)
    parser.add_argument("--shard-size", type=int, default=1)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--cadence", choices=["manual", "daily", "weekly", "monthly"], default="manual")
    parser.add_argument("--symbols", default="600519.SH,000001.SZ")
    parser.add_argument("--secondary-close-offset-bps", type=float, default=10)
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    details = {
        "symbols": [item.strip().upper() for item in args.symbols.split(",") if item.strip()],
        "secondary_kwargs": {
            "fixture_daily_bar_path": "raw/samples/daily_bar.csv",
            "close_offset_bps": args.secondary_close_offset_bps,
        },
    }
    schedule = ensure_vendor_benchmark_schedule(
        args.postgres_dsn,
        schedule_code=args.schedule_code,
        dataset_code=args.dataset_code,
        primary_source_code=args.primary_source_code,
        secondary_source_code=args.secondary_source_code,
        start_date=args.start_date,
        end_date=args.end_date,
        target_trade_days=args.target_trade_days,
        shard_size=args.shard_size,
        max_symbols=args.max_symbols,
        cadence=args.cadence,
        details=details,
    )
    result = run_vendor_benchmark_schedule(args.postgres_dsn, args.schedule_code) if args.run_now else None
    payload = {"schedule": schedule, "run": result}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(f"vendor_benchmark_schedule code={schedule['schedule_code']} cadence={schedule['cadence']} status={schedule['status']}")
        if result:
            print(f"vendor_benchmark_schedule_run suite={result['suite_code']} status={result['status']} db={result['db_result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
