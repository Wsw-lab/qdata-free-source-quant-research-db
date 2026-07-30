from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import re
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
POLICY_OWNERS = {
    "phi-data-quality-gate": "data-ops",
    "phi-vendor-source-role": "vendor-ops",
    "phi-runtime-capacity-gate": "platform-ops",
    "phi-commercial-risk-gate": "commercial-ops",
    "phi-payment-revenue-reconcile": "finance-ops",
}
POLICY_CODES = tuple(POLICY_OWNERS)


def build_strategy_evaluation(
    source_snapshot: dict[str, Any],
    *,
    as_of_date: str | date,
    environment: str = "local",
    trigger_mode: str = "manual",
    run_code: str | None = None,
) -> dict[str, Any]:
    current_date = _coerce_date(as_of_date, "as_of_date")
    code = run_code or _run_code(environment, current_date)
    signals: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    quality_signals, quality_decision = _evaluate_data_quality(source_snapshot, code)
    signals.extend(quality_signals)
    decisions.append(quality_decision)

    vendor_signals, vendor_decisions = _evaluate_vendor_readiness(source_snapshot, code)
    signals.extend(vendor_signals)
    decisions.extend(vendor_decisions)

    runtime_signals, runtime_decision = _evaluate_runtime(source_snapshot, code, environment)
    signals.extend(runtime_signals)
    decisions.append(runtime_decision)

    commercial_signals, commercial_decision = _evaluate_commercial(source_snapshot, code)
    signals.extend(commercial_signals)
    decisions.append(commercial_decision)

    payment_signals, payment_decision = _evaluate_payments(source_snapshot, code)
    signals.extend(payment_signals)
    decisions.append(payment_decision)

    escalations = _build_escalations(code, decisions, signals)
    highest = _highest_severity([row["severity"] for row in signals + decisions + escalations])
    status = _run_status(highest)
    return {
        "run_code": code,
        "run_date": current_date.isoformat(),
        "environment": environment,
        "trigger_mode": trigger_mode,
        "status": status,
        "highest_severity": highest,
        "policy_count": len(POLICY_CODES),
        "signal_count": len(signals),
        "decision_count": len(decisions),
        "escalation_count": len(escalations),
        "signals": signals,
        "decisions": decisions,
        "escalations": escalations,
        "details": {
            "source": "phi_strategy",
            "source_summary": source_snapshot.get("summary") or _source_summary(source_snapshot),
        },
    }


