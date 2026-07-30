#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.epsilon6_route_incident_approval_resilience import (
    format_epsilon6_rows,
    list_route_incident_approval_audit_hashes,
    list_route_incident_approval_lock_events,
    list_route_incident_approval_recovery_drills,
    list_route_incident_approval_sla_actions,
    list_route_incident_approval_state_transitions,
    run_approval_recovery_drill,
    run_approval_sla_automation,
    verify_approval_audit_chain,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Epsilon-6 route incident approval resilience utilities.")
    parser.add_argument(
        "--resource",
        choices=[
            "lock-events",
            "state-transitions",
            "audit-chain",
            "sla-actions",
            "recovery-drills",
            "verify-chain",
            "sla-automation",
            "recovery-drill",
        ],
        default="audit-chain",
    )
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--lock-event-code", default="")
    parser.add_argument("--lock-scope", default="")
    parser.add_argument("--lock-status", default="")
    parser.add_argument("--transition-code", default="")
    parser.add_argument("--transition-status", default="")
    parser.add_argument("--reason-code", default="")
    parser.add_argument("--requested-decision", default="")
    parser.add_argument("--audit-hash-code", default="")
    parser.add_argument("--chain-scope", default="")
    parser.add_argument("--entity-type", default="")
    parser.add_argument("--entity-code", default="")
    parser.add_argument("--entry-hash", default="")
    parser.add_argument("--verification-status", default="")
    parser.add_argument("--sla-action-code", default="")
    parser.add_argument("--action-type", default="")
    parser.add_argument("--action-status", default="")
    parser.add_argument("--drill-code", default="")
    parser.add_argument("--drill-type", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--provider-code", default="")
    parser.add_argument("--control-code", default="")
    parser.add_argument("--approval-code", default="")
    parser.add_argument("--batch-code", default="")
    parser.add_argument("--command-code", default="")
    parser.add_argument("--callback-code", default="")
    parser.add_argument("--signer-code", default="")
    parser.add_argument("--owner-principal-code", default="")
    parser.add_argument("--target-control-code", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--trigger-mode", choices=["", "manual", "smoke", "worker"], default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.resource == "verify-chain":
        payload = verify_approval_audit_chain(
            args.postgres_dsn,
            chain_scope=args.chain_scope or None,
            limit=args.limit,
        )
        _print(payload, args.json)
        return 0
    if args.resource == "sla-automation":
        payload = run_approval_sla_automation(args.postgres_dsn, limit=args.limit, write_db=True)
        _print(payload, args.json)
        return 0
    if args.resource == "recovery-drill":
        payload = run_approval_recovery_drill(
            args.postgres_dsn,
            drill_type=args.drill_type or "full",
            requested_by=args.requested_by or "epsilon6",
            trigger_mode=args.trigger_mode or "manual",
            target_control_code=args.target_control_code or args.control_code or None,
            write_db=True,
        )
        _print(payload, args.json)
        return 0

    params = _params(args)
    if args.resource == "lock-events":
        rows = list_route_incident_approval_lock_events(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "state-transitions":
        rows = list_route_incident_approval_state_transitions(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "sla-actions":
        rows = list_route_incident_approval_sla_actions(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "recovery-drills":
        rows = list_route_incident_approval_recovery_drills(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_route_incident_approval_audit_hashes(args.postgres_dsn, params, args.limit, args.offset)

    if args.json:
        print(json.dumps({"resource": args.resource, "row_count": len(rows), "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_epsilon6_rows(args.resource.replace("-", "_"), rows))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for name in (
        "lock_event_code",
        "lock_scope",
        "lock_status",
        "transition_code",
        "transition_status",
        "reason_code",
        "requested_decision",
        "audit_hash_code",
        "chain_scope",
        "entity_type",
        "entity_code",
        "entry_hash",
        "verification_status",
        "sla_action_code",
        "action_type",
        "action_status",
        "drill_code",
        "drill_type",
        "status",
        "provider_code",
        "control_code",
        "approval_code",
        "batch_code",
        "command_code",
        "callback_code",
        "signer_code",
        "owner_principal_code",
        "target_control_code",
        "requested_by",
        "trigger_mode",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [str(value)]
    return params


def _print(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
