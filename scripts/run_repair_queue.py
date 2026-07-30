#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.pipeline import PostgresPipelineStore, format_results_report, run_daily_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Rerun open daily market repair queue items.")
    parser.add_argument("--job-code", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-retries", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    with PostgresPipelineStore(args.postgres_dsn) as store:
        items = store.list_repair_items(
            job_code=args.job_code or None,
            statuses=["open"],
            limit=args.limit,
        )
        configs = {item["job_code"]: store.get_job_config(item["job_code"]) for item in items}

    if not items:
        print("repair_queue empty")
        return 0

    had_failure = False
    for item in items:
        trade_date = str(item["trade_date"])
        print(
            f"repair_item id={item['repair_id']} job={item['job_code']} "
            f"date={trade_date} reason={item['reason']} missing={item['missing_count']}"
        )
        if args.dry_run:
            continue
        results = run_daily_pipeline(
            config=configs[item["job_code"]],
            start_date=trade_date,
            end_date=trade_date,
            postgres_dsn=args.postgres_dsn,
            clickhouse_dsn=args.clickhouse_dsn,
            force=True,
            dry_run=False,
            max_retries=args.max_retries,
            run_type="retry",
        )
        print(format_results_report(item["job_code"], trade_date, trade_date, results))
        had_failure = had_failure or any(result.status == "failed" for result in results)
    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
