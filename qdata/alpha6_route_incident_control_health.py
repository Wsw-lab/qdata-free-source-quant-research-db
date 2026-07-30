from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
HEALTH_STATUSES = {"healthy", "warning", "critical", "failed", "skipped"}
DEFAULT_CONTROL_SCHEDULE = "omega5_route_incident_control_15m"
CONTROL_WORKER_TASK = "route_incident_control"


def run_route_incident_control_health(
    postgres_dsn: str,
    *,
    requested_by: str = "alpha6",
    trigger_mode: str = "manual",
    environment: str = "local",
    lookback_hours: int = 24,
    approval_sla_hours: int = 4,
    max_pending_controls: int = 50,
    max_failed_execution_rate: float = 0.1,
    max_blocked_receipt_rate: float = 0.8,
    max_stale_minutes: int = 90,
    schedule_code: str = DEFAULT_CONTROL_SCHEDULE,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        lookback_hours=lookback_hours,
        approval_sla_hours=approval_sla_hours,
        max_pending_controls=max_pending_controls,
        max_failed_execution_rate=max_failed_execution_rate,
        max_blocked_receipt_rate=max_blocked_receipt_rate,
        max_stale_minutes=max_stale_minutes,
        schedule_code=schedule_code,
    )
    now = datetime.now(timezone.utc)
    metrics = _fetch_health_metrics(
        _require_dsn(postgres_dsn),
        lookback_hours=lookback_hours,
        approval_sla_hours=approval_sla_hours,
        max_stale_minutes=max_stale_minutes,
        schedule_code=schedule_code,
        now=now,
    )
    thresholds = {
        "max_pending_controls": max_pending_controls,
        "max_failed_execution_rate": max_failed_execution_rate,
        "max_blocked_receipt_rate": max_blocked_receipt_rate,
        "max_stale_minutes": max_stale_minutes,
        "approval_sla_hours": approval_sla_hours,
    }
    evaluation = evaluate_route_incident_control_health(metrics, thresholds)
    runbook_actions = build_route_incident_control_runbook(metrics, evaluation["health_issues"])
    snapshot = {
        "snapshot_id": None,
        "snapshot_code": _snapshot_code(schedule_code, now),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "status": evaluation["status"],
        "as_of_at": now,
        "lookback_hours": lookback_hours,
        "approval_sla_hours": approval_sla_hours,
        "max_pending_controls": max_pending_controls,
        "max_failed_execution_rate": max_failed_execution_rate,
        "max_blocked_receipt_rate": max_blocked_receipt_rate,
        "max_stale_minutes": max_stale_minutes,
        "schedule_code": schedule_code,
        **metrics,
        "health_issues": evaluation["health_issues"],
        "runbook_actions": runbook_actions,
        "evidence": {
            "thresholds": thresholds,
            "schedule": metrics.get("schedule_evidence") or {},
            "policy": {
                "control_worker_task": CONTROL_WORKER_TASK,
                "wecom_blocked_is_local_warning": True,
                "rollback_plan_required_for_high_risk_control": True,
            },
        },
        "error_message": None,
    }
    snapshot.pop("schedule_evidence", None)
    if not write_db:
        return normalize_rows([snapshot])[0]
    return _insert_health_snapshot(_require_dsn(postgres_dsn), snapshot)


