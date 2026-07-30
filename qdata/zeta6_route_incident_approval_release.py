from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.delta6_route_incident_approval_governance import DEFAULT_SECRET, verify_wecom_callback_signature
from qdata.epsilon6_route_incident_approval_resilience import verify_approval_audit_chain
from qdata.exceptions import QDataValidationError


ENVIRONMENTS = {"local", "staging", "production"}
TRIGGER_MODES = {"manual", "worker", "smoke", "release"}
EXPORT_FORMATS = {"json", "markdown", "csv"}


def configured_wecom_secrets(current_secret: str | None = None, next_secret: str | None = None) -> dict[str, Any]:
    current = current_secret if current_secret is not None else os.getenv("QDATA_DELTA6_WECOM_CALLBACK_SECRET", DEFAULT_SECRET)
    next_value = next_secret if next_secret is not None else os.getenv("QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT", "")
    current = str(current or "")
    next_value = str(next_value or "")
    accepted = []
    if current:
        accepted.append("current")
    if next_value and next_value != current:
        accepted.append("next")
    if next_value and not current:
        phase = "next_only"
        active = "next"
    elif next_value and next_value != current:
        phase = "dual_accept"
        active = "current"
    elif current:
        phase = "current_only"
        active = "current"
    else:
        phase = "current_only"
        active = "none"
    return {
        "rotation_phase": phase,
        "active_secret_label": active,
        "accepted_secret_labels": accepted,
        "current_configured": bool(current),
        "next_configured": bool(next_value and next_value != current),
        "dual_secret_enabled": bool(next_value and current and next_value != current),
        "current_secret": current,
        "next_secret": next_value if next_value != current else "",
    }


def verify_wecom_callback_signature_rotating(
    raw_body: bytes | str,
    headers: dict[str, str] | None,
    *,
    payload: dict[str, Any] | None = None,
    current_secret: str | None = None,
    next_secret: str | None = None,
    max_clock_skew_seconds: int = 300,
    now: datetime | None = None,
) -> dict[str, Any]:
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    body = body or b""
    header_map = _normalize_headers(headers or {})
    payload = payload or {}
    timestamp = _header_or_payload(header_map, payload, "timestamp")
    nonce = _header_or_payload(header_map, payload, "nonce")
    signature = _header_or_payload(header_map, payload, "signature")
    request_hash = hashlib.sha256(body).hexdigest()
    secrets = configured_wecom_secrets(current_secret, next_secret)
    attempts: list[dict[str, Any]] = []
    verified_attempt: dict[str, Any] | None = None
    for label, secret in (("current", secrets["current_secret"]), ("next", secrets["next_secret"])):
        if not secret:
            continue
        result = verify_wecom_callback_signature(
            secret,
            timestamp,
            nonce,
            body,
            signature,
            max_clock_skew_seconds=max_clock_skew_seconds,
            now=now,
        )
        public = _public_signature_attempt(label, result)
        attempts.append(public)
        if result.get("verified") and verified_attempt is None:
            verified_attempt = {"label": label, "result": result, "public": public}

    last_result = (verified_attempt or {}).get("result") if verified_attempt else {}
    if not last_result and attempts:
        last_result = {"signature_status": attempts[0].get("signature_status"), "error_message": attempts[0].get("error_message")}
    signature_status = str((last_result or {}).get("signature_status") or "missing_signature")
    verified_label = str((verified_attempt or {}).get("label") or "none")
    return {
        "verified": bool(verified_attempt),
        "signature_status": "verified" if verified_attempt else signature_status,
        "verified_secret_label": verified_label,
        "active_secret_label": secrets["active_secret_label"],
        "rotation_phase": secrets["rotation_phase"],
        "accepted_secret_labels": secrets["accepted_secret_labels"],
        "timestamp_seconds": (last_result or {}).get("timestamp_seconds"),
        "clock_skew_seconds": (last_result or {}).get("clock_skew_seconds"),
        "nonce": nonce,
        "request_hash": request_hash,
        "signature_digest": _normalize_signature(signature),
        "max_clock_skew_seconds": max_clock_skew_seconds,
        "attempts": attempts,
        "evidence": {
            "signature_attempts": attempts,
            "request_hash_tail": request_hash[-12:],
            "secret_material_persisted": False,
        },
        "error_message": None if verified_attempt else str((last_result or {}).get("error_message") or "callback signature mismatch"),
    }


