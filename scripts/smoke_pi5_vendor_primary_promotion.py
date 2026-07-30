#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.pi5_vendor_primary_promotion import run_vendor_primary_promotion_review


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Pi-5 vendor primary promotion guardrail.")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default="csv")
    parser.add_argument("--no-full-market-required", action="store_true")
    parser.add_argument("--no-signoff-required", action="store_true")
    parser.add_argument("--apply-routing", action="store_true")
    parser.add_argument("--target-priority", type=int, default=int(os.getenv("QDATA_PI5_TARGET_PRIORITY", "0")))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    row = run_vendor_primary_promotion_review(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        source_code=args.source_code,
        primary_source_code=args.primary_source_code,
        requested_by="pi5-smoke",
        trigger_mode="smoke",
        environment="local",
        promotion_scope="full_market",
        require_full_market=not args.no_full_market_required,
        require_signoff=not args.no_signoff_required,
        apply_routing=args.apply_routing,
        target_priority=args.target_priority,
        write_db=True,
    )
    if args.json:
        print(json.dumps({"resource": "pi5.vendor-primary-promotion-smoke", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            "pi5_vendor_primary_promotion_smoke=ok "
            f"status={row.get('status')} "
            f"datasets={row.get('dataset_count')} "
            f"approved={row.get('approved_dataset_count')} "
            f"pending={row.get('pending_dataset_count')} "
            f"blocked={row.get('blocked_dataset_count')} "
            f"applied={row.get('applied_dataset_count')} "
            f"routing_allowed={row.get('routing_change_allowed')} "
            f"routing_applied={row.get('routing_change_applied')} "
            f"promotion_code={row.get('promotion_code')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
