#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.omega5_route_incident_control import (
    format_omega5_report,
    format_omega5_rows,
    list_route_incident_controls,
    run_route_incident_control,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Omega-5 route incident control.")
    parser.add_argument("--resource", choices=["run", "controls"], default="run")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--lookback-hours", type=int, default=int(os.getenv("QDATA_OMEGA5_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--max-controls", type=int, default=int(os.getenv("QDATA_OMEGA5_ROUTE_MAX_CONTROLS", "50")))
    parser.add_argument("--execution-mode", choices=["review_only", "dry_run", "execute"], default=os.getenv("QDATA_OMEGA5_ROUTE_EXECUTION_MODE", "review_only"))
    parser.add_argument("--auto-approve", action="store_true", default=os.getenv("QDATA_OMEGA5_ROUTE_AUTO_APPROVE", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--approved-by", default=os.getenv("QDATA_OMEGA5_ROUTE_APPROVED_BY", ""))
    parser.add_argument("--requested-by", default=os.getenv("QDATA_OMEGA5_ROUTE_REQUESTED_BY", "omega5"))
    parser.add_argument("--approval-sla-hours", type=int, default=int(os.getenv("QDATA_OMEGA5_ROUTE_APPROVAL_SLA_HOURS", "4")))
    parser.add_argument("--no-wecom", action="store_true")
    parser.add_argument("--allow-wecom-external", action="store_true", default=os.getenv("QDATA_OMEGA5_ROUTE_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--no-rollback", action="store_true")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "api", "smoke", "demo"], default="manual")
    parser.add_argument("--control-code", default="")
    parser.add_argument("--incident-action-code", default="")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--source-signal-type", default="")
    parser.add_argument("--control-stage", default="")
    parser.add_argument("--approval-status", default="")
    parser.add_argument("--receipt-status", default="")
    parser.add_argument("--attempt-status", default="")
    parser.add_argument("--rollback-status", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.resource == "run":
        payload = run_route_incident_control(
            args.postgres_dsn,
            lookback_hours=args.lookback_hours,
            max_controls=args.max_controls,
            execution_mode=args.execution_mode,
            auto_approve=args.auto_approve,
            approved_by=args.approved_by or None,
            requested_by=args.requested_by,
            approval_sla_hours=args.approval_sla_hours,
            notify_wecom=not args.no_wecom,
            allow_wecom_external=args.allow_wecom_external,
            create_rollback=not args.no_rollback,
            trigger_mode=args.trigger_mode,
        )
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_omega5_report(payload))
        return 0

    rows = list_route_incident_controls(args.postgres_dsn, _params(args), args.limit, args.offset)
    print(json.dumps(rows, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_omega5_rows(args.resource, rows))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for name in [
        "control_code",
        "incident_action_code",
        "action_code",
        "dataset_code",
        "source_code",
        "source_signal_type",
        "control_stage",
        "approval_status",
        "receipt_status",
        "attempt_status",
        "rollback_status",
    ]:
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
