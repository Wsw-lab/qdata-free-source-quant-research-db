#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.omega_control import (
    decide_automation_approval,
    format_omega_report,
    format_omega_rows,
    list_automation_allowlists,
    list_automation_approvals,
    list_automation_attempts,
    list_automation_executors,
    list_automation_rollbacks,
    list_automation_secret_refs,
    request_automation_approval,
    request_automation_rollback,
    run_automation_rollback,
    run_omega_execution,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Omega automation control approvals, executors, retries, and rollbacks.")
    parser.add_argument(
        "--resource",
        choices=[
            "request-approval",
            "decide-approval",
            "execute",
            "request-rollback",
            "run-rollback",
            "approvals",
            "executors",
            "allowlists",
            "secrets",
            "attempts",
            "rollbacks",
        ],
        default="execute",
    )
    parser.add_argument("--action-code", default="")
    parser.add_argument("--approval-code", default="")
    parser.add_argument("--rollback-code", default="")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--action-type", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--executor-code", default="")
    parser.add_argument("--executor-type", default="")
    parser.add_argument("--allowlist-code", default="")
    parser.add_argument("--secret-ref", default="")
    parser.add_argument("--secret-scope", default="")
    parser.add_argument("--secret-kind", default="")
    parser.add_argument("--safety-level", default="")
    parser.add_argument("--trigger-mode", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--decided-by", default="")
    parser.add_argument("--executed-by", default="")
    parser.add_argument("--decision", choices=["approved", "rejected"], default="approved")
    parser.add_argument("--reason", default="")
    parser.add_argument("--expires-at", default="")
    parser.add_argument("--rollback-type", choices=["noop", "manual", "webhook", "script"], default="noop")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--max-actions", type=int, default=20)
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--attempt-code", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "request-approval":
        payload = request_automation_approval(
            args.postgres_dsn,
            action_code=args.action_code,
            requested_by=args.requested_by or "omega",
            reason=args.reason or "Omega approval requested",
            expires_at=args.expires_at or None,
        )
        _emit(payload, format_omega_rows("approvals", [payload]), args.json)
        return 0
    if args.resource == "decide-approval":
        payload = decide_automation_approval(
            args.postgres_dsn,
            approval_code=args.approval_code,
            decision=args.decision,
            decided_by=args.decided_by or args.requested_by or "omega",
            reason=args.reason,
        )
        _emit(payload, format_omega_rows("approvals", [payload]), args.json)
        return 0
    if args.resource == "execute":
        payload = run_omega_execution(
            args.postgres_dsn,
            action_code=args.action_code or None,
            run_code=args.run_code or None,
            action_type=args.action_type or None,
            status=args.status or None,
            trigger_mode=args.trigger_mode or "manual",
            executor_code=args.executor_code or None,
            requested_by=args.requested_by or "omega",
            max_actions=args.max_actions,
            allow_external=args.allow_external,
        )
        _emit(payload, format_omega_report(payload), args.json)
        return 0
    if args.resource == "request-rollback":
        payload = request_automation_rollback(
            args.postgres_dsn,
            action_code=args.action_code,
            requested_by=args.requested_by or "omega",
            reason=args.reason or "Omega rollback requested",
            rollback_type=args.rollback_type,
        )
        _emit(payload, format_omega_rows("rollbacks", [payload]), args.json)
        return 0
    if args.resource == "run-rollback":
        payload = run_automation_rollback(
            args.postgres_dsn,
            rollback_code=args.rollback_code,
            executed_by=args.executed_by or args.requested_by or "omega",
            allow_external=args.allow_external,
        )
        _emit(payload, format_omega_rows("rollbacks", [payload]), args.json)
        return 0

    params = _params(args)
    if args.resource == "approvals":
        rows = list_automation_approvals(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "executors":
        rows = list_automation_executors(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "allowlists":
        rows = list_automation_allowlists(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "secrets":
        rows = list_automation_secret_refs(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "attempts":
        rows = list_automation_attempts(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_automation_rollbacks(args.postgres_dsn, params, args.limit, args.offset)
    payload = {"resource": f"omega.{args.resource}", "row_count": len(rows), "rows": rows}
    _emit(payload, format_omega_rows(args.resource, rows), args.json)
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "action_code",
        "approval_code",
        "rollback_code",
        "attempt_code",
        "run_code",
        "action_type",
        "status",
        "executor_code",
        "executor_type",
        "allowlist_code",
        "secret_ref",
        "secret_scope",
        "secret_kind",
        "safety_level",
        "trigger_mode",
        "requested_by",
        "decided_by",
        "executed_by",
        "tenant_code",
        "project_code",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


def _emit(payload: dict, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
