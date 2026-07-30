#!/usr/bin/env python3
from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.ingest import ingest_daily_bundle
from qdata.ingest.csv_files import read_daily_bars, read_security_master, read_trading_calendar
from qdata.ingest.quality import check_daily_bundle_quality
from qdata.loaders import SqlDailyBundleLoader


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest security master, trading calendar, and daily bars from CSV.")
    parser.add_argument("--security-master", default="raw/samples/security_master.csv")
    parser.add_argument("--calendar", default="raw/samples/trading_calendar.csv")
    parser.add_argument("--daily-bar", default="raw/samples/daily_bar.csv")
    parser.add_argument("--raw-root", default="raw")
    parser.add_argument("--source-name", default="local_csv")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only; do not write databases.")
    parser.add_argument("--no-store-raw", action="store_true", help="Do not copy source files into raw/imports.")
    parser.add_argument("--allow-quality-errors", action="store_true", help="Write even if high/critical quality checks fail.")
    args = parser.parse_args()

    if args.dry_run:
        securities = read_security_master(args.security_master)
        calendars = read_trading_calendar(args.calendar)
        daily_bars = read_daily_bars(args.daily_bar)
        report = check_daily_bundle_quality(securities, calendars, daily_bars)
        print(
            f"dry_run=true securities={len(securities)} calendar_rows={len(calendars)} "
            f"daily_bars={len(daily_bars)} passed={report.passed} errors={report.error_count} warnings={report.warning_count}"
        )
        return 0 if report.passed else 1

    with SqlDailyBundleLoader(args.postgres_dsn, args.clickhouse_dsn, source_code=args.source_name) as loader:
        summary = ingest_daily_bundle(
            security_master_path=args.security_master,
            trading_calendar_path=args.calendar,
            daily_bar_path=args.daily_bar,
            loader=loader,
            raw_root=args.raw_root,
            source_name=args.source_name,
            strict_quality=not args.allow_quality_errors,
            store_raw=not args.no_store_raw,
        )

    print(
        f"ingested securities={summary.security_count} calendar_rows={summary.calendar_count} "
        f"daily_bars={summary.daily_bar_count} quality_passed={summary.quality_report.passed} "
        f"errors={summary.quality_report.error_count} warnings={summary.quality_report.warning_count}"
    )
    for raw_path in summary.raw_paths:
        print(f"raw={raw_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
