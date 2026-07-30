#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.chi5_route_feedback import list_source_route_circuit_breakers, run_source_route_feedback_monitor
from qdata.gamma6_route_incident_approval_api import (
    list_route_incident_approval_command_items,
    list_route_incident_approval_commands,
    list_route_incident_approval_signatures,
)
from qdata.omega5_route_incident_control import list_route_incident_controls, run_route_incident_control
from qdata.psi_automation import run_psi_automation
from scripts.smoke_omega5_route_incident_control import _find_route_action, _insert_decision


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Gamma-6 route incident writable approval API.")
    parser.add_argument("--base-url", default=os.getenv("QDATA_API_BASE_URL", "http://127.0.0.1:18080"))
    parser.add_argument("--token", default=os.getenv("QDATA_API_TOKEN", "devtoken"))
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--allow-wecom-external", action="store_true", default=os.getenv("QDATA_GAMMA6_ROUTE_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    source_code = f"gamma6_smoke_{hashlib.sha1(stamp.encode('utf-8')).hexdigest()[:10]}"
    failed_code = _insert_decision(
        args.postgres_dsn,
        source_code=source_code,
        decision_status="failed",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        row_count=0,
        request_key=f"gamma6-open-{stamp}",
    )
    run_source_route_feedback_monitor(
        args.postgres_dsn,
        requested_by="gamma6-smoke",
        trigger_mode="smoke",
        lookback_hours=4,
        max_failure_rate=0.0,
        max_empty_rate=0.0,
        circuit_open_minutes=0,
        write_db=True,
    )
    circuits = list_source_route_circuit_breakers(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 5, 0)
    if not circuits or circuits[0].get("status") != "open":
        raise RuntimeError(f"Gamma-6 precondition failed: route circuit did not open after {failed_code}")

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
        run_code=f"gamma6-route-open-smoke-{stamp}",
        write_db=True,
    )
    open_action = _find_route_action(psi_result, source_code, "daily_bar", "circuit_open")
    if not open_action or open_action.get("status") != "approval_required":
        raise RuntimeError(f"Psi-5 did not create approval-required action for Gamma-6 smoke: {psi_result}")

    run_route_incident_control(
        args.postgres_dsn,
        lookback_hours=4,
        max_controls=20,
        execution_mode="review_only",
        auto_approve=False,
        requested_by="gamma6-smoke",
        approval_sla_hours=4,
        notify_wecom=True,
        allow_wecom_external=args.allow_wecom_external,
        create_rollback=True,
        trigger_mode="smoke",
        write_db=True,
    )
    pending_control = _latest_control(args.postgres_dsn, source_code)
    if not pending_control or pending_control.get("approval_status") != "pending":
        raise RuntimeError(f"Gamma-6 precondition failed: no pending Omega-5 control for {source_code}")

    control_code = str(pending_control["control_code"])
    key_a = f"gamma6-smoke-a:{control_code}:{stamp}"
    key_b = f"gamma6-smoke-b:{control_code}:{stamp}"
    first = _post_approval(args.base_url, args.token, control_code, "gamma6-smoke-a", key_a, required_approvals=2)
    if first.get("status") != "pending_quorum" or first.get("quorum_status") != "pending":
        raise RuntimeError(f"Gamma-6 first signature should wait for quorum: {first}")
    still_pending = _latest_control(args.postgres_dsn, source_code)
    if not still_pending or still_pending.get("approval_status") != "pending":
        raise RuntimeError(f"Gamma-6 quorum pending changed approval too early: {still_pending}")

    second = _post_approval(args.base_url, args.token, control_code, "gamma6-smoke-b", key_b, required_approvals=2)
    if second.get("status") != "applied" or second.get("quorum_status") != "met":
        raise RuntimeError(f"Gamma-6 second signature did not apply after quorum: {second}")
    replay = _post_approval(args.base_url, args.token, control_code, "gamma6-smoke-a", key_a, required_approvals=2)
    if not replay.get("idempotent_replay"):
        raise RuntimeError(f"Gamma-6 idempotent replay was not detected: {replay}")

    approved_control = _latest_control(args.postgres_dsn, source_code)
    if not approved_control or approved_control.get("approval_status") != "approved":
        raise RuntimeError(f"Gamma-6 did not approve control after quorum: {approved_control}")

    command_rows = list_route_incident_approval_commands(args.postgres_dsn, {"control_code": [control_code]}, 20, 0)
    item_rows = list_route_incident_approval_command_items(args.postgres_dsn, {"control_code": [control_code]}, 20, 0)
    signature_rows = list_route_incident_approval_signatures(args.postgres_dsn, {"control_code": [control_code]}, 20, 0)
    if len(command_rows) < 2 or not item_rows or len(signature_rows) < 2:
        raise RuntimeError(f"Gamma-6 persisted rows are missing: commands={command_rows} items={item_rows} signatures={signature_rows}")

    print(
        "gamma6_route_approval_api_smoke=ok "
        f"first={first.get('status')} "
        f"second={second.get('status')} "
        f"quorum={second.get('quorum_status')} "
        f"signatures={len(signature_rows)} "
        f"approved={approved_control.get('approval_status')} "
        f"command_code={second.get('command_code')} "
        f"control={control_code} "
        f"source={source_code}"
    )
    return 0


def _post_approval(base_url: str, token: str, control_code: str, principal_code: str, key: str, *, required_approvals: int) -> dict[str, object]:
    body = json.dumps(
        {
            "decision": "approve",
            "control_code": control_code,
            "requested_by": principal_code,
            "principal_code": principal_code,
            "required_approvals": required_approvals,
            "trigger_mode": "smoke",
            "idempotency_key": key,
            "notify_wecom": False,
            "allow_wecom_external": False,
        }
    ).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/admin/source-route-incident-approval-commands",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success" or not payload.get("data"):
        raise RuntimeError(f"Gamma-6 POST failed: {payload}")
    return payload["data"][0]


def _latest_control(postgres_dsn: str, source_code: str) -> dict[str, object] | None:
    rows = list_route_incident_controls(postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 20, 0)
    return rows[0] if rows else None


if __name__ == "__main__":
    raise SystemExit(main())

