#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.eta import (
    format_benchmark_report,
    record_benchmark_report,
    run_provider_benchmark,
    score_vendor_quality,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark and score primary/secondary market-data providers.")
    parser.add_argument("--primary-provider", default="csv")
    parser.add_argument("--secondary-provider", default="vendor_http")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--fields", default="open,high,low,close,volume,amount")
    parser.add_argument("--absolute-tolerance", type=float, default=1e-8)
    parser.add_argument("--tolerance-bps", type=float, default=0.0)
    parser.add_argument("--secondary-fixture-daily-bar-path", default="raw/samples/daily_bar.csv")
    parser.add_argument("--secondary-close-offset-bps", type=float, default=10.0)
    parser.add_argument("--secondary-base-url", default=os.getenv("QDATA_VENDOR_BASE_URL", ""))
    parser.add_argument("--secondary-token", default=os.getenv("QDATA_VENDOR_TOKEN", ""))
    parser.add_argument("--secondary-auth-mode", choices=["none", "bearer", "header", "query", "basic"], default=os.getenv("QDATA_VENDOR_AUTH_MODE", "none"))
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--cost-score", type=float, default=80)
    parser.add_argument("--license-risk-score", type=float, default=80)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    fields = [item.strip() for item in args.fields.split(",") if item.strip()]
    secondary_kwargs = _secondary_kwargs(args)
    report = run_provider_benchmark(
        primary_provider=args.primary_provider,
        secondary_provider=args.secondary_provider,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols,
        fields=fields,
        absolute_tolerance=args.absolute_tolerance,
        relative_tolerance=args.tolerance_bps / 10_000 if args.tolerance_bps else None,
        secondary_kwargs=secondary_kwargs,
    )
    score = score_vendor_quality(
        report,
        cost_score=args.cost_score,
        license_risk_score=args.license_risk_score,
    )
    db_result = record_benchmark_report(args.postgres_dsn, report, score) if args.write_db else None
    if args.json:
        print(json.dumps({"report": report, "score": score, "db_result": db_result}, ensure_ascii=False, default=lambda item: getattr(item, "__dict__", str(item)), indent=2, sort_keys=True))
    else:
        print(format_benchmark_report(report, score))
        if db_result:
            print(f"benchmark_db code={db_result['benchmark_code']} score={db_result['total_score']} rating={db_result['rating']}")
    return 0


def _secondary_kwargs(args) -> dict:
    if args.secondary_provider not in {"vendor_http", "commercial_http"}:
        return {}
    if args.secondary_base_url:
        return {
            "base_url": args.secondary_base_url,
            "token": args.secondary_token or None,
            "auth_mode": args.secondary_auth_mode,
        }
    return {
        "fixture_daily_bar_path": args.secondary_fixture_daily_bar_path,
        "close_offset_bps": args.secondary_close_offset_bps,
    }


if __name__ == "__main__":
    raise SystemExit(main())
