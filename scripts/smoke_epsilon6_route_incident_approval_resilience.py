#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import hashlib
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.chi5_route_feedback import list_source_route_circuit_breakers, run_source_route_feedback_monitor
from qdata.delta6_route_incident_approval_governance import (
    ensure_route_approval_policy,
    ensure_route_approval_role_binding,
)
from qdata.epsilon6_route_incident_approval_resilience import (
    list_route_incident_approval_audit_hashes,
    list_route_incident_approval_lock_events,
    list_route_incident_approval_recovery_drills,
    list_route_incident_approval_sla_actions,
    list_route_incident_approval_state_transitions,
    run_approval_recovery_drill,
    run_approval_sla_automation,
    verify_approval_audit_chain,
)
from qdata.omega5_route_incident_control import list_route_incident_controls, run_route_incident_control
from qdata.psi_automation import run_psi_automation
from scripts.smoke_delta6_route_incident_approval_governance import _age_command, _post_callback
from scripts.smoke_omega5_route_incident_control import _find_route_action, _insert_decision


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Epsilon-6 resilient route incident approval callbacks.")
    parser.add_argument("--base-url", default=os.getenv("QDATA_API_BASE_URL", "http://127.0.0.1:18080"))
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--secret", default=os.getenv("QDATA_DELTA6_WECOM_CALLBACK_SECRET", "delta6-local-secret"))
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    source_code = f"epsilon6_smoke_{hashlib.sha1(stamp.encode('utf-8')).hexdigest()[:10]}"
    failed_code = _insert_decision(
        args.postgres_dsn,
        source_code=source_code,
        decision_status="failed",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        row_count=0,
        request_key=f"epsilon6-open-{stamp}",
    )
    run_source_route_feedback_monitor(
        args.postgres_dsn,
        requested_by="epsilon6-smoke",
        trigger_mode="smoke",
        lookback_hours=4,
        max_failure_rate=0.0,
        max_empty_rate=0.0,
        circuit_open_minutes=0,
        write_db=True,
    )
    circuits = list_source_route_circuit_breakers(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 5, 0)
    if not circuits or circuits[0].get("status") != "open":
        raise RuntimeError(f"Epsilon-6 precondition failed: route circuit did not open after {failed_code}")

    psi_result = run_psi_automation(
        args.postgres_dsn,
        environment="local",
        trigger_mode="smoke",
        execution_mode="execute",
        approve=False,
        include_phi=False,
        include_chi=False,
        include_route=True,
        route_lookback_hours=4,
        route_max_actions=20,
        route_owner="platform-ops",
        route_include_recovered=False,
        run_code=f"epsilon6-route-open-smoke-{stamp}",
        write_db=True,
    )
    open_action = _find_route_action(psi_result, source_code, "daily_bar", "circuit_open")
    if not open_action or open_action.get("status") != "approval_required":
        raise RuntimeError(f"Psi-5 did not create approval-required action for Epsilon-6 smoke: {psi_result}")

    run_route_incident_control(
        args.postgres_dsn,
        lookback_hours=4,
        max_controls=20,
        execution_mode="review_only",
        auto_approve=False,
        requested_by="epsilon6-requester",
        approval_sla_hours=4,
        notify_wecom=True,
        allow_wecom_external=False,
        create_rollback=True,
        trigger_mode="smoke",
        write_db=True,
    )
    pending_control = _latest_control(args.postgres_dsn, source_code)
    if not pending_control or pending_control.get("approval_status") != "pending":
        raise RuntimeError(f"Epsilon-6 precondition failed: no pending Omega-5 control for {source_code}")

    control_code = str(pending_control["control_code"])
    ensure_route_approval_policy(
        args.postgres_dsn,
        policy_code="delta6-default-route-approval-policy",
        min_approvals=2,
        timeout_minutes=1,
        require_distinct_requester=True,
        require_wecom_signature=True,
        escalation_principal_code="platform-ops",
        created_by="epsilon6-smoke",
    )
    ensure_route_approval_role_binding(args.postgres_dsn, principal_code="epsilon6-approver-a", role_code="route_approver", created_by="epsilon6-smoke")
    ensure_route_approval_role_binding(args.postgres_dsn, principal_code="epsilon6-approver-b", role_code="route_approver", created_by="epsilon6-smoke")

    first = _post_callback(
        args.base_url,
        args.secret,
        {
            "provider_code": "wecom",
            "decision": "approve",
            "control_code": control_code,
            "requested_by": "epsilon6-smoke",
            "signer_code": "epsilon6-approver-a",
            "required_approvals": 2,
            "trigger_mode": "smoke",
            "idempotency_key": f"epsilon6-approval-a:{control_code}:{stamp}",
        },
        nonce=f"epsilon6-valid-a-{stamp}",
    )
    if first.get("governance_status") != "pending_quorum" or not (first.get("epsilon6") or {}).get("lock_event_code"):
        raise RuntimeError(f"Epsilon-6 first callback should wait for quorum and record lock evidence: {first}")

    _age_command(args.postgres_dsn, str(first["command_code"]), minutes=10)
    sla_result = run_approval_sla_automation(args.postgres_dsn, limit=20, write_db=True)
    if int(sla_result.get("sla_action_count") or 0) < 1:
        raise RuntimeError(f"Epsilon-6 SLA automation did not create an action: {sla_result}")

    drill = run_approval_recovery_drill(
        args.postgres_dsn,
        drill_type="full",
        requested_by="epsilon6-smoke",
        trigger_mode="smoke",
        target_control_code=control_code,
        write_db=True,
    )
    if drill.get("status") != "success":
        raise RuntimeError(f"Epsilon-6 recovery drill failed: {drill}")

    second = _post_callback(
        args.base_url,
        args.secret,
        {
            "provider_code": "wecom",
            "decision": "approve",
            "control_code": control_code,
            "requested_by": "epsilon6-smoke",
            "signer_code": "epsilon6-approver-b",
            "required_approvals": 2,
            "trigger_mode": "smoke",
            "idempotency_key": f"epsilon6-approval-b:{control_code}:{stamp}",
        },
        nonce=f"epsilon6-valid-b-{stamp}",
    )
    if second.get("governance_status") != "applied":
        raise RuntimeError(f"Epsilon-6 second callback did not apply after quorum: {second}")

    approved_control = _latest_control(args.postgres_dsn, source_code)
    if not approved_control or approved_control.get("approval_status") != "approved":
        raise RuntimeError(f"Epsilon-6 did not approve control after governed quorum: {approved_control}")

    terminal_block = _post_callback(
        args.base_url,
        args.secret,
        {
            "provider_code": "wecom",
            "decision": "reject",
            "control_code": control_code,
            "requested_by": "epsilon6-smoke",
            "signer_code": "epsilon6-approver-b",
            "required_approvals": 2,
            "trigger_mode": "smoke",
            "idempotency_key": f"epsilon6-terminal-block:{control_code}:{stamp}",
        },
        nonce=f"epsilon6-terminal-{stamp}",
    )
    state_transition = (terminal_block.get("epsilon6") or {}).get("state_transition") or {}
    if terminal_block.get("governance_status") != "state_blocked" or state_transition.get("reason_code") != "invalid_terminal_state":
        raise RuntimeError(f"Epsilon-6 terminal state guard did not block stale callback: {terminal_block}")

    chain_scope = f"route-approval:control_code:{control_code}"
    chain = verify_approval_audit_chain(args.postgres_dsn, chain_scope=chain_scope, limit=1000)
    if chain.get("broken_count") != 0:
        raise RuntimeError(f"Epsilon-6 audit chain verification failed: {chain}")

    filters = {"control_code": [control_code]}
    lock_events = list_route_incident_approval_lock_events(args.postgres_dsn, filters, 50, 0)
    transitions = list_route_incident_approval_state_transitions(args.postgres_dsn, filters, 50, 0)
    sla_actions = list_route_incident_approval_sla_actions(args.postgres_dsn, filters, 50, 0)
    drills = list_route_incident_approval_recovery_drills(args.postgres_dsn, {"target_control_code": [control_code]}, 20, 0)
    audits = list_route_incident_approval_audit_hashes(args.postgres_dsn, {"chain_scope": [chain_scope]}, 100, 0)
    if len(lock_events) < 3 or len(transitions) < 3 or len(sla_actions) < 1 or len(drills) < 1 or len(audits) < 4:
        raise RuntimeError(
            "Epsilon-6 persisted rows are missing: "
            f"locks={len(lock_events)} transitions={len(transitions)} sla={len(sla_actions)} drills={len(drills)} audits={len(audits)}"
        )

    print(
        "epsilon6_route_approval_resilience_smoke=ok "
        f"first={first.get('governance_status')} "
        f"second={second.get('governance_status')} "
        f"terminal_block={state_transition.get('reason_code')} "
        f"audit_broken={chain.get('broken_count')} "
        f"sla_actions={len(sla_actions)} "
        f"lock_events={len(lock_events)} "
        f"transitions={len(transitions)} "
        f"audit_hashes={len(audits)} "
        f"drills={len(drills)} "
        f"approved={approved_control.get('approval_status')} "
        f"control={control_code} "
        f"source={source_code}"
    )
    return 0


def _latest_control(postgres_dsn: str, source_code: str) -> dict[str, object] | None:
    rows = list_route_incident_controls(postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 20, 0)
    return rows[0] if rows else None


if __name__ == "__main__":
    raise SystemExit(main())
