#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client
from qdata.database import PostgresClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark SQL backend daily price queries.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols.")
    parser.add_argument("--job-code", default="", help="Use latest run input_symbols for this job/date.")
    parser.add_argument("--trade-date", default="", help="Required when --job-code is used.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--adjust", choices=["none", "forward", "backward"], default="none")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if args.job_code:
        if not args.trade_date:
            raise SystemExit("--trade-date is required with --job-code")
        symbols = _symbols_from_latest_run(args.postgres_dsn, args.job_code, args.trade_date)
    if not symbols:
        raise SystemExit("--symbols or --job-code/--trade-date must provide at least one symbol")
    if args.repeat <= 0:
        raise SystemExit("--repeat must be greater than 0")

    durations = []
    row_counts = []
    with Client(
        backend="sql",
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        default_format="records",
    ) as client:
        for _ in range(args.repeat):
            started = perf_counter()
            rows = client.get_price(
                symbols=symbols,
                start_date=args.start_date,
                end_date=args.end_date,
                adjust=args.adjust,
            )
            durations.append((perf_counter() - started) * 1000)
            row_counts.append(len(rows))

    median_ms = statistics.median(durations)
    min_ms = min(durations)
    max_ms = max(durations)
    rows = row_counts[-1]
    rows_per_second = rows / (median_ms / 1000) if median_ms else 0
    print(
        f"benchmark symbols={len(symbols)} rows={rows} repeat={args.repeat} "
        f"median_ms={median_ms:.2f} min_ms={min_ms:.2f} max_ms={max_ms:.2f} "
        f"rows_per_second={rows_per_second:.2f}"
    )
    return 0


def _symbols_from_latest_run(postgres_dsn: str, job_code: str, trade_date: str) -> list[str]:
    postgres = PostgresClient(postgres_dsn)
    try:
        rows = postgres.fetch_all(
            """
            SELECT r.input_symbols
            FROM qmeta.pipeline_run r
            JOIN qmeta.pipeline_job j ON j.job_id = r.job_id
            WHERE j.job_code = %(job_code)s
              AND r.trade_date = %(trade_date)s
            ORDER BY r.run_id DESC
            LIMIT 1
            """,
            {"job_code": job_code, "trade_date": trade_date},
        )
    finally:
        postgres.close()
    if not rows:
        raise SystemExit(f"pipeline_run not found for job={job_code} trade_date={trade_date}")
    return [symbol for symbol in rows[0]["input_symbols"] or [] if symbol]


if __name__ == "__main__":
    raise SystemExit(main())
