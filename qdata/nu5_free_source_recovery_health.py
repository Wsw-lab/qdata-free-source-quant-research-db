from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
HEALTH_STATUSES = {"healthy", "warning", "critical", "failed", "skipped"}
DEFAULT_EXECUTION_SCHEDULE = "mu_free_source_recovery_execute_30m"
EXECUTION_WORKER_TASK = "free_source_recovery_execute"


def run_free_source_recovery_health(
    postgres_dsn: str,
    *,
    requested_by: str = "nu5",
    trigger_mode: str = "manual",
    environment: str = "local",
    lookback_hours: int = 24,
    approval_sla_hours: int = 4,
    max_backlog_actions: int = 50,
    max_failure_rate: float = 0.5,
    max_stale_minutes: int = 90,
    schedule_code: str = DEFAULT_EXECUTION_SCHEDULE,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        lookback_hours=lookback_hours,
        approval_sla_hours=approval_sla_hours,
        max_backlog_actions=max_backlog_actions,
        max_failure_rate=max_failure_rate,
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
        "max_backlog_actions": max_backlog_actions,
        "max_failure_rate": max_failure_rate,
        "max_stale_minutes": max_stale_minutes,
        "approval_sla_hours": approval_sla_hours,
    }
    evaluation = evaluate_recovery_health(metrics, thresholds)
    runbook_actions = build_recovery_runbook(metrics, evaluation["health_issues"])
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
        "max_backlog_actions": max_backlog_actions,
        "max_failure_rate": max_failure_rate,
        "max_stale_minutes": max_stale_minutes,
        "schedule_code": schedule_code,
        **metrics,
        "health_issues": evaluation["health_issues"],
        "runbook_actions": runbook_actions,
        "evidence": {
            "thresholds": thresholds,
            "schedule": metrics.get("schedule_evidence") or {},
            "policy": {
                "free_source_role": "research_validator_backup_only",
                "manual_review_required_before_promotion": True,
            },
        },
        "error_message": None,
    }
    snapshot.pop("schedule_evidence", None)
    if not write_db:
        return normalize_rows([snapshot])[0]
    return _insert_health_snapshot(_require_dsn(postgres_dsn), snapshot)


