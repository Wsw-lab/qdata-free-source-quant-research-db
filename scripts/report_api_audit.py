#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.ops import build_ops_dashboard


def main() -> int:
    parser = argparse.ArgumentParser(description="Print API audit usage, error-rate, and slow-query summary.")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    start_date, end_date = _date_window(args.trade_date, args.start_date, args.end_date)
    dashboard = build_ops_dashboard(args.postgres_dsn, start_date, end_date)
    api = dashboard["api"]
    if args.json:
        print(json.dumps(api, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            f"api_audit start={start_date} end={end_date} requests={api['request_count']} "
            f"failed={api['failed_count']} error_rate={api['error_rate']} statuses={api['status_counts']}"
        )
        for item in api["slowest"]:
            print(f"slow_api api={item['api_name']} date={item['date']} max_duration_ms={item['max_duration_ms']}")
    return 0


def _date_window(trade_date: str, start_date: str, end_date: str) -> tuple[str, str]:
    if trade_date:
        return trade_date, trade_date
    if start_date and end_date:
        return start_date, end_date
    today = date.today().isoformat()
    return today, today


if __name__ == "__main__":
    raise SystemExit(main())
