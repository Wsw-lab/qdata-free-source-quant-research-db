from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from typing import Any

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omega_control import _redact_value, simulate_executor


TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
DISPATCH_TYPES = {"notification", "approval_request", "manual_review"}
ACTIVE_SUCCESS_STATUSES = {"sent", "acknowledged", "recovered"}
RETRY_STATUSES = {"retry_scheduled", "failed", "dead_letter"}


def run_beta2_dispatch(
    postgres_dsn: str,
    *,
    action_code: str,
    channel_code: str,
    requested_by: str = "beta2",
    trigger_mode: str = "manual",
    dispatch_type: str | None = None,
    allow_external: bool = False,
    force: bool = False,
    secret_ref_override: str | None = None,
    idempotency_suffix: str = "",
) -> dict[str, Any]:
    if not action_code:
        raise QDataValidationError("action_code is required")
    if not channel_code:
        raise QDataValidationError("channel_code is required")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            action = _get_action(cursor, action_code)
            channel = _get_channel(cursor, channel_code)
            if secret_ref_override:
                channel = {**channel, "secret_ref": secret_ref_override}
            effective_dispatch_type = dispatch_type or (channel.get("config") or {}).get("dispatch_type") or "notification"
            if effective_dispatch_type not in DISPATCH_TYPES:
                raise QDataValidationError("dispatch_type must be one of: notification, approval_request, manual_review")
            idempotency_key = _idempotency_key(action, channel, effective_dispatch_type)
            if idempotency_suffix:
                idempotency_key = f"{idempotency_key}:{idempotency_suffix}"
            blocked_duplicate = _recent_successful_dispatch(cursor, idempotency_key, channel)
            if blocked_duplicate and not force:
                return _insert_dispatch(
                    cursor,
                    action,
                    channel,
                    dispatch_type=effective_dispatch_type,
                    trigger_mode=trigger_mode,
                    requested_by=requested_by,
                    status="suppressed",
                    idempotency_key=idempotency_key,
                    request_payload=_dispatch_request_payload(action, channel, effective_dispatch_type),
                    response_payload={
                        "blocked_by": "duplicate_window",
                        "existing_dispatch_code": blocked_duplicate["dispatch_code"],
                        "external_side_effect": False,
                    },
                    error_message=None,
                    retry_count=0,
                    next_retry_at=None,
                    dispatched_at=None,
                    acknowledged_at=None,
                )
            retry_not_due = _retry_not_due_dispatch(cursor, idempotency_key)
            if retry_not_due and not force:
                return _insert_dispatch(
                    cursor,
                    action,
                    channel,
                    dispatch_type=effective_dispatch_type,
                    trigger_mode=trigger_mode,
                    requested_by=requested_by,
                    status="suppressed",
                    idempotency_key=idempotency_key,
                    request_payload=_dispatch_request_payload(action, channel, effective_dispatch_type),
                    response_payload={
                        "blocked_by": "retry_not_due",
                        "existing_dispatch_code": retry_not_due["dispatch_code"],
                        "next_retry_at": retry_not_due.get("next_retry_at"),
                        "external_side_effect": False,
                    },
                    error_message=None,
                    retry_count=retry_not_due.get("retry_count") or 0,
                    next_retry_at=None,
                    dispatched_at=None,
                    acknowledged_at=None,
                )
            if not allow_external:
                return _insert_dispatch(
                    cursor,
                    action,
                    channel,
                    dispatch_type=effective_dispatch_type,
                    trigger_mode=trigger_mode,
                    requested_by=requested_by,
                    status="failed",
                    idempotency_key=idempotency_key,
                    request_payload=_dispatch_request_payload(action, channel, effective_dispatch_type),
                    response_payload={"blocked_by": "external_dispatch_disabled", "external_side_effect": False},
                    error_message="external dispatch disabled",
                    retry_count=_next_retry_count(cursor, idempotency_key),
                    next_retry_at=None,
                    dispatched_at=None,
                    acknowledged_at=None,
                )
            allowlist, secret_value = _load_channel_security_context(cursor, channel)
            executor = _channel_executor(channel)
            retry_count = _next_retry_count(cursor, idempotency_key)
            started_at = datetime.now(timezone.utc)
            status, response_payload, error_message = simulate_executor(
                action,
                executor,
                allow_external=True,
                allowlist=allowlist,
                secret_value=secret_value,
            )
            dispatch_status, next_retry_at = _dispatch_status(status, channel, retry_count)
            now = datetime.now(timezone.utc)
            response_payload = {
                **(response_payload or {}),
                "channel_code": channel.get("channel_code"),
                "channel_type": channel.get("channel_type"),
                "environment": channel.get("environment"),
                "duration_ms": int((now - started_at).total_seconds() * 1000),
            }
            return _insert_dispatch(
                cursor,
                action,
                channel,
                dispatch_type=effective_dispatch_type,
                trigger_mode=trigger_mode,
                requested_by=requested_by,
                status=dispatch_status,
                idempotency_key=idempotency_key,
                request_payload=_dispatch_request_payload(action, channel, effective_dispatch_type),
                response_payload=response_payload,
                error_message=error_message,
                retry_count=retry_count,
                next_retry_at=next_retry_at,
                dispatched_at=now,
                acknowledged_at=now if dispatch_status == "acknowledged" else None,
            )


