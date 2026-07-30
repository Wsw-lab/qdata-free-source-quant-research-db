#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.theta import (
    format_benchmark_suite_report,
    load_active_field_mapping,
    load_vendor_runtime_config,
    record_benchmark_suite_report,
    run_sharded_provider_benchmark,
    score_vendor_quality,
    vendor_provider_kwargs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Theta sharded full-universe provider benchmark.")
    parser.add_argument("--primary-provider", default="csv")
    parser.add_argument("--secondary-provider", default="vendor_http")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--target-trade-days", type=int, default=None)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--shard-size", type=int, default=500)
    parser.add_argument("--fields", default="open,high,low,close,volume,amount")
    parser.add_argument("--absolute-tolerance", type=float, default=1e-8)
    parser.add_argument("--tolerance-bps", type=float, default=0.0)
    parser.add_argument("--secondary-base-url", default=os.getenv("QDATA_VENDOR_BASE_URL", ""))
    parser.add_argument("--secondary-fixture-daily-bar-path", default="raw/samples/daily_bar.csv")
    parser.add_argument("--secondary-close-offset-bps", type=float, default=10.0)
    parser.add_argument("--use-db-field-mapping", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--cost-score", type=float, default=80)
    parser.add_argument("--license-risk-score", type=float, default=80)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None
    fields = [item.strip() for item in args.fields.split(",") if item.strip()]
    secondary_kwargs = _secondary_kwargs(args)
    suite = run_sharded_provider_benchmark(
        primary_provider=args.primary_provider,
        secondary_provider=args.secondary_provider,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols,
        fields=fields,
        secondary_kwargs=secondary_kwargs,
        shard_size=args.shard_size,
        max_symbols=args.max_symbols,
        target_trade_days=args.target_trade_days,
        absolute_tolerance=args.absolute_tolerance,
        relative_tolerance=args.tolerance_bps / 10_000 if args.tolerance_bps else None,
    )
    score = score_vendor_quality(
        _suite_to_report_for_cli(suite),
        cost_score=args.cost_score,
        license_risk_score=args.license_risk_score,
    )
    db_result = record_benchmark_suite_report(args.postgres_dsn, suite, cost_score=args.cost_score, license_risk_score=args.license_risk_score) if args.write_db else None
    if args.json:
        print(json.dumps({"suite": suite, "score": score, "db_result": db_result}, ensure_ascii=False, default=lambda item: getattr(item, "__dict__", str(item)), indent=2, sort_keys=True))
    else:
        print(format_benchmark_suite_report(suite, score))
        if db_result:
            print(f"benchmark_suite_db code={db_result['suite_code']} suite_id={db_result['suite_id']} score={db_result['score']} rating={db_result['rating']}")
    return 0


def _secondary_kwargs(args) -> dict:
    if args.secondary_provider not in {"vendor_http", "commercial_http"}:
        return {}
    field_mapping = field_transforms = None
    if args.use_db_field_mapping:
        field_mapping, field_transforms = load_active_field_mapping(args.postgres_dsn, args.secondary_provider)
    if args.secondary_base_url:
        config = load_vendor_runtime_config(args.secondary_provider)
        return vendor_provider_kwargs(config, field_mapping=field_mapping, field_transforms=field_transforms)
    return {
        "fixture_daily_bar_path": args.secondary_fixture_daily_bar_path,
        "close_offset_bps": args.secondary_close_offset_bps,
        "field_mapping": field_mapping,
        "field_transforms": field_transforms,
    }


def _suite_to_report_for_cli(suite):
    from qdata.theta import _suite_to_benchmark_report

    return _suite_to_benchmark_report(suite)


if __name__ == "__main__":
    raise SystemExit(main())
