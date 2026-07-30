from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


EXECUTION_MODES = {"dry_run", "execute"}
TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
HIGH_RISK_ACTIONS = {"repair_data_quality", "degrade_vendor", "pause_product", "freeze_budget", "rotate_token"}
LOW_TOUCH_ACTIONS = {"escalate_commercial", "review_access_policy", "review_budget", "contact_owner", "notify_owner", "monitor"}
PHI_ACTIONABLE_STATUSES = {"watch", "review", "escalate", "block", "hold"}
ROUTE_SOURCE_TYPES = {"route_circuit_breaker", "route_recovery_probe", "route_health_snapshot"}


def run_psi_automation(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    environment: str = "local",
    trigger_mode: str = "manual",
    execution_mode: str = "dry_run",
    approve: bool = False,
    approved_by: str | None = None,
    source_run_code: str | None = None,
    tenant_code: str | None = None,
    project_code: str | None = None,
    include_phi: bool = True,
    include_chi: bool = True,
    include_route: bool = False,
    route_lookback_hours: int = 24,
    route_max_actions: int = 50,
    route_owner: str = "platform-ops",
    route_include_recovered: bool = True,
    run_code: str | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    if execution_mode not in EXECUTION_MODES:
        raise QDataValidationError("execution_mode must be one of: dry_run, execute")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    if route_lookback_hours <= 0:
        raise QDataValidationError("route_lookback_hours must be greater than 0")
    if route_max_actions <= 0 or route_max_actions > 500:
        raise QDataValidationError("route_max_actions must be between 1 and 500")
    current_date = _coerce_date(as_of_date)
    code = run_code or _run_code(environment, current_date, execution_mode)
    started_at = datetime.now(timezone.utc)
    source_filter = {
        "as_of_date": current_date.isoformat(),
        "environment": environment,
        "source_run_code": source_run_code,
        "tenant_code": tenant_code,
        "project_code": project_code,
        "include_phi": include_phi,
        "include_chi": include_chi,
        "include_route": include_route,
        "route_lookback_hours": route_lookback_hours,
        "route_max_actions": route_max_actions,
        "route_include_recovered": route_include_recovered,
    }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            phi_decisions = _fetch_phi_decisions(cursor, current_date, environment, source_run_code) if include_phi else []
            governance_actions = _fetch_chi_actions(cursor, tenant_code, project_code) if include_chi else []
            route_signals = (
                _fetch_route_signals(
                    cursor,
                    lookback_hours=route_lookback_hours,
                    limit=route_max_actions,
                    include_recovered=route_include_recovered,
                )
                if include_route
                else []
            )
            planned = build_automation_actions(
                phi_decisions,
                governance_actions,
                route_signals,
                run_code=code,
                execution_mode=execution_mode,
                route_owner=route_owner,
            )
            run_id: int | None = None
            if write_db:
                run_id = _upsert_run(
                    cursor,
                    run_code=code,
                    run_date=current_date,
                    environment=environment,
                    trigger_mode=trigger_mode,
                    execution_mode=execution_mode,
                    source_filter=source_filter,
                )
            actions: list[dict[str, Any]] = []
            for item in planned:
                result = _evaluate_execution(
                    cursor,
                    item,
                    run_id=run_id,
                    execution_mode=execution_mode,
                    approve=approve,
                    approved_by=approved_by,
                )
                if write_db and run_id is not None:
                    result["automation_run_id"] = run_id
                    result["automation_action_id"] = _upsert_action(cursor, result)
                    if result.get("source_type") in ROUTE_SOURCE_TYPES:
                        _upsert_route_incident_action(cursor, result)
                actions.append(result)
            summary = _summarize_actions(actions, execution_mode)
            finished_at = datetime.now(timezone.utc)
            summary["duration_ms"] = _duration_ms(started_at, finished_at)
            if write_db and run_id is not None:
                _finish_run(cursor, run_id, summary, actions)
    payload = {
        "run_code": code,
        "run_date": current_date.isoformat(),
        "environment": environment,
        "trigger_mode": trigger_mode,
        "execution_mode": execution_mode,
        "status": summary["status"],
        "action_count": summary["action_count"],
        "executable_count": summary["executable_count"],
        "executed_count": summary["executed_count"],
        "approval_required_count": summary["approval_required_count"],
        "skipped_count": summary["skipped_count"],
        "failed_count": summary["failed_count"],
        "duration_ms": summary["duration_ms"],
        "source_filter": source_filter,
        "actions": normalize_rows(actions),
    }
    return payload


def build_automation_actions(
    phi_decisions: list[dict[str, Any]],
    governance_actions: list[dict[str, Any]],
    route_signals: list[dict[str, Any]] | None = None,
    *,
    run_code: str,
    execution_mode: str = "dry_run",
    route_owner: str = "platform-ops",
) -> list[dict[str, Any]]:
    if execution_mode not in EXECUTION_MODES:
        raise QDataValidationError("execution_mode must be one of: dry_run, execute")
    planned: list[dict[str, Any]] = []
    for row in phi_decisions:
        action = _map_phi_decision(row, run_code, execution_mode)
        if action:
            planned.append(action)
    for row in governance_actions:
        action = _map_chi_action(row, run_code, execution_mode)
        if action:
            planned.append(action)
    for row in route_signals or []:
        action = _map_route_signal(row, run_code, execution_mode, route_owner)
        if action:
            planned.append(action)
    planned.sort(key=lambda item: (_safety_rank(item["safety_level"]), item["source_type"], item["source_code"]), reverse=True)
    return planned


def list_automation_runs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "ar.run_code"),
            ("environment", "ar.environment"),
            ("trigger_mode", "ar.trigger_mode"),
            ("execution_mode", "ar.execution_mode"),
            ("status", "ar.status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "ar.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ar.automation_run_id, ar.run_code, ar.run_date, ar.environment,
            ar.trigger_mode, ar.execution_mode, ar.status, ar.action_count,
            ar.executable_count, ar.executed_count, ar.approval_required_count,
            ar.skipped_count, ar.failed_count, ar.started_at, ar.finished_at,
            ar.duration_ms, ar.source_filter, ar.details, ar.error_message,
            ar.created_at, ar.updated_at
        FROM qmeta.automation_run ar
        {where}
        ORDER BY ar.started_at DESC, ar.automation_run_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_automation_actions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "ar.run_code"),
            ("action_code", "aa.action_code"),
            ("source_type", "aa.source_type"),
            ("source_code", "aa.source_code"),
            ("action_type", "aa.action_type"),
            ("safety_level", "aa.safety_level"),
            ("execution_mode", "aa.execution_mode"),
            ("status", "aa.status"),
            ("owner", "aa.owner"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("principal_code", "pr.principal_code"),
            ("dataset_code", "dc.dataset_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "aa.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            aa.automation_action_id, aa.action_code, ar.run_code,
            aa.source_type, aa.source_code, t.tenant_code, p.project_code,
            pr.principal_code, tok.token_name, dc.dataset_code,
            aa.action_type, aa.safety_level, aa.execution_mode, aa.status,
            aa.approval_required, aa.approved_by, aa.approved_at, aa.owner,
            aa.reason, aa.idempotency_key, aa.planned_effect,
            aa.executed_effect, aa.rollback_hint, aa.error_message,
            aa.executed_at, aa.details, aa.created_at, aa.updated_at
        FROM qmeta.automation_action aa
        JOIN qmeta.automation_run ar ON ar.automation_run_id = aa.automation_run_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = aa.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = aa.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = aa.principal_id
        LEFT JOIN qmeta.api_token tok ON tok.token_id = aa.token_id
        LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = aa.dataset_id
        {where}
        ORDER BY aa.updated_at DESC, aa.automation_action_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_actions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("incident_action_code", "sria.incident_action_code"),
            ("run_code", "ar.run_code"),
            ("action_code", "aa.action_code"),
            ("source_signal_type", "sria.source_signal_type"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("action_type", "sria.action_type"),
            ("safety_level", "sria.safety_level"),
            ("execution_mode", "sria.execution_mode"),
            ("status", "sria.status"),
            ("owner", "sria.owner"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "sria.updated_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            sria.incident_action_id,
            sria.incident_action_code,
            ar.run_code,
            aa.action_code,
            dc.dataset_code,
            ss.source_code,
            sria.source_signal_type,
            srcb.breaker_code,
            srhs.snapshot_code,
            srp.probe_code,
            sria.action_type,
            sria.safety_level,
            sria.execution_mode,
            sria.status,
            sria.approval_required,
            sria.owner,
            sria.reason,
            sria.route_status,
            sria.circuit_status,
            sria.probe_status,
            sria.open_until,
            sria.success_rate,
            sria.failure_rate,
            sria.fallback_rate,
            sria.empty_rate,
            sria.latency_p95_ms,
            sria.health_issues,
            sria.planned_effect,
            sria.executed_effect,
            sria.rollback_hint,
            sria.error_message,
            sria.updated_at,
            sria.created_at
        FROM qmeta.source_route_incident_action sria
        LEFT JOIN qmeta.automation_run ar ON ar.automation_run_id = sria.automation_run_id
        LEFT JOIN qmeta.automation_action aa ON aa.automation_action_id = sria.automation_action_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = sria.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = sria.source_id
        LEFT JOIN qmeta.source_route_circuit_breaker srcb ON srcb.breaker_id = sria.breaker_id
        LEFT JOIN qmeta.source_route_health_snapshot srhs ON srhs.snapshot_id = sria.snapshot_id
        LEFT JOIN qmeta.source_route_recovery_probe srp ON srp.probe_id = sria.probe_id
        {where}
        ORDER BY sria.updated_at DESC, sria.incident_action_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_psi_report(payload: dict[str, Any]) -> str:
    lines = [
        (
            f"psi_automation run={payload.get('run_code')} status={payload.get('status')} "
            f"mode={payload.get('execution_mode')} actions={payload.get('action_count')} "
            f"executed={payload.get('executed_count')} approval_required={payload.get('approval_required_count')} "
            f"skipped={payload.get('skipped_count')} failed={payload.get('failed_count')}"
        )
    ]
    for action in payload.get("actions") or []:
        keys = ["action_code", "source_type", "source_code", "action_type", "safety_level", "status", "owner", "reason"]
        lines.append(" ".join(f"{key}={action[key]}" for key in keys if action.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def format_psi_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"psi resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _map_phi_decision(row: dict[str, Any], run_code: str, execution_mode: str) -> dict[str, Any] | None:
    status = row.get("status")
    if status not in PHI_ACTIONABLE_STATUSES:
        return None
    domain = row.get("domain")
    source_action = row.get("action")
    if domain == "data_quality" or source_action in {"hold_production", "block_production"}:
        action_type = "repair_data_quality"
        safety = "high"
        planned = {"operation": "enqueue_repair", "source_action": source_action}
        rollback = "Close generated repair task or mark automation action dismissed."
    elif domain == "vendor":
        action_type = "degrade_vendor"
        safety = "high"
        planned = {"operation": "degrade_vendor_role", "source_action": source_action}
        rollback = "Restore vendor role after readiness review."
    elif domain == "commercial":
        action_type = "escalate_commercial"
        safety = "medium"
        planned = {"operation": "open_commercial_followup", "source_action": source_action}
        rollback = "Resolve or dismiss the follow-up task."
    elif domain == "payment":
        action_type = "contact_owner" if status in {"review", "escalate", "block", "hold"} else "monitor"
        safety = "low"
        planned = {"operation": "record_finance_followup", "source_action": source_action}
        rollback = "Dismiss the follow-up task."
    elif domain == "runtime":
        action_type = "notify_owner"
        safety = "medium"
        planned = {"operation": "notify_runtime_owner", "source_action": source_action}
        rollback = "Acknowledge the runtime notification."
    else:
        action_type = "notify_owner"
        safety = "medium"
        planned = {"operation": "notify_owner", "source_action": source_action}
        rollback = "Acknowledge the notification."
    return _base_action(
        run_code=run_code,
        source_type="phi_decision",
        source_id=row.get("decision_id"),
        source_code=row.get("decision_code") or f"phi-decision-{row.get('decision_id')}",
        action_type=action_type,
        safety_level=safety,
        execution_mode=execution_mode,
        owner=row.get("recommended_owner"),
        reason=row.get("reason") or f"Phi decision {row.get('decision_code')} requires {action_type}",
        planned_effect={**planned, "domain": domain, "decision_status": status},
        rollback_hint=rollback,
        details={"phi": {key: row.get(key) for key in ("run_code", "policy_code", "domain", "subject_type", "subject_code", "status", "severity", "priority_score")}},
    )


def _map_chi_action(row: dict[str, Any], run_code: str, execution_mode: str) -> dict[str, Any] | None:
    status = row.get("status")
    if status not in {"open", "in_progress"}:
        return None
    source_action = row.get("action_type")
    severity = row.get("severity") or "medium"
    if source_action == "review_budget" and severity in {"high", "critical"}:
        action_type = "freeze_budget"
        safety = "high"
        planned = {"operation": "freeze_budget_or_product_access", "source_action": source_action}
        rollback = "Unfreeze the budget/product access after owner approval."
    elif source_action == "review_budget":
        action_type = "review_budget"
        safety = "medium"
        planned = {"operation": "open_budget_review", "source_action": source_action}
        rollback = "Mark the budget review done or dismissed."
    elif source_action == "review_access_policy":
        action_type = "review_access_policy"
        safety = "medium"
        planned = {"operation": "open_access_policy_review", "source_action": source_action}
        rollback = "Mark the access policy review done or dismissed."
    elif source_action == "rotate_token":
        action_type = "rotate_token"
        safety = "high"
        planned = {"operation": "rotate_or_disable_token", "source_action": source_action}
        rollback = "Re-enable old token only after security approval."
    elif source_action == "pause_project":
        action_type = "pause_product"
        safety = "critical"
        planned = {"operation": "pause_project_or_product", "source_action": source_action}
        rollback = "Reactivate the project/product after governance approval."
    elif source_action == "contact_owner":
        action_type = "contact_owner"
        safety = "low"
        planned = {"operation": "record_owner_followup", "source_action": source_action}
        rollback = "Dismiss the follow-up task."
    else:
        action_type = "monitor"
        safety = "low"
        planned = {"operation": "monitor_governance_action", "source_action": source_action}
        rollback = "No rollback needed."
    return _base_action(
        run_code=run_code,
        source_type="chi_governance_action",
        source_id=row.get("action_id"),
        source_code=row.get("action_code") or f"chi-action-{row.get('action_id')}",
        action_type=action_type,
        safety_level=safety,
        execution_mode=execution_mode,
        tenant_id=row.get("tenant_id"),
        project_id=row.get("project_id"),
        principal_id=row.get("principal_id"),
        token_id=row.get("token_id"),
        dataset_id=row.get("dataset_id"),
        owner=row.get("owner"),
        reason=row.get("reason") or f"Chi governance action {row.get('action_code')} requires {action_type}",
        planned_effect={**planned, "governance_status": status, "governance_severity": severity},
        rollback_hint=rollback,
        details={"chi": {key: row.get(key) for key in ("action_code", "action_type", "severity", "status", "tenant_code", "project_code")}},
    )


def _map_route_signal(row: dict[str, Any], run_code: str, execution_mode: str, route_owner: str) -> dict[str, Any] | None:
    signal_type = str(row.get("source_signal_type") or "")
    dataset_code = str(row.get("dataset_code") or "unknown_dataset")
    source_code = str(row.get("source_code") or "unknown_source")
    if signal_type == "circuit_open":
        source_type = "route_circuit_breaker"
        source_id = row.get("breaker_id")
        source_code_value = row.get("breaker_code") or f"route-breaker-{dataset_code}-{source_code}"
        action_type = "degrade_vendor"
        safety = "high"
        operation = "hold_route_weight_and_request_manual_review"
        reason = (
            f"Chi-5 opened route circuit for {dataset_code}/{source_code}; "
            "keep the source out of weighted routing and request owner review."
        )
        rollback = "Close the circuit only after a recovered Chi-5 probe or an approved manual override."
    elif signal_type == "recovery_failed":
        source_type = "route_recovery_probe"
        source_id = row.get("probe_id")
        source_code_value = row.get("probe_code") or f"route-probe-{dataset_code}-{source_code}"
        action_type = "notify_owner"
        safety = "medium"
        operation = "notify_route_recovery_failed"
        reason = f"Chi-5 recovery probe failed for {dataset_code}/{source_code}; keep incident active and notify owner."
        rollback = "Acknowledge the failed probe after a new successful recovery probe is available."
    elif signal_type == "recovered":
        source_type = "route_recovery_probe"
        source_id = row.get("probe_id")
        source_code_value = row.get("probe_code") or f"route-probe-{dataset_code}-{source_code}"
        action_type = "monitor"
        safety = "low"
        operation = "confirm_route_recovered"
        reason = f"Chi-5 recovered route source {dataset_code}/{source_code}; monitor the source before increasing weight."
        rollback = "Reopen the incident if the source degrades again."
    elif signal_type == "health_degraded":
        source_type = "route_health_snapshot"
        source_id = row.get("snapshot_id")
        source_code_value = row.get("snapshot_code") or f"route-health-{dataset_code}-{source_code}"
        action_type = "notify_owner"
        safety = "medium"
        operation = "notify_route_health_degraded"
        reason = f"Chi-5 detected degraded route health for {dataset_code}/{source_code}; notify owner before circuit opens."
        rollback = "Dismiss the notification after route health returns to normal."
    else:
        return None
    planned_effect = {
        "operation": operation,
        "dataset_code": dataset_code,
        "source_code": source_code,
        "source_signal_type": signal_type,
        "notification_channel": "wecom",
        "circuit_status": row.get("circuit_status"),
        "probe_status": row.get("probe_status"),
        "open_until": row.get("open_until"),
    }
    return _base_action(
        run_code=run_code,
        source_type=source_type,
        source_id=source_id,
        source_code=str(source_code_value),
        action_type=action_type,
        safety_level=safety,
        execution_mode=execution_mode,
        dataset_id=row.get("dataset_id"),
        owner=row.get("owner") or route_owner,
        reason=reason,
        planned_effect=planned_effect,
        rollback_hint=rollback,
        details={
            "route": {
                key: row.get(key)
                for key in (
                    "source_signal_type",
                    "dataset_id",
                    "dataset_code",
                    "source_id",
                    "source_code",
                    "breaker_id",
                    "breaker_code",
                    "snapshot_id",
                    "snapshot_code",
                    "probe_id",
                    "probe_code",
                    "route_status",
                    "circuit_status",
                    "probe_status",
                    "open_until",
                    "success_rate",
                    "failure_rate",
                    "fallback_rate",
                    "empty_rate",
                    "latency_p95_ms",
                    "health_issues",
                )
            }
        },
    )


def _base_action(
    *,
    run_code: str,
    source_type: str,
    source_id: Any,
    source_code: str,
    action_type: str,
    safety_level: str,
    execution_mode: str,
    owner: str | None,
    reason: str,
    planned_effect: dict[str, Any],
    rollback_hint: str,
    details: dict[str, Any],
    tenant_id: Any = None,
    project_id: Any = None,
    principal_id: Any = None,
    token_id: Any = None,
    dataset_id: Any = None,
) -> dict[str, Any]:
    idempotency_key = f"{source_type}:{source_code}:{action_type}"
    action_code = _action_code(run_code, idempotency_key)
    return {
        "action_code": action_code,
        "source_type": source_type,
        "source_id": _int_or_none(source_id),
        "source_code": source_code,
        "tenant_id": _int_or_none(tenant_id),
        "project_id": _int_or_none(project_id),
        "principal_id": _int_or_none(principal_id),
        "token_id": _int_or_none(token_id),
        "dataset_id": _int_or_none(dataset_id),
        "action_type": action_type,
        "safety_level": safety_level,
        "execution_mode": execution_mode,
        "approval_required": _requires_approval(action_type, safety_level),
        "owner": owner,
        "reason": reason,
        "idempotency_key": idempotency_key,
        "planned_effect": planned_effect,
        "executed_effect": {},
        "rollback_hint": rollback_hint,
        "details": details,
    }


def _evaluate_execution(
    cursor: Any,
    item: dict[str, Any],
    *,
    run_id: int | None,
    execution_mode: str,
    approve: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    result = dict(item)
    result["approved_by"] = approved_by if approve and result["approval_required"] else None
    result["approved_at"] = datetime.now(timezone.utc) if approve and result["approval_required"] else None
    result["error_message"] = None
    result["executed_at"] = None
    if execution_mode == "dry_run":
        result["status"] = "skipped"
        result["executed_effect"] = {"dry_run": True, "would_execute": True, "requires_approval": result["approval_required"]}
        return result
    if result["approval_required"] and not approve:
        result["status"] = "approval_required"
        result["executed_effect"] = {"blocked_by": "approval_required"}
        return result
    previous = _find_previous_success(cursor, result["idempotency_key"], run_id)
    if previous:
        result["status"] = "skipped"
        result["executed_effect"] = {"skipped_by": "idempotency", "previous_action_code": previous.get("action_code")}
        return result
    try:
        result["executed_effect"] = _execute_low_touch_action(cursor, result)
        result["status"] = "success"
        result["executed_at"] = datetime.now(timezone.utc)
    except Exception as exc:
        result["status"] = "failed"
        result["error_message"] = str(exc)
        result["executed_effect"] = {"error": str(exc)}
    return result


def _execute_low_touch_action(cursor: Any, action: dict[str, Any]) -> dict[str, Any]:
    action_type = action["action_type"]
    if action_type in LOW_TOUCH_ACTIONS:
        effect = {"operation": "recorded_followup", "action_type": action_type}
        if action["source_type"] == "chi_governance_action" and action.get("source_id"):
            cursor.execute(
                """
                UPDATE qmeta.governance_action
                SET status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END,
                    details = details || %s::jsonb,
                    updated_at = now()
                WHERE action_id = %s
                RETURNING status
                """,
                (_json({"psi_last_action_code": action["action_code"], "psi_action_type": action_type}), action["source_id"]),
            )
            row = cursor.fetchone()
            effect["governance_action_status"] = row["status"] if row else None
        return effect
    return {"operation": "approved_recorded", "action_type": action_type, "external_executor_required": True}


def _fetch_phi_decisions(cursor: Any, as_of: date, environment: str, source_run_code: str | None) -> list[dict[str, Any]]:
    values: list[Any]
    if source_run_code:
        run_filter = "sr.run_code = %s"
        values = [source_run_code]
    else:
        run_filter = """
            sr.run_id = (
                SELECT run_id
                FROM qmeta.strategy_run
                WHERE environment = %s AND run_date <= %s
                ORDER BY run_date DESC, started_at DESC, run_id DESC
                LIMIT 1
            )
        """
        values = [environment, as_of]
    cursor.execute(
        f"""
        SELECT
            sd.decision_id, sd.decision_code, sr.run_code, sp.policy_code,
            sd.domain, sd.subject_type, sd.subject_code, sd.decision_type,
            sd.action, sd.status, sd.severity, sd.priority_score,
            sd.recommended_owner, sd.reason, sd.details, sd.decided_at
        FROM qmeta.strategy_decision sd
        JOIN qmeta.strategy_run sr ON sr.run_id = sd.run_id
        LEFT JOIN qmeta.strategy_policy sp ON sp.policy_id = sd.policy_id
        WHERE {run_filter}
          AND sd.status = ANY(%s)
        ORDER BY sd.priority_score DESC, sd.decided_at DESC, sd.decision_id DESC
        """,
        tuple(values + [list(PHI_ACTIONABLE_STATUSES)]),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_chi_actions(cursor: Any, tenant_code: str | None, project_code: str | None) -> list[dict[str, Any]]:
    where = ["ga.status IN ('open', 'in_progress')"]
    values: list[Any] = []
    if tenant_code:
        where.append("t.tenant_code = %s")
        values.append(tenant_code)
    if project_code:
        where.append("p.project_code = %s")
        values.append(project_code)
    cursor.execute(
        f"""
        SELECT
            ga.action_id, ga.action_code, ga.tenant_id, ga.project_id,
            ga.principal_id, ga.token_id, ga.dataset_id, t.tenant_code,
            p.project_code, ga.action_type, ga.severity, ga.status,
            ga.owner, ga.reason, ga.details, ga.created_at, ga.updated_at
        FROM qmeta.governance_action ga
        LEFT JOIN qmeta.tenant t ON t.tenant_id = ga.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = ga.project_id
        WHERE {' AND '.join(where)}
        ORDER BY ga.severity DESC, ga.updated_at DESC, ga.action_id DESC
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_route_signals(cursor: Any, *, lookback_hours: int, limit: int, include_recovered: bool) -> list[dict[str, Any]]:
    cursor.execute(
        """
        WITH route_signals AS (
            SELECT
                'circuit_open'::text AS source_signal_type,
                4 AS signal_rank,
                srcb.updated_at AS signal_at,
                srcb.breaker_id,
                srcb.breaker_code,
                srcb.last_snapshot_id AS snapshot_id,
                srhs.snapshot_code,
                srcb.last_probe_id AS probe_id,
                srp.probe_code,
                srcb.dataset_id,
                dc.dataset_code,
                srcb.source_id,
                ss.source_code,
                ss.owner,
                srhs.status AS route_status,
                srcb.status AS circuit_status,
                srp.status AS probe_status,
                srcb.open_until,
                srcb.failure_rate,
                srcb.fallback_rate,
                srcb.empty_rate,
                srcb.latency_p95_ms,
                srcb.health_issues
            FROM qmeta.source_route_circuit_breaker srcb
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srcb.dataset_id
            JOIN qmeta.source_system ss ON ss.source_id = srcb.source_id
            LEFT JOIN qmeta.source_route_health_snapshot srhs ON srhs.snapshot_id = srcb.last_snapshot_id
            LEFT JOIN qmeta.source_route_recovery_probe srp ON srp.probe_id = srcb.last_probe_id
            WHERE srcb.status = 'open'
              AND (srcb.open_until IS NULL OR srcb.open_until >= now() - INTERVAL '5 minutes')
            UNION ALL
            SELECT
                'recovery_failed'::text AS source_signal_type,
                3 AS signal_rank,
                srp.probe_started_at AS signal_at,
                srp.breaker_id,
                srcb.breaker_code,
                srp.snapshot_id,
                srhs.snapshot_code,
                srp.probe_id,
                srp.probe_code,
                srp.dataset_id,
                dc.dataset_code,
                srp.source_id,
                ss.source_code,
                ss.owner,
                srhs.status AS route_status,
                srcb.status AS circuit_status,
                srp.status AS probe_status,
                srcb.open_until,
                srhs.failure_rate,
                srhs.fallback_rate,
                srhs.empty_rate,
                srhs.latency_p95_ms,
                COALESCE(srhs.health_issues, '{}') AS health_issues
            FROM qmeta.source_route_recovery_probe srp
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srp.dataset_id
            JOIN qmeta.source_system ss ON ss.source_id = srp.source_id
            LEFT JOIN qmeta.source_route_circuit_breaker srcb ON srcb.breaker_id = srp.breaker_id
            LEFT JOIN qmeta.source_route_health_snapshot srhs ON srhs.snapshot_id = srp.snapshot_id
            WHERE srp.status = 'failed'
              AND srp.probe_started_at >= now() - (%s::int * INTERVAL '1 hour')
            UNION ALL
            SELECT
                'recovered'::text AS source_signal_type,
                2 AS signal_rank,
                srp.probe_started_at AS signal_at,
                srp.breaker_id,
                srcb.breaker_code,
                srp.snapshot_id,
                srhs.snapshot_code,
                srp.probe_id,
                srp.probe_code,
                srp.dataset_id,
                dc.dataset_code,
                srp.source_id,
                ss.source_code,
                ss.owner,
                srhs.status AS route_status,
                srcb.status AS circuit_status,
                srp.status AS probe_status,
                srcb.open_until,
                srhs.failure_rate,
                srhs.fallback_rate,
                srhs.empty_rate,
                srhs.latency_p95_ms,
                COALESCE(srhs.health_issues, '{}') AS health_issues
            FROM qmeta.source_route_recovery_probe srp
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srp.dataset_id
            JOIN qmeta.source_system ss ON ss.source_id = srp.source_id
            LEFT JOIN qmeta.source_route_circuit_breaker srcb ON srcb.breaker_id = srp.breaker_id
            LEFT JOIN qmeta.source_route_health_snapshot srhs ON srhs.snapshot_id = srp.snapshot_id
            WHERE (%s::boolean)
              AND srp.status = 'recovered'
              AND srp.probe_started_at >= now() - (%s::int * INTERVAL '1 hour')
            UNION ALL
            SELECT
                'health_degraded'::text AS source_signal_type,
                1 AS signal_rank,
                srhs.as_of_at AS signal_at,
                srcb.breaker_id,
                srcb.breaker_code,
                srhs.snapshot_id,
                srhs.snapshot_code,
                srcb.last_probe_id AS probe_id,
                srp.probe_code,
                srhs.dataset_id,
                dc.dataset_code,
                srhs.source_id,
                ss.source_code,
                ss.owner,
                srhs.status AS route_status,
                srhs.circuit_status,
                srp.status AS probe_status,
                srhs.open_until,
                srhs.failure_rate,
                srhs.fallback_rate,
                srhs.empty_rate,
                srhs.latency_p95_ms,
                srhs.health_issues
            FROM qmeta.source_route_health_snapshot srhs
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srhs.dataset_id
            JOIN qmeta.source_system ss ON ss.source_id = srhs.source_id
            LEFT JOIN qmeta.source_route_circuit_breaker srcb ON srcb.dataset_id = srhs.dataset_id AND srcb.source_id = srhs.source_id
            LEFT JOIN qmeta.source_route_recovery_probe srp ON srp.probe_id = srcb.last_probe_id
            WHERE srhs.status IN ('degraded', 'failed')
              AND srhs.circuit_action = 'none'
              AND srhs.as_of_at >= now() - (%s::int * INTERVAL '1 hour')
        )
        SELECT *
        FROM route_signals
        ORDER BY signal_rank DESC, signal_at DESC
        LIMIT %s
        """,
        (lookback_hours, include_recovered, lookback_hours, lookback_hours, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def _upsert_run(
    cursor: Any,
    *,
    run_code: str,
    run_date: date,
    environment: str,
    trigger_mode: str,
    execution_mode: str,
    source_filter: dict[str, Any],
) -> int:
    cursor.execute(
        """
        INSERT INTO qmeta.automation_run (
            run_code, run_date, environment, trigger_mode, execution_mode,
            status, source_filter, started_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, now(), now())
        ON CONFLICT (run_code) DO UPDATE SET
            run_date = EXCLUDED.run_date,
            environment = EXCLUDED.environment,
            trigger_mode = EXCLUDED.trigger_mode,
            execution_mode = EXCLUDED.execution_mode,
            status = 'running',
            source_filter = EXCLUDED.source_filter,
            started_at = now(),
            finished_at = NULL,
            duration_ms = NULL,
            error_message = NULL,
            updated_at = now()
        RETURNING automation_run_id
        """,
        (run_code, run_date, environment, trigger_mode, execution_mode, _json(source_filter)),
    )
    return int(cursor.fetchone()["automation_run_id"])


def _upsert_action(cursor: Any, action: dict[str, Any]) -> int:
    cursor.execute(
        """
        INSERT INTO qmeta.automation_action (
            action_code, automation_run_id, source_type, source_id, source_code,
            tenant_id, project_id, principal_id, token_id, dataset_id,
            action_type, safety_level, execution_mode, status, approval_required,
            approved_by, approved_at, owner, reason, idempotency_key,
            planned_effect, executed_effect, rollback_hint, error_message,
            executed_at, details, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s::jsonb, %s::jsonb, %s, %s,
            %s, %s::jsonb, now()
        )
        ON CONFLICT (action_code) DO UPDATE SET
            source_type = EXCLUDED.source_type,
            source_id = EXCLUDED.source_id,
            source_code = EXCLUDED.source_code,
            tenant_id = EXCLUDED.tenant_id,
            project_id = EXCLUDED.project_id,
            principal_id = EXCLUDED.principal_id,
            token_id = EXCLUDED.token_id,
            dataset_id = EXCLUDED.dataset_id,
            action_type = EXCLUDED.action_type,
            safety_level = EXCLUDED.safety_level,
            execution_mode = EXCLUDED.execution_mode,
            status = EXCLUDED.status,
            approval_required = EXCLUDED.approval_required,
            approved_by = EXCLUDED.approved_by,
            approved_at = EXCLUDED.approved_at,
            owner = EXCLUDED.owner,
            reason = EXCLUDED.reason,
            idempotency_key = EXCLUDED.idempotency_key,
            planned_effect = EXCLUDED.planned_effect,
            executed_effect = EXCLUDED.executed_effect,
            rollback_hint = EXCLUDED.rollback_hint,
            error_message = EXCLUDED.error_message,
            executed_at = EXCLUDED.executed_at,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING automation_action_id
        """,
        (
            action["action_code"],
            action["automation_run_id"],
            action["source_type"],
            action.get("source_id"),
            action["source_code"],
            action.get("tenant_id"),
            action.get("project_id"),
            action.get("principal_id"),
            action.get("token_id"),
            action.get("dataset_id"),
            action["action_type"],
            action["safety_level"],
            action["execution_mode"],
            action["status"],
            action["approval_required"],
            action.get("approved_by"),
            action.get("approved_at"),
            action.get("owner"),
            action["reason"],
            action["idempotency_key"],
            _json(action.get("planned_effect") or {}),
            _json(action.get("executed_effect") or {}),
            action.get("rollback_hint"),
            action.get("error_message"),
            action.get("executed_at"),
            _json(action.get("details") or {}),
        ),
    )
    return int(cursor.fetchone()["automation_action_id"])


def _upsert_route_incident_action(cursor: Any, action: dict[str, Any]) -> int:
    route = (action.get("details") or {}).get("route") or {}
    cursor.execute(
        """
        INSERT INTO qmeta.source_route_incident_action (
            incident_action_code, automation_run_id, automation_action_id,
            idempotency_key, source_signal_type,
            breaker_id, snapshot_id, probe_id,
            dataset_id, source_id, action_type,
            safety_level, execution_mode, status,
            approval_required, owner, reason,
            planned_effect, executed_effect, rollback_hint,
            route_status, circuit_status, probe_status,
            open_until, success_rate, failure_rate,
            fallback_rate, empty_rate, latency_p95_ms,
            health_issues, details, error_message,
            updated_at
        ) VALUES (
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s::jsonb, %s::jsonb, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s::jsonb, %s,
            now()
        )
        ON CONFLICT (idempotency_key) DO UPDATE SET
            automation_run_id = EXCLUDED.automation_run_id,
            automation_action_id = EXCLUDED.automation_action_id,
            action_type = EXCLUDED.action_type,
            safety_level = EXCLUDED.safety_level,
            execution_mode = EXCLUDED.execution_mode,
            status = EXCLUDED.status,
            approval_required = EXCLUDED.approval_required,
            owner = EXCLUDED.owner,
            reason = EXCLUDED.reason,
            planned_effect = EXCLUDED.planned_effect,
            executed_effect = EXCLUDED.executed_effect,
            rollback_hint = EXCLUDED.rollback_hint,
            route_status = EXCLUDED.route_status,
            circuit_status = EXCLUDED.circuit_status,
            probe_status = EXCLUDED.probe_status,
            open_until = EXCLUDED.open_until,
            success_rate = EXCLUDED.success_rate,
            failure_rate = EXCLUDED.failure_rate,
            fallback_rate = EXCLUDED.fallback_rate,
            empty_rate = EXCLUDED.empty_rate,
            latency_p95_ms = EXCLUDED.latency_p95_ms,
            health_issues = EXCLUDED.health_issues,
            details = EXCLUDED.details,
            error_message = EXCLUDED.error_message,
            updated_at = now()
        RETURNING incident_action_id
        """,
        (
            _route_incident_code(action["idempotency_key"]),
            action.get("automation_run_id"),
            action.get("automation_action_id"),
            action["idempotency_key"],
            route.get("source_signal_type"),
            route.get("breaker_id"),
            route.get("snapshot_id"),
            route.get("probe_id"),
            route.get("dataset_id"),
            route.get("source_id"),
            action["action_type"],
            action["safety_level"],
            action["execution_mode"],
            action["status"],
            action["approval_required"],
            action.get("owner"),
            action["reason"],
            _json(action.get("planned_effect") or {}),
            _json(action.get("executed_effect") or {}),
            action.get("rollback_hint"),
            route.get("route_status"),
            route.get("circuit_status"),
            route.get("probe_status"),
            route.get("open_until"),
            route.get("success_rate"),
            route.get("failure_rate"),
            route.get("fallback_rate"),
            route.get("empty_rate"),
            route.get("latency_p95_ms"),
            route.get("health_issues") or [],
            _json(action.get("details") or {}),
            action.get("error_message"),
        ),
    )
    return int(cursor.fetchone()["incident_action_id"])


def _finish_run(cursor: Any, run_id: int, summary: dict[str, Any], actions: list[dict[str, Any]]) -> None:
    cursor.execute(
        """
        UPDATE qmeta.automation_run
        SET status = %s,
            action_count = %s,
            executable_count = %s,
            executed_count = %s,
            approval_required_count = %s,
            skipped_count = %s,
            failed_count = %s,
            finished_at = now(),
            duration_ms = %s,
            details = %s::jsonb,
            error_message = %s,
            updated_at = now()
        WHERE automation_run_id = %s
        """,
        (
            summary["status"],
            summary["action_count"],
            summary["executable_count"],
            summary["executed_count"],
            summary["approval_required_count"],
            summary["skipped_count"],
            summary["failed_count"],
            summary["duration_ms"],
            _json({"actions": [_action_summary(action) for action in actions]}),
            summary.get("error_message"),
            run_id,
        ),
    )


def _find_previous_success(cursor: Any, idempotency_key: str, run_id: int | None) -> dict[str, Any] | None:
    if run_id is None:
        return None
    cursor.execute(
        """
        SELECT aa.action_code, aa.executed_at
        FROM qmeta.automation_action aa
        WHERE aa.idempotency_key = %s
          AND aa.execution_mode = 'execute'
          AND aa.status = 'success'
          AND aa.automation_run_id <> %s
        ORDER BY aa.executed_at DESC NULLS LAST, aa.updated_at DESC
        LIMIT 1
        """,
        (idempotency_key, run_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _summarize_actions(actions: list[dict[str, Any]], execution_mode: str) -> dict[str, Any]:
    action_count = len(actions)
    failed_count = sum(1 for item in actions if item.get("status") == "failed")
    approval_required_count = sum(1 for item in actions if item.get("status") == "approval_required")
    skipped_count = sum(1 for item in actions if item.get("status") == "skipped")
    executed_count = sum(1 for item in actions if item.get("status") == "success")
    executable_count = sum(1 for item in actions if execution_mode == "execute" and item.get("status") != "approval_required")
    if failed_count:
        status = "failed"
    elif approval_required_count:
        status = "warning"
    elif action_count == 0:
        status = "skipped"
    else:
        status = "success"
    return {
        "status": status,
        "action_count": action_count,
        "executable_count": executable_count,
        "executed_count": executed_count,
        "approval_required_count": approval_required_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "error_message": next((item.get("error_message") for item in actions if item.get("error_message")), None),
    }


def _action_summary(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_code": action.get("action_code"),
        "source_type": action.get("source_type"),
        "source_code": action.get("source_code"),
        "action_type": action.get("action_type"),
        "safety_level": action.get("safety_level"),
        "status": action.get("status"),
        "approval_required": action.get("approval_required"),
    }


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


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
    if resource == "runs":
        preferred = [
            "run_code",
            "run_date",
            "environment",
            "execution_mode",
            "status",
            "action_count",
            "executed_count",
            "approval_required_count",
            "skipped_count",
            "failed_count",
        ]
    elif resource == "route-actions":
        preferred = [
            "incident_action_code",
            "run_code",
            "action_code",
            "source_signal_type",
            "dataset_code",
            "source_code",
            "action_type",
            "safety_level",
            "execution_mode",
            "status",
            "approval_required",
            "owner",
            "circuit_status",
            "probe_status",
            "open_until",
        ]
    else:
        preferred = [
            "action_code",
            "run_code",
            "source_type",
            "source_code",
            "action_type",
            "safety_level",
            "execution_mode",
            "status",
            "approval_required",
            "owner",
            "reason",
        ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _coerce_date(value: str | date | None) -> date:
    if value is None or value == "":
        return date.today()
    if isinstance(value, date):
        return value
    return parse_date(value, "as_of_date")


def _run_code(environment: str, current_date: date, execution_mode: str) -> str:
    return f"psi-{_slug(environment)}-{current_date.strftime('%Y%m%d')}-{execution_mode}"


def _action_code(run_code: str, idempotency_key: str) -> str:
    digest = hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:12]
    source = _slug(idempotency_key.split(":", 2)[1])[:80]
    action_type = _slug(idempotency_key.rsplit(":", 1)[-1])
    return f"psi-action-{_slug(run_code)}-{source}-{action_type}-{digest}"[:260]


def _route_incident_code(idempotency_key: str) -> str:
    digest = hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:12]
    return f"psi5-route-incident-{_slug(idempotency_key)[:180]}-{digest}"[:260]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value)).strip("-").lower() or "unknown"


def _requires_approval(action_type: str, safety_level: str) -> bool:
    return safety_level in {"high", "critical"} or action_type in HIGH_RISK_ACTIONS


def _safety_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(value, 0)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _duration_ms(started_at: datetime, finished_at: datetime | None = None) -> int:
    end = finished_at or datetime.now(timezone.utc)
    return int((end - started_at).total_seconds() * 1000)


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Psi automation") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Psi automation")
    return _connect(postgres_dsn)
