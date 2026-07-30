#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.tau5_vendor_cost_optimization import run_vendor_cost_optimizer


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Tau-5 vendor cost optimization and budget stress.")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    row = run_vendor_cost_optimizer(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        source_code=args.source_code,
        primary_source_code=args.primary_source_code,
        requested_by="tau5-smoke",
        trigger_mode="smoke",
        environment="local",
        optimization_scope="primary_source",
        write_db=True,
    )
    if args.json:
        print(json.dumps({"resource": "tau5.vendor-cost-smoke", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            "tau5_vendor_cost_smoke=ok "
            f"status={row.get('status')} "
            f"role={row.get('optimization_role')} "
            f"datasets={row.get('dataset_count')} "
            f"optimized={row.get('optimized_dataset_count')} "
            f"watch={row.get('watch_dataset_count')} "
            f"over_budget={row.get('over_budget_dataset_count')} "
            f"quota_risk={row.get('quota_risk_dataset_count')} "
            f"blocked={row.get('blocked_dataset_count')} "
            f"no_primary={row.get('no_primary_dataset_count')} "
            f"primary_weight={row.get('recommended_primary_weight_pct')} "
            f"backup_weight={row.get('recommended_backup_weight_pct')} "
            f"free_weight={row.get('recommended_free_source_weight_pct')} "
            f"budget_pct={row.get('projected_budget_usage_pct')} "
            f"monthly_quota_pct={row.get('projected_monthly_quota_usage_pct')} "
            f"score={row.get('optimization_score')} "
            f"stress={len(row.get('stress_snapshots') or [])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
