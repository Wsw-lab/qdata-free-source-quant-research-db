#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.pi5_vendor_primary_promotion import (
    format_pi5_rows,
    list_vendor_primary_promotion_results,
    list_vendor_primary_promotions,
    run_vendor_primary_promotion_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Pi-5 vendor primary promotion guardrail.")
    parser.add_argument("--resource", choices=["run", "runs", "results"], default="run")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default="vendor_http")
    parser.add_argument("--primary-source-code", default="csv")
    parser.add_argument("--dataset-code", action="append")
    parser.add_argument("--requested-by", default="pi5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--promotion-scope", choices=["canary", "full_market"], default="full_market")
    parser.add_argument("--windows", default="5,20,60")
    parser.add_argument("--no-full-market-required", action="store_true")
    parser.add_argument("--no-signoff-required", action="store_true")
    parser.add_argument("--apply-routing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target-priority", type=int, default=0)
    parser.add_argument("--promotion-code", default="")
    parser.add_argument("--result-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--promotion-role", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    params = _params(args)
    if args.resource == "run":
        rows = run_vendor_primary_promotion_review(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            dataset_codes=args.dataset_code,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            promotion_scope=args.promotion_scope,
            required_windows=_windows(args.windows),
            require_full_market=not args.no_full_market_required,
            require_signoff=not args.no_signoff_required,
            apply_routing=args.apply_routing,
            target_priority=args.target_priority,
            write_db=not args.dry_run,
        )
        resource = "run"
    elif args.resource == "runs":
        rows = list_vendor_primary_promotions(args.postgres_dsn, params, args.limit, args.offset)
        resource = "runs"
    else:
        rows = list_vendor_primary_promotion_results(args.postgres_dsn, params, args.limit, args.offset)
        resource = "results"

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_pi5_rows(resource, rows))
    return 0


def _params(args) -> dict[str, list[str]]:
    pairs = {
        "promotion_code": args.promotion_code,
        "result_code": args.result_code,
        "source_code": args.source_code,
        "primary_source_code": args.primary_source_code,
        "dataset_code": args.dataset_code[0] if args.dataset_code else "",
        "status": args.status,
        "promotion_role": args.promotion_role,
        "promotion_scope": args.promotion_scope,
        "as_of_date": args.as_of_date,
        "environment": args.environment,
    }
    return {key: [value] for key, value in pairs.items() if value}


def _windows(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