def evaluate_recovery_health(metrics: dict[str, Any], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = thresholds or {}
    max_backlog_actions = int(thresholds.get("max_backlog_actions", 50))
    max_failure_rate = float(thresholds.get("max_failure_rate", 0.5))
    critical: list[str] = []
    warnings: list[str] = []

    if _int(metrics.get("approval_overdue_count")) > 0:
        critical.append("approval_sla_overdue")
    if _int(metrics.get("backlog_count")) > max_backlog_actions:
        critical.append("recovery_backlog_exceeds_limit")
    if _int(metrics.get("execution_count")) > 0 and _float(metrics.get("failure_rate")) > max_failure_rate:
        critical.append("recovery_execution_failure_rate_high")
    if _int(metrics.get("stale_schedule_count")) > 0:
        critical.append("recovery_schedule_stale")
    if metrics.get("latest_worker_status") == "failed":
        critical.append("recovery_worker_failed")
    if metrics.get("latest_schedule_status") == "failed":
        critical.append("recovery_schedule_failed")

    if _int(metrics.get("backlog_count")) > 0:
        warnings.append("recovery_backlog_pending")
    if _int(metrics.get("approval_pending_count")) > 0:
        warnings.append("manual_review_approval_pending")
    if _int(metrics.get("failed_count")) > 0:
        warnings.append("recent_recovery_execution_failed")
    if _int(metrics.get("blocked_count")) > 0:
        warnings.append("recent_recovery_execution_blocked")
    if _int(metrics.get("suppressed_count")) > 0:
        warnings.append("recent_recovery_execution_suppressed")
    if _int(metrics.get("review_requested_count")) > 0:
        warnings.append("manual_review_requested_recently")
    if _int(metrics.get("execution_count")) == 0 and _int(metrics.get("backlog_count")) > 0:
        warnings.append("no_recent_recovery_execution_with_backlog")
    if _int(metrics.get("recent_worker_run_count")) == 0 and _int(metrics.get("backlog_count")) > 0:
        warnings.append("no_recent_recovery_worker_with_backlog")

    issues = _unique(critical + warnings)
    status = "critical" if critical else "warning" if warnings else "healthy"
    return {"status": status, "health_issues": issues}


def build_recovery_runbook(metrics: dict[str, Any], issues: list[str]) -> list[str]:
    actions: list[str] = []
    issue_set = set(issues)
    if "approval_sla_overdue" in issue_set:
        actions.append("Resolve or reject overdue Mu-5 manual-review approvals before retrying the affected free-source actions.")
    if "manual_review_approval_pending" in issue_set:
        actions.append("Review pending Mu-5 approvals and record the decision in Omega approval control.")
    if "recovery_backlog_exceeds_limit" in issue_set or "recovery_backlog_pending" in issue_set:
        actions.append("Run the Mu-5 recovery executor with a bounded action limit and drain the oldest high-severity backlog first.")
    if "recovery_execution_failure_rate_high" in issue_set or "recent_recovery_execution_failed" in issue_set:
        actions.append("Inspect failed retry-canary executions, then compare source health with Iota-5 adapter pool evidence.")
    if "recovery_schedule_stale" in issue_set or "no_recent_recovery_worker_with_backlog" in issue_set:
        actions.append("Force the Mu-5 execution schedule due or restart the Mu scheduler before backlog grows further.")
    if "recovery_worker_failed" in issue_set or "recovery_schedule_failed" in issue_set:
        actions.append("Open the latest Lambda worker run and scheduler tick, fix the root error, then rerun Nu-5 health.")
    if "recent_recovery_execution_suppressed" in issue_set:
        actions.append("Check whether repeated suppression is expected duplicate protection or a stuck recovery action.")
    if "recent_recovery_execution_blocked" in issue_set:
        actions.append("Treat blocked free-source recovery as non-production evidence until commercial source coverage is restored.")
    if not actions:
        actions.append("Continue scheduled Mu-5 execution and Nu-5 health snapshots; no immediate recovery action is required.")
    evidence_hint = f"Current backlog={_int(metrics.get('backlog_count'))}, approvals={_int(metrics.get('approval_pending_count'))}, failures={_int(metrics.get('failed_count'))}."
    actions.append(evidence_hint)
    return _unique(actions)


def list_free_source_recovery_health(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "fsrhs.snapshot_code"),
            ("status", "fsrhs.status"),
            ("requested_by", "fsrhs.requested_by"),
            ("trigger_mode", "fsrhs.trigger_mode"),
            ("environment", "fsrhs.environment"),
            ("schedule_code", "fsrhs.schedule_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "fsrhs.as_of_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsrhs.snapshot_id, fsrhs.snapshot_code, fsrhs.requested_by,
            fsrhs.trigger_mode, fsrhs.environment, fsrhs.status,
            fsrhs.as_of_at, fsrhs.lookback_hours, fsrhs.approval_sla_hours,
            fsrhs.max_backlog_actions, fsrhs.max_failure_rate,
            fsrhs.max_stale_minutes, fsrhs.schedule_code,
            fsrhs.pending_action_count, fsrhs.pending_retry_count,
            fsrhs.pending_manual_review_count, fsrhs.execution_count,
            fsrhs.recovered_count, fsrhs.failed_count, fsrhs.suppressed_count,
            fsrhs.review_requested_count, fsrhs.blocked_count,
            fsrhs.failure_rate, fsrhs.approval_pending_count,
            fsrhs.approval_overdue_count, fsrhs.backlog_count,
            fsrhs.stale_schedule_count, fsrhs.recent_worker_run_count,
            fsrhs.latest_worker_status, fsrhs.latest_schedule_status,
            fsrhs.latest_execution_status, fsrhs.health_issues,
            fsrhs.runbook_actions, fsrhs.evidence, fsrhs.error_message,
            fsrhs.created_at, fsrhs.updated_at
        FROM qmeta.free_source_recovery_health_snapshot fsrhs
        {where}
        ORDER BY fsrhs.as_of_at DESC, fsrhs.snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_nu5_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"nu5 resource={resource} rows={len(rows)}"]
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
    action_metrics = _fetch_action_metrics(postgres_dsn)
    execution_metrics = _fetch_execution_metrics(postgres_dsn, lookback_hours)
    approval_metrics = _fetch_approval_metrics(postgres_dsn, approval_sla_hours)
    schedule_metrics = _fetch_schedule_metrics(postgres_dsn, lookback_hours, schedule_code)
    stale_schedule_count, latest_schedule_status = _schedule_staleness(schedule_metrics, max_stale_minutes, now)
    pending_action_count = action_metrics["pending_retry_count"] + action_metrics["pending_manual_review_count"]
    return {
        **action_metrics,
        "pending_action_count": pending_action_count,
        "backlog_count": pending_action_count,
        **execution_metrics,
        **approval_metrics,
        "stale_schedule_count": stale_schedule_count,
        "recent_worker_run_count": schedule_metrics["recent_worker_run_count"],
        "latest_worker_status": schedule_metrics.get("latest_worker_status"),
        "latest_schedule_status": latest_schedule_status,
        "schedule_evidence": schedule_metrics.get("schedule") or {},
    }


def _fetch_action_metrics(postgres_dsn: str) -> dict[str, int]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            COUNT(*) FILTER (
                WHERE action_type = 'retry_canary'
                  AND status IN ('planned', 'scheduled', 'alerted', 'failed')
                  AND (next_retry_at IS NULL OR next_retry_at <= now())
            ) AS pending_retry_count,
            COUNT(*) FILTER (
                WHERE action_type = 'manual_review'
                  AND status IN ('planned', 'review_required', 'alerted', 'blocked', 'review_requested', 'notified')
            ) AS pending_manual_review_count
        FROM qmeta.free_source_recovery_action
        """,
        [],
    )
    row = rows[0] if rows else {}
    return {
        "pending_retry_count": _int(row.get("pending_retry_count")),
        "pending_manual_review_count": _int(row.get("pending_manual_review_count")),
    }


def _fetch_execution_metrics(postgres_dsn: str, lookback_hours: int) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        WITH recent AS (
            SELECT *
            FROM qmeta.free_source_recovery_execution
            WHERE started_at >= now() - (%s::int * INTERVAL '1 hour')
        )
        SELECT
            COUNT(*) AS execution_count,
            COUNT(*) FILTER (WHERE status = 'recovered') AS recovered_count,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
            COUNT(*) FILTER (WHERE status = 'suppressed') AS suppressed_count,
            COUNT(*) FILTER (WHERE status = 'review_requested') AS review_requested_count,
            COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_count,
            COALESCE((COUNT(*) FILTER (WHERE status = 'failed'))::numeric / NULLIF(COUNT(*), 0), 0)::numeric(8, 4) AS failure_rate,
            (SELECT status FROM qmeta.free_source_recovery_execution ORDER BY started_at DESC, execution_id DESC LIMIT 1) AS latest_execution_status
        FROM recent
        """,
        [lookback_hours],
    )
    row = rows[0] if rows else {}
    return {
        "execution_count": _int(row.get("execution_count")),
        "recovered_count": _int(row.get("recovered_count")),
        "failed_count": _int(row.get("failed_count")),
        "suppressed_count": _int(row.get("suppressed_count")),
        "review_requested_count": _int(row.get("review_requested_count")),
        "blocked_count": _int(row.get("blocked_count")),
        "failure_rate": _float(row.get("failure_rate")),
        "latest_execution_status": row.get("latest_execution_status"),
    }