def run_phi_strategy(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    environment: str = "local",
    trigger_mode: str = "manual",
    source_snapshot: dict[str, Any] | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    current_date = _coerce_date(as_of_date, "as_of_date") if as_of_date else date.today()
    snapshot = source_snapshot if source_snapshot is not None else fetch_strategy_source_snapshot(
        postgres_dsn,
        as_of_date=current_date,
        environment=environment,
    )
    evaluation = build_strategy_evaluation(
        snapshot,
        as_of_date=current_date,
        environment=environment,
        trigger_mode=trigger_mode,
    )
    if not write_db:
        return evaluation
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            policy_ids = _ensure_default_policies(cursor)
            db_run = _upsert_strategy_run(cursor, evaluation)
            _replace_strategy_children(cursor, db_run["run_id"], evaluation, policy_ids)
            evaluation.update(_public(db_run))
    return evaluation


def fetch_strategy_source_snapshot(
    postgres_dsn: str,
    *,
    as_of_date: str | date,
    environment: str = "local",
) -> dict[str, Any]:
    current_date = _coerce_date(as_of_date, "as_of_date")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            return {
                "quality": _fetch_quality_snapshot(cursor, current_date),
                "vendor_readiness": _fetch_latest_vendor_readiness(cursor, current_date),
                "deployment_health": _fetch_latest_deployment_health(cursor, environment, current_date),
                "runtime_daily_reports": _fetch_latest_runtime_reports(cursor, environment, current_date),
                "capacity_alerts": _fetch_open_capacity_alerts(cursor, environment),
                "budget_usage": _fetch_latest_budget_usage(cursor, current_date),
                "budget_alerts": _fetch_open_budget_alerts(cursor),
                "ar_aging": _fetch_latest_ar_aging(cursor, current_date),
                "customer_health": _fetch_latest_customer_health(cursor, current_date),
                "payments": _fetch_unmatched_payments(cursor),
                "payment_batches": _fetch_latest_payment_batches(cursor),
                "reconciliation": _fetch_latest_reconciliation(cursor, current_date),
            }


def format_strategy_evaluation(payload: dict[str, Any]) -> str:
    lines = [
        (
            f"phi_strategy run={payload.get('run_code')} status={payload.get('status')} "
            f"highest={payload.get('highest_severity')} policies={payload.get('policy_count')} "
            f"signals={payload.get('signal_count')} decisions={payload.get('decision_count')} "
            f"escalations={payload.get('escalation_count')}"
        )
    ]
    for decision in payload.get("decisions") or []:
        lines.append(
            (
                f"decision code={decision.get('decision_code')} domain={decision.get('domain')} "
                f"subject={decision.get('subject_code')} action={decision.get('action')} "
                f"status={decision.get('status')} severity={decision.get('severity')} "
                f"priority={decision.get('priority_score')}"
            )
        )
    for escalation in payload.get("escalations") or []:
        lines.append(
            (
                f"escalation code={escalation.get('event_code')} type={escalation.get('escalation_type')} "
                f"severity={escalation.get('severity')} owner={escalation.get('owner')}"
            )
        )
    return "\n".join(lines)


def list_strategy_runs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "sr.run_code"),
            ("environment", "sr.environment"),
            ("status", "sr.status"),
            ("severity", "sr.highest_severity"),
            ("trigger_mode", "sr.trigger_mode"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            sr.run_id, sr.run_code, sr.run_date, sr.environment, sr.trigger_mode,
            sr.status, sr.highest_severity, sr.policy_count, sr.signal_count,
            sr.decision_count, sr.escalation_count, sr.started_at, sr.finished_at,
            sr.details, sr.created_at, sr.updated_at
        FROM qmeta.strategy_run sr
        {where}
        ORDER BY sr.run_date DESC, sr.started_at DESC, sr.run_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_strategy_signals(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "sr.run_code"),
            ("policy_code", "sp.policy_code"),
            ("domain", "ss.domain"),
            ("status", "ss.status"),
            ("severity", "ss.severity"),
            ("subject_code", "ss.subject_code"),
            ("signal_type", "ss.signal_type"),
            ("metric_name", "ss.metric_name"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ss.signal_id, sr.run_code, sp.policy_code, ss.signal_code,
            ss.domain, ss.subject_type, ss.subject_code, ss.signal_type,
            ss.severity, ss.status, ss.metric_name, ss.metric_value,
            ss.threshold_value, ss.score_delta, ss.source_table, ss.source_ref,
            ss.message, ss.observed_at, ss.details, ss.created_at
        FROM qmeta.strategy_signal ss
        JOIN qmeta.strategy_run sr ON sr.run_id = ss.run_id
        LEFT JOIN qmeta.strategy_policy sp ON sp.policy_id = ss.policy_id
        {where}
        ORDER BY ss.observed_at DESC, ss.signal_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_strategy_decisions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "sr.run_code"),
            ("policy_code", "sp.policy_code"),
            ("domain", "sd.domain"),
            ("status", "sd.status"),
            ("severity", "sd.severity"),
            ("subject_code", "sd.subject_code"),
            ("action", "sd.action"),
            ("decision_type", "sd.decision_type"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            sd.decision_id, sr.run_code, sp.policy_code, sd.decision_code,
            sd.domain, sd.subject_type, sd.subject_code, sd.decision_type,
            sd.action, sd.status, sd.severity, sd.confidence_score,
            sd.priority_score, sd.recommended_owner, sd.reason, sd.signal_count,
            sd.decided_at, sd.details, sd.created_at, sd.updated_at
        FROM qmeta.strategy_decision sd
        JOIN qmeta.strategy_run sr ON sr.run_id = sd.run_id
        LEFT JOIN qmeta.strategy_policy sp ON sp.policy_id = sd.policy_id
        {where}
        ORDER BY sd.priority_score DESC, sd.decided_at DESC, sd.decision_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_strategy_escalations(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "sr.run_code"),
            ("status", "see.status"),
            ("severity", "see.severity"),
            ("escalation_type", "see.escalation_type"),
            ("owner", "see.owner"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            see.escalation_id, sr.run_code, sd.decision_code, ss.signal_code,
            see.event_code, see.escalation_type, see.severity, see.status,
            see.owner, see.message, see.created_at, see.resolved_at,
            see.details, see.updated_at
        FROM qmeta.strategy_escalation_event see
        JOIN qmeta.strategy_run sr ON sr.run_id = see.run_id
        LEFT JOIN qmeta.strategy_decision sd ON sd.decision_id = see.decision_id
        LEFT JOIN qmeta.strategy_signal ss ON ss.signal_id = see.signal_id
        {where}
        ORDER BY see.created_at DESC, see.escalation_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def _evaluate_data_quality(source: dict[str, Any], run_code: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    row = source.get("quality") or {}
    subject = row.get("dataset_code") or "daily_bar"
    signals: list[dict[str, Any]] = []
    open_repairs = int(row.get("open_repair_count") or 0)
    open_alerts = int(row.get("open_quality_alert_count") or 0)
    conflict_rate = _decimal(row.get("max_conflict_rate") or 0)
    latest_status = str(row.get("latest_quality_status") or "pass")
    if open_repairs > 0:
        signals.append(
            _signal(
                run_code,
                "phi-data-quality-gate",
                "data_quality",
                "dataset",
                subject,
                "repair_queue_open",
                "high",
                "open_repair_count",
                open_repairs,
                0,
                "qmeta.pipeline_repair_queue",
                None,
                f"{open_repairs} open repair queue item(s) block production promotion",
            )
        )
    if open_alerts > 0:
        signals.append(
            _signal(
                run_code,
                "phi-data-quality-gate",
                "data_quality",
                "dataset",
                subject,
                "quality_alert_open",
                "medium",
                "open_quality_alert_count",
                open_alerts,
                0,
                "qmeta.alert_event",
                None,
                f"{open_alerts} open data quality alert(s) need review",
            )
        )
    if conflict_rate > 0:
        signals.append(
            _signal(
                run_code,
                "phi-data-quality-gate",
                "data_quality",
                "dataset",
                subject,
                "source_conflict_present",
                "medium",
                "max_conflict_rate",
                conflict_rate,
                0,
                "qmeta.multi_source_quality_daily",
                latest_status,
                f"max conflict rate is {conflict_rate}",
            )
        )
    severity = _highest_severity([signal["severity"] for signal in signals])
    if severity in {"high", "critical"}:
        action, status, reason = "hold_production", "block", "quality gate blocked by repair or critical issue"
    elif severity == "medium":
        action, status, reason = "open_review", "review", "quality has warning signals before production"
    else:
        action, status, reason = "allow_production", "allow", "quality gate has no active blocking signal"
    return signals, _decision(
        run_code,
        "phi-data-quality-gate",
        "data_quality",
        "dataset",
        subject,
        "gate",
        action,
        status,
        severity,
        reason,
        signals,
    )


def _evaluate_vendor_readiness(source: dict[str, Any], run_code: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = source.get("vendor_readiness") or []
    if not rows:
        signal = _signal(
            run_code,
            "phi-vendor-source-role",
            "vendor",
            "source",
            "unknown",
            "readiness_missing",
            "medium",
            "review_count",
            0,
            1,
            "qmeta.vendor_readiness_review",
            None,
            "no vendor readiness review is available",
        )
        decision = _decision(
            run_code,
            "phi-vendor-source-role",
            "vendor",
            "source",
            "unknown",
            "role",
            "keep_backup",
            "watch",
            "medium",
            "vendor role stays research-only until readiness exists",
            [signal],
        )
        return [signal], [decision]

    signals: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for row in rows:
        subject = f"{row.get('source_code') or 'unknown'}:{row.get('dataset_code') or 'dataset'}"
        status = str(row.get("status") or "incomplete")
        recommendation = str(row.get("recommendation") or "watch")
        missing = int(row.get("missing_window_count") or 0)
        failed = int(row.get("failed_window_count") or 0)
        if status == "ready" and recommendation in {"approve_primary", "approve_backup"}:
            severity = "low"
            action = recommendation
            decision_status = "approved"
            message = f"vendor readiness is {status}, recommendation={recommendation}"
        elif status == "rejected" or recommendation == "reject" or failed > 0:
            severity = "high"
            action = "hold_primary"
            decision_status = "hold"
            message = f"vendor readiness is {status}, failed_windows={failed}"
        else:
            severity = "medium"
            action = "keep_backup"
            decision_status = "watch"
            message = f"vendor readiness is {status}, missing_windows={missing}"
        signal = _signal(
            run_code,
            "phi-vendor-source-role",
            "vendor",
            "source",
            subject,
            "vendor_readiness",
            severity,
            "missing_window_count" if missing else "failed_window_count",
            missing if missing else failed,
            0,
            "qmeta.vendor_readiness_review",
            row.get("review_code"),
            message,
            details={"recommendation": recommendation, "recommended_role": row.get("recommended_role")},
        )
        signals.append(signal)
        decisions.append(
            _decision(
                run_code,
                "phi-vendor-source-role",
                "vendor",
                "source",
                subject,
                "role",
                action,
                decision_status,
                severity,
                message,
                [signal],
            )
        )
    return signals, decisions


def _evaluate_runtime(source: dict[str, Any], run_code: str, environment: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    subject = environment
    for row in source.get("deployment_health") or []:
        status = str(row.get("status") or "success")
        if status in {"failed", "critical"}:
            severity = "critical"
        elif status in {"warning", "degraded", "skipped"}:
            severity = "medium"
        else:
            continue
        signals.append(
            _signal(
                run_code,
                "phi-runtime-capacity-gate",
                "runtime",
                "environment",
                subject,
                "deployment_health",
                severity,
                "failed_count",
                row.get("failed_count") or 0,
                0,
                "qmeta.deployment_health_snapshot",
                row.get("snapshot_code"),
                f"deployment health status={status}",
            )
        )
    for row in source.get("runtime_daily_reports") or []:
        status = str(row.get("status") or "success")
        if status == "critical":
            severity = "critical"
        elif status == "warning":
            severity = "medium"
        else:
            continue
        signals.append(
            _signal(
                run_code,
                "phi-runtime-capacity-gate",
                "runtime",
                "environment",
                subject,
                "runtime_daily_report",
                severity,
                "open_capacity_alert_count",
                row.get("open_capacity_alert_count") or 0,
                0,
                "qmeta.runtime_daily_report",
                row.get("report_code"),
                f"runtime daily report status={status}",
            )
        )
    for row in source.get("capacity_alerts") or []:
        severity = _coerce_severity(row.get("severity") or "medium")
        signals.append(
            _signal(
                run_code,
                "phi-runtime-capacity-gate",
                "runtime",
                "environment",
                subject,
                "capacity_alert_open",
                severity,
                row.get("metric_name") or "capacity_alert",
                row.get("metric_value") or 0,
                row.get("threshold_value") or 0,
                "qmeta.capacity_alert",
                row.get("alert_key"),
                str(row.get("message") or "capacity alert is open"),
            )
        )
    severity = _highest_severity([signal["severity"] for signal in signals])
    if severity == "critical":
        action, status, reason = "investigate_runtime", "block", "runtime has critical signal"
    elif severity in {"medium", "high"}:
        action, status, reason = "monitor", "review", "runtime has warning signal"
    else:
        action, status, reason = "allow_production", "allow", "runtime gate is clear"
    return signals, _decision(
        run_code,
        "phi-runtime-capacity-gate",
        "runtime",
        "environment",
        subject,
        "gate",
        action,
        status,
        severity,
        reason,
        signals,
    )


def _evaluate_commercial(source: dict[str, Any], run_code: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    subject = _first_subject(source.get("budget_usage") or source.get("customer_health") or [], "project_code", "all-projects")
    for row in source.get("budget_usage") or []:
        status = str(row.get("status") or "normal")
        if status == "blocked":
            severity = "critical"
        elif status == "exceeded":
            severity = "high"
        elif status == "warning":
            severity = "medium"
        else:
            continue
        signals.append(
            _signal(
                run_code,
                "phi-commercial-risk-gate",
                "commercial",
                "project",
                row.get("project_code") or subject,
                "budget_usage",
                severity,
                "usage_pct",
                row.get("usage_pct") or 0,
                1,
                "qmeta.budget_usage_snapshot",
                row.get("snapshot_code"),
                f"budget usage status={status}",
            )
        )
    for row in source.get("budget_alerts") or []:
        severity = _coerce_severity(row.get("severity") or "medium")
        signals.append(
            _signal(
                run_code,
                "phi-commercial-risk-gate",
                "commercial",
                "project",
                row.get("project_code") or subject,
                "budget_alert_open",
                severity,
                "usage_pct",
                row.get("usage_pct") or 0,
                row.get("threshold_pct") or 0,
                "qmeta.budget_alert",
                row.get("alert_key"),
                str(row.get("message") or "budget alert is open"),
            )
        )
    for row in source.get("ar_aging") or []:
        status = str(row.get("status") or "current")
        if status == "critical":
            severity = "critical"
        elif status == "overdue":
            severity = "high"
        elif status == "watch":
            severity = "medium"
        else:
            continue
        signals.append(
            _signal(
                run_code,
                "phi-commercial-risk-gate",
                "commercial",
                "project",
                row.get("project_code") or subject,
                "ar_aging",
                severity,
                "outstanding_amount",
                row.get("outstanding_amount") or 0,
                0,
                "qmeta.ar_aging_snapshot",
                row.get("aging_code"),
                f"AR aging status={status}",
            )
        )
    for row in source.get("customer_health") or []:
        status = str(row.get("status") or "active")
        if status in {"churned", "dormant"}:
            severity = "high"
        elif status == "at_risk":
            severity = "medium"
        else:
            continue
        signals.append(
            _signal(
                run_code,
                "phi-commercial-risk-gate",
                "commercial",
                "project",
                row.get("project_code") or subject,
                "customer_health",
                severity,
                "health_score",
                row.get("health_score") or 0,
                70,
                "qmeta.customer_health_snapshot",
                row.get("health_code"),
                f"customer health status={status}",
                details={"retention_signal": row.get("retention_signal")},
            )
        )
    severity = _highest_severity([signal["severity"] for signal in signals])
    if severity == "critical":
        action, status, reason = "limit_usage", "block", "commercial risk breached hard limit"
    elif severity == "high":
        action, status, reason = "open_review", "escalate", "commercial risk needs owner follow-up"
    elif severity == "medium":
        action, status, reason = "monitor", "watch", "commercial risk should be monitored"
    else:
        action, status, reason = "monitor", "allow", "commercial risk gate is clear"
    return signals, _decision(
        run_code,
        "phi-commercial-risk-gate",
        "commercial",
        "project",
        subject,
        "limit",
        action,
        status,
        severity,
        reason,
        signals,
    )


def _evaluate_payments(source: dict[str, Any], run_code: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    subject = "revenue-cycle"
    unmatched_count = len(source.get("payments") or [])
    if unmatched_count:
        signals.append(
            _signal(
                run_code,
                "phi-payment-revenue-reconcile",
                "payment",
                "payment",
                subject,
                "unmatched_payment",
                "high",
                "unmatched_payment_count",
                unmatched_count,
                0,
                "qmeta.payment_transaction",
                None,
                f"{unmatched_count} unmatched/imported payment transaction(s) need reconciliation",
            )
        )
    for row in source.get("payment_batches") or []:
        status = str(row.get("status") or "imported")
        if status in {"failed", "partially_matched", "imported"}:
            severity = "high" if status == "failed" else "medium"
            signals.append(
                _signal(
                    run_code,
                    "phi-payment-revenue-reconcile",
                    "payment",
                    "payment",
                    subject,
                    "payment_batch_not_closed",
                    severity,
                    "unmatched_count",
                    row.get("unmatched_count") or 0,
                    0,
                    "qmeta.payment_import_batch",
                    row.get("batch_code"),
                    f"payment batch status={status}",
                )
            )
    for row in source.get("reconciliation") or []:
        status = str(row.get("status") or "matched")
        if status in {"mismatch", "missing_invoice", "warning"}:
            severity = "high" if status in {"mismatch", "missing_invoice"} else "medium"
            signals.append(
                _signal(
                    run_code,
                    "phi-payment-revenue-reconcile",
                    "payment",
                    "payment",
                    subject,
                    "revenue_reconciliation",
                    severity,
                    "amount_delta",
                    row.get("amount_delta") or 0,
                    row.get("tolerance_amount") or 0,
                    "qmeta.revenue_reconciliation_run",
                    row.get("reconciliation_code"),
                    f"revenue reconciliation status={status}",
                )
            )
    severity = _highest_severity([signal["severity"] for signal in signals])
    if severity in {"high", "critical"}:
        action, status, reason = "reconcile_payment", "escalate", "payment or revenue reconciliation needs finance review"
    elif severity == "medium":
        action, status, reason = "reconcile_payment", "review", "payment cycle has warning signal"
    else:
        action, status, reason = "monitor", "allow", "payment and revenue cycle is clear"
    return signals, _decision(
        run_code,
        "phi-payment-revenue-reconcile",
        "payment",
        "payment",
        subject,
        "reconcile",
        action,
        status,
        severity,
        reason,
        signals,
    )


def _signal(
    run_code: str,
    policy_code: str,
    domain: str,
    subject_type: str,
    subject_code: str,
    signal_type: str,
    severity: str,
    metric_name: str,
    metric_value: Any,
    threshold_value: Any,
    source_table: str,
    source_ref: Any,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signal_code = _code("phi-signal", run_code, policy_code, subject_code, signal_type)
    return {
        "policy_code": policy_code,
        "signal_code": signal_code,
        "domain": domain,
        "subject_type": subject_type,
        "subject_code": str(subject_code),
        "signal_type": signal_type,
        "severity": _coerce_severity(severity),
        "status": "active",
        "metric_name": metric_name,
        "metric_value": _decimal(metric_value),
        "threshold_value": _decimal(threshold_value),
        "score_delta": _score_delta(severity),
        "source_table": source_table,
        "source_ref": None if source_ref is None else str(source_ref),
        "message": message,
        "details": details or {},
    }


def _decision(
    run_code: str,
    policy_code: str,
    domain: str,
    subject_type: str,
    subject_code: str,
    decision_type: str,
    action: str,
    status: str,
    severity: str,
    reason: str,
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    decision_code = _code("phi-decision", run_code, policy_code, subject_code)
    severity = _coerce_severity(severity)
    return {
        "policy_code": policy_code,
        "decision_code": decision_code,
        "domain": domain,
        "subject_type": subject_type,
        "subject_code": str(subject_code),
        "decision_type": decision_type,
        "action": action,
        "status": status,
        "severity": severity,
        "confidence_score": Decimal("0.900000") if signals else Decimal("1.000000"),
        "priority_score": _priority_score(severity, len(signals)),
        "recommended_owner": POLICY_OWNERS.get(policy_code),
        "reason": reason,
        "signal_count": len(signals),
        "details": {
            "related_signal_codes": [signal["signal_code"] for signal in signals],
            "policy_code": policy_code,
        },
    }


def _build_escalations(run_code: str, decisions: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    escalations: list[dict[str, Any]] = []
    for decision in decisions:
        if decision["severity"] not in {"high", "critical"} and decision["status"] not in {"block", "escalate"}:
            continue
        matching = [
            signal
            for signal in signals
            if signal["domain"] == decision["domain"] and signal["subject_code"] == decision["subject_code"]
        ]
        escalation_type = {
            "data_quality": "source_owner",
            "vendor": "source_owner",
            "runtime": "runtime_owner",
            "commercial": "commercial_owner",
            "payment": "finance_owner",
        }.get(decision["domain"], "human_review")
        escalations.append(
            {
                "event_code": _code("phi-escalation", run_code, decision["decision_code"]),
                "decision_code": decision["decision_code"],
                "signal_code": matching[0]["signal_code"] if matching else None,
                "escalation_type": escalation_type,
                "severity": decision["severity"],
                "status": "open",
                "owner": decision.get("recommended_owner"),
                "message": decision["reason"],
                "details": {"action": decision["action"], "subject_code": decision["subject_code"]},
            }
        )
    return escalations


def _fetch_quality_snapshot(cursor, as_of_date: date) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            'daily_bar' AS dataset_code,
            (SELECT COUNT(*) FROM qmeta.pipeline_repair_queue WHERE status = 'open') AS open_repair_count,
            (
                SELECT COUNT(*)
                FROM qmeta.alert_event
                WHERE status = 'open'
                  AND alert_type IN ('missing_run', 'pipeline_status', 'pipeline_late', 'completeness_below_sla', 'conflict_rate_above_sla')
            ) AS open_quality_alert_count,
            (
                SELECT status
                FROM qmeta.multi_source_quality_daily
                WHERE trade_date <= %s
                ORDER BY trade_date DESC, created_at DESC
                LIMIT 1
            ) AS latest_quality_status,
            (
                SELECT COALESCE(MAX(conflict_rate), 0)
                FROM qmeta.multi_source_quality_daily
                WHERE trade_date BETWEEN %s::date - INTERVAL '30 days' AND %s
            ) AS max_conflict_rate
        """,
        (as_of_date, as_of_date, as_of_date),
    )
    return _public(dict(cursor.fetchone()))


def _fetch_latest_vendor_readiness(cursor, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT DISTINCT ON (ss.source_code, dc.dataset_code)
            vrr.review_id, vrr.review_code, ss.source_code, dc.dataset_code,
            vrr.review_date, vrr.status, vrr.recommendation,
            vrr.recommended_role, vrr.suite_count, vrr.passed_window_count,
            vrr.warning_window_count, vrr.failed_window_count, vrr.missing_window_count,
            vrr.runtime_mode, vrr.profile_status, vrr.blocking_issues, vrr.next_actions
        FROM qmeta.vendor_readiness_review vrr
        JOIN qmeta.source_system ss ON ss.source_id = vrr.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrr.dataset_id
        WHERE vrr.review_date <= %s
        ORDER BY ss.source_code, dc.dataset_code, vrr.review_date DESC, vrr.updated_at DESC
        LIMIT 20
        """,
        (as_of_date,),
    )
    return _public_rows(cursor.fetchall())


def _fetch_latest_deployment_health(cursor, environment: str, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT snapshot_id, snapshot_code, environment, status, check_count, failed_count, checked_at
        FROM qmeta.deployment_health_snapshot
        WHERE environment = %s
          AND checked_at::date <= %s
        ORDER BY checked_at DESC, snapshot_id DESC
        LIMIT 3
        """,
        (environment, as_of_date),
    )
    return _public_rows(cursor.fetchall())


def _fetch_latest_runtime_reports(cursor, environment: str, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            report_id, report_code, environment, report_date, status,
            api_error_rate, worker_failed_count, deployment_health_status,
            open_capacity_alert_count, customer_health_risk_count
        FROM qmeta.runtime_daily_report
        WHERE environment = %s
          AND report_date <= %s
        ORDER BY report_date DESC, report_id DESC
        LIMIT 3
        """,
        (environment, as_of_date),
    )
    return _public_rows(cursor.fetchall())


def _fetch_open_capacity_alerts(cursor, environment: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            capacity_alert_id, alert_key, environment, component, metric_name,
            severity, status, metric_value, threshold_value, message, last_seen_at
        FROM qmeta.capacity_alert
        WHERE environment = %s
          AND status = 'open'
        ORDER BY severity DESC, last_seen_at DESC
        LIMIT 20
        """,
        (environment,),
    )
    return _public_rows(cursor.fetchall())


def _fetch_latest_budget_usage(cursor, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT DISTINCT ON (bp.budget_id)
            bus.snapshot_id, bus.snapshot_code, bp.budget_code, p.project_code,
            bus.period_start, bus.period_end, bus.usage_amount, bus.budget_amount,
            bus.usage_pct, bus.status
        FROM qmeta.budget_usage_snapshot bus
        JOIN qmeta.budget_policy bp ON bp.budget_id = bus.budget_id
        LEFT JOIN qmeta.project p ON p.project_id = bp.project_id
        WHERE bus.period_start <= %s
          AND bus.period_end >= %s
        ORDER BY bp.budget_id, bus.period_end DESC, bus.updated_at DESC
        LIMIT 20
        """,
        (as_of_date, as_of_date),
    )
    return _public_rows(cursor.fetchall())


def _fetch_open_budget_alerts(cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            ba.budget_alert_id, ba.alert_key, bp.budget_code, p.project_code,
            ba.alert_type, ba.severity, ba.status, ba.threshold_pct,
            ba.usage_pct, ba.message, ba.last_seen_at
        FROM qmeta.budget_alert ba
        JOIN qmeta.budget_policy bp ON bp.budget_id = ba.budget_id
        LEFT JOIN qmeta.project p ON p.project_id = bp.project_id
        WHERE ba.status = 'open'
        ORDER BY ba.severity DESC, ba.last_seen_at DESC
        LIMIT 20
        """
    )
    return _public_rows(cursor.fetchall())


def _fetch_latest_ar_aging(cursor, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT DISTINCT ON (aas.tenant_id, aas.project_id, aas.product_id)
            aas.aging_id, aas.aging_code, p.project_code, aas.as_of_date,
            aas.status, aas.outstanding_amount, aas.overdue_invoice_count,
            aas.max_days_past_due
        FROM qmeta.ar_aging_snapshot aas
        LEFT JOIN qmeta.project p ON p.project_id = aas.project_id
        WHERE aas.as_of_date <= %s
        ORDER BY aas.tenant_id, aas.project_id, aas.product_id, aas.as_of_date DESC
        LIMIT 20
        """,
        (as_of_date,),
    )
    return _public_rows(cursor.fetchall())


def _fetch_latest_customer_health(cursor, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT DISTINCT ON (chs.subscription_id)
            chs.health_id, chs.health_code, p.project_code, chs.as_of_date,
            chs.status, chs.retention_signal, chs.health_score,
            chs.request_count_30d, chs.outstanding_amount, chs.overdue_invoice_count
        FROM qmeta.customer_health_snapshot chs
        LEFT JOIN qmeta.project p ON p.project_id = chs.project_id
        WHERE chs.as_of_date <= %s
        ORDER BY chs.subscription_id, chs.as_of_date DESC
        LIMIT 20
        """,
        (as_of_date,),
    )
    return _public_rows(cursor.fetchall())


def _fetch_unmatched_payments(cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            pt.transaction_id, pt.transaction_code, p.project_code, pt.value_date,
            pt.status, pt.currency, pt.amount, pt.base_amount, pt.reference_text
        FROM qmeta.payment_transaction pt
        LEFT JOIN qmeta.project p ON p.project_id = pt.project_id
        WHERE pt.direction = 'inbound'
          AND pt.status IN ('imported', 'unmatched', 'partially_matched')
        ORDER BY pt.value_date DESC, pt.amount DESC
        LIMIT 20
        """
    )
    return _public_rows(cursor.fetchall())


def _fetch_latest_payment_batches(cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            batch_id, batch_code, source_type, status, transaction_count,
            matched_count, unmatched_count, total_amount, matched_amount,
            unmatched_amount, imported_at
        FROM qmeta.payment_import_batch
        ORDER BY imported_at DESC, batch_id DESC
        LIMIT 5
        """
    )
    return _public_rows(cursor.fetchall())


def _fetch_latest_reconciliation(cursor, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            rrr.reconciliation_id, rrr.reconciliation_code, p.project_code,
            rrr.reconciliation_date, rrr.status, rrr.tolerance_amount,
            rrr.invoice_total_amount, rrr.recomputed_total_amount, rrr.amount_delta,
            rrr.mismatch_line_count, rrr.missing_line_count, rrr.extra_line_count
        FROM qmeta.revenue_reconciliation_run rrr
        LEFT JOIN qmeta.project p ON p.project_id = rrr.project_id
        WHERE rrr.reconciliation_date <= %s
        ORDER BY rrr.reconciliation_date DESC, rrr.updated_at DESC
        LIMIT 20
        """,
        (as_of_date,),
    )
    return _public_rows(cursor.fetchall())


def _ensure_default_policies(cursor) -> dict[str, int]:
    cursor.execute(
        """
        SELECT policy_id, policy_code
        FROM qmeta.strategy_policy
        WHERE policy_code = ANY(%s::text[])
        """,
        (list(POLICY_CODES),),
    )
    return {row["policy_code"]: int(row["policy_id"]) for row in cursor.fetchall()}


def _upsert_strategy_run(cursor, evaluation: dict[str, Any]) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.strategy_run (
            run_code, run_date, environment, trigger_mode, status, policy_count,
            signal_count, decision_count, escalation_count, highest_severity,
            started_at, finished_at, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), %s::jsonb)
        ON CONFLICT (run_code) DO UPDATE SET
            run_date = EXCLUDED.run_date,
            environment = EXCLUDED.environment,
            trigger_mode = EXCLUDED.trigger_mode,
            status = EXCLUDED.status,
            policy_count = EXCLUDED.policy_count,
            signal_count = EXCLUDED.signal_count,
            decision_count = EXCLUDED.decision_count,
            escalation_count = EXCLUDED.escalation_count,
            highest_severity = EXCLUDED.highest_severity,
            finished_at = now(),
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING *
        """,
        (
            evaluation["run_code"],
            evaluation["run_date"],
            evaluation["environment"],
            evaluation["trigger_mode"],
            evaluation["status"],
            evaluation["policy_count"],
            evaluation["signal_count"],
            evaluation["decision_count"],
            evaluation["escalation_count"],
            evaluation["highest_severity"],
            _json(evaluation["details"]),
        ),
    )
    return dict(cursor.fetchone())


def _replace_strategy_children(cursor, run_id: int, evaluation: dict[str, Any], policy_ids: dict[str, int]) -> None:
    cursor.execute("DELETE FROM qmeta.strategy_escalation_event WHERE run_id = %s", (run_id,))
    cursor.execute("DELETE FROM qmeta.strategy_decision WHERE run_id = %s", (run_id,))
    cursor.execute("DELETE FROM qmeta.strategy_signal WHERE run_id = %s", (run_id,))
    signal_ids: dict[str, int] = {}
    decision_ids: dict[str, int] = {}
    for signal in evaluation.get("signals") or []:
        cursor.execute(
            """
            INSERT INTO qmeta.strategy_signal (
                run_id, policy_id, signal_code, domain, subject_type, subject_code,
                signal_type, severity, status, metric_name, metric_value,
                threshold_value, score_delta, source_table, source_ref, message,
                details, observed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
            RETURNING signal_id
            """,
            (
                run_id,
                policy_ids.get(signal["policy_code"]),
                signal["signal_code"],
                signal["domain"],
                signal["subject_type"],
                signal["subject_code"],
                signal["signal_type"],
                signal["severity"],
                signal["status"],
                signal["metric_name"],
                signal["metric_value"],
                signal["threshold_value"],
                signal["score_delta"],
                signal["source_table"],
                signal["source_ref"],
                signal["message"],
                _json(signal["details"]),
            ),
        )
        signal_ids[signal["signal_code"]] = int(cursor.fetchone()["signal_id"])
    for decision in evaluation.get("decisions") or []:
        cursor.execute(
            """
            INSERT INTO qmeta.strategy_decision (
                run_id, policy_id, decision_code, domain, subject_type, subject_code,
                decision_type, action, status, severity, confidence_score,
                priority_score, recommended_owner, reason, signal_count, details,
                decided_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
            RETURNING decision_id
            """,
            (
                run_id,
                policy_ids.get(decision["policy_code"]),
                decision["decision_code"],
                decision["domain"],
                decision["subject_type"],
                decision["subject_code"],
                decision["decision_type"],
                decision["action"],
                decision["status"],
                decision["severity"],
                decision["confidence_score"],
                decision["priority_score"],
                decision["recommended_owner"],
                decision["reason"],
                decision["signal_count"],
                _json(decision["details"]),
            ),
        )
        decision_ids[decision["decision_code"]] = int(cursor.fetchone()["decision_id"])
    for escalation in evaluation.get("escalations") or []:
        cursor.execute(
            """
            INSERT INTO qmeta.strategy_escalation_event (
                event_code, run_id, decision_id, signal_id, escalation_type,
                severity, status, owner, message, details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                escalation["event_code"],
                run_id,
                decision_ids.get(escalation.get("decision_code")),
                signal_ids.get(escalation.get("signal_code")),
                escalation["escalation_type"],
                escalation["severity"],
                escalation["status"],
                escalation["owner"],
                escalation["message"],
                _json(escalation["details"]),
            ),
        )


def _source_summary(source: dict[str, Any]) -> dict[str, int]:
    return {key: len(value) if isinstance(value, list) else 1 for key, value in source.items() if value}


def _highest_severity(values: list[str]) -> str:
    if not values:
        return "low"
    return max((_coerce_severity(value) for value in values), key=lambda item: SEVERITY_ORDER[item])


def _run_status(severity: str) -> str:
    if severity == "critical":
        return "critical"
    if severity in {"medium", "high"}:
        return "warning"
    return "success"


def _priority_score(severity: str, signal_count: int) -> Decimal:
    return (Decimal(SEVERITY_ORDER[_coerce_severity(severity)]) * Decimal("10") + Decimal(signal_count)).quantize(Decimal("0.000001"))


def _score_delta(severity: str) -> Decimal:
    return {
        "low": Decimal("0.000000"),
        "medium": Decimal("-0.250000"),
        "high": Decimal("-0.600000"),
        "critical": Decimal("-1.000000"),
    }[_coerce_severity(severity)]


def _coerce_severity(value: Any) -> str:
    severity = str(value or "low").lower()
    if severity not in SEVERITY_ORDER:
        return "low"
    return severity


def _first_subject(rows: list[dict[str, Any]], key: str, default: str) -> str:
    for row in rows:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _run_code(environment: str, current_date: date) -> str:
    return f"phi-{_slug(environment)}-{current_date.strftime('%Y%m%d')}"


def _code(prefix: str, *parts: Any) -> str:
    return "-".join([prefix] + [_slug(part) for part in parts if part not in (None, "")])[:240]


def _slug(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "none"


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def _coerce_date(value: str | date, field_name: str) -> date:
    return parse_date(value, field_name) if isinstance(value, str) else value


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([{key: _stringify(value) for key, value in row.items()}])[0]


def _public_rows(rows) -> list[dict[str, Any]]:
    return [_public(dict(row)) for row in rows]


def _stringify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_stringify(item) for item in value]
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
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
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), values


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[-1]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return _public_rows(cursor.fetchall())


def _connect(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Phi strategy")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Phi strategy") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