def recover_beta2_dispatch(
    postgres_dsn: str,
    *,
    dispatch_code: str,
    recovered_by: str,
    reason: str,
    runbook_code: str | None = None,
) -> dict[str, Any]:
    if not dispatch_code:
        raise QDataValidationError("dispatch_code is required")
    if not recovered_by:
        raise QDataValidationError("recovered_by is required")
    if not reason:
        raise QDataValidationError("reason is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            dispatch = _get_dispatch(cursor, dispatch_code)
            if dispatch.get("status") not in {"dead_letter", "failed", "retry_scheduled"}:
                raise QDataValidationError("only failed, retry_scheduled, or dead_letter dispatch can be recovered")
            if runbook_code:
                _get_runbook(cursor, runbook_code)
            recovery_payload = {
                "recovered": True,
                "recovered_by": recovered_by,
                "recovery_reason": reason,
                "runbook_code": runbook_code,
                "external_side_effect": False,
            }
            cursor.execute(
                """
                UPDATE qmeta.automation_external_dispatch
                SET status = 'recovered',
                    response_payload = response_payload || %s::jsonb,
                    recovered_at = now(),
                    recovered_by = %s,
                    recovery_reason = %s,
                    details = details || %s::jsonb,
                    updated_at = now()
                WHERE dispatch_code = %s
                RETURNING *
                """,
                (
                    _json(recovery_payload),
                    recovered_by,
                    reason,
                    _json({"runbook_code": runbook_code} if runbook_code else {}),
                    dispatch_code,
                ),
            )
            updated = dict(cursor.fetchone())
            updated.update(
                {
                    "action_code": dispatch.get("action_code"),
                    "run_code": dispatch.get("run_code"),
                    "channel_code": dispatch.get("channel_code"),
                    "channel_type": dispatch.get("channel_type"),
                    "runbook_code": runbook_code or dispatch.get("runbook_code"),
                }
            )
            return normalize_rows([_redact_row(updated)])[0]


def list_automation_channels(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("channel_code", "ch.channel_code"),
            ("channel_type", "ch.channel_type"),
            ("environment", "ch.environment"),
            ("status", "ch.status"),
            ("owner", "ch.owner"),
            ("runbook_code", "ch.runbook_code"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ch.channel_id, ch.channel_code, ch.channel_name, ch.channel_type,
            ch.environment, ch.status, ch.endpoint_url, ch.allowlist_code,
            ch.secret_ref, ch.signing_algorithm, ch.timeout_seconds,
            ch.max_retry_count, ch.retry_backoff_seconds,
            ch.duplicate_window_seconds, ch.owner, ch.runbook_code,
            ch.config, ch.details, ch.created_at, ch.updated_at
        FROM qmeta.automation_external_channel ch
        {where}
        ORDER BY ch.environment, ch.channel_type, ch.channel_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_dispatches(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("dispatch_code", "d.dispatch_code"),
            ("action_code", "aa.action_code"),
            ("run_code", "ar.run_code"),
            ("channel_code", "ch.channel_code"),
            ("channel_type", "ch.channel_type"),
            ("environment", "ch.environment"),
            ("dispatch_type", "d.dispatch_type"),
            ("trigger_mode", "d.trigger_mode"),
            ("status", "d.status"),
            ("requested_by", "d.requested_by"),
            ("recovered_by", "d.recovered_by"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "d.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            d.dispatch_id, d.dispatch_code, aa.action_code, ar.run_code,
            ch.channel_code, ch.channel_type, ch.environment, ch.runbook_code,
            d.dispatch_type, d.trigger_mode, d.status, d.requested_by,
            d.retry_count, d.max_retry_count, d.next_retry_at, d.error_message,
            d.request_payload, d.response_payload, d.dispatched_at,
            d.acknowledged_at, d.recovered_at, d.recovered_by,
            d.recovery_reason, d.details, d.created_at, d.updated_at
        FROM qmeta.automation_external_dispatch d
        JOIN qmeta.automation_action aa ON aa.automation_action_id = d.automation_action_id
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        JOIN qmeta.automation_external_channel ch ON ch.channel_id = d.channel_id
        {where}
        ORDER BY d.updated_at DESC, d.dispatch_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_runbooks(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("runbook_code", "rb.runbook_code"),
            ("failure_class", "rb.failure_class"),
            ("severity", "rb.severity"),
            ("status", "rb.status"),
            ("owner", "rb.owner"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rb.runbook_id, rb.runbook_code, rb.runbook_name,
            rb.failure_class, rb.severity, rb.status, rb.owner,
            rb.recovery_steps, rb.rollback_steps, rb.drill_frequency_days,
            rb.last_drill_at, rb.details, rb.created_at, rb.updated_at
        FROM qmeta.automation_recovery_runbook rb
        {where}
        ORDER BY rb.severity DESC, rb.failure_class, rb.runbook_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_beta2_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"beta2 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _dispatch_status(status: str, channel: dict[str, Any], retry_count: int) -> tuple[str, datetime | None]:
    if status == "success":
        return "acknowledged", None
    max_retry_count = int(channel.get("max_retry_count") or 0)
    if retry_count < max_retry_count:
        delay = int(channel.get("retry_backoff_seconds") or 0) * max(1, 2 ** max(0, retry_count))
        return "retry_scheduled", datetime.now(timezone.utc) + timedelta(seconds=delay)
    return "dead_letter", None


def _idempotency_key(action: dict[str, Any], channel: dict[str, Any], dispatch_type: str) -> str:
    return f"{action['automation_action_id']}:{channel['channel_id']}:{dispatch_type}"


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


def _get_channel(cursor: Any, channel_code: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT *
        FROM qmeta.automation_external_channel
        WHERE channel_code = %s AND status = 'active'
        """,
        (channel_code,),
    )
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"unknown active channel_code: {channel_code}")
    return dict(row)


def _get_dispatch(cursor: Any, dispatch_code: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT d.*, aa.action_code, ar.run_code, ch.channel_code, ch.channel_type, ch.runbook_code
        FROM qmeta.automation_external_dispatch d
        JOIN qmeta.automation_action aa ON aa.automation_action_id = d.automation_action_id
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        JOIN qmeta.automation_external_channel ch ON ch.channel_id = d.channel_id
        WHERE d.dispatch_code = %s
        """,
        (dispatch_code,),
    )
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"unknown dispatch_code: {dispatch_code}")
    return dict(row)


def _get_runbook(cursor: Any, runbook_code: str) -> dict[str, Any]:
    cursor.execute(
        "SELECT * FROM qmeta.automation_recovery_runbook WHERE runbook_code = %s AND status = 'active'",
        (runbook_code,),
    )
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"unknown active runbook_code: {runbook_code}")
    return dict(row)


def _recent_successful_dispatch(cursor: Any, idempotency_key: str, channel: dict[str, Any]) -> dict[str, Any] | None:
    duplicate_window_seconds = int(channel.get("duplicate_window_seconds") or 0)
    if duplicate_window_seconds <= 0:
        return None
    cursor.execute(
        """
        SELECT *
        FROM qmeta.automation_external_dispatch
        WHERE idempotency_key = %s
          AND status = ANY(%s)
          AND created_at >= now() - (%s * INTERVAL '1 second')
        ORDER BY created_at DESC, dispatch_id DESC
        LIMIT 1
        """,
        (idempotency_key, list(ACTIVE_SUCCESS_STATUSES), duplicate_window_seconds),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _retry_not_due_dispatch(cursor: Any, idempotency_key: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT *
        FROM qmeta.automation_external_dispatch
        WHERE idempotency_key = %s
          AND status = 'retry_scheduled'
          AND next_retry_at IS NOT NULL
          AND next_retry_at > now()
        ORDER BY created_at DESC, dispatch_id DESC
        LIMIT 1
        """,
        (idempotency_key,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _next_retry_count(cursor: Any, idempotency_key: str) -> int:
    cursor.execute(
        """
        SELECT retry_count
        FROM qmeta.automation_external_dispatch
        WHERE idempotency_key = %s
          AND status = ANY(%s)
        ORDER BY created_at DESC, dispatch_id DESC
        LIMIT 1
        """,
        (idempotency_key, list(RETRY_STATUSES)),
    )
    row = cursor.fetchone()
    if not row:
        return 0
    return int(row["retry_count"] or 0) + 1


def _load_channel_security_context(cursor: Any, channel: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    allowlist = None
    allowlist_code = channel.get("allowlist_code")
    if allowlist_code:
        cursor.execute("SELECT * FROM qmeta.automation_executor_allowlist WHERE allowlist_code = %s", (allowlist_code,))
        row = cursor.fetchone()
        allowlist = dict(row) if row else None
    secret_value = None
    secret_ref = channel.get("secret_ref")
    if secret_ref:
        cursor.execute("SELECT * FROM qmeta.automation_secret_ref WHERE secret_ref = %s AND status = 'active'", (secret_ref,))
        row = cursor.fetchone()
        if row:
            metadata = dict(row).get("metadata") or {}
            env_var = metadata.get("env_var")
            if env_var:
                secret_value = os.getenv(str(env_var))
    return allowlist, secret_value


def _channel_executor(channel: dict[str, Any]) -> dict[str, Any]:
    executor_type = "webhook" if channel.get("endpoint_url") else "manual"
    return {
        "executor_code": channel.get("channel_code"),
        "executor_type": executor_type,
        "sandbox_mode": True,
        "allowlist_code": channel.get("allowlist_code"),
        "secret_ref": channel.get("secret_ref"),
        "signing_algorithm": channel.get("signing_algorithm") or "none",
        "endpoint_url": channel.get("endpoint_url"),
        "allowed_target": channel.get("endpoint_url"),
        "timeout_seconds": channel.get("timeout_seconds") or 10,
        "config": {
            "operation": "beta2_external_dispatch",
            "channel_type": channel.get("channel_type"),
            "environment": channel.get("environment"),
        },
    }


def _dispatch_request_payload(action: dict[str, Any], channel: dict[str, Any], dispatch_type: str) -> dict[str, Any]:
    return {
        "action_code": action.get("action_code"),
        "run_code": action.get("run_code"),
        "action_type": action.get("action_type"),
        "safety_level": action.get("safety_level"),
        "channel_code": channel.get("channel_code"),
        "channel_type": channel.get("channel_type"),
        "environment": channel.get("environment"),
        "dispatch_type": dispatch_type,
        "allowlist_code": channel.get("allowlist_code"),
        "secret_ref": channel.get("secret_ref"),
        "signing_algorithm": channel.get("signing_algorithm"),
        "planned_effect": action.get("planned_effect") or {},
    }


def _insert_dispatch(
    cursor: Any,
    action: dict[str, Any],
    channel: dict[str, Any],
    *,
    dispatch_type: str,
    trigger_mode: str,
    requested_by: str,
    status: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    error_message: str | None,
    retry_count: int,
    next_retry_at: datetime | None,
    dispatched_at: datetime | None,
    acknowledged_at: datetime | None,
) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.automation_external_dispatch (
            dispatch_code, automation_action_id, channel_id, idempotency_key,
            dispatch_type, trigger_mode, status, requested_by,
            request_payload, response_payload, error_message,
            retry_count, max_retry_count, next_retry_at,
            dispatched_at, acknowledged_at, details, updated_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s::jsonb, %s::jsonb, %s,
            %s, %s, %s,
            %s, %s, %s::jsonb, now()
        )
        RETURNING *
        """,
        (
            _dispatch_code(action.get("action_code"), channel.get("channel_code")),
            action["automation_action_id"],
            channel["channel_id"],
            idempotency_key,
            dispatch_type,
            trigger_mode,
            status,
            requested_by,
            _json(_redact_value("request_payload", request_payload)),
            _json(_redact_value("response_payload", response_payload)),
            error_message,
            retry_count,
            int(channel.get("max_retry_count") or 0),
            next_retry_at,
            dispatched_at,
            acknowledged_at,
            _json(
                {
                    "environment": channel.get("environment"),
                    "channel_type": channel.get("channel_type"),
                    "runbook_code": channel.get("runbook_code"),
                }
            ),
        ),
    )
    row = dict(cursor.fetchone())
    row.update(
        {
            "action_code": action.get("action_code"),
            "run_code": action.get("run_code"),
            "channel_code": channel.get("channel_code"),
            "channel_type": channel.get("channel_type"),
            "environment": channel.get("environment"),
            "runbook_code": channel.get("runbook_code"),
        }
    )
    return normalize_rows([_redact_row(row)])[0]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([_redact_row(dict(row)) for row in cursor.fetchall()])


def _redact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(key, value) for key, value in row.items()}


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
        "channels": ["channel_code", "channel_type", "environment", "status", "endpoint_url", "allowlist_code", "secret_ref", "signing_algorithm", "owner", "runbook_code"],
        "dispatches": ["dispatch_code", "action_code", "run_code", "channel_code", "dispatch_type", "status", "retry_count", "max_retry_count", "next_retry_at", "error_message", "recovered_by"],
        "runbooks": ["runbook_code", "failure_class", "severity", "status", "owner", "drill_frequency_days"],
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _dispatch_code(action_code: str | None, channel_code: str | None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{action_code}:{channel_code}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"beta2-dispatch-{_slug(action_code or 'action')}-{_slug(channel_code or 'channel')}-{digest}"[:260]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value)).strip("-").lower() or "unknown"


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
        raise QDataValidationError("psycopg is required for Beta-2 external dispatch") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Beta-2 external dispatch")
    return _connect(postgres_dsn)