def _fetch_approval_metrics(postgres_dsn: str, approval_sla_hours: int) -> dict[str, int]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            COUNT(*) AS approval_pending_count,
            COUNT(*) FILTER (
                WHERE ap.requested_at <= now() - (%s::int * INTERVAL '1 hour')
            ) AS approval_overdue_count
        FROM qmeta.automation_approval ap
        JOIN qmeta.automation_action aa ON aa.automation_action_id = ap.automation_action_id
        WHERE ap.status = 'pending'
          AND aa.action_code LIKE 'mu5-free-source-review-action-%%'
        """,
        [approval_sla_hours],
    )
    row = rows[0] if rows else {}
    return {
        "approval_pending_count": _int(row.get("approval_pending_count")),
        "approval_overdue_count": _int(row.get("approval_overdue_count")),
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
        [EXECUTION_WORKER_TASK, EXECUTION_WORKER_TASK, lookback_hours],
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
                INSERT INTO qmeta.free_source_recovery_health_snapshot (
                    snapshot_code, requested_by, trigger_mode, environment,
                    status, as_of_at, lookback_hours, approval_sla_hours,
                    max_backlog_actions, max_failure_rate, max_stale_minutes,
                    schedule_code, pending_action_count, pending_retry_count,
                    pending_manual_review_count, execution_count, recovered_count,
                    failed_count, suppressed_count, review_requested_count,
                    blocked_count, failure_rate, approval_pending_count,
                    approval_overdue_count, backlog_count, stale_schedule_count,
                    recent_worker_run_count, latest_worker_status,
                    latest_schedule_status, latest_execution_status,
                    health_issues, runbook_actions, evidence, error_message,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s::jsonb, %s,
                    now()
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
                    snapshot["max_backlog_actions"],
                    snapshot["max_failure_rate"],
                    snapshot["max_stale_minutes"],
                    snapshot["schedule_code"],
                    snapshot["pending_action_count"],
                    snapshot["pending_retry_count"],
                    snapshot["pending_manual_review_count"],
                    snapshot["execution_count"],
                    snapshot["recovered_count"],
                    snapshot["failed_count"],
                    snapshot["suppressed_count"],
                    snapshot["review_requested_count"],
                    snapshot["blocked_count"],
                    snapshot["failure_rate"],
                    snapshot["approval_pending_count"],
                    snapshot["approval_overdue_count"],
                    snapshot["backlog_count"],
                    snapshot["stale_schedule_count"],
                    snapshot["recent_worker_run_count"],
                    snapshot["latest_worker_status"],
                    snapshot["latest_schedule_status"],
                    snapshot["latest_execution_status"],
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
    max_backlog_actions: int,
    max_failure_rate: float,
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
    if max_backlog_actions < 0:
        raise QDataValidationError("max_backlog_actions must be greater than or equal to 0")
    if max_failure_rate < 0 or max_failure_rate > 1:
        raise QDataValidationError("max_failure_rate must be between 0 and 1")
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
        "backlog_count",
        "pending_action_count",
        "approval_pending_count",
        "approval_overdue_count",
        "execution_count",
        "recovered_count",
        "failed_count",
        "failure_rate",
        "stale_schedule_count",
        "latest_worker_status",
        "latest_schedule_status",
        "health_issues",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _snapshot_code(schedule_code: str, as_of_at: datetime) -> str:
    stamp = as_of_at.strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{schedule_code}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"nu5-recovery-health-{digest}"[:180]


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
        raise QDataValidationError("psycopg is required for Nu-5 free source recovery health") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    return _connect(_require_dsn(postgres_dsn))


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Nu-5 free source recovery health")
    return postgres_dsn
