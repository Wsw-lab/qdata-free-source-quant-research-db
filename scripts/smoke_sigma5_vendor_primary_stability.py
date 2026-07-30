#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.sigma5_vendor_primary_stability import run_vendor_primary_stability_monitor


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Sigma-5 primary vendor production stability monitor.")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    row = run_vendor_primary_stability_monitor(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        source_code=args.source_code,
        primary_source_code=args.primary_source_code,
        requested_by="sigma5-smoke",
        trigger_mode="smoke",
        environment="local",
        monitor_scope="primary_source",
        write_db=True,
    )
    if args.json:
        print(json.dumps({"resource": "sigma5.primary-stability-smoke", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            "sigma5_primary_stability_smoke=ok "
            f"status={row.get('status')} "
            f"role={row.get('stability_role')} "
            f"datasets={row.get('dataset_count')} "
            f"primary={row.get('primary_dataset_count')} "
            f"healthy={row.get('healthy_dataset_count')} "
            f"warning={row.get('warning_dataset_count')} "
            f"critical={row.get('critical_dataset_count')} "
            f"blocked={row.get('blocked_dataset_count')} "
            f"no_primary={row.get('no_primary_dataset_count')} "
            f"api_success_rate={row.get('api_success_rate')} "
            f"scheduler_lag={row.get('scheduler_lag_minutes')} "
            f"backlog={row.get('backlog_count')} "
            f"score={row.get('stability_score')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
