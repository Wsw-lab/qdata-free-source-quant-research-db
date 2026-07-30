from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
from typing import Any

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.beta2_external import run_beta2_dispatch
from qdata.exceptions import QDataValidationError
from qdata.omega_control import _redact_value


TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
VALIDATION_TYPES = {"dry_run_dispatch", "live_dispatch", "secret_rotation", "rollback_drill"}
VALIDATION_STATUSES = {"planned", "success", "failed", "blocked", "skipped"}
ROTATION_TYPES = {"manual", "scheduled", "emergency", "drill"}
SUCCESS_DISPATCH_STATUSES = {"acknowledged"}


def run_gamma2_profile_validation(
    postgres_dsn: str,
    *,
    profile_code: str,
    action_code: str,
    requested_by: str = "gamma2",
    validation_type: str = "dry_run_dispatch",
    trigger_mode: str = "manual",
    allow_external: bool = False,
    force: bool = False,
    target_secret_ref: str | None = None,
) -> dict[str, Any]:
    if not profile_code:
        raise QDataValidationError("profile_code is required")
    if not action_code:
        raise QDataValidationError("action_code is required")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if validation_type not in VALIDATION_TYPES:
        raise QDataValidationError("validation_type must be one of: dry_run_dispatch, live_dispatch, secret_rotation, rollback_drill")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")

    started_at = datetime.now(timezone.utc)
    profile = _get_profile(postgres_dsn, profile_code)
    blocked_reason = _profile_blocked_reason(profile, validation_type)
    if blocked_reason:
        return _insert_validation(
            postgres_dsn,
            profile,
            validation_type=validation_type,
            trigger_mode=trigger_mode,
            status="blocked",
            requested_by=requested_by,
            target_secret_ref=target_secret_ref,
            request_payload={"action_code": action_code, "profile_code": profile_code},
            response_payload={"blocked_by": blocked_reason, "external_side_effect": False},
            error_message=blocked_reason,
            started_at=started_at,
            dispatch=None,
        )

    dispatch: dict[str, Any] | None = None
    error_message: str | None = None
    try:
        dispatch = run_beta2_dispatch(
            postgres_dsn,
            action_code=action_code,
            channel_code=profile["channel_code"],
            requested_by=requested_by,
            trigger_mode=trigger_mode,
            allow_external=allow_external,
            force=force,
            secret_ref_override=target_secret_ref,
            idempotency_suffix=f"gamma2:{profile_code}:{validation_type}:{target_secret_ref or profile.get('secret_ref') or ''}",
        )
    except QDataValidationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive shell path
        error_message = str(exc)

    status = _validation_status_from_dispatch(dispatch) if dispatch else "failed"
    if not error_message and dispatch:
        error_message = dispatch.get("error_message")
    return _insert_validation(
        postgres_dsn,
        profile,
        validation_type=validation_type,
        trigger_mode=trigger_mode,
        status=status,
        requested_by=requested_by,
        target_secret_ref=target_secret_ref,
        request_payload={"action_code": action_code, "profile_code": profile_code, "allow_external": allow_external},
        response_payload={"dispatch": dispatch or {}, "external_side_effect": False},
        error_message=error_message,
        started_at=started_at,
        dispatch=dispatch,
    )


