#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.rho5_post_promotion_monitor import run_post_promotion_monitor


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Rho-5 post-promotion monitoring and rollback guardrail.")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default="csv")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    row = run_post_promotion_monitor(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        source_code=args.source_code,
        primary_source_code=args.primary_source_code,
        requested_by="rho5-smoke",
        trigger_mode="smoke",
        environment="local",
        promotion_scope="full_market",
        monitor_scope="post_promotion",
        require_applied_promotion=True,
        apply_rollback=False,
        write_db=True,
    )
    if args.json:
        print(json.dumps({"resource": "rho5.post-promotion-smoke", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            "rho5_post_promotion_monitor_smoke=ok "
            f"status={row.get('status')} "
            f"datasets={row.get('dataset_count')} "
            f"healthy={row.get('healthy_dataset_count')} "
            f"warning={row.get('warning_dataset_count')} "
            f"rollback_recommended={row.get('rollback_recommended_count')} "
            f"rolled_back={row.get('rolled_back_dataset_count')} "
            f"blocked={row.get('blocked_dataset_count')} "
            f"no_applied={row.get('no_applied_dataset_count')} "
            f"rollback_allowed={row.get('rollback_allowed')} "
            f"rollback_applied={row.get('rollback_applied')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
