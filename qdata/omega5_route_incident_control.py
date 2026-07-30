from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any

from qdata.backend_utils import normalize_rows
from qdata.delta2_wecom import DEFAULT_PROFILE_CODE, run_delta2_wecom_live_validation
from qdata.exceptions import QDataValidationError
from qdata.omega_control import (
    decide_automation_approval,
    request_automation_approval,
    request_automation_rollback,
    run_omega_execution,
)


CONTROL_STAGES = {
    "planned",
    "approval_requested",
    "notification_recorded",
    "approved",
    "executed",
    "rollback_planned",
    "closed",
    "blocked",
    "failed",
    "skipped",
}
EXECUTION_MODES = {"review_only", "dry_run", "execute"}
TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo", "once"}
HIGH_RISK_SAFETY_LEVELS = {"high", "critical"}
DEFAULT_REQUESTED_BY = "omega5"
DEFAULT_CHANNEL_CODE = "delta2-wecom-live-webhook"


def run_route_incident_control(
    postgres_dsn: str,
    *,
    lookback_hours: int = 24,
    max_controls: int = 50,
    execution_mode: str = "review_only",
    auto_approve: bool = False,
    approved_by: str | None = None,
    requested_by: str = DEFAULT_REQUESTED_BY,
    approval_sla_hours: int = 4,
    notify_wecom: bool = True,
    allow_wecom_external: bool = False,
    create_rollback: bool = True,
    trigger_mode: str = "manual",
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_run_args(
        lookback_hours=lookback_hours,
        max_controls=max_controls,
        execution_mode=execution_mode,
        requested_by=requested_by,
        approval_sla_hours=approval_sla_hours,
        trigger_mode=trigger_mode,
    )
    started_at = datetime.now(timezone.utc)
    effective_write_db = write_db and execution_mode != "dry_run"
    candidates = _fetch_control_candidates(postgres_dsn, lookback_hours=lookback_hours, limit=max_controls)
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        plan = build_route_incident_control_plan(
            candidate,
            execution_mode=execution_mode,
            auto_approve=auto_approve,
            requested_by=requested_by,
            approval_sla_hours=approval_sla_hours,
            notify_wecom=notify_wecom,
            create_rollback=create_rollback,
        )
        if not effective_write_db:
            results.append(_preview_result(candidate, plan))
            continue
        results.append(
            _apply_control_plan(
                postgres_dsn,
                candidate,
                plan,
                execution_mode=execution_mode,
                auto_approve=auto_approve,
                approved_by=approved_by,
                requested_by=requested_by,
                notify_wecom=notify_wecom,
                allow_wecom_external=allow_wecom_external,
                create_rollback=create_rollback,
                trigger_mode=_normalize_trigger_mode(trigger_mode),
            )
        )
    finished_at = datetime.now(timezone.utc)
    summary = summarize_control_results(results)
    return {
        "status": summary["status"],
        "control_count": len(results),
        "candidate_count": len(candidates),
        "approval_requested_count": summary["approval_requested_count"],
        "approved_count": summary["approved_count"],
        "notification_recorded_count": summary["notification_recorded_count"],
        "executed_count": summary["executed_count"],
        "rollback_planned_count": summary["rollback_planned_count"],
        "skipped_count": summary["skipped_count"],
        "failed_count": summary["failed_count"],
        "duration_ms": _duration_ms(started_at, finished_at),
        "execution_mode": execution_mode,
        "write_db": effective_write_db,
        "controls": normalize_rows(results),
    }


def build_route_incident_control_plan(
    incident_action: dict[str, Any],
    *,
    execution_mode: str = "review_only",
    auto_approve: bool = False,
    requested_by: str = DEFAULT_REQUESTED_BY,
    approval_sla_hours: int = 4,
    notify_wecom: bool = True,
    create_rollback: bool = True,
) -> dict[str, Any]:
    if execution_mode not in EXECUTION_MODES:
        raise QDataValidationError("execution_mode must be one of: review_only, dry_run, execute")
    approval_required = _approval_required(incident_action)
    action_execution_mode = str(incident_action.get("action_execution_mode") or incident_action.get("execution_mode") or "")
    executable = execution_mode == "execute" and action_execution_mode == "execute"
    commands: list[str] = []
    if approval_required:
        commands.append("request_approval")
    if notify_wecom and approval_required:
        commands.append("record_wecom_notification")
    if auto_approve and approval_required:
        commands.append("approve_action")
    if executable and (auto_approve or not approval_required):
        commands.append("execute_action")
    if create_rollback and approval_required:
        commands.append("plan_rollback")
    return {
        "incident_action_code": incident_action.get("incident_action_code"),
        "action_code": incident_action.get("action_code"),
        "dataset_code": incident_action.get("dataset_code"),
        "source_code": incident_action.get("source_code"),
        "source_signal_type": incident_action.get("source_signal_type"),
        "action_type": incident_action.get("action_type"),
        "safety_level": incident_action.get("safety_level"),
        "status": incident_action.get("status"),
        "approval_required": approval_required,
        "auto_approve": auto_approve,
        "notify_wecom": notify_wecom and approval_required,
        "create_rollback": create_rollback and approval_required,
        "requested_by": requested_by,
        "approval_sla_hours": approval_sla_hours,
        "execution_mode": execution_mode,
        "action_execution_mode": action_execution_mode,
        "commands": commands,
        "reason": _control_reason(incident_action),
    }


def summarize_control_results(controls: list[dict[str, Any]]) -> dict[str, int | str]:
    failed_count = sum(1 for item in controls if item.get("control_stage") == "failed")
    skipped_count = sum(1 for item in controls if item.get("control_stage") == "skipped")
    executed_count = sum(1 for item in controls if item.get("attempt_status") == "success" or item.get("control_stage") == "executed")
    approval_requested_count = sum(1 for item in controls if item.get("approval_status") == "pending")
    approved_count = sum(1 for item in controls if item.get("approval_status") == "approved")
    notification_recorded_count = sum(1 for item in controls if item.get("dispatch_status") in {"acknowledged", "sent"} or item.get("receipt_status") in {"success", "blocked"})
    rollback_planned_count = sum(1 for item in controls if item.get("rollback_status") == "planned")
    status = "failed" if failed_count else "warning" if approval_requested_count or skipped_count else "success" if controls else "skipped"
    return {
        "status": status,
        "approval_requested_count": approval_requested_count,
        "approved_count": approved_count,
        "notification_recorded_count": notification_recorded_count,
        "executed_count": executed_count,
        "rollback_planned_count": rollback_planned_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
    }


def list_route_incident_controls(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("control_code", "ctrl.control_code"),
            ("incident_action_code", "sria.incident_action_code"),
            ("action_code", "aa.action_code"),
            ("run_code", "ar.run_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("source_signal_type", "sria.source_signal_type"),
            ("action_type", "sria.action_type"),
            ("safety_level", "sria.safety_level"),
            ("control_stage", "ctrl.control_stage"),
            ("approval_status", "ctrl.approval_status"),
            ("dispatch_status", "ctrl.dispatch_status"),
            ("attempt_status", "ctrl.attempt_status"),
            ("receipt_status", "ctrl.receipt_status"),
            ("rollback_status", "ctrl.rollback_status"),
            ("owner", "ctrl.owner"),
            ("requested_by", "ctrl.requested_by"),
            ("execution_mode", "ctrl.execution_mode"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "ctrl.updated_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ctrl.control_id, ctrl.control_code,
            sria.incident_action_code, ar.run_code, aa.action_code,
            dc.dataset_code, ss.source_code, sria.source_signal_type,
            sria.action_type, sria.safety_level, sria.status AS incident_action_status,
            ctrl.control_stage, ctrl.approval_status, ap.approval_code,
            ctrl.dispatch_status, ed.dispatch_code,
            ctrl.attempt_status, at.attempt_code,
            ctrl.receipt_status, lr.receipt_code,
            ctrl.rollback_status, rb.rollback_code,
            ctrl.owner, ctrl.requested_by, ctrl.approved_by, ctrl.executed_by,
            ctrl.requires_wecom, ctrl.approval_required, ctrl.execution_mode,
            ctrl.notification_channel, ctrl.control_reason,
            ctrl.planned_control, ctrl.executed_control,
            ctrl.rollback_evidence, ctrl.details, ctrl.error_message,
            ctrl.closed_at, ctrl.created_at, ctrl.updated_at
        FROM qmeta.source_route_incident_control ctrl
        JOIN qmeta.source_route_incident_action sria ON sria.incident_action_id = ctrl.incident_action_id
        JOIN qmeta.automation_action aa ON aa.automation_action_id = ctrl.automation_action_id
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = sria.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = sria.source_id
        LEFT JOIN qmeta.automation_approval ap ON ap.approval_id = ctrl.approval_id
        LEFT JOIN qmeta.automation_external_dispatch ed ON ed.dispatch_id = ctrl.dispatch_id
        LEFT JOIN qmeta.automation_execution_attempt at ON at.attempt_id = ctrl.attempt_id
        LEFT JOIN qmeta.automation_live_provider_receipt lr ON lr.receipt_id = ctrl.receipt_id
        LEFT JOIN qmeta.automation_rollback rb ON rb.rollback_id = ctrl.rollback_id
        {where}
        ORDER BY ctrl.updated_at DESC, ctrl.control_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_omega5_report(payload: dict[str, Any]) -> str:
    lines = [
        (
            f"omega5_route_incident_control status={payload.get('status')} controls={payload.get('control_count')} "
            f"approval_requested={payload.get('approval_requested_count')} approved={payload.get('approved_count')} "
            f"notifications={payload.get('notification_recorded_count')} executed={payload.get('executed_count')} "
            f"rollback_planned={payload.get('rollback_planned_count')} skipped={payload.get('skipped_count')} "
            f"failed={payload.get('failed_count')}"
        )
    ]
    for control in payload.get("controls") or []:
        keys = [
            "control_code",
            "incident_action_code",
            "action_code",
            "source_signal_type",
            "control_stage",
            "approval_status",
            "dispatch_status",
            "receipt_status",
            "attempt_status",
            "rollback_status",
            "error_message",
        ]
        lines.append(" ".join(f"{key}={control[key]}" for key in keys if control.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def format_omega5_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"omega5 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _apply_control_plan(
    postgres_dsn: str,
    incident_action: dict[str, Any],
    plan: dict[str, Any],
    *,
    execution_mode: str,
    auto_approve: bool,
    approved_by: str | None,
    requested_by: str,
    notify_wecom: bool,
    allow_wecom_external: bool,
    create_rollback: bool,
    trigger_mode: str,
) -> dict[str, Any]:
    control: dict[str, Any] = {
        "control_code": _control_code(incident_action["incident_action_code"]),
        "incident_action_id": incident_action["incident_action_id"],
        "automation_action_id": incident_action["automation_action_id"],
        "approval_id": None,
        "dispatch_id": None,
        "attempt_id": None,
        "receipt_id": None,
        "rollback_id": None,
        "approval_status": None,
        "dispatch_status": None,
        "attempt_status": None,
        "receipt_status": None,
        "rollback_status": None,
        "owner": incident_action.get("owner"),
        "requested_by": requested_by,
        "approved_by": approved_by if auto_approve else None,
        "executed_by": requested_by if execution_mode == "execute" else None,
        "requires_wecom": bool(notify_wecom and plan["approval_required"]),
        "approval_required": bool(plan["approval_required"]),
        "execution_mode": execution_mode,
        "notification_channel": DEFAULT_PROFILE_CODE,
        "control_reason": plan["reason"],
        "planned_control": plan,
        "executed_control": {},
        "rollback_evidence": {},
        "details": {"source": "omega5", "route_incident": _route_details(incident_action)},
        "error_message": None,
        "closed_at": None,
    }
    try:
        if not plan["approval_required"]:
            control["control_stage"] = "closed" if incident_action.get("status") == "success" else "skipped"
            control["closed_at"] = datetime.now(timezone.utc) if control["control_stage"] == "closed" else None
            return _upsert_control(postgres_dsn, control)

        approval = request_automation_approval(
            postgres_dsn,
            action_code=incident_action["action_code"],
            requested_by=requested_by,
            reason=plan["reason"],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=int(plan["approval_sla_hours"]))).isoformat(),
        )
        control["approval_id"] = approval.get("approval_id")
        control["approval_status"] = approval.get("status")

        receipt: dict[str, Any] | None = None
        if notify_wecom:
            receipt = _record_wecom_notification(
                postgres_dsn,
                incident_action,
                plan,
                requested_by=requested_by,
                trigger_mode=trigger_mode,
                allow_wecom_external=allow_wecom_external,
            )
            control["receipt_id"] = receipt.get("receipt_id")
            control["receipt_status"] = receipt.get("status")
            dispatch = _record_dispatch_audit(
                postgres_dsn,
                incident_action,
                receipt=receipt,
                requested_by=requested_by,
                trigger_mode=trigger_mode,
            )
            control["dispatch_id"] = dispatch.get("dispatch_id")
            control["dispatch_status"] = dispatch.get("status")

        if auto_approve:
            decision = decide_automation_approval(
                postgres_dsn,
                approval_code=str(approval["approval_code"]),
                decision="approved",
                decided_by=approved_by or requested_by,
                reason="Omega-5 smoke/manual auto approval for route incident control",
            )
            control["approval_id"] = decision.get("approval_id")
            control["approval_status"] = decision.get("status")
            control["approved_by"] = approved_by or requested_by

        if create_rollback and execution_mode != "execute":
            rollback = request_automation_rollback(
                postgres_dsn,
                action_code=incident_action["action_code"],
                requested_by=requested_by,
                reason=f"Omega-5 rollback plan for {incident_action['incident_action_code']}",
                rollback_type="noop",
            )
            control["rollback_id"] = rollback.get("rollback_id")
            control["rollback_status"] = rollback.get("status")
            control["rollback_evidence"] = {
                "rollback_code": rollback.get("rollback_code"),
                "rollback_type": rollback.get("rollback_type"),
                "rollback_plan": rollback.get("rollback_plan") or {},
            }

        if execution_mode == "execute":
            execution = run_omega_execution(
                postgres_dsn,
                action_code=incident_action["action_code"],
                trigger_mode=trigger_mode,
                requested_by=requested_by,
                max_actions=1,
                allow_external=False,
            )
            attempt = _latest_attempt_for_action(postgres_dsn, incident_action["action_code"])
            if attempt:
                control["attempt_id"] = attempt.get("attempt_id")
                control["attempt_status"] = attempt.get("status")
            control["executed_control"] = {
                "omega_execution_status": execution.get("status"),
                "attempt_count": execution.get("attempt_count"),
                "success_count": execution.get("success_count"),
                "failed_count": execution.get("failed_count"),
            }
            if control["attempt_status"] == "success":
                _mark_incident_action_success(postgres_dsn, incident_action["incident_action_id"], execution)

        if create_rollback and execution_mode == "execute":
            rollback = request_automation_rollback(
                postgres_dsn,
                action_code=incident_action["action_code"],
                requested_by=requested_by,
                reason=f"Omega-5 rollback plan for {incident_action['incident_action_code']}",
                rollback_type="noop",
            )
            control["rollback_id"] = rollback.get("rollback_id")
            control["rollback_status"] = rollback.get("status")
            control["rollback_evidence"] = {
                "rollback_code": rollback.get("rollback_code"),
                "rollback_type": rollback.get("rollback_type"),
                "rollback_plan": rollback.get("rollback_plan") or {},
            }

        control["control_stage"] = _derive_control_stage(control)
        if control["control_stage"] in {"closed", "executed", "skipped"}:
            control["closed_at"] = datetime.now(timezone.utc)
    except Exception as exc:
        control["control_stage"] = "failed"
        control["error_message"] = str(exc)
    return _upsert_control(postgres_dsn, control)


def _record_wecom_notification(
    postgres_dsn: str,
    incident_action: dict[str, Any],
    plan: dict[str, Any],
    *,
    requested_by: str,
    trigger_mode: str,
    allow_wecom_external: bool,
) -> dict[str, Any]:
    message = "\n".join(
        [
            f"Route incident action: {incident_action.get('incident_action_code')}",
            f"Action: {incident_action.get('action_code')}",
            f"Dataset/source: {incident_action.get('dataset_code')} / {incident_action.get('source_code')}",
            f"Signal: {incident_action.get('source_signal_type')}",
            f"Safety: {incident_action.get('safety_level')}",
            f"Reason: {incident_action.get('reason')}",
            f"Planned commands: {', '.join(plan.get('commands') or [])}",
        ]
    )
    return run_delta2_wecom_live_validation(
        postgres_dsn,
        profile_code=DEFAULT_PROFILE_CODE,
        requested_by=requested_by,
        title="QData Omega-5 route incident approval",
        message=message,
        action_code=incident_action.get("action_code"),
        trigger_mode=trigger_mode,
        message_type="markdown",
        allow_external=allow_wecom_external,
        force=True,
    )


def _record_dispatch_audit(
    postgres_dsn: str,
    incident_action: dict[str, Any],
    *,
    receipt: dict[str, Any],
    requested_by: str,
    trigger_mode: str,
) -> dict[str, Any]:
    dispatch_code = _dispatch_code(incident_action["incident_action_code"])
    idempotency_key = f"omega5:route_incident_control:{incident_action['incident_action_id']}:approval_request"
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT channel_id FROM qmeta.automation_external_channel WHERE channel_code = %s",
                (DEFAULT_CHANNEL_CODE,),
            )
            channel = cursor.fetchone()
            if not channel:
                raise QDataValidationError(f"unknown automation channel: {DEFAULT_CHANNEL_CODE}")
            cursor.execute(
                """
                INSERT INTO qmeta.automation_external_dispatch (
                    dispatch_code, automation_action_id, channel_id, idempotency_key,
                    dispatch_type, trigger_mode, status, requested_by,
                    request_payload, response_payload, dispatched_at,
                    acknowledged_at, details, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    'approval_request', %s, 'acknowledged', %s,
                    %s::jsonb, %s::jsonb, now(),
                    now(), %s::jsonb, now()
                )
                ON CONFLICT (dispatch_code) DO UPDATE SET
                    automation_action_id = EXCLUDED.automation_action_id,
                    channel_id = EXCLUDED.channel_id,
                    idempotency_key = EXCLUDED.idempotency_key,
                    trigger_mode = EXCLUDED.trigger_mode,
                    status = 'acknowledged',
                    requested_by = EXCLUDED.requested_by,
                    request_payload = EXCLUDED.request_payload,
                    response_payload = EXCLUDED.response_payload,
                    dispatched_at = now(),
                    acknowledged_at = now(),
                    error_message = NULL,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING *
                """,
                (
                    dispatch_code,
                    incident_action["automation_action_id"],
                    channel["channel_id"],
                    idempotency_key,
                    trigger_mode,
                    requested_by,
                    _json(
                        {
                            "incident_action_code": incident_action.get("incident_action_code"),
                            "action_code": incident_action.get("action_code"),
                            "dataset_code": incident_action.get("dataset_code"),
                            "source_code": incident_action.get("source_code"),
                            "source_signal_type": incident_action.get("source_signal_type"),
                        }
                    ),
                    _json(
                        {
                            "external_side_effect": False,
                            "wecom_receipt_code": receipt.get("receipt_code"),
                            "wecom_receipt_status": receipt.get("status"),
                            "recorded_by": "omega5",
                        }
                    ),
                    _json({"source": "omega5", "receipt_id": receipt.get("receipt_id")}),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _fetch_control_candidates(postgres_dsn: str, *, lookback_hours: int, limit: int) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sria.incident_action_id, sria.incident_action_code,
                    sria.automation_run_id, sria.automation_action_id,
                    ar.run_code, aa.action_code, aa.status AS action_status,
                    aa.execution_mode AS action_execution_mode,
                    aa.omega_control_status,
                    dc.dataset_code, ss.source_code,
                    sria.source_signal_type, sria.action_type, sria.safety_level,
                    sria.execution_mode, sria.status, sria.approval_required,
                    sria.owner, sria.reason, sria.planned_effect,
                    sria.executed_effect, sria.rollback_hint,
                    sria.route_status, sria.circuit_status, sria.probe_status,
                    sria.open_until, sria.success_rate, sria.failure_rate,
                    sria.fallback_rate, sria.empty_rate, sria.latency_p95_ms,
                    sria.health_issues, sria.details, sria.error_message,
                    sria.created_at, sria.updated_at,
                    ctrl.control_id, ctrl.control_stage
                FROM qmeta.source_route_incident_action sria
                JOIN qmeta.automation_action aa ON aa.automation_action_id = sria.automation_action_id
                JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = sria.dataset_id
                JOIN qmeta.source_system ss ON ss.source_id = sria.source_id
                LEFT JOIN qmeta.source_route_incident_control ctrl
                    ON ctrl.incident_action_id = sria.incident_action_id
                WHERE sria.updated_at >= now() - (%s::text || ' hours')::interval
                  AND sria.source_signal_type IN ('circuit_open', 'recovery_failed', 'recovered', 'health_degraded')
                  AND (
                      ctrl.control_id IS NULL
                      OR ctrl.control_stage IN ('planned', 'approval_requested', 'notification_recorded', 'approved', 'rollback_planned', 'blocked', 'failed')
                  )
                ORDER BY
                    CASE sria.safety_level
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        ELSE 1
                    END DESC,
                    sria.updated_at DESC,
                    sria.incident_action_id DESC
                LIMIT %s
                """,
                (lookback_hours, limit),
            )
            return [dict(row) for row in cursor.fetchall()]


def _latest_attempt_for_action(postgres_dsn: str, action_code: str) -> dict[str, Any] | None:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT at.*
                FROM qmeta.automation_execution_attempt at
                JOIN qmeta.automation_action aa ON aa.automation_action_id = at.automation_action_id
                WHERE aa.action_code = %s
                ORDER BY at.finished_at DESC NULLS LAST, at.started_at DESC, at.attempt_id DESC
                LIMIT 1
                """,
                (action_code,),
            )
            row = cursor.fetchone()
            return normalize_rows([dict(row)])[0] if row else None


def _mark_incident_action_success(postgres_dsn: str, incident_action_id: int, execution: dict[str, Any]) -> None:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.source_route_incident_action
                SET status = 'success',
                    executed_effect = %s::jsonb,
                    error_message = NULL,
                    updated_at = now()
                WHERE incident_action_id = %s
                """,
                (_json({"omega5_execution": execution}), incident_action_id),
            )


def _upsert_control(postgres_dsn: str, control: dict[str, Any]) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_control (
                    control_code, incident_action_id, automation_action_id,
                    approval_id, dispatch_id, attempt_id, receipt_id, rollback_id,
                    control_stage, approval_status, dispatch_status, attempt_status,
                    receipt_status, rollback_status, owner, requested_by,
                    approved_by, executed_by, requires_wecom, approval_required,
                    execution_mode, notification_channel, control_reason,
                    planned_control, executed_control, rollback_evidence,
                    details, error_message, closed_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s, %s, now()
                )
                ON CONFLICT (incident_action_id) DO UPDATE SET
                    control_code = EXCLUDED.control_code,
                    automation_action_id = EXCLUDED.automation_action_id,
                    approval_id = COALESCE(EXCLUDED.approval_id, qmeta.source_route_incident_control.approval_id),
                    dispatch_id = COALESCE(EXCLUDED.dispatch_id, qmeta.source_route_incident_control.dispatch_id),
                    attempt_id = COALESCE(EXCLUDED.attempt_id, qmeta.source_route_incident_control.attempt_id),
                    receipt_id = COALESCE(EXCLUDED.receipt_id, qmeta.source_route_incident_control.receipt_id),
                    rollback_id = COALESCE(EXCLUDED.rollback_id, qmeta.source_route_incident_control.rollback_id),
                    control_stage = EXCLUDED.control_stage,
                    approval_status = COALESCE(EXCLUDED.approval_status, qmeta.source_route_incident_control.approval_status),
                    dispatch_status = COALESCE(EXCLUDED.dispatch_status, qmeta.source_route_incident_control.dispatch_status),
                    attempt_status = COALESCE(EXCLUDED.attempt_status, qmeta.source_route_incident_control.attempt_status),
                    receipt_status = COALESCE(EXCLUDED.receipt_status, qmeta.source_route_incident_control.receipt_status),
                    rollback_status = COALESCE(EXCLUDED.rollback_status, qmeta.source_route_incident_control.rollback_status),
                    owner = EXCLUDED.owner,
                    requested_by = EXCLUDED.requested_by,
                    approved_by = COALESCE(EXCLUDED.approved_by, qmeta.source_route_incident_control.approved_by),
                    executed_by = COALESCE(EXCLUDED.executed_by, qmeta.source_route_incident_control.executed_by),
                    requires_wecom = EXCLUDED.requires_wecom,
                    approval_required = EXCLUDED.approval_required,
                    execution_mode = EXCLUDED.execution_mode,
                    notification_channel = EXCLUDED.notification_channel,
                    control_reason = EXCLUDED.control_reason,
                    planned_control = EXCLUDED.planned_control,
                    executed_control = CASE
                        WHEN EXCLUDED.executed_control = '{}'::jsonb THEN qmeta.source_route_incident_control.executed_control
                        ELSE EXCLUDED.executed_control
                    END,
                    rollback_evidence = CASE
                        WHEN EXCLUDED.rollback_evidence = '{}'::jsonb THEN qmeta.source_route_incident_control.rollback_evidence
                        ELSE EXCLUDED.rollback_evidence
                    END,
                    details = EXCLUDED.details,
                    error_message = EXCLUDED.error_message,
                    closed_at = COALESCE(EXCLUDED.closed_at, qmeta.source_route_incident_control.closed_at),
                    updated_at = now()
                RETURNING *
                """,
                (
                    control["control_code"],
                    control["incident_action_id"],
                    control["automation_action_id"],
                    control.get("approval_id"),
                    control.get("dispatch_id"),
                    control.get("attempt_id"),
                    control.get("receipt_id"),
                    control.get("rollback_id"),
                    control.get("control_stage") or "planned",
                    control.get("approval_status"),
                    control.get("dispatch_status"),
                    control.get("attempt_status"),
                    control.get("receipt_status"),
                    control.get("rollback_status"),
                    control.get("owner"),
                    control.get("requested_by") or DEFAULT_REQUESTED_BY,
                    control.get("approved_by"),
                    control.get("executed_by"),
                    control.get("requires_wecom", True),
                    control.get("approval_required", True),
                    control.get("execution_mode") or "review_only",
                    control.get("notification_channel") or DEFAULT_PROFILE_CODE,
                    control.get("control_reason") or "Omega-5 route incident control",
                    _json(control.get("planned_control") or {}),
                    _json(control.get("executed_control") or {}),
                    _json(control.get("rollback_evidence") or {}),
                    _json(control.get("details") or {}),
                    control.get("error_message"),
                    control.get("closed_at"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _preview_result(incident_action: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    stage = "planned" if plan["approval_required"] else "closed"
    return {
        "control_code": _control_code(incident_action["incident_action_code"]),
        "incident_action_id": incident_action["incident_action_id"],
        "automation_action_id": incident_action["automation_action_id"],
        "incident_action_code": incident_action.get("incident_action_code"),
        "action_code": incident_action.get("action_code"),
        "dataset_code": incident_action.get("dataset_code"),
        "source_code": incident_action.get("source_code"),
        "source_signal_type": incident_action.get("source_signal_type"),
        "control_stage": stage,
        "approval_status": "pending" if plan["approval_required"] else None,
        "dispatch_status": None,
        "attempt_status": None,
        "receipt_status": None,
        "rollback_status": "planned" if plan.get("create_rollback") else None,
        "owner": incident_action.get("owner"),
        "requested_by": plan.get("requested_by"),
        "requires_wecom": bool(plan.get("notify_wecom")),
        "approval_required": bool(plan.get("approval_required")),
        "execution_mode": plan.get("execution_mode"),
        "notification_channel": DEFAULT_PROFILE_CODE,
        "control_reason": plan.get("reason"),
        "planned_control": plan,
        "executed_control": {},
        "rollback_evidence": {},
        "details": {"source": "omega5", "preview": True, "route_incident": _route_details(incident_action)},
        "error_message": None,
    }


def _derive_control_stage(control: dict[str, Any]) -> str:
    if control.get("error_message"):
        return "failed"
    if control.get("attempt_status") == "success":
        return "executed"
    if control.get("approval_status") == "approved":
        return "approved"
    if control.get("rollback_status") == "planned":
        return "rollback_planned"
    if control.get("dispatch_status") in {"acknowledged", "sent"} or control.get("receipt_status") in {"success", "blocked"}:
        return "notification_recorded"
    if control.get("approval_status") == "pending":
        return "approval_requested"
    if not control.get("approval_required"):
        return "closed"
    return "planned"


def _approval_required(incident_action: dict[str, Any]) -> bool:
    return bool(
        incident_action.get("approval_required")
        or incident_action.get("status") == "approval_required"
        or str(incident_action.get("safety_level") or "").lower() in HIGH_RISK_SAFETY_LEVELS
    )


def _control_reason(incident_action: dict[str, Any]) -> str:
    return (
        f"Omega-5 control for route incident {incident_action.get('incident_action_code')}: "
        f"{incident_action.get('source_signal_type')} on {incident_action.get('dataset_code')}/"
        f"{incident_action.get('source_code')}. {incident_action.get('reason') or ''}"
    ).strip()


def _route_details(incident_action: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_status": incident_action.get("route_status"),
        "circuit_status": incident_action.get("circuit_status"),
        "probe_status": incident_action.get("probe_status"),
        "open_until": incident_action.get("open_until"),
        "success_rate": incident_action.get("success_rate"),
        "failure_rate": incident_action.get("failure_rate"),
        "fallback_rate": incident_action.get("fallback_rate"),
        "empty_rate": incident_action.get("empty_rate"),
        "latency_p95_ms": incident_action.get("latency_p95_ms"),
        "health_issues": incident_action.get("health_issues") or [],
    }


def _validate_run_args(
    *,
    lookback_hours: int,
    max_controls: int,
    execution_mode: str,
    requested_by: str,
    approval_sla_hours: int,
    trigger_mode: str,
) -> None:
    if lookback_hours < 1 or lookback_hours > 24 * 30:
        raise QDataValidationError("lookback_hours must be between 1 and 720")
    if max_controls < 1 or max_controls > 500:
        raise QDataValidationError("max_controls must be between 1 and 500")
    if execution_mode not in EXECUTION_MODES:
        raise QDataValidationError("execution_mode must be one of: review_only, dry_run, execute")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if approval_sla_hours < 1 or approval_sla_hours > 24 * 30:
        raise QDataValidationError("approval_sla_hours must be between 1 and 720")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo, once")


def _where_equal(params: dict[str, list[str]], specs: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for param_name, column_name in specs:
        value = _param(params, param_name)
        if value in (None, ""):
            continue
        clauses.append(f"{column_name} = %s")
        values.append(value)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", values)


def _append_date_filter(where: str, values: list[Any], params: dict[str, list[str]], column: str) -> tuple[str, list[Any]]:
    clauses = [where.replace("WHERE ", "", 1)] if where else []
    start = _param(params, "start_date")
    end = _param(params, "end_date")
    if start:
        clauses.append(f"{column} >= %s::date")
        values.append(start)
    if end:
        clauses.append(f"{column} < (%s::date + INTERVAL '1 day')")
        values.append(end)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", values)


def _fetch_rows(postgres_dsn: str | None, sql: str, values: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, values)
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _control_code(incident_action_code: str) -> str:
    return _stable_code("omega5-route-control", incident_action_code, limit=280)


def _dispatch_code(incident_action_code: str) -> str:
    return _stable_code("omega5-route-dispatch", incident_action_code, limit=260)


def _stable_code(prefix: str, value: str, *, limit: int) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{_slug(value)}-{digest}"[:limit]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value)).strip("-").lower() or "unknown"


def _duration_ms(started_at: datetime, finished_at: datetime | None = None) -> int:
    finished = finished_at or datetime.now(timezone.utc)
    return int((finished - started_at).total_seconds() * 1000)


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred = [
        "updated_at",
        "control_code",
        "incident_action_code",
        "run_code",
        "action_code",
        "dataset_code",
        "source_code",
        "source_signal_type",
        "action_type",
        "safety_level",
        "control_stage",
        "approval_status",
        "dispatch_status",
        "receipt_status",
        "attempt_status",
        "rollback_status",
        "owner",
        "requested_by",
        "execution_mode",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _normalize_trigger_mode(trigger_mode: str) -> str:
    return "manual" if trigger_mode == "once" else trigger_mode


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Omega-5 route incident control") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Omega-5 route incident control")
    return _connect(postgres_dsn)