def run_gamma2_secret_rotation(
    postgres_dsn: str,
    *,
    secret_ref: str,
    next_secret_ref: str,
    requested_by: str = "gamma2",
    reason: str = "Gamma-2 secret rotation drill",
    environment: str = "local",
    rotation_type: str = "manual",
    profile_code: str | None = None,
    action_code: str | None = None,
    allow_external: bool = False,
    apply_rotation: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if not secret_ref:
        raise QDataValidationError("secret_ref is required")
    if not next_secret_ref:
        raise QDataValidationError("next_secret_ref is required")
    if secret_ref == next_secret_ref:
        raise QDataValidationError("next_secret_ref must be different from secret_ref")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if rotation_type not in ROTATION_TYPES:
        raise QDataValidationError("rotation_type must be one of: manual, scheduled, emergency, drill")

    current_secret = _get_secret_ref(postgres_dsn, secret_ref)
    next_secret = _get_secret_ref(postgres_dsn, next_secret_ref)
    secret_evidence = {
        "current": _secret_env_evidence(current_secret),
        "next": _secret_env_evidence(next_secret),
    }
    missing = [
        label
        for label, evidence in (("current", secret_evidence["current"]), ("next", secret_evidence["next"]))
        if not evidence["env_present"]
    ]
    profile: dict[str, Any] | None = _get_profile(postgres_dsn, profile_code) if profile_code else None
    validation: dict[str, Any] | None = None
    error_message: str | None = None
    status = "validated"

    if missing:
        status = "blocked"
        error_message = f"missing secret env var: {','.join(missing)}"
    elif profile_code and action_code:
        validation = run_gamma2_profile_validation(
            postgres_dsn,
            profile_code=profile_code,
            action_code=action_code,
            requested_by=requested_by,
            validation_type="secret_rotation",
            trigger_mode="smoke" if allow_external else "manual",
            allow_external=allow_external,
            force=force,
            target_secret_ref=next_secret_ref,
        )
        if validation.get("status") != "success":
            status = "failed"
            error_message = validation.get("error_message") or "candidate secret validation failed"
    elif apply_rotation:
        status = "blocked"
        error_message = "apply_rotation requires profile_code and action_code validation"

    affected_channel_count = 0
    if status == "validated" and apply_rotation:
        affected_channel_count = _apply_secret_rotation(
            postgres_dsn,
            environment=environment,
            secret_ref=secret_ref,
            next_secret_ref=next_secret_ref,
            profile_id=profile.get("profile_id") if profile else None,
            channel_id=profile.get("channel_id") if profile else None,
        )
        status = "applied"

    return _insert_rotation(
        postgres_dsn,
        environment=environment,
        secret_ref=secret_ref,
        next_secret_ref=next_secret_ref,
        rotation_type=rotation_type,
        status=status,
        requested_by=requested_by,
        approved_by=requested_by if apply_rotation and status == "applied" else None,
        reason=reason,
        profile=profile,
        validation=validation,
        affected_channel_count=affected_channel_count,
        error_message=error_message,
        evidence={**secret_evidence, "apply_rotation": apply_rotation},
    )


def rollback_gamma2_secret_rotation(
    postgres_dsn: str,
    *,
    rotation_code: str,
    rolled_back_by: str,
    reason: str,
) -> dict[str, Any]:
    if not rotation_code:
        raise QDataValidationError("rotation_code is required")
    if not rolled_back_by:
        raise QDataValidationError("rolled_back_by is required")
    if not reason:
        raise QDataValidationError("reason is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            rotation = _get_rotation(cursor, rotation_code)
            if rotation.get("status") != "applied":
                raise QDataValidationError("only applied rotations can be rolled back")
            profile_id = rotation.get("profile_id")
            cursor.execute(
                """
                UPDATE qmeta.automation_external_channel ch
                SET secret_ref = %s,
                    updated_at = now()
                WHERE ch.environment = %s
                  AND ch.secret_ref = %s
                  AND (%s::bigint IS NULL OR ch.channel_id = (
                        SELECT profile.channel_id
                        FROM qmeta.automation_channel_profile profile
                        WHERE profile.profile_id = %s
                  ))
                """,
                (rotation["secret_ref"], rotation["environment"], rotation["next_secret_ref"], profile_id, profile_id),
            )
            cursor.execute(
                """
                UPDATE qmeta.automation_channel_profile
                SET secret_ref = %s,
                    readiness_status = 'not_configured',
                    updated_at = now()
                WHERE environment = %s
                  AND secret_ref = %s
                  AND (%s::bigint IS NULL OR profile_id = %s)
                """,
                (rotation["secret_ref"], rotation["environment"], rotation["next_secret_ref"], profile_id, profile_id),
            )
            cursor.execute(
                """
                UPDATE qmeta.automation_secret_rotation
                SET status = 'rolled_back',
                    rolled_back_at = now(),
                    rolled_back_by = %s,
                    rollback_reason = %s,
                    evidence = evidence || %s::jsonb,
                    updated_at = now()
                WHERE rotation_code = %s
                RETURNING *
                """,
                (
                    rolled_back_by,
                    reason,
                    _json({"rollback": {"external_side_effect": False, "reason": reason}}),
                    rotation_code,
                ),
            )
            return normalize_rows([_redact_row(dict(cursor.fetchone()))])[0]


def list_automation_channel_profiles(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("profile_code", "p.profile_code"),
            ("channel_code", "ch.channel_code"),
            ("provider_code", "p.provider_code"),
            ("environment", "p.environment"),
            ("status", "p.profile_status"),
            ("profile_status", "p.profile_status"),
            ("readiness_status", "p.readiness_status"),
            ("owner", "p.owner"),
            ("runbook_code", "p.runbook_code"),
            ("secret_ref", "p.secret_ref"),
            ("next_secret_ref", "p.next_secret_ref"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            p.profile_id, p.profile_code, ch.channel_code, ch.channel_type,
            p.provider_code, p.environment, p.profile_status, p.readiness_status,
            p.dry_run_only, p.endpoint_url, p.dry_run_endpoint_url,
            p.live_endpoint_url, p.allowlist_code, p.secret_ref, p.next_secret_ref,
            p.signing_algorithm, p.owner, p.runbook_code,
            p.last_validation_code, p.last_validation_status, p.last_validated_at,
            p.config, p.details, p.created_at, p.updated_at
        FROM qmeta.automation_channel_profile p
        JOIN qmeta.automation_external_channel ch ON ch.channel_id = p.channel_id
        {where}
        ORDER BY p.environment, p.provider_code, p.profile_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_channel_validations(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("validation_code", "v.validation_code"),
            ("profile_code", "p.profile_code"),
            ("channel_code", "ch.channel_code"),
            ("provider_code", "p.provider_code"),
            ("environment", "p.environment"),
            ("validation_type", "v.validation_type"),
            ("trigger_mode", "v.trigger_mode"),
            ("status", "v.status"),
            ("requested_by", "v.requested_by"),
            ("target_secret_ref", "v.target_secret_ref"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "v.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            v.validation_id, v.validation_code, p.profile_code,
            ch.channel_code, ch.channel_type, p.provider_code, p.environment,
            d.dispatch_code, v.validation_type, v.trigger_mode, v.status,
            v.requested_by, v.target_secret_ref, v.request_payload,
            v.response_payload, v.error_message, v.started_at, v.finished_at,
            v.duration_ms, v.evidence, v.details, v.created_at, v.updated_at
        FROM qmeta.automation_channel_validation v
        JOIN qmeta.automation_channel_profile p ON p.profile_id = v.profile_id
        JOIN qmeta.automation_external_channel ch ON ch.channel_id = v.channel_id
        LEFT JOIN qmeta.automation_external_dispatch d ON d.dispatch_id = v.dispatch_id
        {where}
        ORDER BY v.started_at DESC, v.validation_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_secret_rotations(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("rotation_code", "r.rotation_code"),
            ("environment", "r.environment"),
            ("secret_ref", "r.secret_ref"),
            ("next_secret_ref", "r.next_secret_ref"),
            ("rotation_type", "r.rotation_type"),
            ("status", "r.status"),
            ("requested_by", "r.requested_by"),
            ("approved_by", "r.approved_by"),
            ("profile_code", "p.profile_code"),
            ("validation_code", "v.validation_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "r.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            r.rotation_id, r.rotation_code, r.environment,
            r.secret_ref, r.next_secret_ref, r.rotation_type, r.status,
            r.requested_by, r.approved_by, r.reason, p.profile_code,
            v.validation_code, v.status AS validation_status,
            r.affected_channel_count, r.validated_at, r.applied_at,
            r.rolled_back_at, r.rolled_back_by, r.rollback_reason,
            r.error_message, r.evidence, r.details, r.created_at, r.updated_at
        FROM qmeta.automation_secret_rotation r
        LEFT JOIN qmeta.automation_channel_profile p ON p.profile_id = r.profile_id
        LEFT JOIN qmeta.automation_channel_validation v ON v.validation_id = r.validation_id
        {where}
        ORDER BY r.created_at DESC, r.rotation_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_gamma2_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"gamma2 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _validation_status_from_dispatch(dispatch: dict[str, Any] | None) -> str:
    if not dispatch:
        return "failed"
    dispatch_status = dispatch.get("status")
    if dispatch_status in SUCCESS_DISPATCH_STATUSES:
        return "success"
    if dispatch_status == "suppressed":
        return "skipped"
    return "failed"


def _readiness_after_validation(profile: dict[str, Any], validation_type: str, status: str) -> str:
    if status == "success" and validation_type == "live_dispatch":
        return "live_ready"
    if status == "success":
        return "dry_run_ready"
    if status == "blocked":
        return "blocked"
    if status == "failed":
        return "failed"
    return str(profile.get("readiness_status") or "not_configured")


def _profile_blocked_reason(profile: dict[str, Any], validation_type: str) -> str | None:
    if profile.get("profile_status") != "active":
        return "profile_not_active"
    if profile.get("channel_status") != "active":
        return "channel_not_active"
    if validation_type == "live_dispatch" and profile.get("dry_run_only"):
        return "profile_dry_run_only"
    if not profile.get("endpoint_url") and validation_type != "rollback_drill":
        return "endpoint_missing"
    return None


def _insert_validation(
    postgres_dsn: str,
    profile: dict[str, Any],
    *,
    validation_type: str,
    trigger_mode: str,
    status: str,
    requested_by: str,
    target_secret_ref: str | None,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    error_message: str | None,
    started_at: datetime,
    dispatch: dict[str, Any] | None,
) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc)
    validation_code = _code("gamma2-validation", profile.get("profile_code"), validation_type)
    readiness_status = _readiness_after_validation(profile, validation_type, status)
    evidence = {
        "provider_code": profile.get("provider_code"),
        "environment": profile.get("environment"),
        "channel_code": profile.get("channel_code"),
        "dispatch_status": (dispatch or {}).get("status"),
        "signed": ((dispatch or {}).get("response_payload") or {}).get("signed"),
        "status_code": ((dispatch or {}).get("response_payload") or {}).get("status_code"),
        "external_side_effect": False,
    }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.automation_channel_validation (
                    validation_code, profile_id, channel_id, dispatch_id,
                    validation_type, trigger_mode, status, requested_by,
                    target_secret_ref, request_payload, response_payload,
                    error_message, started_at, finished_at, duration_ms,
                    evidence, details, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, now()
                )
                RETURNING *
                """,
                (
                    validation_code,
                    profile["profile_id"],
                    profile["channel_id"],
                    (dispatch or {}).get("dispatch_id"),
                    validation_type,
                    trigger_mode,
                    status,
                    requested_by,
                    target_secret_ref,
                    _json(_redact_value("request_payload", request_payload)),
                    _json(_redact_value("response_payload", response_payload)),
                    error_message,
                    started_at,
                    finished_at,
                    _duration_ms(started_at, finished_at),
                    _json(_redact_value("evidence", evidence)),
                    _json({"source": "gamma2"}),
                ),
            )
            validation = dict(cursor.fetchone())
            cursor.execute(
                """
                UPDATE qmeta.automation_channel_profile
                SET readiness_status = %s,
                    last_validation_code = %s,
                    last_validation_status = %s,
                    last_validated_at = %s,
                    updated_at = now()
                WHERE profile_id = %s
                """,
                (readiness_status, validation_code, status, finished_at, profile["profile_id"]),
            )
            validation.update(
                {
                    "profile_code": profile.get("profile_code"),
                    "channel_code": profile.get("channel_code"),
                    "provider_code": profile.get("provider_code"),
                    "environment": profile.get("environment"),
                    "dispatch_code": (dispatch or {}).get("dispatch_code"),
                    "readiness_status": readiness_status,
                }
            )
            return normalize_rows([_redact_row(validation)])[0]


def _insert_rotation(
    postgres_dsn: str,
    *,
    environment: str,
    secret_ref: str,
    next_secret_ref: str,
    rotation_type: str,
    status: str,
    requested_by: str,
    approved_by: str | None,
    reason: str,
    profile: dict[str, Any] | None,
    validation: dict[str, Any] | None,
    affected_channel_count: int,
    error_message: str | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    rotation_code = _code("gamma2-rotation", environment, secret_ref, next_secret_ref)
    validated_at = datetime.now(timezone.utc) if status in {"validated", "applied"} else None
    applied_at = datetime.now(timezone.utc) if status == "applied" else None
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.automation_secret_rotation (
                    rotation_code, environment, secret_ref, next_secret_ref,
                    rotation_type, status, requested_by, approved_by, reason,
                    profile_id, validation_id, affected_channel_count,
                    validated_at, applied_at, error_message, evidence, details,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s::jsonb,
                    now()
                )
                RETURNING *
                """,
                (
                    rotation_code,
                    environment,
                    secret_ref,
                    next_secret_ref,
                    rotation_type,
                    status,
                    requested_by,
                    approved_by,
                    reason,
                    (profile or {}).get("profile_id"),
                    (validation or {}).get("validation_id"),
                    affected_channel_count,
                    validated_at,
                    applied_at,
                    error_message,
                    _json(_redact_value("evidence", {**evidence, "validation_code": (validation or {}).get("validation_code")})),
                    _json({"source": "gamma2"}),
                ),
            )
            rotation = dict(cursor.fetchone())
            rotation.update(
                {
                    "profile_code": (profile or {}).get("profile_code"),
                    "validation_code": (validation or {}).get("validation_code"),
                    "validation_status": (validation or {}).get("status"),
                }
            )
            return normalize_rows([_redact_row(rotation)])[0]


def _apply_secret_rotation(
    postgres_dsn: str,
    *,
    environment: str,
    secret_ref: str,
    next_secret_ref: str,
    profile_id: int | None,
    channel_id: int | None,
) -> int:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.automation_external_channel
                SET secret_ref = %s,
                    updated_at = now()
                WHERE environment = %s
                  AND secret_ref = %s
                  AND (%s::bigint IS NULL OR channel_id = %s)
                RETURNING channel_id
                """,
                (next_secret_ref, environment, secret_ref, channel_id, channel_id),
            )
            channel_count = len(cursor.fetchall())
            cursor.execute(
                """
                UPDATE qmeta.automation_channel_profile
                SET secret_ref = %s,
                    readiness_status = 'not_configured',
                    updated_at = now()
                WHERE environment = %s
                  AND secret_ref = %s
                  AND (%s::bigint IS NULL OR profile_id = %s)
                """,
                (next_secret_ref, environment, secret_ref, profile_id, profile_id),
            )
            return channel_count


def _get_profile(postgres_dsn: str, profile_code: str | None) -> dict[str, Any]:
    if not profile_code:
        raise QDataValidationError("profile_code is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    p.*, ch.channel_code, ch.channel_type,
                    ch.status AS channel_status,
                    ch.endpoint_url AS channel_endpoint_url
                FROM qmeta.automation_channel_profile p
                JOIN qmeta.automation_external_channel ch ON ch.channel_id = p.channel_id
                WHERE p.profile_code = %s
                """,
                (profile_code,),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"unknown profile_code: {profile_code}")
            return dict(row)


def _get_secret_ref(postgres_dsn: str, secret_ref: str) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM qmeta.automation_secret_ref WHERE secret_ref = %s AND status = 'active'",
                (secret_ref,),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"unknown active secret_ref: {secret_ref}")
            return dict(row)


def _get_rotation(cursor: Any, rotation_code: str) -> dict[str, Any]:
    cursor.execute(
        "SELECT * FROM qmeta.automation_secret_rotation WHERE rotation_code = %s",
        (rotation_code,),
    )
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"unknown rotation_code: {rotation_code}")
    return dict(row)


def _secret_env_evidence(secret: dict[str, Any]) -> dict[str, Any]:
    metadata = secret.get("metadata") or {}
    env_var = metadata.get("env_var")
    value = os.getenv(str(env_var)) if env_var else None
    return {
        "secret_ref": secret.get("secret_ref"),
        "env_var": env_var,
        "env_present": bool(value),
        "fingerprint": _fingerprint(value) if value else "",
    }


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
        "profiles": [
            "profile_code",
            "channel_code",
            "provider_code",
            "environment",
            "profile_status",
            "readiness_status",
            "dry_run_only",
            "secret_ref",
            "next_secret_ref",
            "last_validation_status",
        ],
        "validations": [
            "validation_code",
            "profile_code",
            "channel_code",
            "provider_code",
            "validation_type",
            "status",
            "dispatch_code",
            "target_secret_ref",
            "error_message",
        ],
        "rotations": [
            "rotation_code",
            "environment",
            "secret_ref",
            "next_secret_ref",
            "rotation_type",
            "status",
            "profile_code",
            "validation_code",
            "validation_status",
            "affected_channel_count",
            "error_message",
        ],
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _code(prefix: str, *parts: object) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(":".join(str(part) for part in (*parts, stamp)).encode("utf-8")).hexdigest()[:10]
    body = "-".join(_slug(str(part)) for part in parts if part not in (None, ""))
    return f"{prefix}-{body}-{digest}"[:160]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value)).strip("-").lower() or "unknown"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _duration_ms(started_at: datetime, finished_at: datetime | None = None) -> int:
    finished = finished_at or datetime.now(timezone.utc)
    return int((finished - started_at).total_seconds() * 1000)


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
        raise QDataValidationError("psycopg is required for Gamma-2 external profile validation") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Gamma-2 external profile validation")
    return _connect(postgres_dsn)
