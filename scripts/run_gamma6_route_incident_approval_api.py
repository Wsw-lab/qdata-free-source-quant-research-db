#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.gamma6_route_incident_approval_api import (
    format_gamma6_report,
    format_gamma6_rows,
    list_route_incident_approval_command_items,
    list_route_incident_approval_commands,
    list_route_incident_approval_signatures,
    submit_route_incident_approval_command,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Gamma-6 route incident writable approval API operations.")
    parser.add_argument("--resource", choices=["submit", "commands", "items", "signatures"], default="commands")
    parser.add_argument("--decision", choices=["approve", "reject", "hold"], default="hold")
    parser.add_argument("--requested-by", default=os.getenv("QDATA_GAMMA6_REQUESTED_BY", "gamma6-cli"))
    parser.add_argument("--principal-code", default=os.getenv("QDATA_GAMMA6_PRINCIPAL_CODE", ""))
    parser.add_argument("--control-code", default="")
    parser.add_argument("--approval-code", default="")
    parser.add_argument("--batch-code", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--required-approvals", type=int, default=1)
    parser.add_argument("--trigger-mode", choices=["api", "manual", "smoke"], default="manual")
    parser.add_argument("--notify-wecom", action="store_true", default=os.getenv("QDATA_GAMMA6_NOTIFY_WECOM", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--allow-wecom-external", action="store_true", default=os.getenv("QDATA_GAMMA6_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--status", default="")
    parser.add_argument("--decision-filter", choices=["", "approve", "reject", "hold"], default="")
    parser.add_argument("--command-code", default="")
    parser.add_argument("--command-scope", default="")
    parser.add_argument("--quorum-status", default="")
    parser.add_argument("--item-status", default="")
    parser.add_argument("--signer-code", default="")
    parser.add_argument("--signature-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--source-signal-type", default="")
    parser.add_argument("--safety-level", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "submit":
        result = submit_route_incident_approval_command(
            args.postgres_dsn,
            decision=args.decision,
            requested_by=args.requested_by,
            principal_code=args.principal_code or None,
            control_code=args.control_code or None,
            approval_code=args.approval_code or None,
            batch_code=args.batch_code or None,
            idempotency_key=args.idempotency_key or None,
            required_approvals=args.required_approvals,
            trigger_mode=args.trigger_mode,
            notify_wecom=args.notify_wecom,
            allow_wecom_external=args.allow_wecom_external,
            write_db=True,
        )
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_gamma6_report(result))
        return 0

    params = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for key, value in {
        "status": args.status,
        "decision": args.decision_filter,
        "command_code": args.command_code,
        "command_scope": args.command_scope,
        "quorum_status": args.quorum_status,
        "item_status": args.item_status,
        "signer_code": args.signer_code,
        "signature_code": args.signature_code,
        "control_code": args.control_code,
        "approval_code": args.approval_code,
        "batch_code": args.batch_code,
        "dataset_code": args.dataset_code,
        "source_code": args.source_code,
        "source_signal_type": args.source_signal_type,
        "safety_level": args.safety_level,
        "start_date": args.start_date,
        "end_date": args.end_date,
    }.items():
        if value:
            params[key] = [value]
    if args.resource == "commands":
        rows = list_route_incident_approval_commands(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "items":
        rows = list_route_incident_approval_command_items(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_route_incident_approval_signatures(args.postgres_dsn, params, args.limit, args.offset)
    print(json.dumps({"resource": args.resource, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True) if args.json else format_gamma6_rows(args.resource, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