def record_secret_rotation_check(
    postgres_dsn: str,
    result: dict[str, Any],
    *,
    environment: str = "local",
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_environment(environment)
    observed_at = datetime.now(timezone.utc)
    record = {
        "rotation_code": _code("zeta6-secret-rotation", environment, str(result.get("request_hash") or ""), observed_at),
        "environment": environment,
        "rotation_phase": result.get("rotation_phase") or "current_only",
        "status": "success" if result.get("verified") else "failed",
        "active_secret_label": result.get("active_secret_label") or "none",
        "accepted_secret_labels": result.get("accepted_secret_labels") or [],
        "verified_secret_label": result.get("verified_secret_label") or "none",
        "timestamp_seconds": result.get("timestamp_seconds"),
        "nonce": result.get("nonce"),
        "request_hash": result.get("request_hash"),
        "signature_digest": result.get("signature_digest"),
        "max_clock_skew_seconds": int(result.get("max_clock_skew_seconds") or 300),
        "evidence": _safe_evidence(result.get("evidence") or {"signature_attempts": result.get("attempts") or []}),
        "error_message": result.get("error_message"),
        "observed_at": observed_at,
    }
    if not write_db:
        return normalize_rows([record])[0]
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_secret_rotation (
                    rotation_code, environment, rotation_phase, status,
                    active_secret_label, accepted_secret_labels, verified_secret_label,
                    timestamp_seconds, nonce, request_hash, signature_digest,
                    max_clock_skew_seconds, evidence, error_message, observed_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::jsonb, %s, %s, now()
                )
                RETURNING *
                """,
                (
                    record["rotation_code"],
                    record["environment"],
                    record["rotation_phase"],
                    record["status"],
                    record["active_secret_label"],
                    record["accepted_secret_labels"],
                    record["verified_secret_label"],
                    record["timestamp_seconds"],
                    record["nonce"],
                    record["request_hash"],
                    record["signature_digest"],
                    record["max_clock_skew_seconds"],
                    _json(record["evidence"]),
                    record["error_message"],
                    record["observed_at"],
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def run_release_preflight(
    postgres_dsn: str,
    *,
    environment: str = "local",
    release_version: str = "zeta6-local",
    requested_by: str = "zeta6",
    trigger_mode: str = "manual",
    require_dual_secret: bool = False,
    audit_verify_limit: int = 1000,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_environment(environment)
    _validate_trigger_mode(trigger_mode)
    if audit_verify_limit <= 0:
        raise QDataValidationError("audit_verify_limit must be greater than 0")
    started_at = datetime.now(timezone.utc)
    checks: list[dict[str, Any]] = []
    latest_drill_status: str | None = None
    audit_broken_count = 0
    secrets = configured_wecom_secrets()

    try:
        with _connect(_require_dsn(postgres_dsn)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                checks.append(_check("db_reconnect", "passed", value=cursor.fetchone()["ok"]))
    except Exception as exc:
        checks.append(_check("db_reconnect", "failed", error_message=str(exc)))

    try:
        chain = verify_approval_audit_chain(_require_dsn(postgres_dsn), limit=audit_verify_limit)
        audit_broken_count = int(chain.get("broken_count") or 0)
        if audit_broken_count:
            checks.append(_check("audit_hash_chain", "failed", result=chain, error_message="audit hash chain has broken entries"))
        elif int(chain.get("checked_count") or 0) == 0:
            checks.append(_check("audit_hash_chain", "warning", result=chain, error_message="no Epsilon-6 audit hash rows yet"))
        else:
            checks.append(_check("audit_hash_chain", "passed", result=chain))
    except Exception as exc:
        checks.append(_check("audit_hash_chain", "failed", error_message=str(exc)))

    try:
        latest_drill = _latest_recovery_drill(postgres_dsn)
        latest_drill_status = str((latest_drill or {}).get("status") or "missing")
        if not latest_drill:
            checks.append(_check("latest_recovery_drill", "warning", error_message="no Epsilon-6 recovery drill evidence yet"))
        elif latest_drill_status == "success":
            checks.append(_check("latest_recovery_drill", "passed", result={"drill_code": latest_drill.get("drill_code"), "status": latest_drill_status}))
        else:
            checks.append(_check("latest_recovery_drill", "failed", result=latest_drill, error_message="latest recovery drill is not successful"))
    except Exception as exc:
        checks.append(_check("latest_recovery_drill", "failed", error_message=str(exc)))

    try:
        schedule = _release_schedule_health(postgres_dsn)
        checks.append(_check("worker_schedule_active", "passed" if schedule["active_count"] >= 2 else "warning", result=schedule, error_message=None if schedule["active_count"] >= 2 else "Epsilon/Zeta worker schedules are not both active"))
    except Exception as exc:
        checks.append(_check("worker_schedule_active", "failed", error_message=str(exc)))

    checks.append(_check("current_secret_configured", "passed" if secrets["current_configured"] else "failed", result={"active_secret_label": secrets["active_secret_label"]}, error_message=None if secrets["current_configured"] else "current callback secret is not configured"))
    if require_dual_secret:
        checks.append(_check("dual_secret_configured", "passed" if secrets["dual_secret_enabled"] else "failed", result={"dual_secret_enabled": secrets["dual_secret_enabled"]}, error_message=None if secrets["dual_secret_enabled"] else "next callback secret is required but not configured"))
    else:
        checks.append(_check("dual_secret_configured", "passed", result={"dual_secret_enabled": secrets["dual_secret_enabled"], "required": False}))

    failed_count = sum(1 for item in checks if item["status"] == "failed")
    warning_count = sum(1 for item in checks if item["status"] == "warning")
    status = "failed" if failed_count else "warning" if warning_count else "success"
    finished_at = datetime.now(timezone.utc)
    record = {
        "preflight_code": _code("zeta6-preflight", environment, release_version, started_at),
        "environment": environment,
        "status": status,
        "release_version": release_version,
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "check_count": len(checks),
        "passed_count": sum(1 for item in checks if item["status"] == "passed"),
        "warning_count": warning_count,
        "failed_count": failed_count,
        "dual_secret_enabled": bool(secrets["dual_secret_enabled"]),
        "audit_broken_count": audit_broken_count,
        "latest_recovery_drill_status": latest_drill_status,
        "checks": checks,
        "evidence": {
            "release_version": release_version,
            "require_dual_secret": require_dual_secret,
            "secret_material_persisted": False,
        },
        "error_message": None if not failed_count else "one or more release preflight checks failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
    }
    if not write_db:
        return normalize_rows([record])[0]
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_release_preflight (
                    preflight_code, environment, status, release_version,
                    requested_by, trigger_mode, check_count, passed_count,
                    warning_count, failed_count, dual_secret_enabled,
                    audit_broken_count, latest_recovery_drill_status,
                    checks, evidence, error_message, started_at, finished_at,
                    duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s::jsonb, %s::jsonb, %s, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    record["preflight_code"],
                    record["environment"],
                    record["status"],
                    record["release_version"],
                    record["requested_by"],
                    record["trigger_mode"],
                    record["check_count"],
                    record["passed_count"],
                    record["warning_count"],
                    record["failed_count"],
                    record["dual_secret_enabled"],
                    record["audit_broken_count"],
                    record["latest_recovery_drill_status"],
                    _json(record["checks"]),
                    _json(record["evidence"]),
                    record["error_message"],
                    record["started_at"],
                    record["finished_at"],
                    record["duration_ms"],
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def record_concurrency_test_result(
    postgres_dsn: str,
    *,
    environment: str = "local",
    target_scope: str,
    callback_count: int,
    success_count: int,
    locked_count: int = 0,
    blocked_count: int = 0,
    replay_rejected_count: int = 0,
    failed_count: int = 0,
    expected_success_count: int = 1,
    max_worker_threads: int = 1,
    evidence: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    status: str | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_environment(environment)
    if not target_scope:
        raise QDataValidationError("target_scope is required")
    for name, value in {
        "callback_count": callback_count,
        "success_count": success_count,
        "locked_count": locked_count,
        "blocked_count": blocked_count,
        "replay_rejected_count": replay_rejected_count,
        "failed_count": failed_count,
        "expected_success_count": expected_success_count,
        "max_worker_threads": max_worker_threads,
    }.items():
        if int(value) < 0:
            raise QDataValidationError(f"{name} must be non-negative")
    if max_worker_threads <= 0:
        raise QDataValidationError("max_worker_threads must be greater than 0")
    started_at = started_at or datetime.now(timezone.utc)
    finished_at = finished_at or datetime.now(timezone.utc)
    if status is None:
        status = "failed" if failed_count else "warning" if success_count < expected_success_count else "success"
    record = {
        "test_code": _code("zeta6-concurrency", environment, target_scope, started_at),
        "environment": environment,
        "status": status,
        "target_scope": target_scope,
        "callback_count": callback_count,
        "expected_success_count": expected_success_count,
        "success_count": success_count,
        "locked_count": locked_count,
        "blocked_count": blocked_count,
        "replay_rejected_count": replay_rejected_count,
        "failed_count": failed_count,
        "duration_ms": _duration_ms(started_at, finished_at),
        "max_worker_threads": max_worker_threads,
        "evidence": _safe_evidence(evidence or {}),
        "error_message": None if status != "failed" else "concurrency callback test failed",
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if not write_db:
        return normalize_rows([record])[0]
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_concurrency_test (
                    test_code, environment, status, target_scope,
                    callback_count, expected_success_count, success_count,
                    locked_count, blocked_count, replay_rejected_count,
                    failed_count, duration_ms, max_worker_threads,
                    evidence, error_message, started_at, finished_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s, %s, %s, now()
                )
                RETURNING *
                """,
                (
                    record["test_code"],
                    record["environment"],
                    record["status"],
                    record["target_scope"],
                    record["callback_count"],
                    record["expected_success_count"],
                    record["success_count"],
                    record["locked_count"],
                    record["blocked_count"],
                    record["replay_rejected_count"],
                    record["failed_count"],
                    record["duration_ms"],
                    record["max_worker_threads"],
                    _json(record["evidence"]),
                    record["error_message"],
                    record["started_at"],
                    record["finished_at"],
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def export_approval_audit_package(
    postgres_dsn: str,
    *,
    environment: str = "local",
    chain_scope: str | None = None,
    control_code: str | None = None,
    approval_code: str | None = None,
    batch_code: str | None = None,
    export_format: str = "json",
    exported_by: str = "zeta6",
    trigger_mode: str = "manual",
    limit: int = 1000,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_environment(environment)
    _validate_trigger_mode(trigger_mode)
    if export_format not in EXPORT_FORMATS:
        raise QDataValidationError("export_format must be one of: json, markdown, csv")
    if limit <= 0:
        raise QDataValidationError("limit must be greater than 0")
    resolved_scope = chain_scope or _chain_scope(control_code=control_code, approval_code=approval_code, batch_code=batch_code)
    generated_at = datetime.now(timezone.utc)
    audit_rows = _audit_rows(postgres_dsn, resolved_scope, limit)
    entity_rows = {
        "lock_events": _target_rows(postgres_dsn, "qmeta.source_route_incident_approval_lock_event", "started_at", control_code, approval_code, batch_code, limit),
        "state_transitions": _target_rows(postgres_dsn, "qmeta.source_route_incident_approval_state_transition", "observed_at", control_code, approval_code, batch_code, limit),
        "sla_actions": _target_rows(postgres_dsn, "qmeta.source_route_incident_approval_sla_action", "generated_at", control_code, approval_code, batch_code, limit),
        "recovery_drills": _recovery_rows(postgres_dsn, control_code, limit),
    }
    chain = verify_approval_audit_chain(_require_dsn(postgres_dsn), chain_scope=resolved_scope, limit=limit) if resolved_scope else {"status": "skipped", "checked_count": 0, "broken_count": 0, "broken_entries": []}
    package = {
        "package_schema": "zeta6.route_incident_approval_audit_export.v1",
        "generated_at": generated_at.isoformat(),
        "environment": environment,
        "selectors": {
            "chain_scope": resolved_scope,
            "control_code": control_code,
            "approval_code": approval_code,
            "batch_code": batch_code,
        },
        "audit_chain": chain,
        "audit_hashes": audit_rows,
        **entity_rows,
    }
    if export_format == "markdown":
        package["document"] = _render_markdown_package(package)
    elif export_format == "csv":
        package["document"] = _render_csv_package(package)
    package_hash = hashlib.sha256(_canonical_json(package).encode("utf-8")).hexdigest()
    broken_count = int(chain.get("broken_count") or 0)
    included_entity_count = len(audit_rows) + sum(len(rows) for rows in entity_rows.values())
    status = "failed" if broken_count else "warning" if not audit_rows else "success"
    record = {
        "export_code": _code("zeta6-audit-export", environment, package_hash, generated_at),
        "environment": environment,
        "status": status,
        "export_format": export_format,
        "chain_scope": resolved_scope,
        "control_code": control_code,
        "approval_code": approval_code,
        "batch_code": batch_code,
        "included_entity_count": included_entity_count,
        "broken_hash_count": broken_count,
        "package_hash": package_hash,
        "exported_by": exported_by,
        "trigger_mode": trigger_mode,
        "generated_at": generated_at,
        "evidence": {"audit_checked_count": chain.get("checked_count"), "secret_material_persisted": False},
        "export_payload": package,
        "error_message": None if status != "failed" else "audit hash chain has broken entries",
    }
    if not write_db:
        return normalize_rows([record])[0]
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_audit_export (
                    export_code, environment, status, export_format,
                    chain_scope, control_code, approval_code, batch_code,
                    included_entity_count, broken_hash_count, package_hash,
                    exported_by, trigger_mode, generated_at, evidence,
                    export_payload, error_message, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s::jsonb,
                    %s::jsonb, %s, now()
                )
                RETURNING *
                """,
                (
                    record["export_code"],
                    record["environment"],
                    record["status"],
                    record["export_format"],
                    record["chain_scope"],
                    record["control_code"],
                    record["approval_code"],
                    record["batch_code"],
                    record["included_entity_count"],
                    record["broken_hash_count"],
                    record["package_hash"],
                    record["exported_by"],
                    record["trigger_mode"],
                    record["generated_at"],
                    _json(record["evidence"]),
                    _json(record["export_payload"]),
                    record["error_message"],
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def list_route_incident_approval_release_preflights(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(params, [("preflight_code", "p.preflight_code"), ("environment", "p.environment"), ("status", "p.status"), ("release_version", "p.release_version"), ("requested_by", "p.requested_by"), ("trigger_mode", "p.trigger_mode")])
    where, values = _append_date_filter(where, values, params, "p.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_release_preflight p
        {where}
        ORDER BY p.started_at DESC, p.preflight_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_secret_rotations(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(params, [("rotation_code", "r.rotation_code"), ("environment", "r.environment"), ("rotation_phase", "r.rotation_phase"), ("status", "r.status"), ("active_secret_label", "r.active_secret_label"), ("verified_secret_label", "r.verified_secret_label"), ("nonce", "r.nonce")])
    where, values = _append_date_filter(where, values, params, "r.observed_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_secret_rotation r
        {where}
        ORDER BY r.observed_at DESC, r.rotation_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_concurrency_tests(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(params, [("test_code", "t.test_code"), ("environment", "t.environment"), ("status", "t.status"), ("target_scope", "t.target_scope")])
    where, values = _append_date_filter(where, values, params, "t.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_concurrency_test t
        {where}
        ORDER BY t.started_at DESC, t.test_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_audit_exports(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(params, [("export_code", "e.export_code"), ("environment", "e.environment"), ("status", "e.status"), ("export_format", "e.export_format"), ("chain_scope", "e.chain_scope"), ("control_code", "e.control_code"), ("approval_code", "e.approval_code"), ("batch_code", "e.batch_code"), ("package_hash", "e.package_hash"), ("exported_by", "e.exported_by"), ("trigger_mode", "e.trigger_mode")])
    where, values = _append_date_filter(where, values, params, "e.generated_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_audit_export e
        {where}
        ORDER BY e.generated_at DESC, e.export_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_zeta6_report(payload: dict[str, Any]) -> str:
    return (
        "zeta6_route_incident_approval_release "
        f"status={payload.get('status') or payload.get('signature_status')} "
        f"preflight={payload.get('preflight_code')} "
        f"rotation={payload.get('rotation_code')} "
        f"export={payload.get('export_code')} "
        f"package_hash={payload.get('package_hash')}"
    )


def format_zeta6_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"zeta6 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "release_preflights": ["preflight_code", "environment", "status", "release_version", "check_count", "passed_count", "warning_count", "failed_count", "dual_secret_enabled", "audit_broken_count", "latest_recovery_drill_status", "started_at"],
        "secret_rotations": ["rotation_code", "environment", "rotation_phase", "status", "active_secret_label", "verified_secret_label", "nonce", "signature_digest", "observed_at"],
        "concurrency_tests": ["test_code", "environment", "status", "target_scope", "callback_count", "expected_success_count", "success_count", "locked_count", "blocked_count", "replay_rejected_count", "failed_count", "duration_ms"],
        "audit_exports": ["export_code", "environment", "status", "export_format", "chain_scope", "control_code", "included_entity_count", "broken_hash_count", "package_hash", "generated_at"],
    }
    preferred = preferred_by_resource.get(resource, [])
    if preferred:
        return [key for key in preferred if key in row]
    return [key for key in row]


def _validate_environment(environment: str) -> None:
    if environment not in ENVIRONMENTS:
        raise QDataValidationError("environment must be one of: local, staging, production")


def _validate_trigger_mode(trigger_mode: str) -> None:
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, worker, smoke, release")


def _check(name: str, status: str, *, value: Any = None, result: Any = None, error_message: str | None = None) -> dict[str, Any]:
    return {
        "check": name,
        "status": status,
        "value": value,
        "result": result,
        "error_message": error_message,
    }


def _latest_recovery_drill(postgres_dsn: str) -> dict[str, Any] | None:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT *
        FROM qmeta.source_route_incident_approval_recovery_drill
        ORDER BY started_at DESC, drill_id DESC
        LIMIT 1
        """,
        [],
    )
    return rows[0] if rows else None


def _release_schedule_health(postgres_dsn: str) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT schedule_code, task_name, status, next_run_at, last_status
        FROM qmeta.worker_schedule
        WHERE schedule_code IN (
            'epsilon6_route_incident_approval_resilience_15m',
            'zeta6_route_incident_approval_release_30m'
        )
        ORDER BY schedule_code
        """,
        [],
    )
    return {
        "schedule_count": len(rows),
        "active_count": sum(1 for row in rows if row.get("status") == "active"),
        "schedules": rows,
    }


def _audit_rows(postgres_dsn: str, chain_scope: str | None, limit: int) -> list[dict[str, Any]]:
    where = "WHERE chain_scope = %s" if chain_scope else ""
    values = [chain_scope] if chain_scope else []
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_audit_hash
        {where}
        ORDER BY chain_scope, sequence_no
        LIMIT %s
        """,
        values + [limit],
    )


def _target_rows(postgres_dsn: str, table_name: str, time_column: str, control_code: str | None, approval_code: str | None, batch_code: str | None, limit: int) -> list[dict[str, Any]]:
    where, values = _selector_where(control_code, approval_code, batch_code)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM {table_name}
        {where}
        ORDER BY {time_column} DESC
        LIMIT %s
        """,
        values + [limit],
    )


def _recovery_rows(postgres_dsn: str, control_code: str | None, limit: int) -> list[dict[str, Any]]:
    where = "WHERE target_control_code = %s" if control_code else ""
    values = [control_code] if control_code else []
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_recovery_drill
        {where}
        ORDER BY started_at DESC, drill_id DESC
        LIMIT %s
        """,
        values + [limit],
    )


