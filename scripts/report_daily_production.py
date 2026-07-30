#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.pipeline import PostgresPipelineStore, format_store_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a daily market production report without rerunning jobs.")
    parser.add_argument("--job-code", default="daily_market_csv_all")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    start_date, end_date = _date_window(args.trade_date, args.start_date, args.end_date)
    with PostgresPipelineStore(args.postgres_dsn) as store:
        report = store.production_report(args.job_code, start_date, end_date)
    print(format_store_report(report))
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
