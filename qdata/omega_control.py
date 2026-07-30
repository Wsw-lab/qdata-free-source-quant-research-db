from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fnmatch
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
APPROVAL_DECISIONS = {"approved", "rejected"}
ROLLBACK_TYPES = {"noop", "manual", "webhook", "script"}
SENSITIVE_KEYS = {"token", "api_token", "access_token", "secret", "password", "authorization", "credential", "private_key"}
PAYLOAD_LIMIT = 4000
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def request_automation_approval(
    postgres_dsn: str,
    *,
    action_code: str,
    requested_by: str,
    reason: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    if not action_code:
        raise QDataValidationError("action_code is required")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if not reason:
        raise QDataValidationError("reason is required")
    expires = _parse_timestamp(expires_at, "expires_at") if expires_at else None
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            action = _get_action(cursor, action_code)
            if not action["approval_required"]:
                raise QDataValidationError("approval can only be requested for approval_required actions")
            approval = _upsert_approval(
                cursor,
                action,
                requested_by=requested_by,
                reason=reason,
                expires_at=expires,
            )
            _update_action_control(
                cursor,
                action["automation_action_id"],
                omega_control_status="pending_approval",
                status="approval_required",
            )
            return normalize_rows([approval])[0]


def decide_automation_approval(
    postgres_dsn: str,
    *,
    approval_code: str,
    decision: str,
    decided_by: str,
    reason: str = "",
) -> dict[str, Any]:
    if decision not in APPROVAL_DECISIONS:
        raise QDataValidationError("decision must be one of: approved, rejected")
    if not approval_code:
        raise QDataValidationError("approval_code is required")
    if not decided_by:
        raise QDataValidationError("decided_by is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.automation_approval
                SET status = %s,
                    decided_by = %s,
                    decision_reason = %s,
                    decided_at = now(),
                    updated_at = now()
                WHERE approval_code = %s
                RETURNING *
                """,
                (decision, decided_by, reason or decision, approval_code),
            )
            approval = cursor.fetchone()
            if not approval:
                raise QDataValidationError(f"unknown approval_code: {approval_code}")
            approval = dict(approval)
            if decision == "approved":
                cursor.execute(
                    """
                    UPDATE qmeta.automation_action
                    SET omega_control_status = 'approved',
                        approved_by = %s,
                        approved_at = now(),
                        updated_at = now()
                    WHERE automation_action_id = %s
                    """,
                    (decided_by, approval["automation_action_id"]),
                )
            else:
                cursor.execute(
                    """
                    UPDATE qmeta.automation_action
                    SET omega_control_status = 'rejected',
                        status = 'skipped',
                        error_message = %s,
                        updated_at = now()
                    WHERE automation_action_id = %s
                    """,
                    (reason or "approval rejected", approval["automation_action_id"]),
                )
            return normalize_rows([approval])[0]


def run_omega_execution(
    postgres_dsn: str,
    *,
    action_code: str | None = None,
    run_code: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    trigger_mode: str = "manual",
    executor_code: str | None = None,
    requested_by: str = "omega",
    max_actions: int = 20,
    allow_external: bool = False,
) -> dict[str, Any]:
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    if max_actions < 1 or max_actions > 500:
        raise QDataValidationError("max_actions must be between 1 and 500")
    started_at = datetime.now(timezone.utc)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            actions = _fetch_execution_candidates(
                cursor,
                action_code=action_code,
                run_code=run_code,
                action_type=action_type,
                status=status,
                limit=max_actions,
            )
            attempts = [
                _process_action(
                    cursor,
                    action,
                    trigger_mode=trigger_mode,
                    executor_code=executor_code,
                    requested_by=requested_by,
                    allow_external=allow_external,
                )
                for action in actions
            ]
    finished_at = datetime.now(timezone.utc)
    return {
        "status": _attempt_summary_status(attempts),
        "action_count": len(actions),
        "attempt_count": len(attempts),
        "success_count": sum(1 for item in attempts if item.get("status") == "success"),
        "approval_required_count": sum(1 for item in attempts if item.get("status") == "approval_required"),
        "retry_scheduled_count": sum(1 for item in attempts if item.get("status") == "retry_scheduled"),
        "failed_count": sum(1 for item in attempts if item.get("status") == "failed"),
        "duration_ms": _duration_ms(started_at, finished_at),
        "attempts": normalize_rows(attempts),
    }


def request_automation_rollback(
    postgres_dsn: str,
    *,
    action_code: str,
    requested_by: str,
    reason: str,
    rollback_type: str = "noop",
) -> dict[str, Any]:
    if rollback_type not in ROLLBACK_TYPES:
        raise QDataValidationError("rollback_type must be one of: noop, manual, webhook, script")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if not reason:
        raise QDataValidationError("reason is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            action = _get_action(cursor, action_code)
            plan = build_rollback_plan(action)
            cursor.execute(
                """
                SELECT attempt_id
                FROM qmeta.automation_execution_attempt
                WHERE automation_action_id = %s
                ORDER BY finished_at DESC NULLS LAST, started_at DESC, attempt_id DESC
                LIMIT 1
                """,
                (action["automation_action_id"],),
            )
            attempt = cursor.fetchone()
            rollback_code = _rollback_code(action["action_code"])
            cursor.execute(
                """
                INSERT INTO qmeta.automation_rollback (
                    rollback_code, automation_action_id, attempt_id, rollback_type,
                    status, requested_by, reason, rollback_plan, updated_at
                ) VALUES (%s, %s, %s, %s, 'planned', %s, %s, %s::jsonb, now())
                ON CONFLICT (rollback_code) DO UPDATE SET
                    attempt_id = EXCLUDED.attempt_id,
                    rollback_type = EXCLUDED.rollback_type,
                    status = 'planned',
                    requested_by = EXCLUDED.requested_by,
                    executed_by = NULL,
                    reason = EXCLUDED.reason,
                    rollback_plan = EXCLUDED.rollback_plan,
                    rollback_result = '{}'::jsonb,
                    executed_at = NULL,
                    error_message = NULL,
                    updated_at = now()
                RETURNING *
                """,
                (
                    rollback_code,
                    action["automation_action_id"],
                    attempt["attempt_id"] if attempt else None,
                    rollback_type,
                    requested_by,
                    reason,
                    _json(plan),
                ),
            )
            rollback = dict(cursor.fetchone())
            _update_action_control(
                cursor,
                action["automation_action_id"],
                omega_control_status="rollback_required",
                rollback_required=True,
                rollback_plan=plan,
            )
            return normalize_rows([rollback])[0]


def run_automation_rollback(
    postgres_dsn: str,
    *,
    rollback_code: str,
    executed_by: str,
    allow_external: bool = False,
) -> dict[str, Any]:
    if not rollback_code:
        raise QDataValidationError("rollback_code is required")
    if not executed_by:
        raise QDataValidationError("executed_by is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rb.*, aa.action_code
                FROM qmeta.automation_rollback rb
                JOIN qmeta.automation_action aa ON aa.automation_action_id = rb.automation_action_id
                WHERE rb.rollback_code = %s
                """,
                (rollback_code,),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"unknown rollback_code: {rollback_code}")
            rollback = dict(row)
            result, status, error = _execute_rollback(rollback, allow_external=allow_external)
            cursor.execute(
                """
                UPDATE qmeta.automation_rollback
                SET status = %s,
                    executed_by = %s,
                    rollback_result = %s::jsonb,
                    error_message = %s,
                    executed_at = now(),
                    updated_at = now()
                WHERE rollback_id = %s
                RETURNING *
                """,
                (status, executed_by, _json(result), error, rollback["rollback_id"]),
            )
            updated = dict(cursor.fetchone())
            if status == "success":
                _update_action_control(
                    cursor,
                    rollback["automation_action_id"],
                    omega_control_status="rolled_back",
                    rollback_required=False,
                )
            return normalize_rows([updated])[0]


def build_rollback_plan(action: dict[str, Any]) -> dict[str, Any]:
    existing = action.get("rollback_plan") or {}
    if existing:
        return existing
    return {
        "action_code": action.get("action_code"),
        "action_type": action.get("action_type"),
        "rollback_hint": action.get("rollback_hint") or "Manual review required before rollback.",
        "source_code": action.get("source_code"),
        "safety_level": action.get("safety_level"),
    }


def simulate_executor(
    action: dict[str, Any],
    executor: dict[str, Any],
    *,
    allow_external: bool = False,
    allowlist: dict[str, Any] | None = None,
    secret_value: str | None = None,
) -> tuple[str, dict[str, Any], str | None]:
    if _force_failure(action, executor):
        return "failed", {"forced_failure": True, "executor_code": executor.get("executor_code")}, "forced executor failure"
    executor_type = executor.get("executor_type") or "noop"
    payload = {
        "executor_code": executor.get("executor_code"),
        "executor_type": executor_type,
        "action_code": action.get("action_code"),
        "action_type": action.get("action_type"),
        "operation": (executor.get("config") or {}).get("operation") or (action.get("planned_effect") or {}).get("operation"),
    }
    if executor_type == "noop":
        payload["external_side_effect"] = False
        return "success", payload, None
    if not allow_external:
        payload["external_side_effect"] = False
        payload["blocked_by"] = "external_executor_disabled"
        return "failed", payload, "external executor disabled"
    validation_error = _validate_sandbox_target(executor, allowlist)
    if validation_error:
        payload["external_side_effect"] = False
        payload["blocked_by"] = validation_error
        return "failed", payload, validation_error
    if executor_type == "webhook":
        return _execute_webhook(action, executor, allowlist or {}, secret_value)
    if executor_type == "script":
        return _execute_script(action, executor, allowlist or {})
    payload["external_side_effect"] = False
    payload["blocked_by"] = "unsupported_executor_type"
    return "failed", payload, "unsupported executor type"


def list_automation_approvals(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("approval_code", "ap.approval_code"),
            ("action_code", "aa.action_code"),
            ("run_code", "ar.run_code"),
            ("status", "ap.status"),
            ("action_type", "aa.action_type"),
            ("requested_by", "ap.requested_by"),
            ("decided_by", "ap.decided_by"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "ap.requested_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ap.approval_id, ap.approval_code, aa.action_code, ar.run_code,
            aa.action_type, aa.safety_level, t.tenant_code, p.project_code,
            ap.status, ap.requested_by, ap.requested_reason, ap.requested_at,
            ap.expires_at, ap.decided_by, ap.decision_reason, ap.decided_at,
            ap.details, ap.created_at, ap.updated_at
        FROM qmeta.automation_approval ap
        JOIN qmeta.automation_action aa ON aa.automation_action_id = ap.automation_action_id
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = aa.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = aa.project_id
        {where}
        ORDER BY ap.requested_at DESC, ap.approval_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_executors(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("executor_code", "ex.executor_code"),
            ("executor_type", "ex.executor_type"),
            ("action_type", "ex.action_type"),
            ("safety_level", "ex.safety_level"),
            ("status", "ex.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ex.executor_id, ex.executor_code, ex.executor_name, ex.executor_type,
            ex.action_type, ex.safety_level, ex.status, ex.requires_approval,
            ex.max_retry_count, ex.retry_backoff_seconds, ex.timeout_seconds,
            ex.endpoint_url, ex.command_name, ex.sandbox_mode, ex.allowlist_code,
            ex.secret_ref, ex.signing_algorithm, ex.allowed_target, ex.config, ex.details,
            ex.created_at, ex.updated_at
        FROM qmeta.automation_executor ex
        {where}
        ORDER BY ex.action_type, ex.safety_level DESC, ex.executor_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_allowlists(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("allowlist_code", "al.allowlist_code"),
            ("executor_type", "al.executor_type"),
            ("status", "al.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            al.allowlist_id, al.allowlist_code, al.executor_type,
            al.target_pattern, al.status, al.sandbox_only,
            al.max_timeout_seconds, al.description, al.details,
            al.created_at, al.updated_at
        FROM qmeta.automation_executor_allowlist al
        {where}
        ORDER BY al.executor_type, al.allowlist_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_secret_refs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("secret_ref", "sr.secret_ref"),
            ("secret_scope", "sr.secret_scope"),
            ("secret_kind", "sr.secret_kind"),
            ("status", "sr.status"),
            ("owner", "sr.owner"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            sr.secret_id, sr.secret_ref, sr.secret_scope, sr.secret_kind,
            sr.status, sr.owner, sr.description, sr.metadata,
            sr.created_at, sr.updated_at
        FROM qmeta.automation_secret_ref sr
        {where}
        ORDER BY sr.secret_scope, sr.secret_ref
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_attempts(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("attempt_code", "at.attempt_code"),
            ("action_code", "aa.action_code"),
            ("run_code", "ar.run_code"),
            ("executor_code", "ex.executor_code"),
            ("status", "at.status"),
            ("trigger_mode", "at.trigger_mode"),
            ("action_type", "aa.action_type"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "at.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            at.attempt_id, at.attempt_code, aa.action_code, ar.run_code,
            ex.executor_code, ex.executor_type, aa.action_type, aa.safety_level,
            t.tenant_code, p.project_code, at.attempt_no, at.trigger_mode,
            at.status, at.retry_count, at.max_retry_count, at.next_retry_at,
            at.error_message, at.request_payload, at.response_payload,
            at.started_at, at.finished_at, at.duration_ms, at.details,
            at.created_at, at.updated_at
        FROM qmeta.automation_execution_attempt at
        JOIN qmeta.automation_action aa ON aa.automation_action_id = at.automation_action_id
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        LEFT JOIN qmeta.automation_executor ex ON ex.executor_id = at.executor_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = aa.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = aa.project_id
        {where}
        ORDER BY at.started_at DESC, at.attempt_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_rollbacks(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("rollback_code", "rb.rollback_code"),
            ("action_code", "aa.action_code"),
            ("run_code", "ar.run_code"),
            ("status", "rb.status"),
            ("rollback_type", "rb.rollback_type"),
            ("action_type", "aa.action_type"),
            ("requested_by", "rb.requested_by"),
            ("executed_by", "rb.executed_by"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "rb.requested_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rb.rollback_id, rb.rollback_code, aa.action_code, ar.run_code,
            rb.attempt_id, aa.action_type, aa.safety_level, t.tenant_code,
            p.project_code, rb.rollback_type, rb.status, rb.requested_by,
            rb.executed_by, rb.reason, rb.rollback_plan, rb.rollback_result,
            rb.requested_at, rb.executed_at, rb.error_message, rb.details,
            rb.created_at, rb.updated_at
        FROM qmeta.automation_rollback rb
        JOIN qmeta.automation_action aa ON aa.automation_action_id = rb.automation_action_id
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = aa.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = aa.project_id
        {where}
        ORDER BY rb.requested_at DESC, rb.rollback_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_omega_report(payload: dict[str, Any]) -> str:
    lines = [
        (
            f"omega_control status={payload.get('status')} actions={payload.get('action_count')} "
            f"attempts={payload.get('attempt_count')} success={payload.get('success_count')} "
            f"approval_required={payload.get('approval_required_count')} retry_scheduled={payload.get('retry_scheduled_count')} "
            f"failed={payload.get('failed_count')}"
        )
    ]
    for attempt in payload.get("attempts") or []:
        keys = ["attempt_code", "action_code", "executor_code", "action_type", "status", "retry_count", "error_message"]
        lines.append(" ".join(f"{key}={attempt[key]}" for key in keys if attempt.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def format_omega_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"omega resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _process_action(
    cursor: Any,
    action: dict[str, Any],
    *,
    trigger_mode: str,
    executor_code: str | None,
    requested_by: str,
    allow_external: bool,
) -> dict[str, Any]:
    approval = _latest_approval(cursor, action["automation_action_id"])
    if action["approval_required"] and not _approval_allows_execution(approval):
        if not approval or approval.get("status") in {"expired", "cancelled"}:
            approval = _upsert_approval(cursor, action, requested_by=requested_by, reason=action.get("reason") or "approval required")
        blocked_status = "skipped" if approval.get("status") == "rejected" else "approval_required"
        attempt = _insert_attempt(
            cursor,
            action,
            executor=None,
            trigger_mode=trigger_mode,
            status=blocked_status,
            request_payload={"approval_code": approval.get("approval_code"), "approval_status": approval.get("status")},
            response_payload={"blocked_by": approval.get("status") or "approval_required"},
            error_message=None,
            retry_count=action.get("retry_count") or 0,
            max_retry_count=action.get("max_retry_count") or 0,
            next_retry_at=None,
        )
        _update_action_control(
            cursor,
            action["automation_action_id"],
            omega_control_status="pending_approval" if approval.get("status") == "pending" else "rejected",
            status=blocked_status,
        )
        return attempt

    executor = _select_executor(cursor, action, executor_code)
    allowlist, secret_value = _load_executor_security_context(cursor, executor)
    status, response_payload, error_message = simulate_executor(
        action,
        executor,
        allow_external=allow_external,
        allowlist=allowlist,
        secret_value=secret_value,
    )
    next_retry_at = None
    retry_count = int(action.get("retry_count") or 0)
    max_retry_count = int(executor.get("max_retry_count") or 0)
    attempt_status = status
    omega_status = status
    action_status = "success" if status == "success" else "failed"
    if status == "failed":
        retry_count += 1
        if retry_count <= max_retry_count:
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=_backoff_seconds(executor, retry_count))
            attempt_status = "retry_scheduled"
            omega_status = "retry_scheduled"
        else:
            omega_status = "failed"
    attempt = _insert_attempt(
        cursor,
        action,
        executor=executor,
        trigger_mode=trigger_mode,
        status=attempt_status,
        request_payload={
            "planned_effect": action.get("planned_effect"),
            "executor_config": executor.get("config"),
            "sandbox_mode": executor.get("sandbox_mode"),
            "allowlist_code": executor.get("allowlist_code"),
            "secret_ref": executor.get("secret_ref"),
            "signing_algorithm": executor.get("signing_algorithm"),
        },
        response_payload=response_payload,
        error_message=error_message,
        retry_count=retry_count,
        max_retry_count=max_retry_count,
        next_retry_at=next_retry_at,
    )
    _update_action_control(
        cursor,
        action["automation_action_id"],
        omega_control_status=omega_status,
        status=action_status,
        executor_code=executor["executor_code"],
        retry_count=retry_count,
        max_retry_count=max_retry_count,
        next_retry_at=next_retry_at,
        rollback_required=False,
        rollback_plan=build_rollback_plan(action) if status == "success" else (action.get("rollback_plan") or {}),
        error_message=error_message,
    )
    return attempt


def _fetch_execution_candidates(
    cursor: Any,
    *,
    action_code: str | None,
    run_code: str | None,
    action_type: str | None,
    status: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    where = ["aa.execution_mode = 'execute'"]
    values: list[Any] = []
    if action_code:
        where.append("aa.action_code = %s")
        values.append(action_code)
    else:
        where.append(
            """
            (
                aa.status = 'approval_required'
                OR aa.omega_control_status IN ('approved', 'retry_scheduled', 'failed')
                OR (aa.status = 'failed' AND aa.next_retry_at IS NULL)
            )
            """
        )
        where.append("(aa.next_retry_at IS NULL OR aa.next_retry_at <= now())")
    if run_code:
        where.append("ar.run_code = %s")
        values.append(run_code)
    if action_type:
        where.append("aa.action_type = %s")
        values.append(action_type)
    if status:
        where.append("aa.status = %s")
        values.append(status)
    cursor.execute(
        f"""
        SELECT
            aa.*, ar.run_code
        FROM qmeta.automation_action aa
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        WHERE {' AND '.join(where)}
        ORDER BY aa.safety_level DESC, aa.updated_at DESC, aa.automation_action_id DESC
        LIMIT %s
        """,
        tuple(values + [limit]),
    )
    return [dict(row) for row in cursor.fetchall()]


def _get_action(cursor: Any, action_code: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT aa.*, ar.run_code
        FROM qmeta.automation_action aa
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        WHERE aa.action_code = %s
        """,
        (action_code,),
    )
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"unknown action_code: {action_code}")
    return dict(row)


def _latest_approval(cursor: Any, action_id: int) -> dict[str, Any] | None:
    cursor.execute(
        """
        UPDATE qmeta.automation_approval
        SET status = 'expired',
            updated_at = now()
        WHERE automation_action_id = %s
          AND status = 'pending'
          AND expires_at IS NOT NULL
          AND expires_at <= now()
        RETURNING approval_id
        """,
        (action_id,),
    )
    cursor.execute(
        """
        SELECT *
        FROM qmeta.automation_approval
        WHERE automation_action_id = %s
        ORDER BY requested_at DESC, approval_id DESC
        LIMIT 1
        """,
        (action_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _upsert_approval(
    cursor: Any,
    action: dict[str, Any],
    *,
    requested_by: str,
    reason: str,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    approval_code = _approval_code(action["action_code"])
    cursor.execute(
        """
        INSERT INTO qmeta.automation_approval (
            approval_code, automation_action_id, status, requested_by,
            requested_reason, expires_at, decided_by, decision_reason, decided_at, updated_at
        ) VALUES (%s, %s, 'pending', %s, %s, %s, NULL, NULL, NULL, now())
        ON CONFLICT (approval_code) DO UPDATE SET
            status = 'pending',
            requested_by = EXCLUDED.requested_by,
            requested_reason = EXCLUDED.requested_reason,
            requested_at = now(),
            expires_at = EXCLUDED.expires_at,
            decided_by = NULL,
            decision_reason = NULL,
            decided_at = NULL,
            updated_at = now()
        RETURNING *
        """,
        (approval_code, action["automation_action_id"], requested_by, reason, expires_at),
    )
    return dict(cursor.fetchone())


def _approval_allows_execution(approval: dict[str, Any] | None) -> bool:
    return bool(approval and approval.get("status") == "approved")


def _select_executor(cursor: Any, action: dict[str, Any], executor_code: str | None) -> dict[str, Any]:
    if executor_code:
        cursor.execute(
            """
            SELECT *
            FROM qmeta.automation_executor
            WHERE executor_code = %s AND status = 'active'
            """,
            (executor_code,),
        )
    else:
        cursor.execute(
            """
            SELECT *
            FROM qmeta.automation_executor
            WHERE action_type = %s
              AND status = 'active'
              AND safety_level IN (%s, %s)
            ORDER BY requires_approval DESC, safety_level DESC, executor_id
            LIMIT 1
            """,
            (action["action_type"], action.get("safety_level") or "medium", _downgrade_safety(action.get("safety_level") or "medium")),
        )
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"no active executor for action_type={action['action_type']}")
    return dict(row)


def _load_executor_security_context(cursor: Any, executor: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    allowlist = None
    allowlist_code = executor.get("allowlist_code")
    if allowlist_code:
        cursor.execute(
            """
            SELECT *
            FROM qmeta.automation_executor_allowlist
            WHERE allowlist_code = %s
            """,
            (allowlist_code,),
        )
        row = cursor.fetchone()
        allowlist = dict(row) if row else None
    secret_value = None
    secret_ref = executor.get("secret_ref")
    if secret_ref:
        cursor.execute(
            """
            SELECT *
            FROM qmeta.automation_secret_ref
            WHERE secret_ref = %s AND status = 'active'
            """,
            (secret_ref,),
        )
        row = cursor.fetchone()
        if row:
            metadata = dict(row).get("metadata") or {}
            env_var = metadata.get("env_var")
            if env_var:
                secret_value = os.getenv(str(env_var))
    return allowlist, secret_value


def _insert_attempt(
    cursor: Any,
    action: dict[str, Any],
    *,
    executor: dict[str, Any] | None,
    trigger_mode: str,
    status: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    error_message: str | None,
    retry_count: int,
    max_retry_count: int,
    next_retry_at: datetime | None,
) -> dict[str, Any]:
    attempt_no = _next_attempt_no(cursor, action["automation_action_id"])
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)
    cursor.execute(
        """
        INSERT INTO qmeta.automation_execution_attempt (
            attempt_code, automation_action_id, executor_id, attempt_no,
            trigger_mode, status, request_payload, response_payload,
            error_message, retry_count, max_retry_count, next_retry_at,
            started_at, finished_at, duration_ms, updated_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s::jsonb, %s::jsonb,
            %s, %s, %s, %s,
            %s, %s, %s, now()
        )
        RETURNING *
        """,
        (
            _attempt_code(action["action_code"], attempt_no),
            action["automation_action_id"],
            executor.get("executor_id") if executor else None,
            attempt_no,
            trigger_mode,
            status,
            _json(_redact_value("request_payload", request_payload)),
            _json(_redact_value("response_payload", response_payload)),
            error_message,
            retry_count,
            max_retry_count,
            next_retry_at,
            started_at,
            finished_at,
            _duration_ms(started_at, finished_at),
        ),
    )
    attempt = dict(cursor.fetchone())
    attempt["action_code"] = action["action_code"]
    attempt["run_code"] = action.get("run_code")
    attempt["action_type"] = action.get("action_type")
    attempt["executor_code"] = executor.get("executor_code") if executor else None
    return normalize_rows([attempt])[0]


def _next_attempt_no(cursor: Any, action_id: int) -> int:
    cursor.execute(
        "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_attempt_no FROM qmeta.automation_execution_attempt WHERE automation_action_id = %s",
        (action_id,),
    )
    return int(cursor.fetchone()["next_attempt_no"])


def _update_action_control(cursor: Any, action_id: int, **updates: Any) -> None:
    allowed = {
        "omega_control_status",
        "status",
        "executor_code",
        "retry_count",
        "max_retry_count",
        "next_retry_at",
        "rollback_required",
        "rollback_plan",
        "error_message",
    }
    fields: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        if key not in allowed:
            continue
        if key == "rollback_plan":
            fields.append(f"{key} = %s::jsonb")
            values.append(_json(value or {}))
        else:
            fields.append(f"{key} = %s")
            values.append(value)
    if not fields:
        return
    fields.append("updated_at = now()")
    values.append(action_id)
    cursor.execute(f"UPDATE qmeta.automation_action SET {', '.join(fields)} WHERE automation_action_id = %s", tuple(values))


def _execute_rollback(rollback: dict[str, Any], *, allow_external: bool) -> tuple[dict[str, Any], str, str | None]:
    rollback_type = rollback.get("rollback_type") or "noop"
    result = {
        "rollback_code": rollback.get("rollback_code"),
        "action_code": rollback.get("action_code"),
        "rollback_type": rollback_type,
    }
    if rollback_type in {"noop", "manual"}:
        result["external_side_effect"] = False
        result["operation"] = "rollback_recorded"
        return result, "success", None
    if not allow_external:
        result["blocked_by"] = "external_rollback_disabled"
        result["external_side_effect"] = False
        return result, "failed", "external rollback disabled"
    result["external_side_effect"] = True
    result["dispatched"] = True
    return result, "success", None


def _validate_sandbox_target(executor: dict[str, Any], allowlist: dict[str, Any] | None) -> str | None:
    executor_type = executor.get("executor_type")
    if not allowlist:
        return "allowlist_missing"
    if allowlist.get("status") != "active":
        return "allowlist_inactive"
    if allowlist.get("executor_type") != executor_type:
        return "allowlist_type_mismatch"
    if allowlist.get("sandbox_only") and not executor.get("sandbox_mode", True):
        return "allowlist_requires_sandbox"
    target = _executor_target(executor)
    if not target:
        return "target_missing"
    pattern = allowlist.get("target_pattern") or ""
    if not fnmatch.fnmatch(target, pattern):
        return "target_not_allowlisted"
    if executor_type == "script":
        script_error = _validate_script_path(target)
        if script_error:
            return script_error
    return None


def _execute_webhook(
    action: dict[str, Any],
    executor: dict[str, Any],
    allowlist: dict[str, Any],
    secret_value: str | None,
) -> tuple[str, dict[str, Any], str | None]:
    target = _executor_target(executor)
    payload = _executor_payload(action, executor)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-QData-Executor": str(executor.get("executor_code") or ""),
        "X-QData-Sandbox": "true" if executor.get("sandbox_mode", True) else "false",
    }
    signing_algorithm = executor.get("signing_algorithm") or "none"
    if signing_algorithm == "hmac_sha256":
        if not secret_value:
            return "failed", {"executor_code": executor.get("executor_code"), "blocked_by": "secret_missing", "external_side_effect": False}, "secret missing"
        headers["X-QData-Signature"] = _hmac_signature(body, secret_value)
    timeout = _executor_timeout(executor, allowlist)
    request = Request(str(target), data=body, headers=headers, method="POST")
    started_at = datetime.now(timezone.utc)
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = _safe_decode(response.read(PAYLOAD_LIMIT))
            status_code = int(response.status)
    except HTTPError as exc:
        response_body = _safe_decode(exc.read(PAYLOAD_LIMIT))
        status_code = int(exc.code)
        return (
            "failed",
            _webhook_response(executor, status_code, response_body, started_at, timeout, signed="X-QData-Signature" in headers),
            f"webhook http {status_code}",
        )
    except (URLError, TimeoutError, OSError) as exc:
        return (
            "failed",
            _webhook_response(executor, None, "", started_at, timeout, signed="X-QData-Signature" in headers, error=str(exc)),
            str(exc),
        )
    status = "success" if 200 <= status_code < 300 else "failed"
    error = None if status == "success" else f"webhook http {status_code}"
    return status, _webhook_response(executor, status_code, response_body, started_at, timeout, signed="X-QData-Signature" in headers), error


def _execute_script(action: dict[str, Any], executor: dict[str, Any], allowlist: dict[str, Any]) -> tuple[str, dict[str, Any], str | None]:
    target = _executor_target(executor)
    if not target:
        return "failed", {"blocked_by": "target_missing", "external_side_effect": False}, "target missing"
    payload = _executor_payload(action, executor)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    timeout = _executor_timeout(executor, allowlist)
    started_at = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            [sys.executable, str(target)],
            input=body,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            "failed",
            _script_response(executor, None, exc.stdout or "", exc.stderr or "", started_at, timeout, timed_out=True),
            "script timeout",
        )
    status = "success" if completed.returncode == 0 else "failed"
    error = None if status == "success" else f"script exit {completed.returncode}"
    return (
        status,
        _script_response(executor, completed.returncode, completed.stdout, completed.stderr, started_at, timeout),
        error,
    )


def _executor_payload(action: dict[str, Any], executor: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_code": action.get("action_code"),
        "action_type": action.get("action_type"),
        "source_type": action.get("source_type"),
        "source_code": action.get("source_code"),
        "safety_level": action.get("safety_level"),
        "planned_effect": action.get("planned_effect") or {},
        "executor_code": executor.get("executor_code"),
        "executor_type": executor.get("executor_type"),
        "sandbox_mode": executor.get("sandbox_mode", True),
        "operation": (executor.get("config") or {}).get("operation") or (action.get("planned_effect") or {}).get("operation"),
    }


def _webhook_response(
    executor: dict[str, Any],
    status_code: int | None,
    response_body: str,
    started_at: datetime,
    timeout: int,
    *,
    signed: bool,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "executor_code": executor.get("executor_code"),
        "executor_type": "webhook",
        "sandbox_mode": executor.get("sandbox_mode", True),
        "external_side_effect": False,
        "sandbox_dispatch": True,
        "allowlist_code": executor.get("allowlist_code"),
        "target": executor.get("endpoint_url"),
        "status_code": status_code,
        "response_body": response_body[:PAYLOAD_LIMIT],
        "duration_ms": _duration_ms(started_at),
        "timeout_seconds": timeout,
        "signed": signed,
        "error": error,
    }


def _script_response(
    executor: dict[str, Any],
    returncode: int | None,
    stdout: str,
    stderr: str,
    started_at: datetime,
    timeout: int,
    *,
    timed_out: bool = False,
) -> dict[str, Any]:
    return {
        "executor_code": executor.get("executor_code"),
        "executor_type": "script",
        "sandbox_mode": executor.get("sandbox_mode", True),
        "external_side_effect": False,
        "sandbox_dispatch": True,
        "allowlist_code": executor.get("allowlist_code"),
        "target": executor.get("command_name"),
        "returncode": returncode,
        "stdout": (stdout or "")[:PAYLOAD_LIMIT],
        "stderr": (stderr or "")[:PAYLOAD_LIMIT],
        "duration_ms": _duration_ms(started_at),
        "timeout_seconds": timeout,
        "timed_out": timed_out,
    }


def _executor_timeout(executor: dict[str, Any], allowlist: dict[str, Any]) -> int:
    executor_timeout = int(executor.get("timeout_seconds") or 1)
    allowlist_timeout = int(allowlist.get("max_timeout_seconds") or executor_timeout)
    return max(1, min(executor_timeout, allowlist_timeout))


def _executor_target(executor: dict[str, Any]) -> str | None:
    return executor.get("allowed_target") or executor.get("endpoint_url") or executor.get("command_name")


def _validate_script_path(target: str) -> str | None:
    path = Path(target)
    if path.is_absolute():
        return "script_path_must_be_relative"
    if ".." in path.parts:
        return "script_path_escape"
    resolved = (PROJECT_ROOT / path).resolve()
    root = PROJECT_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return "script_path_escape"
    if not resolved.exists():
        return "script_not_found"
    if resolved.suffix != ".py":
        return "script_extension_not_allowed"
    return None


def _hmac_signature(body: bytes, secret_value: str) -> str:
    digest = hmac.new(secret_value.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _safe_decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return _redact_rows(normalize_rows([dict(row) for row in cursor.fetchall()]))


def _redact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: _redact_value(key, value) for key, value in row.items()} for row in rows]


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {inner_key: _redact_value(inner_key, inner_value) for inner_key, inner_value in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def _where_equal(params: dict[str, list[str]], fields: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for param_name, column_name in fields:
        value = _param(params, param_name)
        if value in (None, ""):
            continue
        clauses.append(f"{column_name} = %s")
        values.append(value)
    if not clauses:
        return "", values
    return "WHERE " + " AND ".join(clauses), values


def _append_date_filter(where: str, values: list[Any], params: dict[str, list[str]], column: str) -> tuple[str, list[Any]]:
    start = _param(params, "start_date")
    end = _param(params, "end_date")
    if start and end:
        date_range(start, end)
        return _append_where(where, values, f"{column}::date BETWEEN %s AND %s", start, end)
    if start:
        parse_date(start, "start_date")
        return _append_where(where, values, f"{column}::date >= %s", start)
    if end:
        parse_date(end, "end_date")
        return _append_where(where, values, f"{column}::date <= %s", end)
    return where, values


def _append_where(where: str, values: list[Any], clause: str, *new_values: Any) -> tuple[str, list[Any]]:
    prefix = " AND " if where else "WHERE "
    return f"{where}{prefix}{clause}", values + list(new_values)


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "approvals": ["approval_code", "action_code", "run_code", "action_type", "safety_level", "status", "requested_by", "decided_by"],
        "executors": ["executor_code", "executor_type", "action_type", "safety_level", "status", "requires_approval", "sandbox_mode", "allowlist_code", "secret_ref", "signing_algorithm"],
        "allowlists": ["allowlist_code", "executor_type", "target_pattern", "status", "sandbox_only", "max_timeout_seconds"],
        "secrets": ["secret_ref", "secret_scope", "secret_kind", "status", "owner", "metadata"],
        "attempts": ["attempt_code", "action_code", "run_code", "executor_code", "action_type", "status", "retry_count", "max_retry_count", "next_retry_at", "error_message"],
        "rollbacks": ["rollback_code", "action_code", "run_code", "rollback_type", "status", "requested_by", "executed_by", "reason"],
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _attempt_summary_status(attempts: list[dict[str, Any]]) -> str:
    if any(item.get("status") == "failed" for item in attempts):
        return "failed"
    if any(item.get("status") in {"approval_required", "retry_scheduled"} for item in attempts):
        return "warning"
    if not attempts:
        return "skipped"
    return "success"


def _force_failure(action: dict[str, Any], executor: dict[str, Any]) -> bool:
    return bool((action.get("details") or {}).get("omega_force_fail") or (executor.get("config") or {}).get("force_fail"))


def _backoff_seconds(executor: dict[str, Any], retry_count: int) -> int:
    base = int(executor.get("retry_backoff_seconds") or 0)
    return base * max(1, 2 ** max(0, retry_count - 1))


def _downgrade_safety(value: str) -> str:
    return {"critical": "high", "high": "medium", "medium": "low", "low": "low"}.get(value, "medium")


def _parse_timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QDataValidationError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _approval_code(action_code: str) -> str:
    return f"omega-approval-{_slug(action_code)}"[:260]


def _attempt_code(action_code: str, attempt_no: int) -> str:
    digest = hashlib.sha1(f"{action_code}:{attempt_no}".encode("utf-8")).hexdigest()[:10]
    return f"omega-attempt-{_slug(action_code)}-{attempt_no}-{digest}"[:280]


def _rollback_code(action_code: str) -> str:
    return f"omega-rollback-{_slug(action_code)}"[:280]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value)).strip("-").lower() or "unknown"


def _duration_ms(started_at: datetime, finished_at: datetime | None = None) -> int:
    end = finished_at or datetime.now(timezone.utc)
    return int((end - started_at).total_seconds() * 1000)


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Omega automation control") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Omega automation control")
    return _connect(postgres_dsn)
