#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.nu5_free_source_recovery_health import (
    DEFAULT_EXECUTION_SCHEDULE,
    format_nu5_rows,
    list_free_source_recovery_health,
    run_free_source_recovery_health,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Nu-5 free source recovery health checks.")
    parser.add_argument("--resource", choices=["check", "snapshots"], default="check")
    parser.add_argument("--requested-by", default="nu5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--lookback-hours", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--approval-sla-hours", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_APPROVAL_SLA_HOURS", "4")))
    parser.add_argument("--max-backlog-actions", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_MAX_BACKLOG_ACTIONS", "50")))
    parser.add_argument("--max-failure-rate", type=float, default=float(os.getenv("QDATA_NU5_FREE_SOURCE_MAX_FAILURE_RATE", "0.5")))
    parser.add_argument("--max-stale-minutes", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_MAX_STALE_MINUTES", "90")))
    parser.add_argument("--schedule-code", default=os.getenv("QDATA_NU5_RECOVERY_EXECUTION_SCHEDULE", DEFAULT_EXECUTION_SCHEDULE))
    parser.add_argument("--dry-run", action="store_true", help="Evaluate health without writing a snapshot.")
    parser.add_argument("--status", default="")
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "check":
        result = run_free_source_recovery_health(
            args.postgres_dsn,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            lookback_hours=args.lookback_hours,
            approval_sla_hours=args.approval_sla_hours,
            max_backlog_actions=args.max_backlog_actions,
            max_failure_rate=args.max_failure_rate,
            max_stale_minutes=args.max_stale_minutes,
            schedule_code=args.schedule_code,
            write_db=not args.dry_run,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, default=str, indent=2, sort_keys=True))
        else:
            print(
                "nu5_free_source_recovery_health "
                f"status={result.get('status')} snapshot_code={result.get('snapshot_code')} "
                f"backlog={result.get('backlog_count')} approvals={result.get('approval_pending_count')} "
                f"overdue={result.get('approval_overdue_count')} failures={result.get('failed_count')} "
                f"stale_schedule={result.get('stale_schedule_count')}"
            )
        return 0

    params = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for key, value in {
        "status": args.status,
        "snapshot_code": args.snapshot_code,
        "environment": args.environment,
        "schedule_code": args.schedule_code,
    }.items():
        if value:
            params[key] = [value]
    rows = list_free_source_recovery_health(args.postgres_dsn, params, args.limit, args.offset)
    if args.json:
        print(json.dumps({"resource": "snapshots", "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_nu5_rows("snapshots", rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
