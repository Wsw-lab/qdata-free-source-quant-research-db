from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from typing import Any, Iterable

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.delta2_wecom import run_delta2_wecom_live_validation
from qdata.exceptions import QDataValidationError
from qdata.iota3_free_source_fabric import DEFAULT_CANARY_SYMBOLS
from qdata.iota5_free_source_adapter_pool import run_free_source_adapter_pool
from qdata.omega_control import request_automation_approval


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
EXECUTION_TYPES = {"retry_canary", "manual_review", "observe", "suppress"}
FINAL_EXECUTION_STATUSES = {"recovered", "failed", "suppressed", "review_requested", "notified", "blocked", "skipped"}
RECENT_SUPPRESSION_HOURS = 24


def execute_free_source_recovery_actions(
    postgres_dsn: str,
    *,
    action_code: str | None = None,
    recovery_code: str | None = None,
    action_types: Iterable[str] | None = None,
    source_codes: Iterable[str] | None = None,
    dataset_codes: Iterable[str] | None = None,
    max_actions: int = 20,
    requested_by: str = "mu5",
    trigger_mode: str = "manual",
    environment: str = "local",
    dry_run: bool = False,
    execute_retry_canary: bool = True,
    request_manual_review: bool = True,
    notify_wecom: bool = True,
    allow_wecom_external: bool = False,
    start_date: str = "2024-01-04",
    end_date: str = "2024-01-04",
    canary_symbols: Iterable[str] | None = None,
    baostock_timeout_seconds: float = 3.0,
    tushare_token: str | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(max_actions=max_actions, trigger_mode=trigger_mode, requested_by=requested_by)
    start, end = date_range(start_date, end_date)
    normalized_types = _normalize_action_types(action_types, execute_retry_canary, request_manual_review, action_code)
    normalized_sources = _normalize_codes(source_codes)
    normalized_datasets = _normalize_codes(dataset_codes)
    symbols = _normalize_codes(canary_symbols) or list(DEFAULT_CANARY_SYMBOLS)
    started_at = datetime.now(timezone.utc)
    dsn = _require_dsn(postgres_dsn)
    candidates = _fetch_execution_candidates(
        dsn,
        action_code=action_code,
        recovery_code=recovery_code,
        action_types=normalized_types,
        source_codes=normalized_sources,
        dataset_codes=normalized_datasets,
        max_actions=max_actions,
    )
    executions: list[dict[str, Any]] = []
    if dry_run or not write_db:
        executions = [_preview_execution(action, requested_by=requested_by, trigger_mode=trigger_mode, environment=environment) for action in candidates]
        return _summary_payload(
            started_at,
            candidates,
            executions,
            requested_by=requested_by,
            trigger_mode=trigger_mode,
            environment=environment,
            dry_run=dry_run,
            write_db=False,
            filters={
                "action_code": action_code,
                "recovery_code": recovery_code,
                "action_types": normalized_types,
                "source_codes": normalized_sources or [],
                "dataset_codes": normalized_datasets or [],
            },
        )

    provider_kwargs = _provider_kwargs(baostock_timeout_seconds=baostock_timeout_seconds, tushare_token=tushare_token)
    for action in candidates:
        try:
            duplicate = _recent_final_execution(dsn, int(action["action_id"]), str(action["action_type"]))
            if duplicate:
                execution = _record_suppressed_execution(
                    dsn,
                    action,
                    duplicate,
                    requested_by=requested_by,
                    trigger_mode=trigger_mode,
                    environment=environment,
                )
            elif action["action_type"] == "retry_canary":
                execution = _execute_retry_canary(
                    dsn,
                    action,
                    requested_by=requested_by,
                    trigger_mode=trigger_mode,
                    environment=environment,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    canary_symbols=symbols,
                    execute_retry_canary=execute_retry_canary,
                    provider_kwargs_by_source=provider_kwargs,
                )
            elif action["action_type"] == "manual_review":
                execution = _execute_manual_review(
                    dsn,
                    action,
                    requested_by=requested_by,
                    trigger_mode=trigger_mode,
                    environment=environment,
                    request_manual_review=request_manual_review,
                    notify_wecom=notify_wecom,
                    allow_wecom_external=allow_wecom_external,
                )
            elif action["action_type"] in {"observe", "suppress"}:
                execution = _record_suppressed_execution(
                    dsn,
                    action,
                    None,
                    requested_by=requested_by,
                    trigger_mode=trigger_mode,
                    environment=environment,
                    reason=f"{action['action_type']}_does_not_require_execution",
                )
            else:
                raise QDataValidationError(f"unsupported recovery action_type: {action['action_type']}")
        except Exception as exc:
            execution = _record_failed_execution(
                dsn,
                action,
                requested_by=requested_by,
                trigger_mode=trigger_mode,
                environment=environment,
                error_message=str(exc),
            )
        executions.append(execution)

    return _summary_payload(
        started_at,
        candidates,
        executions,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        dry_run=False,
        write_db=True,
        filters={
            "action_code": action_code,
            "recovery_code": recovery_code,
            "action_types": normalized_types,
            "source_codes": normalized_sources or [],
            "dataset_codes": normalized_datasets or [],
        },
    )


def classify_retry_execution_result(row: dict[str, Any]) -> str:
    if str(row.get("iota5_pool_status") or "") == "ok":
        return "recovered"
    return "failed"


def build_manual_review_message(action: dict[str, Any]) -> str:
    source_code = action.get("source_code") or "unknown_source"
    dataset_code = action.get("dataset_code") or "unknown_dataset"
    reason_code = action.get("reason_code") or "manual_review_required"
    severity = action.get("severity") or "high"
    score = action.get("reliability_score")
    recovery_actions = action.get("recovery_actions") or []
    lines = [
        f"免费源人工复核：{source_code}/{dataset_code}",
        f"- action_code: {action.get('action_code')}",
        f"- severity: {severity}",
        f"- reason_code: {reason_code}",
        f"- reliability_score: {score}",
        "- policy: free sources are research/validation/backup evidence only before commercial clearance.",
    ]
    if recovery_actions:
        lines.append("- recovery_actions:")
        lines.extend(f"  - {item}" for item in recovery_actions[:6])
    return "\n".join(lines)


def list_free_source_recovery_executions(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("execution_code", "fsre.execution_code"),
            ("action_code", "fsra.action_code"),
            ("recovery_code", "fsrr.recovery_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("execution_type", "fsre.execution_type"),
            ("status", "fsre.status"),
            ("requested_by", "fsre.requested_by"),
            ("trigger_mode", "fsre.trigger_mode"),
            ("environment", "fsre.environment"),
            ("fabric_code", "fsre.fabric_code"),
            ("approval_code", "fsre.approval_code"),
            ("wecom_receipt_code", "fsre.wecom_receipt_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "fsre.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsre.execution_id, fsre.execution_code, fsre.execution_type,
            fsre.status, fsre.requested_by, fsre.trigger_mode,
            fsre.environment, fsre.dry_run, fsre.action_id,
            fsra.action_code, fsrr.recovery_code, ss.source_code,
            dc.dataset_code, fsra.reason_code, fsra.severity,
            fsre.fabric_id, fsre.fabric_code, fsre.iota5_pool_status,
            ar.run_code AS automation_run_code,
            aa.action_code AS automation_action_code,
            fsre.approval_code, fsre.wecom_receipt_code,
            fsre.result_summary, fsre.evidence, fsre.error_message,
            fsre.started_at, fsre.finished_at, fsre.duration_ms,
            fsre.created_at, fsre.updated_at
        FROM qmeta.free_source_recovery_execution fsre
        JOIN qmeta.free_source_recovery_action fsra ON fsra.action_id = fsre.action_id
        LEFT JOIN qmeta.free_source_recovery_run fsrr ON fsrr.recovery_run_id = fsre.recovery_run_id
        LEFT JOIN qmeta.source_system ss ON ss.source_id = fsre.source_id
        LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsre.dataset_id
        LEFT JOIN qmeta.automation_run ar ON ar.automation_run_id = fsre.automation_run_id
        LEFT JOIN qmeta.automation_action aa ON aa.automation_action_id = fsre.automation_action_id
        {where}
        ORDER BY fsre.started_at DESC, fsre.execution_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_mu5_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"mu5 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _execute_retry_canary(
    postgres_dsn: str,
    action: dict[str, Any],
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    start_date: str,
    end_date: str,
    canary_symbols: list[str],
    execute_retry_canary: bool,
    provider_kwargs_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    if not execute_retry_canary:
        return _insert_execution_and_update_action(
            postgres_dsn,
            action,
            execution_code=_execution_code(action["action_code"], "retry_canary", "suppressed"),
            execution_type="retry_canary",
            status="suppressed",
            requested_by=requested_by,
            trigger_mode=trigger_mode,
            environment=environment,
            result_summary={"status": "suppressed", "reason": "retry_canary_disabled"},
            evidence={"retry_canary_enabled": False, "external_side_effect": False},
            error_message=None,
            started_at=started_at,
        )
    row = run_free_source_adapter_pool(
        postgres_dsn,
        source_codes=[action["source_code"]],
        dataset_codes=[action["dataset_code"]],
        start_date=start_date,
        end_date=end_date,
        canary_symbols=canary_symbols,
        requested_by=requested_by,
        trigger_mode=_iota_trigger_mode(trigger_mode),
        environment=environment,
        min_source_count=1,
        min_external_successful=1,
        min_coverage_rate=0.5,
        max_conflict_rate_bps=100000.0,
        require_commercial_clearance=False,
        provider_kwargs_by_source=provider_kwargs_by_source,
    )
    status = classify_retry_execution_result(row)
    summary = {
        "status": status,
        "fabric_status": row.get("status"),
        "fabric_code": row.get("fabric_code"),
        "iota5_pool_status": row.get("iota5_pool_status"),
        "coverage_rate": row.get("coverage_rate"),
        "conflict_rate_bps": row.get("conflict_rate_bps"),
        "recommendation": row.get("recommendation"),
        "risk_level": row.get("risk_level"),
        "commercial_clearance": (row.get("iota5_evaluation") or {}).get("commercial_clearance"),
    }
    error_message = None if status == "recovered" else _retry_error_message(row)
    return _insert_execution_and_update_action(
        postgres_dsn,
        action,
        execution_code=_execution_code(action["action_code"], "retry_canary", status),
        execution_type="retry_canary",
        status=status,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        fabric_id=row.get("fabric_id"),
        fabric_code=row.get("fabric_code"),
        iota5_pool_status=row.get("iota5_pool_status"),
        result_summary=summary,
        evidence={
            "retry_window": {"start_date": start_date, "end_date": end_date},
            "canary_symbols": canary_symbols,
            "provider_kwargs": _safe_provider_kwargs(provider_kwargs_by_source),
            "iota5_evaluation": row.get("iota5_evaluation") or {},
            "external_side_effect": True,
            "policy": {"free_source_never_promotes_to_commercial_primary": True},
        },
        error_message=error_message,
        started_at=started_at,
    )


def _execute_manual_review(
    postgres_dsn: str,
    action: dict[str, Any],
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    request_manual_review: bool,
    notify_wecom: bool,
    allow_wecom_external: bool,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    if not request_manual_review:
        return _insert_execution_and_update_action(
            postgres_dsn,
            action,
            execution_code=_execution_code(action["action_code"], "manual_review", "suppressed"),
            execution_type="manual_review",
            status="suppressed",
            requested_by=requested_by,
            trigger_mode=trigger_mode,
            environment=environment,
            result_summary={"status": "suppressed", "reason": "manual_review_disabled"},
            evidence={"manual_review_enabled": False, "external_side_effect": False},
            error_message=None,
            started_at=started_at,
        )

    automation = _upsert_manual_review_automation_action(postgres_dsn, action, requested_by=requested_by, trigger_mode=trigger_mode, environment=environment)
    approval = request_automation_approval(
        postgres_dsn,
        action_code=automation["automation_action_code"],
        requested_by=requested_by,
        reason=automation["reason"],
    )
    receipt: dict[str, Any] | None = None
    receipt_error: str | None = None
    if notify_wecom:
        try:
            receipt = run_delta2_wecom_live_validation(
                postgres_dsn,
                requested_by=requested_by,
                title="QData Mu-5 免费源人工复核",
                message=build_manual_review_message(action),
                action_code=automation["automation_action_code"],
                trigger_mode=_automation_trigger_mode(trigger_mode),
                message_type="markdown",
                allow_external=allow_wecom_external,
                force=True,
            )
        except Exception as exc:
            receipt_error = str(exc)
    status = "review_requested"
    result_summary = {
        "status": status,
        "automation_run_code": automation.get("automation_run_code"),
        "automation_action_code": automation.get("automation_action_code"),
        "approval_code": approval.get("approval_code"),
        "approval_status": approval.get("status"),
        "wecom_receipt_code": receipt.get("receipt_code") if receipt else None,
        "wecom_status": receipt.get("status") if receipt else "skipped" if not notify_wecom else "failed",
    }
    return _insert_execution_and_update_action(
        postgres_dsn,
        action,
        execution_code=_execution_code(action["action_code"], "manual_review", status),
        execution_type="manual_review",
        status=status,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        automation_run_id=automation.get("automation_run_id"),
        automation_action_id=automation.get("automation_action_id"),
        approval_id=approval.get("approval_id"),
        approval_code=approval.get("approval_code"),
        wecom_receipt_id=receipt.get("receipt_id") if receipt else None,
        wecom_receipt_code=receipt.get("receipt_code") if receipt else None,
        result_summary=result_summary,
        evidence={
            "manual_review_message": build_manual_review_message(action),
            "approval": {"approval_code": approval.get("approval_code"), "status": approval.get("status")},
            "wecom": {
                "notify_wecom": notify_wecom,
                "allow_external": allow_wecom_external,
                "receipt_status": receipt.get("status") if receipt else None,
                "receipt_error": receipt_error,
                "external_side_effect": bool(receipt and receipt.get("sent_at")),
            },
            "policy": {"free_source_never_promotes_to_commercial_primary": True},
        },
        error_message=receipt_error,
        started_at=started_at,
    )


def _upsert_manual_review_automation_action(
    postgres_dsn: str,
    action: dict[str, Any],
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
) -> dict[str, Any]:
    run_code = _automation_run_code(action["action_code"])
    automation_action_code = _automation_action_code(action["action_code"])
    reason = f"Review free source recovery action {action['action_code']} before any production fallback decision."
    current_date = datetime.now(timezone.utc).date()
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.automation_run (
                    run_code, run_date, environment, trigger_mode,
                    execution_mode, status, source_filter,
                    action_count, executable_count, approval_required_count,
                    details, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    'execute', 'warning', %s::jsonb,
                    1, 0, 1,
                    %s::jsonb, now()
                )
                ON CONFLICT (run_code) DO UPDATE SET
                    trigger_mode = EXCLUDED.trigger_mode,
                    status = 'warning',
                    action_count = 1,
                    approval_required_count = 1,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING automation_run_id, run_code
                """,
                (
                    run_code,
                    current_date,
                    environment,
                    _automation_trigger_mode(trigger_mode),
                    _json({"free_source_action_code": action["action_code"], "requested_by": requested_by}),
                    _json({"source": "mu5", "purpose": "free_source_manual_review"}),
                ),
            )
            run = dict(cursor.fetchone())
            cursor.execute(
                """
                INSERT INTO qmeta.automation_action (
                    action_code, automation_run_id, source_type, source_id,
                    source_code, dataset_id, action_type, safety_level,
                    execution_mode, status, approval_required, owner, reason,
                    idempotency_key, planned_effect, rollback_hint, details,
                    updated_at
                ) VALUES (
                    %s, %s, 'manual', %s,
                    %s, %s, 'review_access_policy', %s,
                    'execute', 'approval_required', TRUE, 'platform-ops', %s,
                    %s, %s::jsonb, %s, %s::jsonb,
                    now()
                )
                ON CONFLICT (action_code) DO UPDATE SET
                    status = 'approval_required',
                    approval_required = TRUE,
                    reason = EXCLUDED.reason,
                    planned_effect = EXCLUDED.planned_effect,
                    rollback_hint = EXCLUDED.rollback_hint,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING automation_action_id, action_code
                """,
                (
                    automation_action_code,
                    run["automation_run_id"],
                    action["action_id"],
                    action.get("source_code") or action["action_code"],
                    action.get("dataset_id"),
                    "critical" if action.get("severity") == "critical" else "high",
                    reason,
                    f"mu5:{action['action_code']}",
                    _json(
                        {
                            "operation": "manual_review_free_source",
                            "free_source_action_code": action["action_code"],
                            "source_code": action.get("source_code"),
                            "dataset_code": action.get("dataset_code"),
                            "reason_code": action.get("reason_code"),
                            "recommended_role": action.get("recommended_role"),
                        }
                    ),
                    "Resolve or dismiss the free source recovery action after manual review.",
                    _json({"source": "mu5", "free_source_recovery_action_id": action["action_id"]}),
                ),
            )
            automation_action = dict(cursor.fetchone())
            return {
                "automation_run_id": run["automation_run_id"],
                "automation_run_code": run["run_code"],
                "automation_action_id": automation_action["automation_action_id"],
                "automation_action_code": automation_action["action_code"],
                "reason": reason,
            }


def _insert_execution_and_update_action(
    postgres_dsn: str,
    action: dict[str, Any],
    *,
    execution_code: str,
    execution_type: str,
    status: str,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    fabric_id: int | None = None,
    fabric_code: str | None = None,
    iota5_pool_status: str | None = None,
    automation_run_id: int | None = None,
    automation_action_id: int | None = None,
    approval_id: int | None = None,
    approval_code: str | None = None,
    wecom_receipt_id: int | None = None,
    wecom_receipt_code: str | None = None,
    result_summary: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    started = started_at or datetime.now(timezone.utc)
    finished = datetime.now(timezone.utc)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.free_source_recovery_execution (
                    execution_code, action_id, recovery_run_id,
                    execution_type, trigger_mode, status, requested_by,
                    environment, dry_run, source_id, dataset_id,
                    fabric_id, fabric_code, iota5_pool_status,
                    automation_run_id, automation_action_id, approval_id,
                    approval_code, wecom_receipt_id, wecom_receipt_code,
                    result_summary, evidence, error_message,
                    started_at, finished_at, duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, FALSE, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s, now()
                )
                ON CONFLICT (execution_code) DO UPDATE SET
                    status = EXCLUDED.status,
                    fabric_id = EXCLUDED.fabric_id,
                    fabric_code = EXCLUDED.fabric_code,
                    iota5_pool_status = EXCLUDED.iota5_pool_status,
                    automation_run_id = EXCLUDED.automation_run_id,
                    automation_action_id = EXCLUDED.automation_action_id,
                    approval_id = EXCLUDED.approval_id,
                    approval_code = EXCLUDED.approval_code,
                    wecom_receipt_id = EXCLUDED.wecom_receipt_id,
                    wecom_receipt_code = EXCLUDED.wecom_receipt_code,
                    result_summary = EXCLUDED.result_summary,
                    evidence = EXCLUDED.evidence,
                    error_message = EXCLUDED.error_message,
                    finished_at = EXCLUDED.finished_at,
                    duration_ms = EXCLUDED.duration_ms,
                    updated_at = now()
                RETURNING *
                """,
                (
                    execution_code,
                    action["action_id"],
                    action.get("recovery_run_id"),
                    execution_type,
                    trigger_mode,
                    status,
                    requested_by,
                    environment,
                    action.get("source_id"),
                    action.get("dataset_id"),
                    fabric_id,
                    fabric_code,
                    iota5_pool_status,
                    automation_run_id,
                    automation_action_id,
                    approval_id,
                    approval_code,
                    wecom_receipt_id,
                    wecom_receipt_code,
                    _json(result_summary or {}),
                    _json(evidence or {}),
                    error_message,
                    started,
                    finished,
                    _duration_ms(started, finished),
                ),
            )
            execution = dict(cursor.fetchone())
            cursor.execute(
                """
                UPDATE qmeta.free_source_recovery_action
                SET status = %s,
                    error_message = %s,
                    evidence = jsonb_strip_nulls(evidence || %s::jsonb),
                    updated_at = now()
                WHERE action_id = %s
                """,
                (
                    _action_writeback_status(status),
                    error_message,
                    _json({"mu5_execution_code": execution_code, "mu5_execution_status": status}),
                    action["action_id"],
                ),
            )
            execution.update(
                {
                    "action_code": action.get("action_code"),
                    "recovery_code": action.get("recovery_code"),
                    "source_code": action.get("source_code"),
                    "dataset_code": action.get("dataset_code"),
                    "reason_code": action.get("reason_code"),
                    "severity": action.get("severity"),
                }
            )
            return normalize_rows([execution])[0]


def _record_suppressed_execution(
    postgres_dsn: str,
    action: dict[str, Any],
    duplicate: dict[str, Any] | None,
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    reason: str = "recent_final_execution_exists",
) -> dict[str, Any]:
    return _insert_execution_and_update_action(
        postgres_dsn,
        action,
        execution_code=_execution_code(action["action_code"], str(action["action_type"]), "suppressed"),
        execution_type=str(action["action_type"]),
        status="suppressed",
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        result_summary={"status": "suppressed", "reason": reason},
        evidence={
            "reason": reason,
            "duplicate_execution_code": duplicate.get("execution_code") if duplicate else None,
            "external_side_effect": False,
        },
        error_message=None,
    )


def _record_failed_execution(
    postgres_dsn: str,
    action: dict[str, Any],
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    error_message: str,
) -> dict[str, Any]:
    return _insert_execution_and_update_action(
        postgres_dsn,
        action,
        execution_code=_execution_code(action["action_code"], str(action["action_type"]), "failed"),
        execution_type=str(action["action_type"]),
        status="failed",
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        result_summary={"status": "failed"},
        evidence={"external_side_effect": False},
        error_message=error_message,
    )


def _fetch_execution_candidates(
    postgres_dsn: str,
    *,
    action_code: str | None,
    recovery_code: str | None,
    action_types: list[str],
    source_codes: list[str] | None,
    dataset_codes: list[str] | None,
    max_actions: int,
) -> list[dict[str, Any]]:
    where = ["fsra.action_type = ANY(%s::text[])"]
    values: list[Any] = [action_types]
    if action_code:
        where.append("fsra.action_code = %s")
        values.append(action_code)
    else:
        where.append(
            """
            (
                (fsra.action_type = 'retry_canary' AND fsra.status IN ('planned', 'scheduled', 'alerted', 'failed') AND (fsra.next_retry_at IS NULL OR fsra.next_retry_at <= now()))
                OR (fsra.action_type = 'manual_review' AND fsra.status IN ('planned', 'review_required', 'alerted', 'blocked'))
                OR (fsra.action_type IN ('observe', 'suppress') AND fsra.status IN ('planned', 'scheduled', 'alerted', 'review_required'))
            )
            """
        )
    if recovery_code:
        where.append("fsrr.recovery_code = %s")
        values.append(recovery_code)
    if source_codes:
        where.append("ss.source_code = ANY(%s::text[])")
        values.append(source_codes)
    if dataset_codes:
        where.append("dc.dataset_code = ANY(%s::text[])")
        values.append(dataset_codes)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsra.action_id, fsra.action_code, fsra.recovery_run_id,
            fsrr.recovery_code, fsra.snapshot_id, fsrs.snapshot_code,
            fsra.source_id, ss.source_code, fsra.dataset_id, dc.dataset_code,
            fsra.action_type, fsra.status, fsra.severity, fsra.reason_code,
            fsra.recommended_role, fsra.reliability_score,
            fsra.retry_after_minutes, fsra.next_retry_at,
            fsra.degradation_reasons, fsra.recovery_actions,
            fsra.evidence, fsra.error_message, fsra.created_at,
            fsra.updated_at
        FROM qmeta.free_source_recovery_action fsra
        JOIN qmeta.free_source_recovery_run fsrr ON fsrr.recovery_run_id = fsra.recovery_run_id
        LEFT JOIN qmeta.free_source_reliability_snapshot fsrs ON fsrs.snapshot_id = fsra.snapshot_id
        LEFT JOIN qmeta.source_system ss ON ss.source_id = fsra.source_id
        LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsra.dataset_id
        WHERE {' AND '.join(where)}
        ORDER BY
            CASE fsra.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
            CASE fsra.action_type WHEN 'manual_review' THEN 0 WHEN 'retry_canary' THEN 1 ELSE 2 END,
            fsra.created_at ASC,
            fsra.action_id ASC
        LIMIT %s
        """,
        values + [max_actions],
    )


def _recent_final_execution(postgres_dsn: str, action_id: int, execution_type: str) -> dict[str, Any] | None:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT execution_id, execution_code, execution_type, status, started_at
        FROM qmeta.free_source_recovery_execution
        WHERE action_id = %s
          AND execution_type = %s
          AND status = ANY(%s::text[])
          AND started_at >= now() - (%s * INTERVAL '1 hour')
        ORDER BY started_at DESC, execution_id DESC
        LIMIT 1
        """,
        [action_id, execution_type, sorted(FINAL_EXECUTION_STATUSES - {"suppressed"}), RECENT_SUPPRESSION_HOURS],
    )
    return rows[0] if rows else None


def _preview_execution(action: dict[str, Any], *, requested_by: str, trigger_mode: str, environment: str) -> dict[str, Any]:
    return normalize_rows(
        [
            {
                "execution_id": None,
                "execution_code": _execution_code(action["action_code"], str(action["action_type"]), "preview"),
                "execution_type": action["action_type"],
                "status": "skipped",
                "requested_by": requested_by,
                "trigger_mode": trigger_mode,
                "environment": environment,
                "dry_run": True,
                "action_id": action.get("action_id"),
                "action_code": action.get("action_code"),
                "recovery_code": action.get("recovery_code"),
                "source_code": action.get("source_code"),
                "dataset_code": action.get("dataset_code"),
                "reason_code": action.get("reason_code"),
                "severity": action.get("severity"),
                "result_summary": {"status": "skipped", "reason": "dry_run"},
                "evidence": {"external_side_effect": False},
                "error_message": None,
            }
        ]
    )[0]


def _summary_payload(
    started_at: datetime,
    candidates: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    dry_run: bool,
    write_db: bool,
    filters: dict[str, Any],
) -> dict[str, Any]:
    status = _summary_status(executions, dry_run=dry_run)
    return {
        "status": status,
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "dry_run": dry_run,
        "write_db": write_db,
        "candidate_count": len(candidates),
        "execution_count": len(executions),
        "recovered_count": _count_status(executions, "recovered"),
        "failed_count": _count_status(executions, "failed"),
        "suppressed_count": _count_status(executions, "suppressed"),
        "review_requested_count": _count_status(executions, "review_requested"),
        "notified_count": _count_status(executions, "notified"),
        "blocked_count": _count_status(executions, "blocked"),
        "skipped_count": _count_status(executions, "skipped"),
        "duration_ms": _duration_ms(started_at),
        "filters": filters,
        "executions": normalize_rows(executions),
    }


def _summary_status(executions: list[dict[str, Any]], *, dry_run: bool) -> str:
    if not executions:
        return "skipped"
    if dry_run:
        return "warning"
    if any(item.get("status") == "failed" for item in executions):
        return "failed"
    if any(item.get("status") in {"blocked", "review_requested", "suppressed", "skipped"} for item in executions):
        return "warning"
    return "success"


def _action_writeback_status(execution_status: str) -> str:
    if execution_status in {"recovered", "failed", "suppressed", "review_requested", "notified", "blocked", "skipped"}:
        return execution_status
    return "failed"


def _count_status(rows: list[dict[str, Any]], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


def _validate_inputs(*, max_actions: int, trigger_mode: str, requested_by: str) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, once, scheduled, smoke")
    if max_actions < 1 or max_actions > 500:
        raise QDataValidationError("max_actions must be between 1 and 500")


def _normalize_action_types(
    values: Iterable[str] | None,
    execute_retry_canary: bool,
    request_manual_review: bool,
    action_code: str | None,
) -> list[str]:
    if values:
        result = _normalize_codes(values) or []
    elif action_code:
        result = sorted(EXECUTION_TYPES)
    else:
        result = []
        if execute_retry_canary:
            result.append("retry_canary")
        if request_manual_review:
            result.append("manual_review")
    if not result:
        raise QDataValidationError("at least one Mu-5 execution type must be enabled")
    unknown = [item for item in result if item not in EXECUTION_TYPES]
    if unknown:
        raise QDataValidationError(f"unknown execution type: {unknown[0]}")
    return result


def _normalize_codes(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    result = list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
    return result or None


def _provider_kwargs(*, baostock_timeout_seconds: float, tushare_token: str | None) -> dict[str, dict[str, Any]]:
    kwargs: dict[str, dict[str, Any]] = {"baostock": {"timeout_seconds": max(1.0, float(baostock_timeout_seconds))}}
    token = tushare_token or os.getenv("QDATA_TUSHARE_TOKEN")
    if token:
        kwargs["tushare_free"] = {"token": token}
    return kwargs


def _safe_provider_kwargs(provider_kwargs_by_source: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    safe: dict[str, dict[str, Any]] = {}
    for source, values in provider_kwargs_by_source.items():
        safe[source] = {key: ("***" if "token" in key.lower() else value) for key, value in values.items()}
        if source == "tushare_free":
            safe[source]["token_present"] = bool(values.get("token"))
            safe[source].pop("token", None)
    return safe


def _retry_error_message(row: dict[str, Any]) -> str:
    evaluation = row.get("iota5_evaluation") or {}
    issues = list(evaluation.get("blocking_issues") or []) + list(evaluation.get("degraded_reasons") or [])
    if issues:
        return ",".join(str(item) for item in issues[:10])
    return str(row.get("error_message") or row.get("status") or "retry_canary_not_recovered")


def _iota_trigger_mode(trigger_mode: str) -> str:
    return "manual" if trigger_mode == "once" else trigger_mode


def _automation_trigger_mode(trigger_mode: str) -> str:
    return "manual" if trigger_mode == "once" else trigger_mode


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


def _report_keys(row: dict[str, Any]) -> list[str]:
    preferred = [
        "execution_code",
        "action_code",
        "recovery_code",
        "source_code",
        "dataset_code",
        "execution_type",
        "status",
        "iota5_pool_status",
        "fabric_code",
        "approval_code",
        "wecom_receipt_code",
        "error_message",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _execution_code(action_code: str, execution_type: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{action_code}:{execution_type}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"mu5-{execution_type}-{status}-{digest}"[:180]


def _automation_run_code(action_code: str) -> str:
    digest = hashlib.sha1(action_code.encode("utf-8")).hexdigest()[:16]
    return f"mu5-free-source-review-run-{digest}"


def _automation_action_code(action_code: str) -> str:
    digest = hashlib.sha1(action_code.encode("utf-8")).hexdigest()[:16]
    return f"mu5-free-source-review-action-{digest}"


def _duration_ms(start: datetime, end: datetime | None = None) -> int:
    finished = end or datetime.now(timezone.utc)
    return int((finished - start).total_seconds() * 1000)


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


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
        raise QDataValidationError("psycopg is required for Mu-5 free source recovery execution") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    return _connect(_require_dsn(postgres_dsn))


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Mu-5 free source recovery execution")
    return postgres_dsn