def _selector_where(control_code: str | None, approval_code: str | None, batch_code: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if control_code:
        clauses.append("control_code = %s")
        values.append(control_code)
    if approval_code:
        clauses.append("approval_code = %s")
        values.append(approval_code)
    if batch_code:
        clauses.append("batch_code = %s")
        values.append(batch_code)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", values)


def _chain_scope(*, control_code: str | None, approval_code: str | None, batch_code: str | None) -> str | None:
    if control_code:
        return f"route-approval:control_code:{control_code}"
    if approval_code:
        return f"route-approval:approval_code:{approval_code}"
    if batch_code:
        return f"route-approval:batch_code:{batch_code}"
    return None


def _render_markdown_package(package: dict[str, Any]) -> str:
    selectors = package.get("selectors") or {}
    lines = [
        "# Zeta-6 Route Approval Audit Export",
        "",
        f"- generated_at: {package.get('generated_at')}",
        f"- environment: {package.get('environment')}",
        f"- chain_scope: {selectors.get('chain_scope')}",
        f"- audit_checked_count: {(package.get('audit_chain') or {}).get('checked_count')}",
        f"- audit_broken_count: {(package.get('audit_chain') or {}).get('broken_count')}",
    ]
    return "\n".join(lines)


def _render_csv_package(package: dict[str, Any]) -> str:
    rows = package.get("audit_hashes") or []
    header = ["chain_scope", "sequence_no", "entity_type", "entity_code", "entry_hash", "verification_status"]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(row.get(key) or "").replace(",", " ") for key in header))
    return "\n".join(lines)


