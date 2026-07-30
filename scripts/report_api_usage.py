#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.iota import fetch_api_usage_daily, format_usage_report, rollup_api_usage_daily


def main() -> int:
    parser = argparse.ArgumentParser(description="Roll up and report Iota API usage billing metrics.")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--rollup", action="store_true")
    parser.add_argument("--cost-per-request", type=float, default=1.0)
    parser.add_argument("--cost-per-1000-rows", type=float, default=0.1)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    start_date, end_date = _date_window(args.trade_date, args.start_date, args.end_date)
    if args.rollup:
        rollup_api_usage_daily(
            args.postgres_dsn,
            start_date,
            end_date,
            cost_per_request=args.cost_per_request,
            cost_per_1000_rows=args.cost_per_1000_rows,
        )
    rows = fetch_api_usage_daily(args.postgres_dsn, start_date, end_date, project_code=args.project_code or None)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_usage_report(rows))
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
