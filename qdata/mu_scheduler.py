from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import socket
import time
from typing import Any

from qdata.backend_utils import date_range, normalize_row
from qdata.exceptions import QDataValidationError
from qdata.lambda_worker import WORKER_TASKS, LambdaWorkerResult, run_lambda_worker


SCHEDULER_STATUSES = {"running", "stopping", "stopped", "failed"}
TICK_STATUSES = {"running", "success", "warning", "failed", "skipped", "skipped_locked"}
WORKER_KWARG_KEYS = {
    "trade_date",
    "start_date",
    "end_date",
    "channel_code",
    "alert_limit",
    "schedule_code",
    "include_manual_schedules",
    "cost_per_request",
    "cost_per_1000_rows",
    "free_source_lookback_hours",
    "free_source_max_actions",
    "free_source_min_retry_score",
    "free_source_write_alerts",
    "mu5_max_actions",
    "mu5_start_date",
    "mu5_end_date",
    "mu5_execute_retry_canary",
    "mu5_request_manual_review",
    "mu5_notify_wecom",
    "mu5_allow_wecom_external",
    "mu5_baostock_timeout_seconds",
    "nu5_lookback_hours",
    "nu5_approval_sla_hours",
    "nu5_max_backlog_actions",
    "nu5_max_failure_rate",
    "nu5_max_stale_minutes",
    "xi5_lookback_days",
    "xi5_min_validator_score",
    "xi5_min_backup_score",
    "xi5_min_primary_score",
    "xi5_min_coverage_rate",
    "xi5_max_conflict_rate_bps",
    "omicron5_min_sla_uptime_pct",
    "omicron5_min_rate_limit_per_min",
    "omicron5_require_live_evidence",
    "pi5_promotion_scope",
    "pi5_require_full_market",
    "pi5_require_signoff",
    "pi5_apply_routing",
    "pi5_target_priority",
    "rho5_monitor_scope",
    "rho5_require_applied_promotion",
    "rho5_apply_rollback",
    "rho5_shadow_window_hours",
    "rho5_max_conflict_rate_bps",
    "rho5_max_failure_rate",
    "rho5_max_stale_minutes",
    "sigma5_monitor_scope",
    "sigma5_lookback_hours",
    "sigma5_capacity_window_days",
    "sigma5_min_success_rate",
    "sigma5_max_error_rate",
    "sigma5_max_latency_p95_ms",
    "sigma5_max_timeout_rate",
    "sigma5_max_cost_units",
    "sigma5_max_scheduler_lag_minutes",
    "sigma5_max_backlog_count",
    "sigma5_max_post_promotion_no_applied_count",
    "tau5_optimization_scope",
    "tau5_lookback_hours",
    "tau5_forecast_window_days",
    "tau5_monthly_budget_amount",
    "tau5_max_budget_usage_pct",
    "tau5_max_daily_quota_usage_pct",
    "tau5_max_monthly_quota_usage_pct",
    "tau5_min_stability_score",
    "tau5_cost_safety_margin_pct",
    "tau5_default_unit_cost",
    "tau5_stress_multipliers",
    "upsilon5_execution_scope",
    "upsilon5_execution_mode",
    "upsilon5_approval_policy",
    "upsilon5_approval_status",
    "upsilon5_rollout_policy",
    "upsilon5_rollout_stages",
    "upsilon5_current_stage_sequence",
    "upsilon5_max_initial_primary_weight_pct",
    "upsilon5_allow_over_budget",
    "upsilon5_allow_quota_risk",
    "upsilon5_rollback_requested",
    "chi5_lookback_hours",
    "chi5_min_request_count",
    "chi5_min_success_rate",
    "chi5_max_failure_rate",
    "chi5_max_fallback_rate",
    "chi5_max_empty_rate",
    "chi5_max_latency_p95_ms",
    "chi5_circuit_open_minutes",
    "chi5_recovery_probe_min_success_rate",
    "psi5_route_lookback_hours",
    "psi5_route_max_actions",
    "psi5_route_execution_mode",
    "psi5_route_approve_high_risk",
    "psi5_route_approved_by",
    "psi5_route_owner",
    "psi5_route_include_recovered",
    "omega5_route_lookback_hours",
    "omega5_route_max_controls",
    "omega5_route_execution_mode",
    "omega5_route_auto_approve",
    "omega5_route_approved_by",
    "omega5_route_requested_by",
    "omega5_route_approval_sla_hours",
    "omega5_route_notify_wecom",
    "omega5_route_allow_wecom_external",
    "omega5_route_create_rollback",
    "alpha6_route_lookback_hours",
    "alpha6_route_approval_sla_hours",
    "alpha6_route_max_pending_controls",
    "alpha6_route_max_failed_execution_rate",
    "alpha6_route_max_blocked_receipt_rate",
    "alpha6_route_max_stale_minutes",
    "alpha6_route_requested_by",
    "alpha6_route_environment",
    "alpha6_route_control_schedule_code",
    "beta6_route_lookback_hours",
    "beta6_route_max_controls",
    "beta6_route_approval_decision",
    "beta6_route_apply_decisions",
    "beta6_route_requested_by",
    "beta6_route_environment",
    "beta6_route_notification_policy",
    "beta6_route_stress_scope",
    "beta6_route_notify_wecom",
    "beta6_route_allow_wecom_external",
    "epsilon6_sla_automation",
    "epsilon6_hash_verify",
    "epsilon6_recovery_drill",
    "epsilon6_requested_by",
    "epsilon6_environment",
    "epsilon6_sla_limit",
    "epsilon6_audit_verify_limit",
    "zeta6_environment",
    "zeta6_release_version",
    "zeta6_requested_by",
    "zeta6_require_dual_secret",
    "zeta6_export_audit",
    "zeta6_export_chain_scope",
    "zeta6_export_control_code",
    "zeta6_export_limit",
    "eta6_source_code",
    "eta6_primary_source_code",
    "eta6_dataset_codes",
    "eta6_environment",
    "eta6_closure_scope",
    "eta6_closure_mode",
    "eta6_requested_by",
    "eta6_require_real_vendor_env",
    "eta6_external_probe_allowed",
    "eta6_min_stability_score",
    "eta6_allow_cost_watch",
}


