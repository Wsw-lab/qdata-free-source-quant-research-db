#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.pi_readiness import ReadinessThresholds, format_readiness_review, generate_vendor_readiness_review


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or report Pi vendor readiness review from benchmark suites.")
    parser.add_argument("--dataset-code", default="daily_bar")
    parser.add_argument("--source-code", default="vendor_http")
    parser.add_argument("--primary-source-code", default="csv")
    parser.add_argument("--windows", default="5,20,60")
    parser.add_argument("--review-date", default="")
    parser.add_argument("--min-coverage-rate", type=float, default=0.95)
    parser.add_argument("--max-conflict-rate", type=float, default=0.005)
    parser.add_argument("--max-failure-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-latency-ms", type=float, default=5000)
    parser.add_argument("--min-rows-per-second", type=float, default=0)
    parser.add_argument("--require-live-endpoint", action="store_true")
    parser.add_argument("--require-active-profile", action="store_true")
    parser.add_argument("--require-contract", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    thresholds = ReadinessThresholds(
        min_coverage_rate=args.min_coverage_rate,
        max_conflict_rate=args.max_conflict_rate,
        max_failure_rate=args.max_failure_rate,
        max_p95_latency_ms=args.max_p95_latency_ms,
        min_rows_per_second=args.min_rows_per_second,
    )
    review = generate_vendor_readiness_review(
        args.postgres_dsn,
        dataset_code=args.dataset_code,
        source_code=args.source_code,
        primary_source_code=args.primary_source_code,
        required_windows=[int(item.strip()) for item in args.windows.split(",") if item.strip()],
        thresholds=thresholds,
        review_date=args.review_date or None,
        require_live_endpoint=args.require_live_endpoint,
        require_active_profile=args.require_active_profile,
        require_contract=args.require_contract,
        write_db=not args.dry_run,
    )
    if args.json:
        print(json.dumps({"data": review, "meta": {"dry_run": args.dry_run}}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_readiness_review(review))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
