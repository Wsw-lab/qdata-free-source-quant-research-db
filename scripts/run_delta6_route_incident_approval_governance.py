#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.delta6_route_incident_approval_governance import (
    cancel_route_incident_approval,
    ensure_route_approval_policy,
    ensure_route_approval_role_binding,
    escalate_route_approval_timeouts,
    format_delta6_report,
    format_delta6_rows,
    list_route_incident_approval_callbacks,
    list_route_incident_approval_escalations,
    list_route_incident_approval_policies,
    list_route_incident_approval_role_bindings,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Delta-6 route incident approval governance utilities.")
    parser.add_argument(
        "--resource",
        choices=["callbacks", "escalations", "policies", "role-bindings", "seed-role", "ensure-policy", "timeout-scan", "cancel"],
        default="callbacks",
    )
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--principal-code", default="")
    parser.add_argument("--role-code", default="route_approver")
    parser.add_argument("--binding-code", default="")
    parser.add_argument("--policy-code", default="delta6-default-route-approval-policy")
    parser.add_argument("--dataset-code", default="*")
    parser.add_argument("--source-code", default="*")
    parser.add_argument("--safety-level", default="*")
    parser.add_argument("--min-approvals", type=int, default=2)
    parser.add_argument("--timeout-minutes", type=int, default=240)
    parser.add_argument("--escalation-principal-code", default="platform-ops")
    parser.add_argument("--callback-code", default="")
    parser.add_argument("--command-code", default="")
    parser.add_argument("--control-code", default="")
    parser.add_argument("--approval-code", default="")
    parser.add_argument("--signature-status", default="")
    parser.add_argument("--governance-status", default="")
    parser.add_argument("--reason-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--requested-by", default="delta6")
    parser.add_argument("--reason", default="Delta-6 manual cancellation")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.resource == "seed-role":
        row = ensure_route_approval_role_binding(
            args.postgres_dsn,
            principal_code=_required(args.principal_code, "principal-code"),
            role_code=args.role_code,
            dataset_code=args.dataset_code,
            source_code=args.source_code,
            safety_level=args.safety_level,
            binding_code=args.binding_code or None,
            created_by=args.requested_by,
        )
        _print(row, args.json, row_formatter=format_delta6_report)
        return 0
    if args.resource == "ensure-policy":
        row = ensure_route_approval_policy(
            args.postgres_dsn,
            policy_code=args.policy_code,
            dataset_code=args.dataset_code,
            source_code=args.source_code,
            safety_level=args.safety_level,
            min_approvals=args.min_approvals,
            timeout_minutes=args.timeout_minutes,
            escalation_principal_code=args.escalation_principal_code,
            created_by=args.requested_by,
        )
        _print(row, args.json, row_formatter=format_delta6_report)
        return 0
    if args.resource == "timeout-scan":
        payload = escalate_route_approval_timeouts(args.postgres_dsn, limit=args.limit, write_db=True)
        _print(payload, args.json)
        return 0
    if args.resource == "cancel":
        payload = cancel_route_incident_approval(
            args.postgres_dsn,
            requested_by=args.requested_by,
            reason=args.reason,
            control_code=args.control_code or None,
            approval_code=args.approval_code or None,
        )
        _print(payload, args.json)
        return 0

    params = _params(args)
    if args.resource == "role-bindings":
        rows = list_route_incident_approval_role_bindings(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "policies":
        rows = list_route_incident_approval_policies(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "escalations":
        rows = list_route_incident_approval_escalations(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_route_incident_approval_callbacks(args.postgres_dsn, params, args.limit, args.offset)
    if args.json:
        print(json.dumps({"resource": args.resource, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_delta6_rows(args.resource.replace("-", "_"), rows))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for name in (
        "principal_code",
        "role_code",
        "binding_code",
        "policy_code",
        "dataset_code",
        "source_code",
        "safety_level",
        "callback_code",
        "command_code",
        "control_code",
        "approval_code",
        "signature_status",
        "governance_status",
        "reason_code",
        "status",
    ):
        value = getattr(args, name)
        if value and value != "*":
            params[name] = [str(value)]
    return params


def _print(payload: dict[str, object], as_json: bool, row_formatter=None) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    elif row_formatter:
        print(row_formatter(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


def _required(value: str, name: str) -> str:
    if not value:
        raise SystemExit(f"{name} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
