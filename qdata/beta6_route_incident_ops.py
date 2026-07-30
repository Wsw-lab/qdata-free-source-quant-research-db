from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omega_control import decide_automation_approval


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
APPROVAL_DECISIONS = {"approve", "reject", "hold"}
OPERATION_MODES = {"approval_queue", "batch_approval", "pressure_test", "smoke"}
NOTIFICATION_POLICIES = {"dedupe_digest", "critical_only", "none"}
STRESS_SCOPES = {"full_market", "active_sources", "smoke"}
HIGH_RISK_SAFETY_LEVELS = {"high", "critical"}
DEFAULT_OPERATION_SCHEDULE = "beta6_route_incident_operations_30m"


def run_route_incident_operations(
    postgres_dsn: str,
    *,
    requested_by: str = "beta6",
    trigger_mode: str = "manual",
    environment: str = "local",
    operation_mode: str = "approval_queue",
    approval_decision: str = "hold",
    notification_policy: str = "dedupe_digest",
    stress_scope: str = "full_market",
    lookback_hours: int = 24,
    max_controls: int = 100,
    dry_run: bool = True,
    apply_decisions: bool = False,
    notify_wecom: bool = False,
    allow_wecom_external: bool = False,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_run_args(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        operation_mode=operation_mode,
        approval_decision=approval_decision,
        notification_policy=notification_policy,
        stress_scope=stress_scope,
        lookback_hours=lookback_hours,
        max_controls=max_controls,
    )
    started_at = datetime.now(timezone.utc)
    controls = _fetch_approval_queue(_require_dsn(postgres_dsn), lookback_hours=lookback_hours, limit=max_controls)
    items = build_approval_queue_items(controls, approval_decision=approval_decision, max_controls=max_controls)
    notification = build_notification_dedupe_plan(items, notification_policy=notification_policy)
    pressure = build_route_incident_pressure_plan(
        _fetch_pressure_metrics(_require_dsn(postgres_dsn)),
        stress_scope=stress_scope,
        max_controls=max_controls,
    )
    items = notification["items"]
    if write_db and apply_decisions and not dry_run:
        items = _apply_approval_decisions(
            _require_dsn(postgres_dsn),
            items,
            requested_by=requested_by,
            approval_decision=approval_decision,
        )
    else:
        preview_status = "preview" if dry_run or not apply_decisions else "skipped"
        for item in items:
            item["operation_status"] = preview_status if item["operation_decision"] != "skip" else "skipped"
            item["control_stage_after"] = item.get("control_stage_before")
            item["approval_status_after"] = item.get("approval_status_before")
    finished_at = datetime.now(timezone.utc)
    summary = summarize_route_incident_operations(
        items,
        notification_summary=notification["summary"],
        pressure_plan=pressure,
        dry_run=dry_run,
        apply_decisions=apply_decisions,
    )
    batch = {
        "batch_id": None,
        "batch_code": _batch_code(started_at),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "operation_mode": operation_mode,
        "approval_decision": approval_decision,
        "notification_policy": notification_policy,
        "stress_scope": stress_scope,
        "status": summary["status"],
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
        "lookback_hours": lookback_hours,
        "max_controls": max_controls,
        "dry_run": dry_run,
        "apply_decisions": apply_decisions,
        "notify_wecom": notify_wecom,
        "allow_wecom_external": allow_wecom_external,
        **summary["counts"],
        "operation_issues": summary["operation_issues"],
        "required_actions": summary["required_actions"],
        "evidence": {
            "notification_summary": notification["summary"],
            "pressure_plan": pressure,
            "policy": {
                "approval_queue_source": "qmeta.source_route_incident_control",
                "notification_external_side_effect": False,
                "notify_wecom_requested": notify_wecom,
                "allow_wecom_external": allow_wecom_external,
                "dry_run": dry_run,
                "apply_decisions": apply_decisions,
            },
        },
        "error_message": summary.get("error_message"),
        "items": items,
    }
    if not write_db:
        return normalize_rows([batch])[0]
    return _insert_operation_batch(_require_dsn(postgres_dsn), batch, items)


def build_approval_queue_items(
    controls: list[dict[str, Any]],
    *,
    approval_decision: str = "hold",
    max_controls: int = 100,
) -> list[dict[str, Any]]:
    if approval_decision not in APPROVAL_DECISIONS:
        raise QDataValidationError("approval_decision must be one of: approve, reject, hold")
    ranked = sorted((dict(control) for control in controls), key=_priority_sort_key)
    items: list[dict[str, Any]] = []
    for control in ranked[:max_controls]:
        eligible = control.get("approval_status") == "pending" and bool(control.get("approval_code"))
        decision = approval_decision if eligible else "skip"
        items.append(
            {
                "control_id": control.get("control_id"),
                "approval_id": control.get("approval_id"),
                "control_code": control.get("control_code"),
                "approval_code": control.get("approval_code"),
                "incident_action_code": control.get("incident_action_code"),
                "dataset_code": control.get("dataset_code"),
                "source_code": control.get("source_code"),
                "source_signal_type": control.get("source_signal_type"),
                "safety_level": control.get("safety_level"),
                "control_stage_before": control.get("control_stage"),
                "control_stage_after": control.get("control_stage"),
                "approval_status_before": control.get("approval_status"),
                "approval_status_after": control.get("approval_status"),
                "receipt_status": control.get("receipt_status"),
                "rollback_status": control.get("rollback_status"),
                "operation_decision": decision,
                "operation_status": "preview" if eligible else "skipped",
                "notification_group_key": "",
                "suppress_notification": False,
                "priority_score": _priority_score(control),
                "reason": _decision_reason(control, decision),
                "evidence": {
                    "overdue": bool(control.get("approval_overdue")),
                    "age_hours": _float(control.get("age_hours")),
                    "approval_expires_at": control.get("approval_expires_at"),
                    "control_updated_at": control.get("updated_at"),
                },
                "error_message": None,
            }
        )
    return items


def build_notification_dedupe_plan(items: list[dict[str, Any]], *, notification_policy: str = "dedupe_digest") -> dict[str, Any]:
    if notification_policy not in NOTIFICATION_POLICIES:
        raise QDataValidationError("notification_policy must be one of: dedupe_digest, critical_only, none")
    grouped_seen: set[str] = set()
    group_count: dict[str, int] = {}
    output: list[dict[str, Any]] = []
    suppressed_count = 0
    critical_count = 0
    for item in items:
        updated = dict(item)
        group_key = _notification_group_key(updated)
        updated["notification_group_key"] = group_key
        is_critical = updated.get("safety_level") == "critical"
        if is_critical:
            critical_count += 1
        group_count[group_key] = group_count.get(group_key, 0) + 1
        suppress = False
        if notification_policy == "none":
            suppress = True
        elif notification_policy == "critical_only" and not is_critical:
            suppress = True
        elif notification_policy == "dedupe_digest" and group_key in grouped_seen and not is_critical:
            suppress = True
        if suppress:
            suppressed_count += 1
        grouped_seen.add(group_key)
        updated["suppress_notification"] = suppress
        output.append(updated)
    return {
        "items": output,
        "summary": {
            "notification_group_count": len(group_count),
            "deduped_notification_count": sum(max(value - 1, 0) for value in group_count.values()),
            "suppressed_notification_count": suppressed_count,
            "critical_notification_count": critical_count,
            "group_counts": group_count,
        },
    }


def build_route_incident_pressure_plan(
    metrics: dict[str, Any],
    *,
    stress_scope: str = "full_market",
    max_controls: int = 100,
) -> dict[str, Any]:
    if stress_scope not in STRESS_SCOPES:
        raise QDataValidationError("stress_scope must be one of: full_market, active_sources, smoke")
    dataset_count = _int(metrics.get("dataset_count"))
    source_count = _int(metrics.get("active_source_count") if stress_scope == "active_sources" else metrics.get("source_count"))
    if stress_scope == "smoke":
        dataset_count = max(1, min(dataset_count, 2))
        source_count = max(1, min(source_count, 2))
    base_scenarios = [
        "circuit_open_fanout",
        "recovery_probe_backlog",
        "approval_queue_overdue",
        "wecom_blocked_dedupe",
    ]
    scenario_count = dataset_count * source_count * len(base_scenarios) if dataset_count and source_count else 0
    capped_scenarios = min(scenario_count, max(max_controls, 1) * len(base_scenarios))
    issues: list[str] = []
    if dataset_count == 0:
        issues.append("pressure_test_no_dataset")
    if source_count == 0:
        issues.append("pressure_test_no_source")
    if stress_scope == "full_market" and scenario_count > capped_scenarios:
        issues.append("pressure_test_scenarios_capped")
    return {
        "stress_scope": stress_scope,
        "dataset_count": dataset_count,
        "source_count": source_count,
        "scenario_count": capped_scenarios,
        "raw_scenario_count": scenario_count,
        "scenario_templates": base_scenarios,
        "open_circuit_count": _int(metrics.get("open_circuit_count")),
        "pending_control_count": _int(metrics.get("pending_control_count")),
        "issues": issues,
    }


def summarize_route_incident_operations(
    items: list[dict[str, Any]],
    *,
    notification_summary: dict[str, Any],
    pressure_plan: dict[str, Any],
    dry_run: bool,
    apply_decisions: bool,
) -> dict[str, Any]:
    eligible = [item for item in items if item.get("operation_decision") in {"approve", "reject", "hold"}]
    failed_count = sum(1 for item in items if item.get("operation_status") == "failed")
    approved_count = sum(1 for item in items if item.get("approval_status_after") == "approved")
    rejected_count = sum(1 for item in items if item.get("approval_status_after") == "rejected")
    held_count = sum(1 for item in items if item.get("operation_decision") == "hold")
    skipped_count = sum(1 for item in items if item.get("operation_decision") == "skip" or item.get("operation_status") == "skipped")
    issues: list[str] = []
    if dry_run:
        issues.append("operation_preview_only")
    if eligible and not apply_decisions:
        issues.append("approval_queue_waiting_for_operator")
    if notification_summary.get("suppressed_notification_count"):
        issues.append("notification_dedupe_active")
    issues.extend(pressure_plan.get("issues") or [])
    if failed_count:
        issues.append("batch_approval_item_failed")
    if not items:
        status = "skipped"
    elif failed_count:
        status = "failed"
    elif issues:
        status = "warning"
    else:
        status = "success"
    required_actions = build_operation_required_actions(issues, eligible_count=len(eligible), pressure_plan=pressure_plan)
    counts = {
        "candidate_count": len(items),
        "eligible_count": len(eligible),
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "held_count": held_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "high_risk_count": sum(1 for item in items if item.get("safety_level") in HIGH_RISK_SAFETY_LEVELS),
        "overdue_count": sum(1 for item in items if (item.get("evidence") or {}).get("overdue")),
        "blocked_receipt_count": sum(1 for item in items if item.get("receipt_status") == "blocked"),
        "notification_group_count": _int(notification_summary.get("notification_group_count")),
        "deduped_notification_count": _int(notification_summary.get("deduped_notification_count")),
        "suppressed_notification_count": _int(notification_summary.get("suppressed_notification_count")),
        "critical_notification_count": _int(notification_summary.get("critical_notification_count")),
        "stress_dataset_count": _int(pressure_plan.get("dataset_count")),
        "stress_source_count": _int(pressure_plan.get("source_count")),
        "stress_scenario_count": _int(pressure_plan.get("scenario_count")),
    }
    return {
        "status": status,
        "counts": counts,
        "operation_issues": _unique(issues),
        "required_actions": required_actions,
        "error_message": "one or more approval items failed" if failed_count else None,
    }


def build_operation_required_actions(issues: list[str], *, eligible_count: int, pressure_plan: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    issue_set = set(issues)
    if "operation_preview_only" in issue_set:
        actions.append("Review the Beta-6 approval queue preview, then rerun with apply_decisions enabled for bounded approval changes.")
    if "approval_queue_waiting_for_operator" in issue_set:
        actions.append("Use the operation items table to approve, reject or hold pending Omega-5 route incident controls in batches.")
    if "notification_dedupe_active" in issue_set:
        actions.append("Send only the Beta-6 digest group head for duplicated route incident notifications; keep suppressed rows as audit evidence.")
    if "pressure_test_scenarios_capped" in issue_set:
        actions.append("Run the full-market pressure test in shards before enabling a wider automatic route incident operation policy.")
    if "pressure_test_no_dataset" in issue_set or "pressure_test_no_source" in issue_set:
        actions.append("Seed active datasets and route sources before considering the pressure test complete.")
    if "batch_approval_item_failed" in issue_set:
        actions.append("Inspect failed operation items, then retry only unresolved approval codes.")
    if not actions:
        actions.append("Continue scheduled Beta-6 queue refresh and monitor Alpha-6 health for new incidents.")
    actions.append(
        f"Queue eligible={eligible_count}, stress_scenarios={_int(pressure_plan.get('scenario_count'))}, scope={pressure_plan.get('stress_scope')}."
    )
    return _unique(actions)


def list_route_incident_operation_batches(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("batch_code", "b.batch_code"),
            ("status", "b.status"),
            ("requested_by", "b.requested_by"),
            ("trigger_mode", "b.trigger_mode"),
            ("environment", "b.environment"),
            ("operation_mode", "b.operation_mode"),
            ("approval_decision", "b.approval_decision"),
            ("notification_policy", "b.notification_policy"),
            ("stress_scope", "b.stress_scope"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "b.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            b.batch_id, b.batch_code, b.requested_by, b.trigger_mode,
            b.environment, b.operation_mode, b.approval_decision,
            b.notification_policy, b.stress_scope, b.status,
            b.started_at, b.finished_at, b.duration_ms,
            b.lookback_hours, b.max_controls, b.dry_run,
            b.apply_decisions, b.notify_wecom, b.allow_wecom_external,
            b.candidate_count, b.eligible_count, b.approved_count,
            b.rejected_count, b.held_count, b.skipped_count, b.failed_count,
            b.high_risk_count, b.overdue_count, b.blocked_receipt_count,
            b.notification_group_count, b.deduped_notification_count,
            b.suppressed_notification_count, b.critical_notification_count,
            b.stress_dataset_count, b.stress_source_count,
            b.stress_scenario_count, b.operation_issues,
            b.required_actions, b.evidence, b.error_message,
            b.created_at, b.updated_at
        FROM qmeta.source_route_incident_operation_batch b
        {where}
        ORDER BY b.started_at DESC, b.batch_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_operation_items(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("batch_code", "i.batch_code"),
            ("control_code", "i.control_code"),
            ("approval_code", "i.approval_code"),
            ("incident_action_code", "i.incident_action_code"),
            ("dataset_code", "i.dataset_code"),
            ("source_code", "i.source_code"),
            ("source_signal_type", "i.source_signal_type"),
            ("safety_level", "i.safety_level"),
            ("operation_decision", "i.operation_decision"),
            ("operation_status", "i.operation_status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "i.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            i.item_id, i.batch_id, i.batch_code, i.control_id, i.approval_id,
            i.control_code, i.approval_code, i.incident_action_code,
            i.dataset_code, i.source_code, i.source_signal_type,
            i.safety_level, i.control_stage_before, i.control_stage_after,
            i.approval_status_before, i.approval_status_after,
            i.receipt_status, i.rollback_status, i.operation_decision,
            i.operation_status, i.notification_group_key,
            i.suppress_notification, i.priority_score, i.reason,
            i.evidence, i.error_message, i.created_at, i.updated_at
        FROM qmeta.source_route_incident_operation_item i
        {where}
        ORDER BY i.created_at DESC, i.item_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_beta6_report(payload: dict[str, Any]) -> str:
    return (
        "beta6_route_incident_operations "
        f"status={payload.get('status')} batch_code={payload.get('batch_code')} "
        f"candidates={payload.get('candidate_count')} eligible={payload.get('eligible_count')} "
        f"approved={payload.get('approved_count')} rejected={payload.get('rejected_count')} "
        f"held={payload.get('held_count')} suppressed={payload.get('suppressed_notification_count')} "
        f"stress_scenarios={payload.get('stress_scenario_count')}"
    )


def format_beta6_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"beta6 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _fetch_approval_queue(postgres_dsn: str, *, lookback_hours: int, limit: int) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        SELECT
            ctrl.control_id, ctrl.control_code, ctrl.approval_id,
            ap.approval_code, ap.expires_at AS approval_expires_at,
            ap.requested_at AS approval_requested_at,
            sria.incident_action_code, dc.dataset_code, ss.source_code,
            sria.source_signal_type, sria.safety_level,
            ctrl.control_stage, ctrl.approval_status, ctrl.receipt_status,
            ctrl.rollback_status, ctrl.updated_at, ctrl.created_at,
            EXTRACT(EPOCH FROM (now() - COALESCE(ap.requested_at, ctrl.created_at))) / 3600.0 AS age_hours,
            CASE
                WHEN ap.status = 'pending'
                 AND COALESCE(ap.expires_at, ap.requested_at + INTERVAL '4 hours', ctrl.created_at + INTERVAL '4 hours') <= now()
                THEN TRUE ELSE FALSE
            END AS approval_overdue
        FROM qmeta.source_route_incident_control ctrl
        JOIN qmeta.source_route_incident_action sria ON sria.incident_action_id = ctrl.incident_action_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = sria.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = sria.source_id
        LEFT JOIN qmeta.automation_approval ap ON ap.approval_id = ctrl.approval_id
        WHERE ctrl.updated_at >= now() - (%s::int * INTERVAL '1 hour')
          AND (
              ctrl.approval_status = 'pending'
              OR ctrl.control_stage IN ('approval_requested', 'notification_recorded', 'rollback_planned', 'blocked')
          )
        ORDER BY
            CASE sria.safety_level
                WHEN 'critical' THEN 4
                WHEN 'high' THEN 3
                WHEN 'medium' THEN 2
                ELSE 1
            END DESC,
            COALESCE(ap.expires_at, ap.requested_at, ctrl.created_at) ASC,
            ctrl.updated_at DESC,
            ctrl.control_id DESC
        LIMIT %s
        """,
        [lookback_hours, limit],
    )


def _fetch_pressure_metrics(postgres_dsn: str) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            (SELECT COUNT(*) FROM qmeta.dataset_catalog WHERE is_active = TRUE) AS dataset_count,
            (SELECT COUNT(*) FROM qmeta.source_system) AS source_count,
            (SELECT COUNT(*) FROM qmeta.source_system WHERE is_active = TRUE) AS active_source_count,
            (SELECT COUNT(*) FROM qmeta.source_route_circuit_breaker WHERE status = 'open') AS open_circuit_count,
            (SELECT COUNT(*) FROM qmeta.source_route_incident_control WHERE approval_status = 'pending') AS pending_control_count
        """,
        [],
    )
    return rows[0] if rows else {}


def _apply_approval_decisions(
    postgres_dsn: str,
    items: list[dict[str, Any]],
    *,
    requested_by: str,
    approval_decision: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        if updated.get("operation_decision") == "skip":
            updated["operation_status"] = "skipped"
            output.append(updated)
            continue
        if approval_decision == "hold":
            updated["operation_status"] = "skipped"
            output.append(updated)
            continue
        try:
            decision = decide_automation_approval(
                postgres_dsn,
                approval_code=str(updated["approval_code"]),
                decision="approved" if approval_decision == "approve" else "rejected",
                decided_by=requested_by,
                reason=f"Beta-6 batch {approval_decision} for route incident control",
            )
            after_status = decision.get("status")
            after_stage = "approved" if after_status == "approved" else "blocked"
            _update_control_after_decision(
                postgres_dsn,
                control_id=int(updated["control_id"]),
                approval_status=str(after_status),
                control_stage=after_stage,
                requested_by=requested_by,
                decision=approval_decision,
            )
            updated["operation_status"] = "applied"
            updated["approval_status_after"] = after_status
            updated["control_stage_after"] = after_stage
            updated["evidence"] = {
                **(updated.get("evidence") or {}),
                "automation_approval": decision,
                "external_side_effect": False,
            }
        except Exception as exc:  # pragma: no cover - covered through smoke/integration
            updated["operation_status"] = "failed"
            updated["error_message"] = str(exc)
        output.append(updated)
    return output


def _update_control_after_decision(
    postgres_dsn: str,
    *,
    control_id: int,
    approval_status: str,
    control_stage: str,
    requested_by: str,
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
                    requested_by,
                    _json({"beta6": {"decision": decision, "decided_by": requested_by}}),
                    control_id,
                ),
            )


def _insert_operation_batch(postgres_dsn: str, batch: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_operation_batch (
                    batch_code, requested_by, trigger_mode, environment,
                    operation_mode, approval_decision, notification_policy,
                    stress_scope, status, started_at, finished_at, duration_ms,
                    lookback_hours, max_controls, dry_run, apply_decisions,
                    notify_wecom, allow_wecom_external, candidate_count,
                    eligible_count, approved_count, rejected_count, held_count,
                    skipped_count, failed_count, high_risk_count, overdue_count,
                    blocked_receipt_count, notification_group_count,
                    deduped_notification_count, suppressed_notification_count,
                    critical_notification_count, stress_dataset_count,
                    stress_source_count, stress_scenario_count, operation_issues,
                    required_actions, evidence, error_message, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s::jsonb, %s, now()
                )
                RETURNING *
                """,
                (
                    batch["batch_code"],
                    batch["requested_by"],
                    batch["trigger_mode"],
                    batch["environment"],
                    batch["operation_mode"],
                    batch["approval_decision"],
                    batch["notification_policy"],
                    batch["stress_scope"],
                    batch["status"],
                    batch["started_at"],
                    batch["finished_at"],
                    batch["duration_ms"],
                    batch["lookback_hours"],
                    batch["max_controls"],
                    batch["dry_run"],
                    batch["apply_decisions"],
                    batch["notify_wecom"],
                    batch["allow_wecom_external"],
                    batch["candidate_count"],
                    batch["eligible_count"],
                    batch["approved_count"],
                    batch["rejected_count"],
                    batch["held_count"],
                    batch["skipped_count"],
                    batch["failed_count"],
                    batch["high_risk_count"],
                    batch["overdue_count"],
                    batch["blocked_receipt_count"],
                    batch["notification_group_count"],
                    batch["deduped_notification_count"],
                    batch["suppressed_notification_count"],
                    batch["critical_notification_count"],
                    batch["stress_dataset_count"],
                    batch["stress_source_count"],
                    batch["stress_scenario_count"],
                    batch["operation_issues"],
                    batch["required_actions"],
                    _json(batch["evidence"]),
                    batch.get("error_message"),
                ),
            )
            inserted = dict(cursor.fetchone())
            for item in items:
                _insert_operation_item(cursor, inserted["batch_id"], inserted["batch_code"], item)
            result = normalize_rows([inserted])[0]
            result["items"] = normalize_rows(items)
            return result


def _insert_operation_item(cursor, batch_id: int, batch_code: str, item: dict[str, Any]) -> None:
    cursor.execute(
        """
        INSERT INTO qmeta.source_route_incident_operation_item (
            batch_id, batch_code, control_id, approval_id, control_code,
            approval_code, incident_action_code, dataset_code, source_code,
            source_signal_type, safety_level, control_stage_before,
            control_stage_after, approval_status_before, approval_status_after,
            receipt_status, rollback_status, operation_decision,
            operation_status, notification_group_key, suppress_notification,
            priority_score, reason, evidence, error_message, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s::jsonb, %s, now()
        )
        ON CONFLICT (batch_id, control_id) DO UPDATE SET
            approval_id = EXCLUDED.approval_id,
            approval_code = EXCLUDED.approval_code,
            control_stage_after = EXCLUDED.control_stage_after,
            approval_status_after = EXCLUDED.approval_status_after,
            operation_decision = EXCLUDED.operation_decision,
            operation_status = EXCLUDED.operation_status,
            notification_group_key = EXCLUDED.notification_group_key,
            suppress_notification = EXCLUDED.suppress_notification,
            priority_score = EXCLUDED.priority_score,
            reason = EXCLUDED.reason,
            evidence = EXCLUDED.evidence,
            error_message = EXCLUDED.error_message,
            updated_at = now()
        """,
        (
            batch_id,
            batch_code,
            item.get("control_id"),
            item.get("approval_id"),
            item.get("control_code"),
            item.get("approval_code"),
            item.get("incident_action_code"),
            item.get("dataset_code"),
            item.get("source_code"),
            item.get("source_signal_type"),
            item.get("safety_level"),
            item.get("control_stage_before"),
            item.get("control_stage_after"),
            item.get("approval_status_before"),
            item.get("approval_status_after"),
            item.get("receipt_status"),
            item.get("rollback_status"),
            item.get("operation_decision"),
            item.get("operation_status"),
            item.get("notification_group_key"),
            item.get("suppress_notification"),
            item.get("priority_score"),
            item.get("reason"),
            _json(item.get("evidence") or {}),
            item.get("error_message"),
        ),
    )


def _validate_run_args(
    *,
    requested_by: str,
    trigger_mode: str,
    operation_mode: str,
    approval_decision: str,
    notification_policy: str,
    stress_scope: str,
    lookback_hours: int,
    max_controls: int,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, once, scheduled, smoke")
    if operation_mode not in OPERATION_MODES:
        raise QDataValidationError("operation_mode must be one of: approval_queue, batch_approval, pressure_test, smoke")
    if approval_decision not in APPROVAL_DECISIONS:
        raise QDataValidationError("approval_decision must be one of: approve, reject, hold")
    if notification_policy not in NOTIFICATION_POLICIES:
        raise QDataValidationError("notification_policy must be one of: dedupe_digest, critical_only, none")
    if stress_scope not in STRESS_SCOPES:
        raise QDataValidationError("stress_scope must be one of: active_sources, full_market, smoke")
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    if max_controls <= 0:
        raise QDataValidationError("max_controls must be greater than 0")


def _priority_sort_key(control: dict[str, Any]) -> tuple[float, str]:
    return (-_priority_score(control), str(control.get("control_code") or ""))


def _priority_score(control: dict[str, Any]) -> float:
    safety_score = {"critical": 400.0, "high": 300.0, "medium": 200.0, "low": 100.0}.get(str(control.get("safety_level") or "low"), 100.0)
    overdue_score = 120.0 if control.get("approval_overdue") else 0.0
    blocked_score = 30.0 if control.get("receipt_status") == "blocked" else 0.0
    age_score = min(_float(control.get("age_hours")), 168.0)
    return round(safety_score + overdue_score + blocked_score + age_score, 2)


def _decision_reason(control: dict[str, Any], decision: str) -> str:
    if decision == "skip":
        return "Control is not eligible for Beta-6 batch approval."
    return (
        f"Beta-6 {decision} decision for {control.get('safety_level') or 'unknown'} "
        f"{control.get('source_signal_type') or 'route'} incident on "
        f"{control.get('dataset_code') or 'unknown_dataset'}/{control.get('source_code') or 'unknown_source'}."
    )


def _notification_group_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("dataset_code") or "*"),
            str(item.get("source_code") or "*"),
            str(item.get("source_signal_type") or "*"),
            str(item.get("safety_level") or "*"),
        ]
    )[:260]


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


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    batch_keys = [
        "started_at",
        "batch_code",
        "status",
        "approval_decision",
        "dry_run",
        "apply_decisions",
        "candidate_count",
        "eligible_count",
        "approved_count",
        "rejected_count",
        "held_count",
        "suppressed_notification_count",
        "stress_scenario_count",
        "operation_issues",
        "required_actions",
    ]
    item_keys = [
        "created_at",
        "batch_code",
        "control_code",
        "approval_code",
        "dataset_code",
        "source_code",
        "source_signal_type",
        "safety_level",
        "operation_decision",
        "operation_status",
        "approval_status_before",
        "approval_status_after",
        "suppress_notification",
        "priority_score",
        "error_message",
    ]
    preferred = item_keys if resource == "items" else batch_keys
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]


def _batch_code(started_at: datetime) -> str:
    stamp = started_at.strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"beta6:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"beta6-route-ops-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Beta-6 route incident operations") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    return _connect(_require_dsn(postgres_dsn))


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Beta-6 route incident operations")
    return postgres_dsn
