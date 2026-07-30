#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import hashlib
import hmac
import json
import os
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.chi5_route_feedback import list_source_route_circuit_breakers, run_source_route_feedback_monitor
from qdata.delta6_route_incident_approval_governance import (
    ensure_route_approval_policy,
    ensure_route_approval_role_binding,
    escalate_route_approval_timeouts,
    list_route_incident_approval_callbacks,
    list_route_incident_approval_escalations,
    list_route_incident_approval_policies,
    list_route_incident_approval_role_bindings,
)
from qdata.omega5_route_incident_control import list_route_incident_controls, run_route_incident_control
from qdata.psi_automation import run_psi_automation
from scripts.smoke_omega5_route_incident_control import _find_route_action, _insert_decision


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Delta-6 production governance for route incident approvals.")
    parser.add_argument("--base-url", default=os.getenv("QDATA_API_BASE_URL", "http://127.0.0.1:18080"))
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--secret", default=os.getenv("QDATA_DELTA6_WECOM_CALLBACK_SECRET", "delta6-local-secret"))
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    source_code = f"delta6_smoke_{hashlib.sha1(stamp.encode('utf-8')).hexdigest()[:10]}"
    failed_code = _insert_decision(
        args.postgres_dsn,
        source_code=source_code,
        decision_status="failed",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        row_count=0,
        request_key=f"delta6-open-{stamp}",
    )
    run_source_route_feedback_monitor(
        args.postgres_dsn,
        requested_by="delta6-smoke",
        trigger_mode="smoke",
        lookback_hours=4,
        max_failure_rate=0.0,
        max_empty_rate=0.0,
        circuit_open_minutes=0,
        write_db=True,
    )
    circuits = list_source_route_circuit_breakers(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 5, 0)
    if not circuits or circuits[0].get("status") != "open":
        raise RuntimeError(f"Delta-6 precondition failed: route circuit did not open after {failed_code}")

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
        run_code=f"delta6-route-open-smoke-{stamp}",
        write_db=True,
    )
    open_action = _find_route_action(psi_result, source_code, "daily_bar", "circuit_open")
    if not open_action or open_action.get("status") != "approval_required":
        raise RuntimeError(f"Psi-5 did not create approval-required action for Delta-6 smoke: {psi_result}")

    run_route_incident_control(
        args.postgres_dsn,
        lookback_hours=4,
        max_controls=20,
        execution_mode="review_only",
        auto_approve=False,
        requested_by="delta6-requester",
        approval_sla_hours=4,
        notify_wecom=True,
        allow_wecom_external=False,
        create_rollback=True,
        trigger_mode="smoke",
        write_db=True,
    )
    pending_control = _latest_control(args.postgres_dsn, source_code)
    if not pending_control or pending_control.get("approval_status") != "pending":
        raise RuntimeError(f"Delta-6 precondition failed: no pending Omega-5 control for {source_code}")

    control_code = str(pending_control["control_code"])
    requester = str(pending_control.get("requested_by") or "delta6-requester")
    ensure_route_approval_policy(
        args.postgres_dsn,
        policy_code="delta6-default-route-approval-policy",
        min_approvals=2,
        timeout_minutes=1,
        require_distinct_requester=True,
        require_wecom_signature=True,
        escalation_principal_code="platform-ops",
        created_by="delta6-smoke",
    )
    ensure_route_approval_role_binding(args.postgres_dsn, principal_code="delta6-approver-a", role_code="route_approver", created_by="delta6-smoke")
    ensure_route_approval_role_binding(args.postgres_dsn, principal_code="delta6-approver-b", role_code="route_approver", created_by="delta6-smoke")

    denied = _post_callback(
        args.base_url,
        args.secret,
        {
            "provider_code": "wecom",
            "decision": "approve",
            "control_code": control_code,
            "requested_by": requester,
            "signer_code": requester,
            "required_approvals": 2,
            "trigger_mode": "smoke",
            "idempotency_key": f"delta6-denied:{control_code}:{stamp}",
        },
        nonce=f"delta6-denied-{stamp}",
    )
    if denied.get("governance_status") != "denied":
        raise RuntimeError(f"Delta-6 SoD denial did not persist: {denied}")

    first_body = {
        "provider_code": "wecom",
        "decision": "approve",
        "control_code": control_code,
        "requested_by": "delta6-smoke",
        "signer_code": "delta6-approver-a",
        "required_approvals": 2,
        "trigger_mode": "smoke",
        "idempotency_key": f"delta6-approval-a:{control_code}:{stamp}",
    }
    first_nonce = f"delta6-valid-a-{stamp}"
    first = _post_callback(args.base_url, args.secret, first_body, nonce=first_nonce)
    if first.get("governance_status") != "pending_quorum":
        raise RuntimeError(f"Delta-6 first callback should wait for quorum: {first}")
    _age_command(args.postgres_dsn, str(first["command_code"]), minutes=10)
    timeout_result = escalate_route_approval_timeouts(args.postgres_dsn, limit=20, write_db=True)
    if timeout_result.get("escalation_count", 0) < 1:
        raise RuntimeError(f"Delta-6 timeout escalation did not open: {timeout_result}")

    replay = _post_callback(args.base_url, args.secret, first_body, nonce=first_nonce)
    if replay.get("governance_status") != "replay_rejected" or not replay.get("replay_detected"):
        raise RuntimeError(f"Delta-6 replay was not rejected: {replay}")

    second = _post_callback(
        args.base_url,
        args.secret,
        {
            "provider_code": "wecom",
            "decision": "approve",
            "control_code": control_code,
            "requested_by": "delta6-smoke",
            "signer_code": "delta6-approver-b",
            "required_approvals": 2,
            "trigger_mode": "smoke",
            "idempotency_key": f"delta6-approval-b:{control_code}:{stamp}",
        },
        nonce=f"delta6-valid-b-{stamp}",
    )
    if second.get("governance_status") != "applied":
        raise RuntimeError(f"Delta-6 second callback did not apply after quorum: {second}")

    approved_control = _latest_control(args.postgres_dsn, source_code)
    if not approved_control or approved_control.get("approval_status") != "approved":
        raise RuntimeError(f"Delta-6 did not approve control after governed quorum: {approved_control}")

    callbacks = list_route_incident_approval_callbacks(args.postgres_dsn, {"control_code": [control_code]}, 20, 0)
    escalations = list_route_incident_approval_escalations(args.postgres_dsn, {"control_code": [control_code]}, 20, 0)
    roles = list_route_incident_approval_role_bindings(args.postgres_dsn, {"principal_code": ["delta6-approver-a"]}, 20, 0)
    policies = list_route_incident_approval_policies(args.postgres_dsn, {"policy_code": ["delta6-default-route-approval-policy"]}, 5, 0)
    if len(callbacks) < 3 or not escalations or not roles or not policies:
        raise RuntimeError(f"Delta-6 persisted rows are missing: callbacks={callbacks} escalations={escalations} roles={roles} policies={policies}")

    replay_count = sum(int(row.get("replay_count") or 0) for row in callbacks)
    print(
        "delta6_route_approval_governance_smoke=ok "
        f"denied={denied.get('governance_status')} "
        f"first={first.get('governance_status')} "
        f"second={second.get('governance_status')} "
        f"replay={replay.get('governance_status')} "
        f"replay_count={replay_count} "
        f"escalations={len(escalations)} "
        f"approved={approved_control.get('approval_status')} "
        f"callback_code={second.get('callback_code')} "
        f"command_code={second.get('command_code')} "
        f"control={control_code} "
        f"source={source_code}"
    )
    return 0


def _post_callback(base_url: str, secret: str, body: dict[str, object], *, nonce: str) -> dict[str, object]:
    raw = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = hmac.new(secret.encode("utf-8"), f"{timestamp}\n{nonce}\n".encode("utf-8") + raw, hashlib.sha256).hexdigest()
    request = Request(
        f"{base_url.rstrip('/')}/webhooks/wecom/source-route-incident-approval-callbacks",
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-QData-Timestamp": timestamp,
            "X-QData-Nonce": nonce,
            "X-QData-Signature": f"sha256={signature}",
        },
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success" or not payload.get("data"):
        raise RuntimeError(f"Delta-6 callback POST failed: {payload}")
    return payload["data"][0]


def _age_command(postgres_dsn: str, command_code: str, *, minutes: int) -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for Delta-6 smoke") from exc
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.source_route_incident_approval_command
                SET started_at = now() - (%s || ' minutes')::interval,
                    updated_at = now()
                WHERE command_code = %s
                """,
                (minutes, command_code),
            )


def _latest_control(postgres_dsn: str, source_code: str) -> dict[str, object] | None:
    rows = list_route_incident_controls(postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 20, 0)
    return rows[0] if rows else None


if __name__ == "__main__":
    raise SystemExit(main())
