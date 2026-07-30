#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.ops import build_ops_dashboard, format_ops_dashboard, record_dashboard_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the Zeta ops dashboard summary.")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--job-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-snapshot", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    start_date, end_date = _date_window(args.trade_date, args.start_date, args.end_date)
    dashboard = build_ops_dashboard(
        args.postgres_dsn,
        start_date,
        end_date,
        job_code=args.job_code or None,
        dataset_code=args.dataset_code or None,
    )
    if args.write_snapshot:
        snapshot = record_dashboard_snapshot(args.postgres_dsn, dashboard)
        dashboard["snapshot"] = snapshot
    if args.json:
        print(json.dumps(dashboard, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_ops_dashboard(dashboard))
        if dashboard.get("snapshot"):
            print(f"snapshot={dashboard['snapshot']['snapshot_code']}")
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