@dataclass(frozen=True)
class MuTickResult:
    schedule_code: str
    task_name: str
    status: str
    tick_id: int | None = None
    worker_run_id: int | None = None
    lock_acquired: bool = False
    duration_ms: int = 0
    error_message: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class MuSchedulerResult:
    scheduler_id: str
    status: str
    scan_count: int
    tick_results: list[MuTickResult]
    duration_ms: int


def run_mu_scheduler(
    postgres_dsn: str | None,
    *,
    scheduler_id: str | None = None,
    schedule_codes: list[str] | None = None,
    task_names: list[str] | None = None,
    once: bool = False,
    max_ticks: int | None = 1,
    poll_seconds: float = 30.0,
    due_limit: int = 100,
    dry_run: bool | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    mark_stopped: bool = True,
) -> MuSchedulerResult:
    dsn = _require_dsn(postgres_dsn)
    if max_ticks is not None and max_ticks < 1:
        raise QDataValidationError("max_ticks must be greater than 0 when provided")
    if poll_seconds <= 0:
        raise QDataValidationError("poll_seconds must be greater than 0")
    if due_limit < 1 or due_limit > 500:
        raise QDataValidationError("due_limit must be between 1 and 500")
    if trade_date:
        date_range(trade_date, trade_date)
    if start_date or end_date:
        if not start_date or not end_date:
            raise QDataValidationError("start_date and end_date must be provided together")
        date_range(start_date, end_date)
    normalized_schedule_codes = normalize_schedule_codes(schedule_codes)
    normalized_task_names = normalize_task_names(task_names)
    scheduler_id = scheduler_id or default_scheduler_id()
    started_at = datetime.now(timezone.utc)
    scan_count = 0
    tick_results: list[MuTickResult] = []
    _upsert_heartbeat(dsn, scheduler_id, "running", 0, 0, None, {"mode": "once" if once else "loop"})
    try:
        while True:
            scan_count += 1
            schedules = _fetch_due_schedules(dsn, normalized_schedule_codes, normalized_task_names, due_limit)
            for schedule in schedules:
                tick_results.append(
                    _run_schedule_tick(
                        dsn,
                        scheduler_id,
                        schedule,
                        dry_run=dry_run,
                        trade_date=trade_date,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
            _upsert_heartbeat(dsn, scheduler_id, "running", scan_count, len(tick_results), None, {"due_count": len(schedules)})
            if once or (max_ticks is not None and scan_count >= max_ticks):
                break
            time.sleep(poll_seconds)
    except Exception:
        _upsert_heartbeat(dsn, scheduler_id, "failed", scan_count, len(tick_results), None, {})
        raise
    finally:
        if mark_stopped:
            _mark_heartbeat_stopped(dsn, scheduler_id, scan_count, len(tick_results))
    return MuSchedulerResult(
        scheduler_id=scheduler_id,
        status=_overall_status(tick_results),
        scan_count=scan_count,
        tick_results=tick_results,
        duration_ms=_duration_ms(started_at),
    )


def normalize_schedule_codes(schedule_codes: list[str] | None) -> list[str] | None:
    if not schedule_codes:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for schedule_code in schedule_codes:
        code = schedule_code.strip()
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized or None


def normalize_task_names(task_names: list[str] | None) -> list[str] | None:
    if not task_names:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for task_name in task_names:
        if task_name not in WORKER_TASKS:
            raise QDataValidationError(f"unknown worker task: {task_name}")
        if task_name in seen:
            continue
        seen.add(task_name)
        normalized.append(task_name)
    return normalized or None


def build_worker_kwargs(
    schedule: dict[str, Any],
    *,
    dry_run: bool | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    task_args = dict(schedule.get("task_args") or {})
    kwargs = {key: value for key, value in task_args.items() if key in WORKER_KWARG_KEYS and value not in (None, "")}
    if trade_date:
        kwargs["trade_date"] = trade_date
        kwargs.pop("start_date", None)
        kwargs.pop("end_date", None)
    elif start_date and end_date:
        kwargs["start_date"] = start_date
        kwargs["end_date"] = end_date
        kwargs.pop("trade_date", None)
    elif ("start_date" in kwargs) != ("end_date" in kwargs):
        raise QDataValidationError("task_args start_date and end_date must be provided together")
    if "trade_date" in kwargs:
        date_range(str(kwargs["trade_date"]), str(kwargs["trade_date"]))
    elif "start_date" in kwargs and "end_date" in kwargs:
        date_range(str(kwargs["start_date"]), str(kwargs["end_date"]))
    kwargs["dry_run"] = bool(schedule.get("dry_run")) if dry_run is None else dry_run
    return kwargs


def compute_next_run_at(started_at: datetime, frequency_seconds: int) -> datetime:
    if frequency_seconds <= 0:
        raise QDataValidationError("frequency_seconds must be greater than 0")
    return started_at + timedelta(seconds=frequency_seconds)


def format_scheduler_report(result: MuSchedulerResult) -> str:
    lines = [
        (
            f"mu_scheduler scheduler_id={result.scheduler_id} status={result.status} scans={result.scan_count} "
            f"ticks={len(result.tick_results)} duration_ms={result.duration_ms}"
        )
    ]
    for tick in result.tick_results:
        lines.append(
            f"tick schedule={tick.schedule_code} task={tick.task_name} status={tick.status} "
            f"lock_acquired={tick.lock_acquired} worker_run_id={tick.worker_run_id} duration_ms={tick.duration_ms}"
        )
        if tick.error_message:
            lines.append(f"tick_error schedule={tick.schedule_code} message={tick.error_message}")
    return "\n".join(lines)


def force_schedule_due(postgres_dsn: str | None, schedule_code: str) -> dict[str, Any]:
    dsn = _require_dsn(postgres_dsn)
    with _connect_required(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.worker_schedule
                SET next_run_at = now(), status = 'active', updated_at = now()
                WHERE schedule_code = %s
                RETURNING schedule_id, schedule_code, task_name, status, next_run_at
                """,
                (schedule_code,),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"worker schedule not found: {schedule_code}")
            return normalize_row(dict(row))


def default_scheduler_id() -> str:
    return f"mu-{socket.gethostname()}-{os.getpid()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _run_schedule_tick(
    postgres_dsn: str,
    scheduler_id: str,
    schedule: dict[str, Any],
    *,
    dry_run: bool | None,
    trade_date: str | None,
    start_date: str | None,
    end_date: str | None,
) -> MuTickResult:
    schedule_code = schedule["schedule_code"]
    task_name = schedule["task_name"]
    lock_name = f"worker_schedule:{schedule_code}"
    worker_kwargs = build_worker_kwargs(schedule, dry_run=dry_run, trade_date=trade_date, start_date=start_date, end_date=end_date)
    started_at = datetime.now(timezone.utc)
    tick_id = _insert_tick(postgres_dsn, scheduler_id, schedule, lock_name, worker_kwargs["dry_run"])
    _upsert_heartbeat(postgres_dsn, scheduler_id, "running", None, None, schedule_code, {"tick_id": tick_id})
    lock_acquired = _acquire_lock(postgres_dsn, lock_name, scheduler_id, int(schedule["lock_timeout_seconds"]), {"schedule_code": schedule_code, "task_name": task_name})
    if not lock_acquired:
        result = MuTickResult(
            schedule_code=schedule_code,
            task_name=task_name,
            status="skipped_locked",
            tick_id=tick_id,
            lock_acquired=False,
            duration_ms=_duration_ms(started_at),
            details={"reason": "lock is held by another scheduler"},
        )
        _finish_tick(postgres_dsn, tick_id, result)
        return result
    try:
        worker_result = run_lambda_worker(
            postgres_dsn,
            task_names=[task_name],
            trigger_mode="scheduled",
            **worker_kwargs,
        )
        status = worker_result.status
        details = {"worker": _worker_result_dict(worker_result), "next_run_at": compute_next_run_at(started_at, int(schedule["frequency_seconds"])).isoformat()}
        result = MuTickResult(
            schedule_code=schedule_code,
            task_name=task_name,
            status=status,
            tick_id=tick_id,
            worker_run_id=worker_result.worker_run_id,
            lock_acquired=True,
            duration_ms=_duration_ms(started_at),
            details=details,
        )
        _finish_schedule(postgres_dsn, schedule, status, worker_result.worker_run_id, started_at, result.details or {})
        _finish_tick(postgres_dsn, tick_id, result)
        return result
    except Exception as exc:
        result = MuTickResult(
            schedule_code=schedule_code,
            task_name=task_name,
            status="failed",
            tick_id=tick_id,
            lock_acquired=True,
            duration_ms=_duration_ms(started_at),
            error_message=str(exc),
            details={"retry_next_run_at": (started_at + timedelta(seconds=int(schedule["retry_backoff_seconds"]))).isoformat()},
        )
        _finish_schedule_failure(postgres_dsn, schedule, str(exc), started_at, result.details or {})
        _finish_tick(postgres_dsn, tick_id, result)
        return result
    finally:
        _release_lock(postgres_dsn, lock_name, scheduler_id)


def _fetch_due_schedules(
    postgres_dsn: str,
    schedule_codes: list[str] | None,
    task_names: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    where = ["status = 'active'", "(next_run_at IS NULL OR next_run_at <= now())"]
    values: list[Any] = []
    if schedule_codes:
        where.append(f"schedule_code IN ({', '.join(['%s'] * len(schedule_codes))})")
        values.extend(schedule_codes)
    if task_names:
        where.append(f"task_name IN ({', '.join(['%s'] * len(task_names))})")
        values.extend(task_names)
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    schedule_id, schedule_code, task_name, status, frequency_seconds,
                    max_runtime_seconds, lock_timeout_seconds, retry_limit,
                    retry_backoff_seconds, dry_run, task_args, last_worker_run_id,
                    last_status, last_run_at, next_run_at, run_count,
                    success_count, warning_count, failed_count, details
                FROM qmeta.worker_schedule
                WHERE {' AND '.join(where)}
                ORDER BY next_run_at NULLS FIRST, schedule_code
                LIMIT %s
                """,
                tuple(values + [limit]),
            )
            return [dict(row) for row in cursor.fetchall()]


def _insert_tick(postgres_dsn: str, scheduler_id: str, schedule: dict[str, Any], lock_name: str, dry_run: bool) -> int:
    tick_code = f"mu-tick-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.worker_schedule_tick (
                    tick_code, scheduler_id, schedule_id, schedule_code, task_name,
                    status, due_at, lock_name, dry_run, details
                ) VALUES (%s, %s, %s, %s, %s, 'running', %s, %s, %s, %s::jsonb)
                RETURNING tick_id
                """,
                (
                    tick_code,
                    scheduler_id,
                    schedule["schedule_id"],
                    schedule["schedule_code"],
                    schedule["task_name"],
                    schedule.get("next_run_at"),
                    lock_name,
                    dry_run,
                    _json({"task_args": schedule.get("task_args") or {}}),
                ),
            )
            return int(cursor.fetchone()["tick_id"])


def _finish_tick(postgres_dsn: str, tick_id: int, result: MuTickResult) -> None:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.worker_schedule_tick
                SET status = %s,
                    finished_at = now(),
                    duration_ms = %s,
                    worker_run_id = %s,
                    lock_acquired = %s,
                    details = %s::jsonb,
                    error_message = %s,
                    updated_at = now()
                WHERE tick_id = %s
                """,
                (
                    result.status,
                    result.duration_ms,
                    result.worker_run_id,
                    result.lock_acquired,
                    _json(result.details or {}),
                    result.error_message,
                    tick_id,
                ),
            )


def _finish_schedule(
    postgres_dsn: str,
    schedule: dict[str, Any],
    status: str,
    worker_run_id: int | None,
    started_at: datetime,
    details: dict[str, Any],
) -> None:
    next_run_at = compute_next_run_at(started_at, int(schedule["frequency_seconds"]))
    success_increment = 1 if status == "success" else 0
    warning_increment = 1 if status == "warning" else 0
    failed_increment = 1 if status == "failed" else 0
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.worker_schedule
                SET last_worker_run_id = %s,
                    last_status = %s,
                    last_run_at = now(),
                    next_run_at = %s,
                    run_count = run_count + 1,
                    success_count = success_count + %s,
                    warning_count = warning_count + %s,
                    failed_count = failed_count + %s,
                    details = %s::jsonb,
                    updated_at = now()
                WHERE schedule_id = %s
                """,
                (
                    worker_run_id,
                    status,
                    next_run_at,
                    success_increment,
                    warning_increment,
                    failed_increment,
                    _json(details),
                    schedule["schedule_id"],
                ),
            )


def _finish_schedule_failure(postgres_dsn: str, schedule: dict[str, Any], error_message: str, started_at: datetime, details: dict[str, Any]) -> None:
    retry_delay = int(schedule.get("retry_backoff_seconds") or 0)
    next_run_at = started_at + timedelta(seconds=retry_delay if retry_delay > 0 else int(schedule["frequency_seconds"]))
    payload = dict(details)
    payload["error_message"] = error_message
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.worker_schedule
                SET last_status = 'failed',
                    last_run_at = now(),
                    next_run_at = %s,
                    run_count = run_count + 1,
                    failed_count = failed_count + 1,
                    details = %s::jsonb,
                    updated_at = now()
                WHERE schedule_id = %s
                """,
                (next_run_at, _json(payload), schedule["schedule_id"]),
            )


