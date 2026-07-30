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
from qdata.omega5_route_incident_control import list_route_incident_controls, run_route_incident_control
from qdata.psi_automation import run_psi_automation


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Omega-5 route incident approval/control loop.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--allow-wecom-external", action="store_true", default=os.getenv("QDATA_OMEGA5_ROUTE_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    source_code = f"omega5_smoke_{hashlib.sha1(stamp.encode('utf-8')).hexdigest()[:10]}"
    failed_code = _insert_decision(
        args.postgres_dsn,
        source_code=source_code,
        decision_status="failed",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        row_count=0,
        request_key=f"omega5-open-{stamp}",
    )
    run_source_route_feedback_monitor(
        args.postgres_dsn,
        requested_by="omega5-smoke",
        trigger_mode="smoke",
        lookback_hours=4,
        max_failure_rate=0.0,
        max_empty_rate=0.0,
        circuit_open_minutes=0,
        write_db=True,
    )
    circuits = list_source_route_circuit_breakers(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 5, 0)
    if not circuits or circuits[0].get("status") != "open":
        raise RuntimeError(f"Omega-5 precondition failed: Chi-5 circuit did not open after {failed_code}")

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
        run_code=f"omega5-route-open-smoke-{stamp}",
        write_db=True,
    )
    open_action = _find_route_action(psi_result, source_code, "daily_bar", "circuit_open")
    if not open_action or open_action.get("status") != "approval_required":
        raise RuntimeError(f"Psi-5 did not create approval-required action for Omega-5 smoke: {psi_result}")

    pending_result = run_route_incident_control(
        args.postgres_dsn,
        lookback_hours=4,
        max_controls=20,
        execution_mode="review_only",
        auto_approve=False,
        requested_by="omega5-smoke",
        approval_sla_hours=4,
        notify_wecom=True,
        allow_wecom_external=args.allow_wecom_external,
        create_rollback=True,
        trigger_mode="smoke",
        write_db=True,
    )
    pending_control = _latest_control(args.postgres_dsn, source_code)
    if not pending_control or pending_control.get("approval_status") != "pending":
        raise RuntimeError(f"Omega-5 did not create pending approval control: {pending_result}")
    if pending_control.get("dispatch_status") != "acknowledged":
        raise RuntimeError(f"Omega-5 did not create acknowledged dispatch audit: {pending_control}")
    if pending_control.get("receipt_status") not in {"blocked", "success"}:
        raise RuntimeError(f"Omega-5 did not create WeCom receipt evidence: {pending_control}")
    if pending_control.get("rollback_status") != "planned":
        raise RuntimeError(f"Omega-5 did not create rollback plan: {pending_control}")

    executed_result = run_route_incident_control(
        args.postgres_dsn,
        lookback_hours=4,
        max_controls=20,
        execution_mode="execute",
        auto_approve=True,
        approved_by="omega5-smoke-approver",
        requested_by="omega5-smoke",
        approval_sla_hours=4,
        notify_wecom=True,
        allow_wecom_external=args.allow_wecom_external,
        create_rollback=True,
        trigger_mode="smoke",
        write_db=True,
    )
    executed_control = _latest_control(args.postgres_dsn, source_code)
    if not executed_control or executed_control.get("approval_status") != "approved":
        raise RuntimeError(f"Omega-5 did not approve control: {executed_result}")
    if executed_control.get("attempt_status") != "success" or executed_control.get("control_stage") != "executed":
        raise RuntimeError(f"Omega-5 did not execute approved action: {executed_control}")

    print(
        "omega5_route_incident_smoke=ok "
        f"pending_approval={pending_control.get('approval_status')} "
        f"approved={executed_control.get('approval_status')} "
        f"dispatch={executed_control.get('dispatch_status')} "
        f"receipt={executed_control.get('receipt_status')} "
        f"attempt={executed_control.get('attempt_status')} "
        f"rollback={executed_control.get('rollback_status')} "
        f"control={executed_control.get('control_stage')} "
        f"source={source_code}"
    )
    return 0


def _latest_control(postgres_dsn: str, source_code: str) -> dict[str, object] | None:
    rows = list_route_incident_controls(postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": [source_code]}, 20, 0)
    return rows[0] if rows else None


def _find_route_action(result: dict[str, object], source_code: str, dataset_code: str, signal_type: str) -> dict[str, object] | None:
    for action in result.get("actions") or []:
        if not isinstance(action, dict):
            continue
        route = (action.get("details") or {}).get("route") if isinstance(action.get("details"), dict) else {}
        if (
            isinstance(route, dict)
            and route.get("source_code") == source_code
            and route.get("dataset_code") == dataset_code
            and route.get("source_signal_type") == signal_type
        ):
            return action
    return None


def _insert_decision(
    postgres_dsn: str,
    *,
    source_code: str,
    decision_status: str,
    started_at: datetime,
    row_count: int,
    request_key: str,
) -> str:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("psycopg is required for Omega-5 smoke") from exc
    digest = hashlib.sha1(f"{source_code}:{decision_status}:{request_key}".encode("utf-8")).hexdigest()[:12]
    decision_code = f"omega5-smoke-route-{source_code}-{decision_status}-{digest}"
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = 'daily_bar'")
            dataset = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO qmeta.source_system (
                    source_code, source_name, source_type,
                    license_scope, update_frequency, latency_level,
                    owner, is_active, updated_at
                ) VALUES (
                    %s, %s, 'other',
                    'local smoke only', 'ad_hoc', 'L4',
                    'platform-data', TRUE, now()
                )
                ON CONFLICT (source_code) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    owner = EXCLUDED.owner,
                    is_active = TRUE,
                    updated_at = now()
                """,
                (source_code, f"Omega-5 smoke source {source_code}"),
            )
            cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = %s", (source_code,))
            source = cursor.fetchone()
            if not dataset or not source:
                raise RuntimeError("daily_bar dataset and smoke source must exist before Omega-5 smoke")
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_decision_audit (
                    decision_code, dataset_id,
                    requested_source_id, selected_source_id,
                    final_source_id, primary_source_id,
                    request_key, decision_context,
                    route_mode, decision_status,
                    selected_role, effective_date,
                    selected_weight_pct, deterministic_bucket,
                    candidate_sources, attempt_sources,
                    fallback_attempted, fallback_applied,
                    row_count, duration_ms,
                    details, started_at, finished_at,
                    updated_at
                ) VALUES (
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, 'smoke',
                    'default', %s,
                    'requested', CURRENT_DATE,
                    100, 0,
                    ARRAY[%s]::text[], ARRAY[%s]::text[],
                    FALSE, FALSE,
                    %s, 5,
                    '{"owner":"omega5-smoke"}'::jsonb, %s, %s,
                    now()
                )
                ON CONFLICT (decision_code) DO NOTHING
                """,
                (
                    decision_code,
                    dataset["dataset_id"],
                    source["source_id"],
                    source["source_id"],
                    source["source_id"],
                    source["source_id"],
                    request_key,
                    decision_status,
                    source_code,
                    source_code,
                    row_count,
                    started_at,
                    started_at + timedelta(milliseconds=5),
                ),
            )
    return decision_code


if __name__ == "__main__":
    raise SystemExit(main())
