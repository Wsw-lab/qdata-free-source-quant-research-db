#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.beta6_route_incident_ops import (
    format_beta6_report,
    format_beta6_rows,
    list_route_incident_operation_batches,
    list_route_incident_operation_items,
    run_route_incident_operations,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Beta-6 route incident operations.")
    parser.add_argument("--resource", choices=["run", "batches", "items"], default="run")
    parser.add_argument("--requested-by", default=os.getenv("QDATA_BETA6_ROUTE_REQUESTED_BY", "beta6-cli"))
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default=os.getenv("QDATA_BETA6_ROUTE_ENVIRONMENT", "local"))
    parser.add_argument("--operation-mode", choices=["approval_queue", "batch_approval", "pressure_test", "smoke"], default="approval_queue")
    parser.add_argument("--approval-decision", choices=["approve", "reject", "hold"], default=os.getenv("QDATA_BETA6_ROUTE_APPROVAL_DECISION", "hold"))
    parser.add_argument("--notification-policy", choices=["dedupe_digest", "critical_only", "none"], default=os.getenv("QDATA_BETA6_ROUTE_NOTIFICATION_POLICY", "dedupe_digest"))
    parser.add_argument("--stress-scope", choices=["full_market", "active_sources", "smoke"], default=os.getenv("QDATA_BETA6_ROUTE_STRESS_SCOPE", "full_market"))
    parser.add_argument("--lookback-hours", type=int, default=int(os.getenv("QDATA_BETA6_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--max-controls", type=int, default=int(os.getenv("QDATA_BETA6_ROUTE_MAX_CONTROLS", "100")))
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("QDATA_BETA6_ROUTE_DRY_RUN", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--apply-decisions", action="store_true", default=os.getenv("QDATA_BETA6_ROUTE_APPLY_DECISIONS", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--notify-wecom", action="store_true", default=os.getenv("QDATA_BETA6_ROUTE_NOTIFY_WECOM", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--allow-wecom-external", action="store_true", default=os.getenv("QDATA_BETA6_ROUTE_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--status", default="")
    parser.add_argument("--batch-code", default="")
    parser.add_argument("--control-code", default="")
    parser.add_argument("--approval-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--source-signal-type", default="")
    parser.add_argument("--safety-level", default="")
    parser.add_argument("--operation-decision", default="")
    parser.add_argument("--operation-status", default="")
    parser.add_argument("--requested-by-filter", default="")
    parser.add_argument("--trigger-mode-filter", default="")
    parser.add_argument("--environment-filter", default="")
    parser.add_argument("--operation-mode-filter", default="")
    parser.add_argument("--approval-decision-filter", default="")
    parser.add_argument("--notification-policy-filter", default="")
    parser.add_argument("--stress-scope-filter", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        result = run_route_incident_operations(
            args.postgres_dsn,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            operation_mode=args.operation_mode,
            approval_decision=args.approval_decision,
            notification_policy=args.notification_policy,
            stress_scope=args.stress_scope,
            lookback_hours=args.lookback_hours,
            max_controls=args.max_controls,
            dry_run=args.dry_run,
            apply_decisions=args.apply_decisions,
            notify_wecom=args.notify_wecom,
            allow_wecom_external=args.allow_wecom_external,
            write_db=True,
        )
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_beta6_report(result))
        return 0

    params = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for key, value in {
        "status": args.status,
        "batch_code": args.batch_code,
        "control_code": args.control_code,
        "approval_code": args.approval_code,
        "dataset_code": args.dataset_code,
        "source_code": args.source_code,
        "source_signal_type": args.source_signal_type,
        "safety_level": args.safety_level,
        "operation_decision": args.operation_decision,
        "operation_status": args.operation_status,
        "requested_by": args.requested_by_filter,
        "trigger_mode": args.trigger_mode_filter,
        "environment": args.environment_filter,
        "operation_mode": args.operation_mode_filter,
        "approval_decision": args.approval_decision_filter,
        "notification_policy": args.notification_policy_filter,
        "stress_scope": args.stress_scope_filter,
        "start_date": args.start_date,
        "end_date": args.end_date,
    }.items():
        if value:
            params[key] = [value]
    if args.resource == "batches":
        rows = list_route_incident_operation_batches(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_route_incident_operation_items(args.postgres_dsn, params, args.limit, args.offset)
    print(json.dumps({"resource": args.resource, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_beta6_rows(args.resource, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
