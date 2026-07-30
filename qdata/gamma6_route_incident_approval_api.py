from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omega_control import decide_automation_approval


APPROVAL_DECISIONS = {"approve", "reject", "hold"}
TRIGGER_MODES = {"api", "manual", "smoke"}
MAX_REQUIRED_APPROVALS = 5


def submit_route_incident_approval_command(
    postgres_dsn: str,
    *,
    decision: str,
    requested_by: str,
    principal_code: str | None = None,
    control_code: str | None = None,
    approval_code: str | None = None,
    batch_code: str | None = None,
    idempotency_key: str | None = None,
    required_approvals: int = 1,
    trigger_mode: str = "api",
    notify_wecom: bool = False,
    allow_wecom_external: bool = False,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_command_args(
        decision=decision,
        requested_by=requested_by,
        principal_code=principal_code or requested_by,
        control_code=control_code,
        approval_code=approval_code,
        batch_code=batch_code,
        required_approvals=required_approvals,
        trigger_mode=trigger_mode,
    )
    postgres_dsn = _require_dsn(postgres_dsn)
    signer_code = principal_code or requested_by
    started_at = datetime.now(timezone.utc)
    key = _bounded_idempotency_key(idempotency_key or _default_idempotency_key(
        decision=decision,
        signer_code=signer_code,
        control_code=control_code,
        approval_code=approval_code,
        batch_code=batch_code,
        started_at=started_at,
    ))
    existing = _fetch_command_by_idempotency(postgres_dsn, key) if write_db else None
    if existing:
        existing["idempotent_replay"] = True
        return existing

    targets = _fetch_targets(
        postgres_dsn,
        control_code=control_code,
        approval_code=approval_code,
        batch_code=batch_code,
    )
    command_code = _command_code(started_at, key)
    command_scope = "batch" if batch_code else "single"
    command = {
        "command_id": None,
        "command_code": command_code,
        "idempotency_key": key,
        "requested_by": requested_by,
        "principal_code": signer_code,
        "trigger_mode": trigger_mode,
        "decision": decision,
        "status": "pending_quorum",
        "command_scope": command_scope,
        "batch_code": batch_code,
        "control_code": control_code,
        "approval_code": approval_code,
        "required_approvals": required_approvals,
        "notify_wecom": notify_wecom,
        "allow_wecom_external": allow_wecom_external,
        "started_at": started_at,
        "finished_at": None,
        "duration_ms": None,
        "response_payload": {},
        "evidence": {
            "external_side_effect": False,
            "notify_wecom_requested": notify_wecom,
            "allow_wecom_external": allow_wecom_external,
            "wecom_interactive_preview": _wecom_preview(decision, targets, signer_code) if notify_wecom else None,
        },
        "command_issues": [],
        "error_message": None,
    }
    if not targets:
        command["status"] = "skipped"
        command.update(_summarize_items([]))
        command["command_issues"] = ["approval_target_not_found"]
        command["response_payload"] = {"target_selector": _target_selector(control_code, approval_code, batch_code)}
        finished_at = datetime.now(timezone.utc)
        command["finished_at"] = finished_at
        command["duration_ms"] = _duration_ms(started_at, finished_at)
        if not write_db:
            return normalize_rows([command])[0]
        return _insert_command_with_items(postgres_dsn, command, [])

    if not write_db:
        preview_items = [
            build_approval_command_item(
                target,
                decision=decision,
                signer_code=signer_code,
                required_approvals=required_approvals,
                idempotency_key=key,
                item_status="pending_quorum" if decision != "hold" and required_approvals > 1 else "held" if decision == "hold" else "applied",
                signature_count=0,
            )
            for target in targets
        ]
        command.update(_summarize_items(preview_items))
        command["response_payload"] = {"items": preview_items}
        finished_at = datetime.now(timezone.utc)
        command["finished_at"] = finished_at
        command["duration_ms"] = _duration_ms(started_at, finished_at)
        return normalize_rows([command])[0]

    inserted = _insert_command(postgres_dsn, command)
    items = _process_targets(
        postgres_dsn,
        targets,
        inserted,
        decision=decision,
        signer_code=signer_code,
        required_approvals=required_approvals,
        idempotency_key=key,
    )
    summary = _summarize_items(items)
    finished_at = datetime.now(timezone.utc)
    issues = command_issues(items, targets)
    status = command_status(summary, decision=decision)
    response_payload = {
        "items": items,
        "quorum": {
            "required_approvals": required_approvals,
            "approval_count": summary["approval_count"],
            "quorum_status": summary["quorum_status"],
        },
    }
    _finalize_command(
        postgres_dsn,
        command_id=int(inserted["command_id"]),
        status=status,
        summary=summary,
        response_payload=response_payload,
        evidence=command["evidence"],
        command_issues=issues,
        error_message="one or more approval command items failed" if summary["failed_count"] else None,
        finished_at=finished_at,
        duration_ms=_duration_ms(started_at, finished_at),
    )
    result = _fetch_command_by_idempotency(postgres_dsn, key)
    if not result:
        raise QDataValidationError("Gamma-6 approval command was not persisted")
    return result


def build_approval_command_item(
    target: dict[str, Any],
    *,
    decision: str,
    signer_code: str,
    required_approvals: int,
    idempotency_key: str,
    item_status: str,
    signature_count: int,
    evidence: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "control_id": target.get("control_id"),
        "approval_id": target.get("approval_id"),
        "control_code": target.get("control_code"),
        "approval_code": target.get("approval_code"),
        "incident_action_code": target.get("incident_action_code"),
        "dataset_code": target.get("dataset_code"),
        "source_code": target.get("source_code"),
        "source_signal_type": target.get("source_signal_type"),
        "safety_level": target.get("safety_level"),
        "decision": decision,
        "item_status": item_status,
        "approval_status_before": target.get("approval_status"),
        "approval_status_after": target.get("approval_status"),
        "control_stage_before": target.get("control_stage"),
        "control_stage_after": target.get("control_stage"),
        "signer_code": signer_code,
        "signature_count": signature_count,
        "required_approvals": required_approvals,
        "idempotency_key": idempotency_key,
        "evidence": evidence or {},
        "error_message": error_message,
    }


def evaluate_approval_quorum(signature_count: int, required_approvals: int) -> dict[str, Any]:
    if required_approvals < 1 or required_approvals > MAX_REQUIRED_APPROVALS:
        raise QDataValidationError("required_approvals must be between 1 and 5")
    met = signature_count >= required_approvals
    return {
        "required_approvals": required_approvals,
        "signature_count": signature_count,
        "quorum_met": met,
        "quorum_status": "met" if met else "pending",
        "remaining_approvals": max(required_approvals - signature_count, 0),
    }


def command_status(summary: dict[str, Any], *, decision: str) -> str:
    if summary["failed_count"]:
        return "failed"
    if summary["target_count"] == 0 or summary["skipped_count"] == summary["target_count"]:
        return "skipped"
    if summary["quorum_status"] == "pending":
        return "pending_quorum"
    return "applied"


def command_issues(items: list[dict[str, Any]], targets: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if not targets:
        issues.append("approval_target_not_found")
    if any(item.get("item_status") == "pending_quorum" for item in items):
        issues.append("approval_quorum_pending")
    if any(item.get("item_status") == "skipped" for item in items):
        issues.append("approval_item_skipped")
    if any(item.get("item_status") == "failed" for item in items):
        issues.append("approval_item_failed")
    if any((item.get("evidence") or {}).get("duplicate_signature") for item in items):
        issues.append("approval_signature_duplicate")
    return _unique(issues)


def list_route_incident_approval_commands(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("command_code", "c.command_code"),
            ("idempotency_key", "c.idempotency_key"),
            ("status", "c.status"),
            ("decision", "c.decision"),
            ("requested_by", "c.requested_by"),
            ("principal_code", "c.principal_code"),
            ("trigger_mode", "c.trigger_mode"),
            ("command_scope", "c.command_scope"),
            ("quorum_status", "c.quorum_status"),
            ("batch_code", "c.batch_code"),
            ("control_code", "c.control_code"),
            ("approval_code", "c.approval_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "c.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            c.command_id, c.command_code, c.idempotency_key, c.requested_by,
            c.principal_code, c.trigger_mode, c.decision, c.status,
            c.command_scope, c.batch_code, c.control_code, c.approval_code,
            c.required_approvals, c.approval_count, c.duplicate_count,
            c.target_count, c.applied_count, c.held_count, c.rejected_count,
            c.skipped_count, c.failed_count, c.quorum_status, c.notify_wecom,
            c.allow_wecom_external, c.response_payload, c.evidence,
            c.command_issues, c.error_message, c.started_at, c.finished_at,
            c.duration_ms, c.created_at, c.updated_at
        FROM qmeta.source_route_incident_approval_command c
        {where}
        ORDER BY c.started_at DESC, c.command_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_command_items(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("command_code", "i.command_code"),
            ("control_code", "i.control_code"),
            ("approval_code", "i.approval_code"),
            ("incident_action_code", "i.incident_action_code"),
            ("dataset_code", "i.dataset_code"),
            ("source_code", "i.source_code"),
            ("source_signal_type", "i.source_signal_type"),
            ("safety_level", "i.safety_level"),
            ("decision", "i.decision"),
            ("item_status", "i.item_status"),
            ("signer_code", "i.signer_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "i.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            i.item_id, i.command_id, i.command_code, i.control_id, i.approval_id,
            i.control_code, i.approval_code, i.incident_action_code,
            i.dataset_code, i.source_code, i.source_signal_type, i.safety_level,
            i.decision, i.item_status, i.approval_status_before,
            i.approval_status_after, i.control_stage_before, i.control_stage_after,
            i.signer_code, i.signature_count, i.required_approvals,
            i.idempotency_key, i.evidence, i.error_message, i.created_at, i.updated_at
        FROM qmeta.source_route_incident_approval_command_item i
        {where}
        ORDER BY i.created_at DESC, i.item_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_signatures(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("signature_code", "s.signature_code"),
            ("command_code", "c.command_code"),
            ("control_code", "s.control_code"),
            ("approval_code", "s.approval_code"),
            ("decision", "s.decision"),
            ("signer_code", "s.signer_code"),
            ("idempotency_key", "s.idempotency_key"),
            ("status", "s.status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "s.signed_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            s.signature_id, s.signature_code, s.command_id, c.command_code,
            s.control_id, s.approval_id, s.control_code, s.approval_code,
            s.decision, s.signer_code, s.idempotency_key, s.status,
            s.evidence, s.signed_at, s.created_at, s.updated_at
        FROM qmeta.source_route_incident_approval_signature s
        LEFT JOIN qmeta.source_route_incident_approval_command c ON c.command_id = s.command_id
        {where}
        ORDER BY s.signed_at DESC, s.signature_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_gamma6_report(payload: dict[str, Any]) -> str:
    return (
        "gamma6_route_incident_approval_api "
        f"status={payload.get('status')} command_code={payload.get('command_code')} "
        f"decision={payload.get('decision')} targets={payload.get('target_count')} "
        f"applied={payload.get('applied_count')} held={payload.get('held_count')} "
        f"rejected={payload.get('rejected_count')} quorum={payload.get('quorum_status')} "
        f"approvals={payload.get('approval_count')}/{payload.get('required_approvals')}"
    )


def format_gamma6_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"gamma6 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _process_targets(
    postgres_dsn: str,
    targets: list[dict[str, Any]],
    command: dict[str, Any],
    *,
    decision: str,
    signer_code: str,
    required_approvals: int,
    idempotency_key: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for target in targets:
        item = _process_target(
            postgres_dsn,
            target,
            command,
            decision=decision,
            signer_code=signer_code,
            required_approvals=required_approvals,
            idempotency_key=idempotency_key,
        )
        _insert_command_item(postgres_dsn, int(command["command_id"]), str(command["command_code"]), item)
        items.append(item)
    return items


def _process_target(
    postgres_dsn: str,
    target: dict[str, Any],
    command: dict[str, Any],
    *,
    decision: str,
    signer_code: str,
    required_approvals: int,
    idempotency_key: str,
) -> dict[str, Any]:
    eligible = target.get("approval_status") == "pending" and bool(target.get("approval_code"))
    if not eligible:
        return build_approval_command_item(
            target,
            decision=decision,
            signer_code=signer_code,
            required_approvals=required_approvals,
            idempotency_key=idempotency_key,
            item_status="skipped",
            signature_count=_signature_count(postgres_dsn, target, decision),
            evidence={"skip_reason": "approval is not pending or approval_code is missing"},
        )
    signature = _record_signature(
        postgres_dsn,
        target,
        command,
        decision=decision,
        signer_code=signer_code,
        idempotency_key=_signature_idempotency_key(idempotency_key, target),
    )
    signature_count = _signature_count(postgres_dsn, target, decision)
    evidence = {
        "signature_code": signature.get("signature_code"),
        "duplicate_signature": bool(signature.get("duplicate_signature")),
        "quorum": evaluate_approval_quorum(signature_count, required_approvals),
        "external_side_effect": False,
    }
    if decision == "hold":
        return build_approval_command_item(
            target,
            decision=decision,
            signer_code=signer_code,
            required_approvals=required_approvals,
            idempotency_key=idempotency_key,
            item_status="held",
            signature_count=signature_count,
            evidence={**evidence, "hold_reason": "operator requested hold without changing Omega approval state"},
        )
    quorum = evaluate_approval_quorum(signature_count, required_approvals)
    if not quorum["quorum_met"]:
        return build_approval_command_item(
            target,
            decision=decision,
            signer_code=signer_code,
            required_approvals=required_approvals,
            idempotency_key=idempotency_key,
            item_status="pending_quorum",
            signature_count=signature_count,
            evidence=evidence,
        )
    try:
        approval_decision = decide_automation_approval(
            postgres_dsn,
            approval_code=str(target["approval_code"]),
            decision="approved" if decision == "approve" else "rejected",
            decided_by=signer_code,
            reason=f"Gamma-6 {decision} quorum for route incident control",
        )
        after_status = approval_decision.get("status")
        after_stage = "approved" if after_status == "approved" else "blocked"
        _update_control_after_decision(
            postgres_dsn,
            control_id=int(target["control_id"]),
            approval_status=str(after_status),
            control_stage=after_stage,
            signer_code=signer_code,
            decision=decision,
        )
        item = build_approval_command_item(
            target,
            decision=decision,
            signer_code=signer_code,
            required_approvals=required_approvals,
            idempotency_key=idempotency_key,
            item_status="applied",
            signature_count=signature_count,
            evidence={**evidence, "automation_approval": approval_decision},
        )
        item["approval_status_after"] = after_status
        item["control_stage_after"] = after_stage
        return item
    except Exception as exc:  # pragma: no cover - covered by integration smoke
        return build_approval_command_item(
            target,
            decision=decision,
            signer_code=signer_code,
            required_approvals=required_approvals,
            idempotency_key=idempotency_key,
            item_status="failed",
            signature_count=signature_count,
            evidence=evidence,
            error_message=str(exc),
        )


def _fetch_targets(
    postgres_dsn: str,
    *,
    control_code: str | None,
    approval_code: str | None,
    batch_code: str | None,
) -> list[dict[str, Any]]:
    values: list[Any] = []
    if batch_code:
        selector = "ctrl.control_code IN (SELECT control_code FROM qmeta.source_route_incident_operation_item WHERE batch_code = %s AND control_code IS NOT NULL)"
        values.append(batch_code)
    elif control_code:
        selector = "ctrl.control_code = %s"
        values.append(control_code)
    else:
        selector = "ap.approval_code = %s"
        values.append(approval_code)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ctrl.control_id, ctrl.control_code, ctrl.approval_id,
            ap.approval_code, ap.status AS omega_approval_status,
            sria.incident_action_code, dc.dataset_code, ss.source_code,
            sria.source_signal_type, sria.safety_level,
            ctrl.control_stage, ctrl.approval_status, ctrl.receipt_status,
            ctrl.rollback_status, ctrl.updated_at, ctrl.created_at
        FROM qmeta.source_route_incident_control ctrl
        JOIN qmeta.source_route_incident_action sria ON sria.incident_action_id = ctrl.incident_action_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = sria.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = sria.source_id
        LEFT JOIN qmeta.automation_approval ap ON ap.approval_id = ctrl.approval_id
        WHERE {selector}
        ORDER BY ctrl.updated_at DESC, ctrl.control_id DESC
        LIMIT 200
        """,
        values,
    )


def _insert_command(postgres_dsn: str, command: dict[str, Any]) -> dict[str, Any]:
    return _insert_command_with_items(postgres_dsn, command, [], insert_items=False)


def _insert_command_with_items(
    postgres_dsn: str,
    command: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    insert_items: bool = True,
) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_command (
                    command_code, idempotency_key, requested_by, principal_code,
                    trigger_mode, decision, status, command_scope, batch_code,
                    control_code, approval_code, required_approvals, approval_count,
                    duplicate_count, target_count, applied_count, held_count,
                    rejected_count, skipped_count, failed_count, quorum_status,
                    notify_wecom, allow_wecom_external, response_payload, evidence,
                    command_issues, error_message, started_at, finished_at,
                    duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    command["command_code"],
                    command["idempotency_key"],
                    command["requested_by"],
                    command["principal_code"],
                    command["trigger_mode"],
                    command["decision"],
                    command.get("status", "pending_quorum"),
                    command["command_scope"],
                    command.get("batch_code"),
                    command.get("control_code"),
                    command.get("approval_code"),
                    command["required_approvals"],
                    command.get("approval_count", 0),
                    command.get("duplicate_count", 0),
                    command.get("target_count", 0),
                    command.get("applied_count", 0),
                    command.get("held_count", 0),
                    command.get("rejected_count", 0),
                    command.get("skipped_count", 0),
                    command.get("failed_count", 0),
                    command.get("quorum_status", "pending"),
                    command["notify_wecom"],
                    command["allow_wecom_external"],
                    _json(command.get("response_payload") or {}),
                    _json(command.get("evidence") or {}),
                    command.get("command_issues") or [],
                    command.get("error_message"),
                    command["started_at"],
                    command.get("finished_at"),
                    command.get("duration_ms"),
                ),
            )
            inserted = dict(cursor.fetchone())
            if insert_items:
                for item in items:
                    _insert_command_item_with_cursor(cursor, inserted["command_id"], inserted["command_code"], item)
            result = normalize_rows([inserted])[0]
            result["items"] = normalize_rows(items)
            return result


def _finalize_command(
    postgres_dsn: str,
    *,
    command_id: int,
    status: str,
    summary: dict[str, Any],
    response_payload: dict[str, Any],
    evidence: dict[str, Any],
    command_issues: list[str],
    error_message: str | None,
    finished_at: datetime,
    duration_ms: int,
) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.source_route_incident_approval_command
                SET status = %s,
                    approval_count = %s,
                    duplicate_count = %s,
                    target_count = %s,
                    applied_count = %s,
                    held_count = %s,
                    rejected_count = %s,
                    skipped_count = %s,
                    failed_count = %s,
                    quorum_status = %s,
                    response_payload = %s::jsonb,
                    evidence = %s::jsonb,
                    command_issues = %s,
                    error_message = %s,
                    finished_at = %s,
                    duration_ms = %s,
                    updated_at = now()
                WHERE command_id = %s
                """,
                (
                    status,
                    summary["approval_count"],
                    summary["duplicate_count"],
                    summary["target_count"],
                    summary["applied_count"],
                    summary["held_count"],
                    summary["rejected_count"],
                    summary["skipped_count"],
                    summary["failed_count"],
                    summary["quorum_status"],
                    _json(response_payload),
                    _json(evidence),
                    command_issues,
                    error_message,
                    finished_at,
                    duration_ms,
                    command_id,
                ),
            )


def _insert_command_item(postgres_dsn: str, command_id: int, command_code: str, item: dict[str, Any]) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _insert_command_item_with_cursor(cursor, command_id, command_code, item)


def _insert_command_item_with_cursor(cursor: Any, command_id: int, command_code: str, item: dict[str, Any]) -> None:
    cursor.execute(
        """
        INSERT INTO qmeta.source_route_incident_approval_command_item (
            command_id, command_code, control_id, approval_id, control_code,
            approval_code, incident_action_code, dataset_code, source_code,
            source_signal_type, safety_level, decision, item_status,
            approval_status_before, approval_status_after, control_stage_before,
            control_stage_after, signer_code, signature_count, required_approvals,
            idempotency_key, evidence, error_message, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s::jsonb, %s, now()
        )
        ON CONFLICT (command_id, control_id) DO UPDATE SET
            approval_id = EXCLUDED.approval_id,
            approval_code = EXCLUDED.approval_code,
            item_status = EXCLUDED.item_status,
            approval_status_after = EXCLUDED.approval_status_after,
            control_stage_after = EXCLUDED.control_stage_after,
            signer_code = EXCLUDED.signer_code,
            signature_count = EXCLUDED.signature_count,
            required_approvals = EXCLUDED.required_approvals,
            evidence = EXCLUDED.evidence,
            error_message = EXCLUDED.error_message,
            updated_at = now()
        """,
        (
            command_id,
            command_code,
            item.get("control_id"),
            item.get("approval_id"),
            item.get("control_code"),
            item.get("approval_code"),
            item.get("incident_action_code"),
            item.get("dataset_code"),
            item.get("source_code"),
            item.get("source_signal_type"),
            item.get("safety_level"),
            item.get("decision"),
            item.get("item_status"),
            item.get("approval_status_before"),
            item.get("approval_status_after"),
            item.get("control_stage_before"),
            item.get("control_stage_after"),
            item.get("signer_code"),
            item.get("signature_count"),
            item.get("required_approvals"),
            item.get("idempotency_key"),
            _json(item.get("evidence") or {}),
            item.get("error_message"),
        ),
    )


def _record_signature(
    postgres_dsn: str,
    target: dict[str, Any],
    command: dict[str, Any],
    *,
    decision: str,
    signer_code: str,
    idempotency_key: str,
) -> dict[str, Any]:
    existing = _fetch_rows(
        postgres_dsn,
        """
        SELECT *, TRUE AS duplicate_signature
        FROM qmeta.source_route_incident_approval_signature
        WHERE control_id = %s
          AND decision = %s
          AND signer_code = %s
        LIMIT 1
        """,
        [target["control_id"], decision, signer_code],
    )
    if existing:
        return existing[0]
    signature_code = _signature_code(command["command_code"], target, signer_code, decision)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_signature (
                    signature_code, command_id, control_id, approval_id,
                    control_code, approval_code, decision, signer_code,
                    idempotency_key, status, evidence, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, 'active', %s::jsonb, now()
                )
                RETURNING *, FALSE AS duplicate_signature
                """,
                (
                    signature_code,
                    command["command_id"],
                    target["control_id"],
                    target.get("approval_id"),
                    target.get("control_code"),
                    target.get("approval_code"),
                    decision,
                    signer_code,
                    idempotency_key,
                    _json({"command_code": command["command_code"], "external_side_effect": False}),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _signature_count(postgres_dsn: str, target: dict[str, Any], decision: str) -> int:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT COUNT(*) AS signature_count
        FROM qmeta.source_route_incident_approval_signature
        WHERE control_id = %s
          AND decision = %s
          AND status = 'active'
        """,
        [target["control_id"], decision],
    )
    return int(rows[0]["signature_count"]) if rows else 0


def _update_control_after_decision(
    postgres_dsn: str,
    *,
    control_id: int,
    approval_status: str,
    control_stage: str,
    signer_code: str,
    decision: str,
) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.source_route_incident_control
                SET approval_status = %s,
                    control_stage = %s,
                    approved_by = CASE WHEN %s = 'approved' THEN %s ELSE approved_by END,
                    details = COALESCE(details, '{}'::jsonb) || %s::jsonb,
                    updated_at = now()
                WHERE control_id = %s
                """,
                (
                    approval_status,
                    control_stage,
                    approval_status,
                    signer_code,
                    _json({"gamma6": {"decision": decision, "decided_by": signer_code}}),
                    control_id,
                ),
            )


def _fetch_command_by_idempotency(postgres_dsn: str, idempotency_key: str) -> dict[str, Any] | None:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT *
        FROM qmeta.source_route_incident_approval_command
        WHERE idempotency_key = %s
        LIMIT 1
        """,
        [idempotency_key],
    )
    if not rows:
        return None
    result = normalize_rows(rows)[0]
    result["items"] = list_route_incident_approval_command_items(
        postgres_dsn,
        {"command_code": [str(result["command_code"])]},
        200,
        0,
    )
    return result


def _summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    target_count = len(items)
    applied_count = sum(1 for item in items if item.get("item_status") == "applied")
    held_count = sum(1 for item in items if item.get("item_status") == "held")
    rejected_count = sum(1 for item in items if item.get("decision") == "reject" and item.get("item_status") == "applied")
    skipped_count = sum(1 for item in items if item.get("item_status") == "skipped")
    failed_count = sum(1 for item in items if item.get("item_status") == "failed")
    pending_quorum_count = sum(1 for item in items if item.get("item_status") == "pending_quorum")
    duplicate_count = sum(1 for item in items if (item.get("evidence") or {}).get("duplicate_signature"))
    approval_count = max([int(item.get("signature_count") or 0) for item in items] or [0])
    if target_count == 0:
        quorum_status = "not_required"
    elif held_count == target_count:
        quorum_status = "not_required"
    elif pending_quorum_count:
        quorum_status = "pending"
    else:
        quorum_status = "met"
    return {
        "target_count": target_count,
        "applied_count": applied_count,
        "held_count": held_count,
        "rejected_count": rejected_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "approval_count": approval_count,
        "duplicate_count": duplicate_count,
        "quorum_status": quorum_status,
    }


def _validate_command_args(
    *,
    decision: str,
    requested_by: str,
    principal_code: str,
    control_code: str | None,
    approval_code: str | None,
    batch_code: str | None,
    required_approvals: int,
    trigger_mode: str,
) -> None:
    if decision not in APPROVAL_DECISIONS:
        raise QDataValidationError("decision must be one of: approve, reject, hold")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, smoke")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if not principal_code:
        raise QDataValidationError("principal_code is required")
    selectors = [bool(control_code), bool(approval_code), bool(batch_code)]
    if sum(selectors) != 1:
        raise QDataValidationError("exactly one of control_code, approval_code or batch_code is required")
    if required_approvals < 1 or required_approvals > MAX_REQUIRED_APPROVALS:
        raise QDataValidationError("required_approvals must be between 1 and 5")


def _where_equal(params: dict[str, list[str]], pairs: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for name, column in pairs:
        value = _param(params, name)
        if value:
            clauses.append(f"{column} = %s")
            values.append(value)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", values)


def _append_where(where: str, values: list[Any], clause: str, value: Any) -> tuple[str, list[Any]]:
    prefix = " AND " if where else "WHERE "
    return where + prefix + clause, values + [value]


def _append_date_filter(where: str, values: list[Any], params: dict[str, list[str]], column: str) -> tuple[str, list[Any]]:
    start = _param(params, "start_date")
    end = _param(params, "end_date")
    if start:
        where, values = _append_where(where, values, f"{column}::date >= %s", parse_date(start, "start_date"))
    if end:
        where, values = _append_where(where, values, f"{column}::date <= %s", parse_date(end, "end_date"))
    return where, values


def _param(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = params.get(name)
    if not values:
        return default
    return values[-1]


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "commands": [
            "started_at",
            "command_code",
            "status",
            "decision",
            "principal_code",
            "command_scope",
            "batch_code",
            "control_code",
            "approval_code",
            "required_approvals",
            "approval_count",
            "quorum_status",
            "target_count",
            "applied_count",
            "held_count",
            "rejected_count",
            "skipped_count",
            "failed_count",
            "command_issues",
        ],
        "items": [
            "created_at",
            "command_code",
            "control_code",
            "approval_code",
            "dataset_code",
            "source_code",
            "decision",
            "item_status",
            "signer_code",
            "signature_count",
            "required_approvals",
            "approval_status_before",
            "approval_status_after",
            "error_message",
        ],
        "signatures": [
            "signed_at",
            "signature_code",
            "command_code",
            "control_code",
            "approval_code",
            "decision",
            "signer_code",
            "status",
            "idempotency_key",
        ],
    }
    preferred = preferred_by_resource.get(resource, preferred_by_resource["commands"])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Gamma-6 route incident approval API") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _command_code(started_at: datetime, idempotency_key: str) -> str:
    stamp = started_at.strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"gamma6:{idempotency_key}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"gamma6-route-approval-{digest}"[:180]


def _signature_code(command_code: str, target: dict[str, Any], signer_code: str, decision: str) -> str:
    digest = hashlib.sha1(
        f"{command_code}:{target.get('control_code') or target.get('control_id')}:{signer_code}:{decision}".encode("utf-8")
    ).hexdigest()[:12]
    return f"gamma6-sig-{digest}"[:220]


def _default_idempotency_key(
    *,
    decision: str,
    signer_code: str,
    control_code: str | None,
    approval_code: str | None,
    batch_code: str | None,
    started_at: datetime,
) -> str:
    target = _target_selector(control_code, approval_code, batch_code)
    digest = hashlib.sha1(f"{decision}:{signer_code}:{target}:{started_at.isoformat()}".encode("utf-8")).hexdigest()[:16]
    return f"gamma6:{digest}"


def _signature_idempotency_key(base_key: str, target: dict[str, Any]) -> str:
    return _bounded_idempotency_key(f"{base_key}:signature:{target.get('control_code') or target.get('control_id')}")


def _bounded_idempotency_key(value: str) -> str:
    if len(value) <= 220:
        return value
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return f"gamma6-key-{digest}"


def _target_selector(control_code: str | None, approval_code: str | None, batch_code: str | None) -> dict[str, str | None]:
    return {"control_code": control_code, "approval_code": approval_code, "batch_code": batch_code}


def _wecom_preview(decision: str, targets: list[dict[str, Any]], signer_code: str) -> dict[str, Any]:
    return {
        "provider": "wecom",
        "interactive": True,
        "external_send": False,
        "decision": decision,
        "signer_code": signer_code,
        "target_count": len(targets),
        "control_codes": [target.get("control_code") for target in targets[:20]],
    }


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Gamma-6 route incident approval API")
    return postgres_dsn
