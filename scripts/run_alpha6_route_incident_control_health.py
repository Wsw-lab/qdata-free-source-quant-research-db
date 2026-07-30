#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.alpha6_route_incident_control_health import (
    DEFAULT_CONTROL_SCHEDULE,
    format_alpha6_report,
    format_alpha6_rows,
    list_route_incident_control_health,
    run_route_incident_control_health,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Alpha-6 route incident control health checks.")
    parser.add_argument("--resource", choices=["check", "health"], default="check")
    parser.add_argument("--requested-by", default=os.getenv("QDATA_ALPHA6_ROUTE_REQUESTED_BY", "alpha6-cli"))
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default=os.getenv("QDATA_ALPHA6_ROUTE_ENVIRONMENT", "local"))
    parser.add_argument("--lookback-hours", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--approval-sla-hours", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_APPROVAL_SLA_HOURS", "4")))
    parser.add_argument("--max-pending-controls", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_MAX_PENDING_CONTROLS", "50")))
    parser.add_argument("--max-failed-execution-rate", type=float, default=float(os.getenv("QDATA_ALPHA6_ROUTE_MAX_FAILED_EXECUTION_RATE", "0.1")))
    parser.add_argument("--max-blocked-receipt-rate", type=float, default=float(os.getenv("QDATA_ALPHA6_ROUTE_MAX_BLOCKED_RECEIPT_RATE", "0.8")))
    parser.add_argument("--max-stale-minutes", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_MAX_STALE_MINUTES", "90")))
    parser.add_argument("--schedule-code", default=os.getenv("QDATA_ALPHA6_ROUTE_CONTROL_SCHEDULE_CODE", DEFAULT_CONTROL_SCHEDULE))
    parser.add_argument("--dry-run", action="store_true", help="Evaluate health without writing a snapshot.")
    parser.add_argument("--status", default="")
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--requested-by-filter", default="")
    parser.add_argument("--trigger-mode-filter", default="")
    parser.add_argument("--environment-filter", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "check":
        result = run_route_incident_control_health(
            args.postgres_dsn,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            lookback_hours=args.lookback_hours,
            approval_sla_hours=args.approval_sla_hours,
            max_pending_controls=args.max_pending_controls,
            max_failed_execution_rate=args.max_failed_execution_rate,
            max_blocked_receipt_rate=args.max_blocked_receipt_rate,
            max_stale_minutes=args.max_stale_minutes,
            schedule_code=args.schedule_code,
            write_db=not args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_alpha6_report(result))
        return 0

    params = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for key, value in {
        "status": args.status,
        "snapshot_code": args.snapshot_code,
        "requested_by": args.requested_by_filter,
        "trigger_mode": args.trigger_mode_filter,
        "environment": args.environment_filter,
        "schedule_code": args.schedule_code,
        "start_date": args.start_date,
        "end_date": args.end_date,
    }.items():
        if value:
            params[key] = [value]
    rows = list_route_incident_control_health(args.postgres_dsn, params, args.limit, args.offset)
    print(json.dumps({"resource": "health", "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_alpha6_rows("health", rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
