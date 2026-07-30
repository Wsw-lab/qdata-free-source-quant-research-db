#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.pipeline import PipelineJobConfig, run_daily_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily market data production pipeline.")
    parser.add_argument("--provider", choices=["csv", "akshare"], default="csv")
    parser.add_argument("--job-code", default="", help="Stable scheduler job code.")
    parser.add_argument("--trade-date", default="", help="Single YYYY-MM-DD trade date.")
    parser.add_argument("--start-date", default="", help="Inclusive YYYY-MM-DD start date.")
    parser.add_argument("--end-date", default="", help="Inclusive YYYY-MM-DD end date.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols, e.g. 600519.SH,000001.SZ")
    parser.add_argument("--raw-root", default="raw")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    parser.add_argument("--retry-limit", type=int, default=1, help="Retry limit stored on the scheduler job.")
    parser.add_argument("--max-retries", type=int, default=None, help="Override retries for this run.")
    parser.add_argument("--all-market", action="store_true", help="Resolve the provider's full A-share symbol universe.")
    parser.add_argument("--batch-size", type=int, default=0, help="Fetch symbols in batches, then ingest one merged bundle.")
    parser.add_argument("--max-symbols", type=int, default=None, help="Cap resolved symbols for smoke tests.")
    parser.add_argument("--min-completeness", type=float, default=None, help="Minimum actual/expected daily bar ratio.")
    parser.add_argument("--sleep-seconds", type=float, default=0, help="Sleep between symbol batches.")
    parser.add_argument("--no-skip-closed-days", action="store_true", help="Run even when provider calendar says the market is closed.")
    parser.add_argument("--force", action="store_true", help="Rerun dates that already have a successful run.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and export raw/vendor files without database ingestion.")
    parser.add_argument("--allow-quality-errors", action="store_true")
    parser.add_argument("--run-type", choices=["manual", "scheduled", "backfill", "retry"], default="manual")
    parser.add_argument("--csv-security-master", default="raw/samples/security_master.csv")
    parser.add_argument("--csv-calendar", default="raw/samples/trading_calendar.csv")
    parser.add_argument("--csv-daily-bar", default="raw/samples/daily_bar.csv")
    parser.add_argument("--akshare-adjust", default="", help="AkShare adjust mode: empty, qfq or hfq")
    parser.add_argument("--akshare-lookup-names", action="store_true", help="Fetch full-market spot names before syncing.")
    args = parser.parse_args()

    start_date, end_date = _date_window(args.trade_date, args.start_date, args.end_date)
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    provider_config = _provider_config(args)
    job_code = args.job_code or f"daily_market_{args.provider}{'_all' if args.all_market else ''}"
    min_completeness = args.min_completeness
    if min_completeness is None:
        min_completeness = 0.99 if args.all_market else 1.0
    config = PipelineJobConfig(
        job_code=job_code,
        provider=args.provider,
        dataset_code="daily_bar",
        frequency="daily",
        symbols=symbols,
        provider_config=provider_config,
        raw_root=args.raw_root,
        strict_quality=not args.allow_quality_errors,
        retry_limit=args.retry_limit,
        all_market=args.all_market,
        batch_size=args.batch_size,
        max_symbols=args.max_symbols,
        min_completeness=min_completeness,
        skip_closed_days=not args.no_skip_closed_days,
        sleep_seconds=args.sleep_seconds,
    )
    results = run_daily_pipeline(
        config=config,
        start_date=start_date,
        end_date=end_date,
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        force=args.force,
        dry_run=args.dry_run,
        max_retries=args.max_retries,
        run_type=args.run_type,
    )
    for result in results:
        text = (
            f"job={result.job_code} date={result.trade_date} attempt={result.attempt} "
            f"status={result.status} rows={result.row_count} errors={result.error_count} "
            f"warnings={result.warning_count} expected={result.expected_row_count} "
            f"missing={result.missing_count} completeness={_format_ratio(result.completeness_rate)} "
            f"batches={result.batch_count} repair={result.repair_status} run_id={result.run_id}"
        )
        if result.skipped_reason:
            text = f"{text} reason={result.skipped_reason}"
        if result.error_message:
            text = f"{text} error={result.error_message}"
        print(text)
    status_counts = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    print(
        "summary "
        + " ".join(f"{status}={count}" for status, count in sorted(status_counts.items()))
        + f" total={len(results)}"
    )
    return 1 if any(result.status == "failed" for result in results) else 0


def _date_window(trade_date: str, start_date: str, end_date: str) -> tuple[str, str]:
    if trade_date:
        return trade_date, trade_date
    if start_date and end_date:
        return start_date, end_date
    raise SystemExit("--trade-date or both --start-date and --end-date are required")


def _provider_config(args) -> dict:
    if args.provider == "csv":
        return {
            "security_master_path": args.csv_security_master,
            "trading_calendar_path": args.csv_calendar,
            "daily_bar_path": args.csv_daily_bar,
        }
    if args.provider == "akshare":
        return {
            "adjust": args.akshare_adjust,
            "lookup_names": args.akshare_lookup_names,
            "allow_full_market": args.all_market,
        }
    return {}


def _format_ratio(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