def _acquire_lock(postgres_dsn: str, lock_name: str, owner_id: str, lock_timeout_seconds: int, details: dict[str, Any]) -> bool:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.worker_lock (
                    lock_name, owner_id, acquired_at, heartbeat_at, expires_at, details
                ) VALUES (%s, %s, now(), now(), now() + (%s * INTERVAL '1 second'), %s::jsonb)
                ON CONFLICT (lock_name) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id,
                    acquired_at = CASE
                        WHEN qmeta.worker_lock.owner_id = EXCLUDED.owner_id THEN qmeta.worker_lock.acquired_at
                        ELSE now()
                    END,
                    heartbeat_at = now(),
                    expires_at = EXCLUDED.expires_at,
                    details = EXCLUDED.details,
                    updated_at = now()
                WHERE qmeta.worker_lock.owner_id = EXCLUDED.owner_id
                   OR qmeta.worker_lock.expires_at <= now()
                RETURNING lock_name
                """,
                (lock_name, owner_id, lock_timeout_seconds, _json(details)),
            )
            return cursor.fetchone() is not None


def _release_lock(postgres_dsn: str, lock_name: str, owner_id: str) -> None:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM qmeta.worker_lock WHERE lock_name = %s AND owner_id = %s", (lock_name, owner_id))


def _upsert_heartbeat(
    postgres_dsn: str,
    scheduler_id: str,
    status: str,
    tick_count: int | None,
    run_count: int | None,
    current_schedule_code: str | None,
    details: dict[str, Any],
) -> None:
    if status not in SCHEDULER_STATUSES:
        raise QDataValidationError(f"unknown scheduler status: {status}")
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.worker_heartbeat (
                    scheduler_id, status, host_name, process_id, started_at,
                    last_seen_at, current_schedule_code, tick_count, run_count, details
                ) VALUES (%s, %s, %s, %s, now(), now(), %s, COALESCE(%s, 0), COALESCE(%s, 0), %s::jsonb)
                ON CONFLICT (scheduler_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    last_seen_at = now(),
                    stopped_at = CASE WHEN EXCLUDED.status = 'stopped' THEN now() ELSE NULL END,
                    current_schedule_code = EXCLUDED.current_schedule_code,
                    tick_count = COALESCE(%s, qmeta.worker_heartbeat.tick_count),
                    run_count = COALESCE(%s, qmeta.worker_heartbeat.run_count),
                    details = EXCLUDED.details,
                    updated_at = now()
                """,
                (
                    scheduler_id,
                    status,
                    socket.gethostname(),
                    os.getpid(),
                    current_schedule_code,
                    tick_count,
                    run_count,
                    _json(details),
                    tick_count,
                    run_count,
                ),
            )


def _mark_heartbeat_stopped(postgres_dsn: str, scheduler_id: str, tick_count: int, run_count: int) -> None:
    _upsert_heartbeat(postgres_dsn, scheduler_id, "stopped", tick_count, run_count, None, {"stopped": True})


def _worker_result_dict(result: LambdaWorkerResult) -> dict[str, Any]:
    return {
        "run_code": result.run_code,
        "status": result.status,
        "worker_run_id": result.worker_run_id,
        "processed_count": result.processed_count,
        "success_count": result.success_count,
        "warning_count": result.warning_count,
        "failed_count": result.failed_count,
        "duration_ms": result.duration_ms,
        "dry_run": result.dry_run,
    }


def _overall_status(results: list[MuTickResult]) -> str:
    if not results:
        return "skipped"
    if any(item.status == "failed" for item in results):
        return "failed"
    if any(item.status in {"warning", "skipped_locked"} for item in results):
        return "warning"
    if any(item.status == "success" for item in results):
        return "success"
    return "skipped"


def _duration_ms(started_at: datetime) -> int:
    return int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Mu scheduler")
    return postgres_dsn


def _connect_required(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Mu scheduler") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