def _public_signature_attempt(label: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "secret_label": label,
        "signature_status": result.get("signature_status"),
        "verified": bool(result.get("verified")),
        "clock_skew_seconds": result.get("clock_skew_seconds"),
        "expected_digest_tail": str(result.get("expected_digest") or "")[-8:],
        "received_digest_tail": str(result.get("received_digest") or "")[-8:],
        "error_message": result.get("error_message"),
    }


def _safe_evidence(value: Any) -> Any:
    allowed_secret_labels = {"secret_label", "active_secret_label", "verified_secret_label", "accepted_secret_labels", "secret_material_persisted"}
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in ("secret", "token", "password", "authorization")) and key not in allowed_secret_labels:
                safe[key] = "<redacted>"
            else:
                safe[key] = _safe_evidence(item)
        return safe
    if isinstance(value, list):
        return [_safe_evidence(item) for item in value]
    return value


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


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Zeta-6 route incident approval release") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Zeta-6 route incident approval release")
    return postgres_dsn


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name) or []
    return values[0] if values else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _header_or_payload(headers: dict[str, str], payload: dict[str, Any], name: str) -> str | None:
    aliases = {
        "timestamp": ["x-qdata-timestamp", "x-wecom-timestamp", "x-wx-timestamp", "timestamp"],
        "nonce": ["x-qdata-nonce", "x-wecom-nonce", "x-wx-nonce", "nonce"],
        "signature": ["x-qdata-signature", "x-wecom-signature", "x-wx-signature", "msg_signature", "signature"],
    }[name]
    for alias in aliases:
        if headers.get(alias):
            return headers[alias]
    for alias in aliases:
        if payload.get(alias):
            return str(payload[alias])
    return None


def _normalize_signature(signature: str | None) -> str | None:
    if signature is None:
        return None
    text = str(signature).strip()
    if text.lower().startswith("sha256="):
        return text.split("=", 1)[1].strip().lower()
    return text.lower()


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(int((finished_at - started_at).total_seconds() * 1000), 0)


def _code(prefix: str, environment: str, key: str, observed_at: datetime) -> str:
    stamp = observed_at.strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{prefix}:{environment}:{key}:{stamp}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{stamp}-{digest}"
