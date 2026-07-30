#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.pipeline import (
    PipelineJobConfig,
    PostgresPipelineStore,
    format_results_report,
    resolve_production_window,
    run_daily_pipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily market production with watermark/backfill/reporting.")
    parser.add_argument("--provider", choices=["csv", "akshare"], default="csv")
    parser.add_argument("--job-code", default="")
    parser.add_argument("--mode", choices=["incremental", "backfill", "rerun"], default="incremental")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--from-watermark", action="store_true")
    parser.add_argument("--watermark-lookback-days", type=int, default=0)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--no-all-market", dest="all_market", action="store_false")
    parser.set_defaults(all_market=True)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--min-completeness", type=float, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=0)
    parser.add_argument("--retry-limit", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=None)
    parser.add_argument("--raw-root", default="raw")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    parser.add_argument("--allow-quality-errors", action="store_true")
    parser.add_argument("--no-skip-closed-days", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--csv-security-master", default="raw/samples/security_master.csv")
    parser.add_argument("--csv-calendar", default="raw/samples/trading_calendar.csv")
    parser.add_argument("--csv-daily-bar", default="raw/samples/daily_bar.csv")
    parser.add_argument("--akshare-adjust", default="")
    parser.add_argument("--akshare-lookup-names", action="store_true")
    args = parser.parse_args()

    if args.trade_date:
        requested_start = args.trade_date
        end_date = args.trade_date
    else:
        requested_start = args.start_date or None
        end_date = args.end_date or date.today().isoformat()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
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
        provider_config=_provider_config(args),
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

    use_watermark = args.from_watermark or (args.mode == "incremental" and not args.trade_date)
    with PostgresPipelineStore(args.postgres_dsn) as store:
        start_date, end_date = resolve_production_window(
            store=store,
            config=config,
            start_date=requested_start,
            end_date=end_date,
            from_watermark=use_watermark,
            watermark_lookback_days=args.watermark_lookback_days,
        )

    run_type = "backfill" if args.mode == "backfill" else "manual"
    force = args.force or args.mode == "rerun"
    results = run_daily_pipeline(
        config=config,
        start_date=start_date,
        end_date=end_date,
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        force=force,
        dry_run=False,
        max_retries=args.max_retries,
        run_type=run_type,
    )
    print(format_results_report(job_code, start_date, end_date, results))
    return 1 if any(result.status == "failed" for result in results) else 0


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


if __name__ == "__main__":
    raise SystemExit(main())
