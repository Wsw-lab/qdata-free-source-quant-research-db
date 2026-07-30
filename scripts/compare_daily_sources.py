#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.fusion import compare_provider_daily, record_fusion_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare primary and secondary daily-market sources.")
    parser.add_argument("--primary-provider", default="csv")
    parser.add_argument("--secondary-provider", default="csv_mirror")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--fields", default="open,high,low,close,volume,amount")
    parser.add_argument("--absolute-tolerance", type=float, default=1e-8)
    parser.add_argument("--tolerance-bps", type=float, default=0.0)
    parser.add_argument("--secondary-close-offset-bps", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None
    fields = [item.strip() for item in args.fields.split(",") if item.strip()]
    secondary_kwargs = {"close_offset_bps": args.secondary_close_offset_bps}
    report = compare_provider_daily(
        primary_provider=args.primary_provider,
        secondary_provider=args.secondary_provider,
        trade_date=args.trade_date,
        symbols=symbols,
        fields=fields,
        absolute_tolerance=args.absolute_tolerance,
        relative_tolerance=args.tolerance_bps / 10_000 if args.tolerance_bps else None,
        secondary_kwargs=secondary_kwargs,
    )
    if not args.dry_run:
        record_fusion_report(
            args.postgres_dsn,
            report,
            details={"script": "compare_daily_sources.py", "secondary_close_offset_bps": args.secondary_close_offset_bps},
        )

    print(
        "fusion_report "
        f"date={report.trade_date} primary={report.primary_source_code} secondary={report.secondary_source_code} "
        f"primary_count={report.primary_count} secondary_count={report.secondary_count} matched={report.matched_count} "
        f"conflicts={report.conflict_count} coverage_rate={report.coverage_rate} conflict_rate={report.conflict_rate} "
        f"status={report.status} dry_run={args.dry_run}"
    )
    for conflict in report.conflicts[:10]:
        print(
            "conflict "
            f"symbol={conflict.symbol} field={conflict.field_name} "
            f"primary={conflict.primary_value} secondary={conflict.secondary_value} "
            f"abs={conflict.absolute_diff} rel={conflict.relative_diff} severity={conflict.severity}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
