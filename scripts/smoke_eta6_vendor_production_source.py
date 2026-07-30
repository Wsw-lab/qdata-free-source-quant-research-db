#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.eta6_vendor_production_source import run_vendor_production_source_closure


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Eta-6 real-vendor production primary-source closure.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--dataset-code", action="append", default=[])
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--allow-missing-real-vendor-env", action="store_true")
    parser.add_argument("--min-stability-score", type=float, default=70.0)
    args = parser.parse_args()

    row = run_vendor_production_source_closure(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        source_code=args.source_code,
        primary_source_code=args.primary_source_code,
        dataset_codes=args.dataset_code or None,
        requested_by="eta6-smoke",
        trigger_mode="smoke",
        environment="local",
        closure_scope="production_primary",
        closure_mode="review_only",
        require_real_vendor_env=not args.allow_missing_real_vendor_env,
        external_probe_allowed=False,
        min_stability_score=args.min_stability_score,
        write_db=True,
    )
    if row.get("status") not in {"blocked", "ready_for_pilot", "ready_for_primary", "ready_for_rollout", "production_ready", "monitoring"}:
        raise RuntimeError(f"unexpected Eta-6 status: {row.get('status')}")
    print(
        "eta6_vendor_production_source_smoke=ok "
        f"status={row.get('status')} "
        f"role={row.get('production_role')} "
        f"datasets={row.get('dataset_count')} "
        f"production_ready={row.get('production_ready_dataset_count')} "
        f"blocked={row.get('blocked_dataset_count')} "
        f"decisions={len(row.get('decisions') or [])} "
        f"live_base_url_present={row.get('live_base_url_present')} "
        f"live_token_present={row.get('live_token_present')} "
        f"score={row.get('production_score')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
