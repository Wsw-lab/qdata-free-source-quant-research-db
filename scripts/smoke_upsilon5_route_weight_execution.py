#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.upsilon5_route_weight_execution import run_vendor_route_weight_execution


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Upsilon-5 route-weight execution guardrails.")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    result = run_vendor_route_weight_execution(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        source_code=args.source_code,
        primary_source_code=args.primary_source_code,
        requested_by="upsilon5-smoke",
        trigger_mode="smoke",
        execution_scope="primary_source",
        execution_mode="review_only",
        approval_policy="manual_required",
        approval_status="pending",
        rollout_policy="gradual",
        write_db=True,
    )
    print(
        " ".join(
            [
                "upsilon5_route_execution_smoke=ok",
                f"status={result.get('status')}",
                f"datasets={result.get('dataset_count')}",
                f"pending={result.get('pending_approval_dataset_count')}",
                f"approved={result.get('approved_dataset_count')}",
                f"staged={result.get('staged_dataset_count')}",
                f"applied={result.get('applied_dataset_count')}",
                f"blocked={result.get('blocked_dataset_count')}",
                f"no_primary={result.get('no_primary_dataset_count')}",
                f"target_primary={result.get('target_primary_weight_pct')}",
                f"applied_primary={result.get('applied_primary_weight_pct')}",
                f"policies={len(result.get('policies') or [])}",
                f"stages={len(result.get('stages') or [])}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
