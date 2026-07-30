#!/usr/bin/env python3
from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.sources.sync import sync_daily_market


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync daily A-share market data from a provider into local databases.")
    parser.add_argument(
        "--provider",
        choices=[
            "csv",
            "csv_mirror",
            "akshare",
            "baostock",
            "tushare_free",
            "cninfo_public",
            "sse_public",
            "szse_public",
            "nbs_public",
            "vendor_http",
            "commercial_http",
        ],
        default="csv",
    )
    parser.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols, e.g. 600519.SH,000001.SZ")
    parser.add_argument("--raw-root", default="raw")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-quality-errors", action="store_true")
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--min-completeness", type=float, default=1.0)
    parser.add_argument("--sleep-seconds", type=float, default=0)
    parser.add_argument("--csv-security-master", default="raw/samples/security_master.csv")
    parser.add_argument("--csv-calendar", default="raw/samples/trading_calendar.csv")
    parser.add_argument("--csv-daily-bar", default="raw/samples/daily_bar.csv")
    parser.add_argument("--akshare-adjust", default="", help="AkShare adjust mode: empty, qfq or hfq")
    parser.add_argument("--akshare-lookup-names", action="store_true", help="Fetch full-market spot names before syncing.")
    parser.add_argument("--use-route-policy", action="store_true", help="Resolve active Phi-5 route policy before selecting provider.")
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    csv_kwargs = {
        "security_master_path": args.csv_security_master,
        "trading_calendar_path": args.csv_calendar,
        "daily_bar_path": args.csv_daily_bar,
    }
    provider_kwargs = _provider_kwargs(args.provider, csv_kwargs, args.akshare_adjust, args.akshare_lookup_names)
    route_provider_kwargs = {
        "csv": csv_kwargs,
        "csv_mirror": {**csv_kwargs, "provider_name": "csv_mirror"},
        "akshare": {"adjust": args.akshare_adjust, "lookup_names": args.akshare_lookup_names},
    }

    result = sync_daily_market(
        provider_name=args.provider,
        trade_date=args.trade_date,
        symbols=symbols or None,
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        raw_root=args.raw_root,
        strict_quality=not args.allow_quality_errors,
        dry_run=args.dry_run,
        provider_kwargs=provider_kwargs,
        expected_symbols=symbols or None,
        min_completeness=args.min_completeness,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep_seconds,
        use_route_policy=args.use_route_policy,
        route_provider_kwargs=route_provider_kwargs,
    )
    bundle = result["bundle"]
    summary = result["summary"]
    print(
        f"provider={bundle.provider} trade_date={bundle.trade_date} "
        f"securities={len(bundle.securities)} calendars={len(bundle.calendars)} daily_bars={len(bundle.daily_bars)}"
    )
    completeness = result.get("completeness") or {}
    if completeness:
        print(
            "completeness="
            f"{completeness.get('completeness_rate')} expected={completeness.get('expected_count')} "
            f"actual={completeness.get('actual_count')} missing={completeness.get('missing_count')}"
        )
        missing = completeness.get("missing_symbols") or []
        if missing:
            print(f"missing_symbols={','.join(missing[:50])}")
    for key, path in result["paths"].items():
        print(f"{key}={path}")
    if summary:
        print(
            f"ingested=true quality_passed={summary.quality_report.passed} "
            f"errors={summary.quality_report.error_count} warnings={summary.quality_report.warning_count}"
        )
    else:
        print("ingested=false dry_run=true")
    route_decision = result.get("route_decision")
    if route_decision:
        print(
            "route_policy="
            f"mode={route_decision.get('route_mode')} status={route_decision.get('decision_status')} "
            f"requested={route_decision.get('requested_source_code')} selected={route_decision.get('selected_source_code')} "
            f"final={route_decision.get('final_source_code')} fallback={route_decision.get('fallback_applied')}"
        )
    return 0


def _provider_kwargs(provider: str, csv_kwargs: dict, akshare_adjust: str, akshare_lookup_names: bool) -> dict:
    if provider in {"csv", "csv_mirror"}:
        kwargs = dict(csv_kwargs)
        if provider == "csv_mirror":
            kwargs["provider_name"] = "csv_mirror"
        return kwargs
    if provider == "akshare":
        return {"adjust": akshare_adjust, "lookup_names": akshare_lookup_names}
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