def evaluate_route_incident_control_health(metrics: dict[str, Any], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = thresholds or {}
    max_pending_controls = int(thresholds.get("max_pending_controls", 50))
    max_failed_execution_rate = float(thresholds.get("max_failed_execution_rate", 0.1))
    max_blocked_receipt_rate = float(thresholds.get("max_blocked_receipt_rate", 0.8))
    critical: list[str] = []
    warnings: list[str] = []

    if _int(metrics.get("approval_overdue_count")) > 0:
        critical.append("route_control_approval_sla_overdue")
    if _int(metrics.get("pending_control_count")) > max_pending_controls:
        critical.append("route_control_backlog_exceeds_limit")
    if _int(metrics.get("execution_count")) > 0 and _float(metrics.get("execution_failure_rate")) > max_failed_execution_rate:
        critical.append("route_control_execution_failure_rate_high")
    if _int(metrics.get("dispatch_failed_count")) > 0:
        critical.append("route_control_dispatch_failed")
    if _int(metrics.get("missing_rollback_count")) > 0:
        critical.append("route_control_rollback_missing")
    if _int(metrics.get("stale_schedule_count")) > 0:
        critical.append("route_control_schedule_stale")
    if metrics.get("latest_worker_status") == "failed":
        critical.append("route_control_worker_failed")
    if metrics.get("latest_schedule_status") == "failed":
        critical.append("route_control_schedule_failed")

    if _int(metrics.get("pending_control_count")) > 0:
        warnings.append("route_control_pending")
    if _int(metrics.get("approval_pending_count")) > 0:
        warnings.append("route_control_approval_pending")
    if _int(metrics.get("notification_blocked_count")) > 0:
        warnings.append("route_control_wecom_blocked")
    if _float(metrics.get("blocked_receipt_rate")) > max_blocked_receipt_rate:
        warnings.append("route_control_wecom_blocked_rate_high")
    if _int(metrics.get("rollback_planned_count")) > 0:
        warnings.append("route_control_rollback_plan_open")
    if _int(metrics.get("recent_worker_run_count")) == 0 and _int(metrics.get("pending_control_count")) > 0:
        warnings.append("no_recent_route_control_worker_with_backlog")

    issues = _unique(critical + warnings)
    status = "critical" if critical else "warning" if warnings else "healthy"
    return {"status": status, "health_issues": issues}


def build_route_incident_control_runbook(metrics: dict[str, Any], issues: list[str]) -> list[str]:
    actions: list[str] = []
    issue_set = set(issues)
    if "route_control_approval_sla_overdue" in issue_set:
        actions.append("Resolve or reject overdue Omega-5 route-control approvals before running the next execute pass.")
    if "route_control_approval_pending" in issue_set:
        actions.append("Review pending Omega-5 approvals and record a decision with the automation approval control plane.")
    if "route_control_backlog_exceeds_limit" in issue_set or "route_control_pending" in issue_set:
        actions.append("Drain the oldest high-safety route incident controls with a bounded Omega-5 control run.")
    if "route_control_wecom_blocked" in issue_set or "route_control_wecom_blocked_rate_high" in issue_set:
        actions.append("Configure QDATA_DELTA2_WECOM_WEBHOOK_URL for live delivery, or keep blocked receipts as local audit evidence.")
    if "route_control_execution_failure_rate_high" in issue_set:
        actions.append("Inspect recent Omega execution attempts and rerun only idempotent route actions after the executor error is fixed.")
    if "route_control_dispatch_failed" in issue_set:
        actions.append("Inspect Delta-2 dispatch audit dead letters before requesting new route-control approvals.")
    if "route_control_rollback_missing" in issue_set:
        actions.append("Rerun Omega-5 route incident control with rollback planning enabled for approved or executed high-risk controls.")
    if "route_control_schedule_stale" in issue_set or "no_recent_route_control_worker_with_backlog" in issue_set:
        actions.append("Force the Omega-5 route-control Mu schedule due, then restart the Mu scheduler if the tick stays stale.")
    if "route_control_worker_failed" in issue_set or "route_control_schedule_failed" in issue_set:
        actions.append("Open the latest Lambda worker run and scheduler tick, fix the root error, then rerun Alpha-6 health.")
    if not actions:
        actions.append("Continue scheduled Omega-5 route-control and Alpha-6 health snapshots; no immediate control action is required.")
    evidence_hint = (
        f"Current controls={_int(metrics.get('control_count'))}, pending={_int(metrics.get('pending_control_count'))}, "
        f"approvals={_int(metrics.get('approval_pending_count'))}, blocked_receipts={_int(metrics.get('notification_blocked_count'))}."
    )
    actions.append(evidence_hint)
    return _unique(actions)


def list_route_incident_control_health(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "srcichs.snapshot_code"),
            ("status", "srcichs.status"),
            ("requested_by", "srcichs.requested_by"),
            ("trigger_mode", "srcichs.trigger_mode"),
            ("environment", "srcichs.environment"),
            ("schedule_code", "srcichs.schedule_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "srcichs.as_of_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            srcichs.snapshot_id, srcichs.snapshot_code, srcichs.requested_by,
            srcichs.trigger_mode, srcichs.environment, srcichs.status,
            srcichs.as_of_at, srcichs.lookback_hours, srcichs.approval_sla_hours,
            srcichs.max_pending_controls, srcichs.max_failed_execution_rate,
            srcichs.max_blocked_receipt_rate, srcichs.max_stale_minutes,
            srcichs.schedule_code, srcichs.control_count,
            srcichs.pending_control_count, srcichs.approval_pending_count,
            srcichs.approval_overdue_count, srcichs.notification_blocked_count,
            srcichs.notification_success_count, srcichs.blocked_receipt_rate,
            srcichs.dispatch_failed_count, srcichs.execution_count,
            srcichs.executed_count, srcichs.failed_execution_count,
            srcichs.execution_failure_rate, srcichs.rollback_planned_count,
            srcichs.missing_rollback_count, srcichs.stale_schedule_count,
            srcichs.recent_worker_run_count, srcichs.latest_worker_status,
            srcichs.latest_schedule_status, srcichs.latest_control_stage,
            srcichs.health_issues, srcichs.runbook_actions, srcichs.evidence,
            srcichs.error_message, srcichs.created_at, srcichs.updated_at
        FROM qmeta.source_route_incident_control_health_snapshot srcichs
        {where}
        ORDER BY srcichs.as_of_at DESC, srcichs.snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_alpha6_report(payload: dict[str, Any]) -> str:
    return (
        "alpha6_route_incident_control_health "
        f"status={payload.get('status')} snapshot_code={payload.get('snapshot_code')} "
        f"controls={payload.get('control_count')} pending={payload.get('pending_control_count')} "
        f"approvals={payload.get('approval_pending_count')} overdue={payload.get('approval_overdue_count')} "
        f"blocked_receipts={payload.get('notification_blocked_count')} failed_execution={payload.get('failed_execution_count')} "
        f"stale_schedule={payload.get('stale_schedule_count')}"
    )


def format_alpha6_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"alpha6 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _fetch_health_metrics(
    postgres_dsn: str,
    *,
    lookback_hours: int,
    approval_sla_hours: int,
    max_stale_minutes: int,
    schedule_code: str,
    now: datetime,
) -> dict[str, Any]:
    control_metrics = _fetch_control_metrics(postgres_dsn, lookback_hours, approval_sla_hours)
    schedule_metrics = _fetch_schedule_metrics(postgres_dsn, lookback_hours, schedule_code)
    stale_schedule_count, latest_schedule_status = _schedule_staleness(schedule_metrics, max_stale_minutes, now)
    return {
        **control_metrics,
        "stale_schedule_count": stale_schedule_count,
        "recent_worker_run_count": schedule_metrics["recent_worker_run_count"],
        "latest_worker_status": schedule_metrics.get("latest_worker_status"),
        "latest_schedule_status": latest_schedule_status,
        "schedule_evidence": schedule_metrics.get("schedule") or {},
    }


def _fetch_control_metrics(postgres_dsn: str, lookback_hours: int, approval_sla_hours: int) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        WITH recent AS (
            SELECT ctrl.*, ap.requested_at AS approval_requested_at, ap.expires_at AS approval_expires_at
            FROM qmeta.source_route_incident_control ctrl
            LEFT JOIN qmeta.automation_approval ap ON ap.approval_id = ctrl.approval_id
            WHERE ctrl.updated_at >= now() - (%s::int * INTERVAL '1 hour')
        )
        SELECT
            COUNT(*) AS control_count,
            COUNT(*) FILTER (
                WHERE approval_status = 'pending'
                   OR control_stage IN ('planned', 'approval_requested', 'notification_recorded', 'rollback_planned', 'blocked')
            ) AS pending_control_count,
            COUNT(*) FILTER (WHERE approval_status = 'pending') AS approval_pending_count,
            COUNT(*) FILTER (
                WHERE approval_status = 'pending'
                  AND COALESCE(approval_expires_at, approval_requested_at + (%s::int * INTERVAL '1 hour'), created_at + (%s::int * INTERVAL '1 hour')) <= now()
            ) AS approval_overdue_count,
            COUNT(*) FILTER (WHERE receipt_status = 'blocked') AS notification_blocked_count,
            COUNT(*) FILTER (WHERE receipt_status = 'success') AS notification_success_count,
            COALESCE(
                (COUNT(*) FILTER (WHERE receipt_status = 'blocked'))::numeric
                / NULLIF(COUNT(*) FILTER (WHERE receipt_status IN ('blocked', 'success')), 0),
                0
            )::numeric(8, 4) AS blocked_receipt_rate,
            COUNT(*) FILTER (WHERE dispatch_status IN ('failed', 'dead_letter')) AS dispatch_failed_count,
            COUNT(*) FILTER (WHERE attempt_status IS NOT NULL) AS execution_count,
            COUNT(*) FILTER (WHERE attempt_status = 'success') AS executed_count,
            COUNT(*) FILTER (WHERE attempt_status IN ('failed', 'retry_scheduled')) AS failed_execution_count,
            COALESCE(
                (COUNT(*) FILTER (WHERE attempt_status IN ('failed', 'retry_scheduled')))::numeric
                / NULLIF(COUNT(*) FILTER (WHERE attempt_status IS NOT NULL), 0),
                0
            )::numeric(8, 4) AS execution_failure_rate,
            COUNT(*) FILTER (WHERE rollback_status = 'planned') AS rollback_planned_count,
            COUNT(*) FILTER (
                WHERE approval_required = TRUE
                  AND control_stage IN ('approved', 'executed')
                  AND COALESCE(rollback_status, '') NOT IN ('planned', 'success')
            ) AS missing_rollback_count,
            (SELECT control_stage
             FROM qmeta.source_route_incident_control
             ORDER BY updated_at DESC, control_id DESC
             LIMIT 1) AS latest_control_stage
        FROM recent
        """,
        [lookback_hours, approval_sla_hours, approval_sla_hours],
    )
    row = rows[0] if rows else {}
    return {
        "control_count": _int(row.get("control_count")),
        "pending_control_count": _int(row.get("pending_control_count")),
        "approval_pending_count": _int(row.get("approval_pending_count")),
        "approval_overdue_count": _int(row.get("approval_overdue_count")),
        "notification_blocked_count": _int(row.get("notification_blocked_count")),
        "notification_success_count": _int(row.get("notification_success_count")),
        "blocked_receipt_rate": _float(row.get("blocked_receipt_rate")),
        "dispatch_failed_count": _int(row.get("dispatch_failed_count")),
        "execution_count": _int(row.get("execution_count")),
        "executed_count": _int(row.get("executed_count")),
        "failed_execution_count": _int(row.get("failed_execution_count")),
        "execution_failure_rate": _float(row.get("execution_failure_rate")),
        "rollback_planned_count": _int(row.get("rollback_planned_count")),
        "missing_rollback_count": _int(row.get("missing_rollback_count")),
        "latest_control_stage": row.get("latest_control_stage"),
    }


def _fetch_schedule_metrics(postgres_dsn: str, lookback_hours: int, schedule_code: str) -> dict[str, Any]:
    schedule_rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT schedule_code, task_name, status, last_status, last_run_at, next_run_at, run_count, failed_count
        FROM qmeta.worker_schedule
        WHERE schedule_code = %s
        LIMIT 1
        """,
        [schedule_code],
    )
    worker_rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            COUNT(*) AS recent_worker_run_count,
            (SELECT status
             FROM qmeta.worker_run
             WHERE task_filter @> ARRAY[%s]::text[]
             ORDER BY started_at DESC, worker_run_id DESC
             LIMIT 1) AS latest_worker_status
        FROM qmeta.worker_run
        WHERE task_filter @> ARRAY[%s]::text[]
          AND started_at >= now() - (%s::int * INTERVAL '1 hour')
        """,
        [CONTROL_WORKER_TASK, CONTROL_WORKER_TASK, lookback_hours],
    )
    worker = worker_rows[0] if worker_rows else {}
    return {
        "schedule": schedule_rows[0] if schedule_rows else None,
        "recent_worker_run_count": _int(worker.get("recent_worker_run_count")),
        "latest_worker_status": worker.get("latest_worker_status"),
    }


def _schedule_staleness(metrics: dict[str, Any], max_stale_minutes: int, now: datetime) -> tuple[int, str | None]:
    schedule = metrics.get("schedule")
    if not schedule:
        return 1, "missing"
    latest_schedule_status = schedule.get("last_status") or schedule.get("status")
    if schedule.get("status") != "active":
        return 1, str(latest_schedule_status)
    if latest_schedule_status == "failed":
        return 1, str(latest_schedule_status)
    if _int(metrics.get("recent_worker_run_count")) > 0:
        return 0, str(latest_schedule_status) if latest_schedule_status else None
    last_run_at = schedule.get("last_run_at")
    if last_run_at is None:
        return 1, str(latest_schedule_status) if latest_schedule_status else None
    if isinstance(last_run_at, str):
        try:
            last_run_at = datetime.fromisoformat(last_run_at)
        except ValueError:
            return 1, str(latest_schedule_status) if latest_schedule_status else None
    if last_run_at.tzinfo is None:
        last_run_at = last_run_at.replace(tzinfo=timezone.utc)
    age_minutes = (now - last_run_at).total_seconds() / 60.0
    return (1 if age_minutes > max_stale_minutes else 0), str(latest_schedule_status) if latest_schedule_status else None


def _insert_health_snapshot(postgres_dsn: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_control_health_snapshot (
                    snapshot_code, requested_by, trigger_mode, environment,
                    status, as_of_at, lookback_hours, approval_sla_hours,
                    max_pending_controls, max_failed_execution_rate,
                    max_blocked_receipt_rate, max_stale_minutes, schedule_code,
                    control_count, pending_control_count, approval_pending_count,
                    approval_overdue_count, notification_blocked_count,
                    notification_success_count, blocked_receipt_rate,
                    dispatch_failed_count, execution_count, executed_count,
                    failed_execution_count, execution_failure_rate,
                    rollback_planned_count, missing_rollback_count,
                    stale_schedule_count, recent_worker_run_count,
                    latest_worker_status, latest_schedule_status,
                    latest_control_stage, health_issues, runbook_actions,
                    evidence, error_message, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s, now()
                )
                RETURNING *
                """,
                (
                    snapshot["snapshot_code"],
                    snapshot["requested_by"],
                    snapshot["trigger_mode"],
                    snapshot["environment"],
                    snapshot["status"],
                    snapshot["as_of_at"],
                    snapshot["lookback_hours"],
                    snapshot["approval_sla_hours"],
                    snapshot["max_pending_controls"],
                    snapshot["max_failed_execution_rate"],
                    snapshot["max_blocked_receipt_rate"],
                    snapshot["max_stale_minutes"],
                    snapshot["schedule_code"],
                    snapshot["control_count"],
                    snapshot["pending_control_count"],
                    snapshot["approval_pending_count"],
                    snapshot["approval_overdue_count"],
                    snapshot["notification_blocked_count"],
                    snapshot["notification_success_count"],
                    snapshot["blocked_receipt_rate"],
                    snapshot["dispatch_failed_count"],
                    snapshot["execution_count"],
                    snapshot["executed_count"],
                    snapshot["failed_execution_count"],
                    snapshot["execution_failure_rate"],
                    snapshot["rollback_planned_count"],
                    snapshot["missing_rollback_count"],
                    snapshot["stale_schedule_count"],
                    snapshot["recent_worker_run_count"],
                    snapshot["latest_worker_status"],
                    snapshot["latest_schedule_status"],
                    snapshot["latest_control_stage"],
                    snapshot["health_issues"],
                    snapshot["runbook_actions"],
                    _json(snapshot["evidence"]),
                    snapshot.get("error_message"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    lookback_hours: int,
    approval_sla_hours: int,
    max_pending_controls: int,
    max_failed_execution_rate: float,
    max_blocked_receipt_rate: float,
    max_stale_minutes: int,
    schedule_code: str,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, once, scheduled, smoke")
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    if approval_sla_hours <= 0:
        raise QDataValidationError("approval_sla_hours must be greater than 0")
    if max_pending_controls < 0:
        raise QDataValidationError("max_pending_controls must be greater than or equal to 0")
    if max_failed_execution_rate < 0 or max_failed_execution_rate > 1:
        raise QDataValidationError("max_failed_execution_rate must be between 0 and 1")
    if max_blocked_receipt_rate < 0 or max_blocked_receipt_rate > 1:
        raise QDataValidationError("max_blocked_receipt_rate must be between 0 and 1")
    if max_stale_minutes <= 0:
        raise QDataValidationError("max_stale_minutes must be greater than 0")
    if not schedule_code:
        raise QDataValidationError("schedule_code is required")


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
        "as_of_at",
        "snapshot_code",
        "status",
        "control_count",
        "pending_control_count",
        "approval_pending_count",
        "approval_overdue_count",
        "notification_blocked_count",
        "blocked_receipt_rate",
        "execution_count",
        "failed_execution_count",
        "execution_failure_rate",
        "rollback_planned_count",
        "missing_rollback_count",
        "stale_schedule_count",
        "latest_worker_status",
        "latest_schedule_status",
        "latest_control_stage",
        "health_issues",
        "runbook_actions",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _snapshot_code(schedule_code: str, as_of_at: datetime) -> str:
    stamp = as_of_at.strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{schedule_code}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"alpha6-route-control-health-{digest}"[:180]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]


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
        raise QDataValidationError("psycopg is required for Alpha-6 route incident control health") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    return _connect(_require_dsn(postgres_dsn))


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Alpha-6 route incident control health")
    return postgres_dsn
