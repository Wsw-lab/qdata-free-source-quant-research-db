from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omicron5_vendor_contract import DEFAULT_VENDOR_DATASETS, DEFAULT_VENDOR_SOURCE_CODES


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
MONITOR_SCOPES = {"primary_source", "all_datasets", "full_market"}
STABILITY_STATUSES = {"healthy", "warning", "critical", "blocked", "no_primary_promotion"}
STABILITY_ROLES = {"primary", "watch", "degraded", "blocked"}


def run_vendor_primary_stability_monitor(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    source_code: str = DEFAULT_VENDOR_SOURCE_CODES[0],
    primary_source_code: str = "csv",
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "sigma5",
    trigger_mode: str = "manual",
    environment: str = "local",
    monitor_scope: str = "primary_source",
    lookback_hours: int = 24,
    capacity_window_days: int = 7,
    min_success_rate: float = 0.995,
    max_error_rate: float = 0.005,
    max_latency_p95_ms: float = 2000.0,
    max_timeout_rate: float = 0.01,
    max_cost_units: float = 500.0,
    max_scheduler_lag_minutes: int = 90,
    max_backlog_count: int = 50,
    max_post_promotion_no_applied_count: int = 0,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        monitor_scope=monitor_scope,
        lookback_hours=lookback_hours,
        capacity_window_days=capacity_window_days,
        min_success_rate=min_success_rate,
        max_error_rate=max_error_rate,
        max_latency_p95_ms=max_latency_p95_ms,
        max_timeout_rate=max_timeout_rate,
        max_cost_units=max_cost_units,
        max_scheduler_lag_minutes=max_scheduler_lag_minutes,
        max_backlog_count=max_backlog_count,
        max_post_promotion_no_applied_count=max_post_promotion_no_applied_count,
    )
    snapshot_date = _as_of_date(as_of_date)
    datasets = _normalize_optional_codes(dataset_codes) or list(DEFAULT_VENDOR_DATASETS)
    dsn = _require_dsn(postgres_dsn)
    started_at = datetime.now(timezone.utc)
    rows = _load_stability_inputs(
        dsn,
        as_of_date=snapshot_date,
        source_code=source_code,
        primary_source_code=primary_source_code,
        dataset_codes=datasets,
    )
    dataset_api_metrics = _load_dataset_api_metrics(dsn, lookback_hours=lookback_hours, dataset_codes=datasets)
    api_metrics = _load_api_metrics(dsn, lookback_hours=lookback_hours)
    worker_metrics = _load_worker_metrics(dsn, lookback_hours=lookback_hours)
    scheduler_metrics = _load_scheduler_metrics(dsn)
    post_metrics = _load_post_promotion_metrics(dsn, source_code=source_code, lookback_hours=lookback_hours)
    capacity_metrics = _load_capacity_metrics(dsn, capacity_window_days=capacity_window_days)
    results = build_vendor_primary_stability_dataset_snapshots(
        rows,
        dataset_api_metrics=dataset_api_metrics,
        as_of_date=snapshot_date,
        monitor_scope=monitor_scope,
        min_success_rate=min_success_rate,
        max_error_rate=max_error_rate,
        max_latency_p95_ms=max_latency_p95_ms,
        max_timeout_rate=max_timeout_rate,
        max_cost_units=max_cost_units,
    )
    finished_at = datetime.now(timezone.utc)
    snapshot = build_vendor_primary_stability_snapshot(
        results,
        source_code=source_code,
        primary_source_code=primary_source_code,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        monitor_scope=monitor_scope,
        lookback_hours=lookback_hours,
        capacity_window_days=capacity_window_days,
        min_success_rate=min_success_rate,
        max_error_rate=max_error_rate,
        max_latency_p95_ms=max_latency_p95_ms,
        max_timeout_rate=max_timeout_rate,
        max_cost_units=max_cost_units,
        max_scheduler_lag_minutes=max_scheduler_lag_minutes,
        max_backlog_count=max_backlog_count,
        max_post_promotion_no_applied_count=max_post_promotion_no_applied_count,
        api_metrics=api_metrics,
        worker_metrics=worker_metrics,
        scheduler_metrics=scheduler_metrics,
        post_metrics=post_metrics,
        capacity_metrics=capacity_metrics,
        promotion_id=_first_value(results, "promotion_id"),
        promotion_code=_first_value(results, "promotion_code"),
        post_promotion_monitor_id=post_metrics.get("latest_post_promotion_monitor_id"),
        started_at=started_at,
        finished_at=finished_at,
    )
    if not write_db:
        snapshot["results"] = normalize_rows(results)
        return normalize_rows([snapshot])[0]
    stored = _insert_stability_snapshot(dsn, snapshot)
    stored["results"] = _insert_dataset_snapshots(dsn, stored, results)
    return stored


def build_vendor_primary_stability_dataset_snapshots(
    rows: list[dict[str, Any]],
    *,
    dataset_api_metrics: dict[str, dict[str, Any]] | None = None,
    as_of_date: str | date | None = None,
    monitor_scope: str = "primary_source",
    min_success_rate: float = 0.995,
    max_error_rate: float = 0.005,
    max_latency_p95_ms: float = 2000.0,
    max_timeout_rate: float = 0.01,
    max_cost_units: float = 500.0,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    if monitor_scope not in MONITOR_SCOPES:
        raise QDataValidationError("monitor_scope must be one of: primary_source, all_datasets, full_market")
    metric_map = dataset_api_metrics or {}
    results: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        dataset_code = str(row.get("dataset_code") or "unknown")
        metrics = metric_map.get(dataset_code, {})
        merged = {
            **row,
            "api_request_count": _int_or_zero(metrics.get("api_request_count")),
            "api_failed_count": _int_or_zero(metrics.get("api_failed_count")),
            "api_timeout_count": _int_or_zero(metrics.get("api_timeout_count")),
            "api_latency_p95_ms": _float_or_zero(metrics.get("api_latency_p95_ms")),
            "rows_returned_count": _int_or_zero(metrics.get("rows_returned_count")),
            "cost_units": _float_or_zero(metrics.get("cost_units")),
        }
        evaluation = evaluate_vendor_primary_stability_dataset(
            merged,
            min_success_rate=min_success_rate,
            max_error_rate=max_error_rate,
            max_latency_p95_ms=max_latency_p95_ms,
            max_timeout_rate=max_timeout_rate,
            max_cost_units=max_cost_units,
        )
        request_count = _int_or_zero(merged.get("api_request_count"))
        failed_count = _int_or_zero(merged.get("api_failed_count"))
        timeout_count = _int_or_zero(merged.get("api_timeout_count"))
        api_error_rate = _rate(failed_count, request_count)
        api_timeout_rate = _rate(timeout_count, request_count)
        result = {
            "dataset_snapshot_code": _dataset_snapshot_code(str(row.get("source_code") or "unknown"), dataset_code, evaluation["status"]),
            "source_id": row["source_id"],
            "source_code": row.get("source_code"),
            "dataset_id": row["dataset_id"],
            "dataset_code": dataset_code,
            "primary_source_id": row.get("primary_source_id"),
            "primary_source_code": row.get("primary_source_code"),
            "current_priority_id": row.get("current_priority_id"),
            "as_of_date": snapshot_date.isoformat(),
            "monitor_scope": monitor_scope,
            "status": evaluation["status"],
            "stability_role": evaluation["stability_role"],
            "entitlement_status": row.get("entitlement_status"),
            "allowed_role": row.get("allowed_role"),
            "production_use_allowed": bool(row.get("production_use_allowed")),
            "schema_status": row.get("schema_status"),
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": _int_or_none(row.get("current_priority")),
            "is_primary_route": bool(evaluation["is_primary_route"]),
            "promotion_id": row.get("promotion_id"),
            "promotion_code": row.get("promotion_code"),
            "promotion_status": row.get("promotion_status"),
            "promotion_result_status": row.get("promotion_result_status"),
            "post_promotion_status": row.get("post_promotion_status"),
            "api_request_count": request_count,
            "api_failed_count": failed_count,
            "api_error_rate": api_error_rate,
            "api_success_rate": round(1.0 - api_error_rate, 6) if request_count else 1.0,
            "api_timeout_count": timeout_count,
            "api_timeout_rate": api_timeout_rate,
            "api_latency_p95_ms": _float_or_zero(merged.get("api_latency_p95_ms")),
            "rows_returned_count": _int_or_zero(merged.get("rows_returned_count")),
            "cost_units": _float_or_zero(merged.get("cost_units")),
            "stability_score": evaluation["stability_score"],
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": evaluation["required_actions"],
            "evidence": _dataset_evidence(row, metrics, evaluation),
            "error_message": "; ".join(evaluation["blocking_issues"]) if evaluation["status"] in {"blocked", "critical", "no_primary_promotion"} and evaluation["blocking_issues"] else None,
        }
        results.append(result)
    return results


def evaluate_vendor_primary_stability_dataset(
    row: dict[str, Any],
    *,
    min_success_rate: float = 0.995,
    max_error_rate: float = 0.005,
    max_latency_p95_ms: float = 2000.0,
    max_timeout_rate: float = 0.01,
    max_cost_units: float = 500.0,
) -> dict[str, Any]:
    issues: list[str] = []
    warning_issues: list[str] = []
    critical_issues: list[str] = []
    source_code = row.get("source_code")
    current_primary_source_code = row.get("current_primary_source_code")
    current_priority = _int_or_none(row.get("current_priority"))
    promotion_applied = (
        row.get("promotion_status") == "applied"
        and row.get("promotion_result_status") == "applied"
    )
    is_primary_route = current_primary_source_code == source_code and current_priority == 0

    entitlement_status = row.get("entitlement_status")
    allowed_role = row.get("allowed_role")
    schema_status = row.get("schema_status")
    if entitlement_status != "active":
        issues.append(f"entitlement_not_active:{entitlement_status or 'missing'}")
    if allowed_role not in {"primary_candidate", "primary"}:
        issues.append(f"allowed_role_not_primary:{allowed_role or 'missing'}")
    if not row.get("production_use_allowed"):
        issues.append("production_use_not_allowed")
    if schema_status not in {"validated", "mapped"}:
        warning_issues.append(f"schema_not_validated:{schema_status or 'missing'}")

    if not promotion_applied:
        issues.append(f"pi5_applied_promotion_missing:{row.get('promotion_status') or 'missing'}")
    if not is_primary_route:
        issues.append(f"primary_route_not_active:{current_primary_source_code or 'missing'}/{current_priority if current_priority is not None else 'missing'}")

    request_count = _int_or_zero(row.get("api_request_count"))
    failed_count = _int_or_zero(row.get("api_failed_count"))
    timeout_count = _int_or_zero(row.get("api_timeout_count"))
    error_rate = _rate(failed_count, request_count)
    success_rate = round(1.0 - error_rate, 6) if request_count else 1.0
    timeout_rate = _rate(timeout_count, request_count)
    latency_p95 = _float_or_zero(row.get("api_latency_p95_ms"))
    cost_units = _float_or_zero(row.get("cost_units"))
    if request_count:
        if success_rate < min_success_rate:
            critical_issues.append(f"success_rate_below_sla:{success_rate}")
        if error_rate > max_error_rate:
            critical_issues.append(f"error_rate_high:{error_rate}")
        if timeout_rate > max_timeout_rate:
            critical_issues.append(f"timeout_rate_high:{timeout_rate}")
        if latency_p95 > max_latency_p95_ms:
            critical_issues.append(f"latency_p95_high:{latency_p95}")
    if cost_units > max_cost_units:
        warning_issues.append(f"cost_units_high:{cost_units}")

    if not promotion_applied or not is_primary_route:
        status = "no_primary_promotion"
        role = "watch"
        all_issues = _dedupe(issues + warning_issues + critical_issues)
    elif issues:
        status = "blocked"
        role = "blocked"
        all_issues = _dedupe(issues + warning_issues + critical_issues)
    elif critical_issues:
        status = "critical"
        role = "degraded"
        all_issues = _dedupe(critical_issues + warning_issues)
    elif warning_issues:
        status = "warning"
        role = "primary"
        all_issues = _dedupe(warning_issues)
    else:
        status = "healthy"
        role = "primary"
        all_issues = []
    return {
        "status": status,
        "stability_role": role,
        "is_primary_route": is_primary_route,
        "stability_score": _status_score(status),
        "blocking_issues": all_issues,
        "required_actions": build_vendor_primary_stability_required_actions(all_issues, status),
    }


def build_vendor_primary_stability_snapshot(
    results: list[dict[str, Any]],
    *,
    source_code: str,
    primary_source_code: str,
    as_of_date: str | date | None = None,
    requested_by: str = "sigma5",
    trigger_mode: str = "manual",
    environment: str = "local",
    monitor_scope: str = "primary_source",
    lookback_hours: int = 24,
    capacity_window_days: int = 7,
    min_success_rate: float = 0.995,
    max_error_rate: float = 0.005,
    max_latency_p95_ms: float = 2000.0,
    max_timeout_rate: float = 0.01,
    max_cost_units: float = 500.0,
    max_scheduler_lag_minutes: int = 90,
    max_backlog_count: int = 50,
    max_post_promotion_no_applied_count: int = 0,
    api_metrics: dict[str, Any] | None = None,
    worker_metrics: dict[str, Any] | None = None,
    scheduler_metrics: dict[str, Any] | None = None,
    post_metrics: dict[str, Any] | None = None,
    capacity_metrics: dict[str, Any] | None = None,
    promotion_id: int | None = None,
    promotion_code: str | None = None,
    post_promotion_monitor_id: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot_date = _as_of_date(as_of_date)
    api = api_metrics or {}
    worker = worker_metrics or {}
    scheduler = scheduler_metrics or {}
    post = post_metrics or {}
    capacity = capacity_metrics or {}
    request_count = _int_or_zero(api.get("api_request_count"))
    failed_count = _int_or_zero(api.get("api_failed_count"))
    timeout_count = _int_or_zero(api.get("api_timeout_count"))
    error_rate = _rate(failed_count, request_count)
    timeout_rate = _rate(timeout_count, request_count)
    success_rate = round(1.0 - error_rate, 6) if request_count else 1.0
    latency_p95 = _float_or_zero(api.get("api_latency_p95_ms"))
    cost_units = _float_or_zero(api.get("cost_units"))
    dataset_statuses = [str(result.get("status")) for result in results]
    dataset_issues = _dedupe(issue for result in results for issue in result.get("blocking_issues") or [])
    global_issues = _global_issues(
        request_count=request_count,
        success_rate=success_rate,
        error_rate=error_rate,
        timeout_rate=timeout_rate,
        latency_p95=latency_p95,
        cost_units=cost_units,
        min_success_rate=min_success_rate,
        max_error_rate=max_error_rate,
        max_timeout_rate=max_timeout_rate,
        max_latency_p95_ms=max_latency_p95_ms,
        max_cost_units=max_cost_units,
        worker_failed_count=_int_or_zero(worker.get("worker_failed_count")),
        worker_warning_count=_int_or_zero(worker.get("worker_warning_count")),
        scheduler_lag_minutes=_int_or_zero(scheduler.get("scheduler_lag_minutes")),
        backlog_count=_int_or_zero(scheduler.get("backlog_count")),
        max_scheduler_lag_minutes=max_scheduler_lag_minutes,
        max_backlog_count=max_backlog_count,
        post_promotion_no_applied_count=_int_or_zero(post.get("post_promotion_no_applied_count")),
        post_promotion_rollback_recommended_count=_int_or_zero(post.get("post_promotion_rollback_recommended_count")),
        max_post_promotion_no_applied_count=max_post_promotion_no_applied_count,
        open_capacity_alert_count=_int_or_zero(capacity.get("open_capacity_alert_count")),
        open_critical_capacity_alert_count=_int_or_zero(capacity.get("open_critical_capacity_alert_count")),
    )
    blocking_issues = _dedupe(dataset_issues + global_issues)
    status = _aggregate_status(dataset_statuses, global_issues)
    primary_dataset_count = sum(1 for result in results if result.get("is_primary_route"))
    role = _snapshot_role(status, primary_dataset_count, len(results))
    required_actions = build_vendor_primary_stability_required_actions(blocking_issues, status)
    started = started_at or datetime.now(timezone.utc)
    finished = finished_at or datetime.now(timezone.utc)
    return {
        "snapshot_code": _snapshot_code(source_code, monitor_scope, status),
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "promotion_id": promotion_id,
        "promotion_code": promotion_code,
        "post_promotion_monitor_id": post_promotion_monitor_id,
        "as_of_date": snapshot_date.isoformat(),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "monitor_scope": monitor_scope,
        "status": status,
        "stability_role": role,
        "lookback_hours": lookback_hours,
        "capacity_window_days": capacity_window_days,
        "min_success_rate": min_success_rate,
        "max_error_rate": max_error_rate,
        "max_latency_p95_ms": max_latency_p95_ms,
        "max_timeout_rate": max_timeout_rate,
        "max_cost_units": max_cost_units,
        "max_scheduler_lag_minutes": max_scheduler_lag_minutes,
        "max_backlog_count": max_backlog_count,
        "max_post_promotion_no_applied_count": max_post_promotion_no_applied_count,
        "dataset_count": len(results),
        "primary_dataset_count": primary_dataset_count,
        "healthy_dataset_count": sum(1 for result in results if result.get("status") == "healthy"),
        "warning_dataset_count": sum(1 for result in results if result.get("status") == "warning"),
        "critical_dataset_count": sum(1 for result in results if result.get("status") == "critical"),
        "blocked_dataset_count": sum(1 for result in results if result.get("status") == "blocked"),
        "no_primary_dataset_count": sum(1 for result in results if result.get("status") == "no_primary_promotion"),
        "api_request_count": request_count,
        "api_failed_count": failed_count,
        "api_error_rate": error_rate,
        "api_success_rate": success_rate,
        "api_timeout_count": timeout_count,
        "api_timeout_rate": timeout_rate,
        "api_latency_p95_ms": latency_p95,
        "rows_returned_count": _int_or_zero(api.get("rows_returned_count")),
        "cost_units": cost_units,
        "worker_run_count": _int_or_zero(worker.get("worker_run_count")),
        "worker_failed_count": _int_or_zero(worker.get("worker_failed_count")),
        "worker_warning_count": _int_or_zero(worker.get("worker_warning_count")),
        "scheduler_lag_minutes": _int_or_zero(scheduler.get("scheduler_lag_minutes")),
        "backlog_count": _int_or_zero(scheduler.get("backlog_count")),
        "post_promotion_monitor_count": _int_or_zero(post.get("post_promotion_monitor_count")),
        "post_promotion_no_applied_count": _int_or_zero(post.get("post_promotion_no_applied_count")),
        "post_promotion_rollback_recommended_count": _int_or_zero(post.get("post_promotion_rollback_recommended_count")),
        "open_capacity_alert_count": _int_or_zero(capacity.get("open_capacity_alert_count")),
        "open_critical_capacity_alert_count": _int_or_zero(capacity.get("open_critical_capacity_alert_count")),
        "stability_score": _average_score(results, status),
        "blocking_issues": blocking_issues,
        "required_actions": required_actions,
        "request_payload": {
            "source_code": source_code,
            "primary_source_code": primary_source_code,
            "dataset_codes": [result.get("dataset_code") for result in results],
            "monitor_scope": monitor_scope,
            "lookback_hours": lookback_hours,
            "capacity_window_days": capacity_window_days,
            "thresholds": {
                "min_success_rate": min_success_rate,
                "max_error_rate": max_error_rate,
                "max_latency_p95_ms": max_latency_p95_ms,
                "max_timeout_rate": max_timeout_rate,
                "max_cost_units": max_cost_units,
                "max_scheduler_lag_minutes": max_scheduler_lag_minutes,
                "max_backlog_count": max_backlog_count,
                "max_post_promotion_no_applied_count": max_post_promotion_no_applied_count,
            },
        },
        "response_payload": {
            "status": status,
            "stability_role": role,
            "dataset_count": len(results),
            "primary_dataset_count": primary_dataset_count,
            "no_primary_dataset_count": sum(1 for result in results if result.get("status") == "no_primary_promotion"),
            "api_success_rate": success_rate,
            "cost_units": cost_units,
            "scheduler_lag_minutes": _int_or_zero(scheduler.get("scheduler_lag_minutes")),
        },
        "evidence": {
            "promotion_code": promotion_code,
            "latest_post_promotion_status": post.get("latest_post_promotion_status"),
            "policy": {
                "requires_pi5_applied_promotion": True,
                "requires_source_priority_zero": True,
                "requires_success_rate_gte": min_success_rate,
                "requires_error_rate_lte": max_error_rate,
                "requires_latency_p95_lte_ms": max_latency_p95_ms,
                "requires_cost_lte": max_cost_units,
            },
        },
        "details": {
            "api_metrics": api,
            "worker_metrics": worker,
            "scheduler_metrics": scheduler,
            "post_promotion_metrics": post,
            "capacity_metrics": capacity,
        },
        "error_message": "; ".join(blocking_issues) if status in {"blocked", "critical", "no_primary_promotion"} and blocking_issues else None,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": _duration_ms(started, finished),
    }


def build_vendor_primary_stability_required_actions(issues: list[str], status: str) -> list[str]:
    issue_text = " ".join(issues)
    actions: list[str] = []
    if "pi5_applied_promotion_missing" in issue_text or "primary_route_not_active" in issue_text:
        actions.append("Run Pi-5 in apply mode only after contract, entitlement, full-market pilot and signoff gates are approved.")
    if "entitlement_not_active" in issue_text or "production_use_not_allowed" in issue_text or "allowed_role_not_primary" in issue_text:
        actions.append("Complete Omicron-5 contract and dataset entitlement approval before using this vendor as production primary.")
    if "schema_not_validated" in issue_text:
        actions.append("Validate endpoint schema and field mapping before expanding primary traffic.")
    if "success_rate_below_sla" in issue_text or "error_rate_high" in issue_text or "timeout_rate_high" in issue_text or "latency_p95_high" in issue_text:
        actions.append("Hold primary traffic expansion and review vendor API SLA, timeout, latency and retry evidence.")
    if "cost_units_high" in issue_text:
        actions.append("Review vendor quota and cost envelope before increasing production traffic.")
    if "scheduler_lag_minutes_high" in issue_text or "scheduler_backlog_high" in issue_text:
        actions.append("Increase scheduler capacity or reduce due backlog before relying on hourly production stability checks.")
    if "rho5_no_applied_promotion_pending" in issue_text:
        actions.append("Keep Rho-5 monitoring enabled until an applied Pi-5 promotion is visible in the latest window.")
    if "rho5_rollback_recommended" in issue_text:
        actions.append("Do not expand traffic; review Rho-5 rollback recommendation and prepare fallback route.")
    if "capacity_alert_open" in issue_text:
        actions.append("Resolve open Sigma capacity alerts before declaring the primary vendor stable.")
    if status == "healthy":
        actions.append("Keep Sigma-5 hourly monitoring active and retain fallback source evidence.")
    elif status == "no_primary_promotion":
        actions.append("Sigma-5 is waiting for a real applied primary-source promotion before production SLA can be trusted.")
    elif status == "warning":
        actions.append("Keep the vendor under production watch and clear warning items before further rollout.")
    elif status == "critical":
        actions.append("Freeze expansion and escalate the primary vendor stability incident.")
    elif status == "blocked":
        actions.append("Resolve blocking legal, routing or evidence gaps before declaring primary stability.")
    return _dedupe(actions)


def list_vendor_primary_stability_snapshots(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "vpss.snapshot_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vpss.status"),
            ("stability_role", "vpss.stability_role"),
            ("monitor_scope", "vpss.monitor_scope"),
            ("requested_by", "vpss.requested_by"),
            ("trigger_mode", "vpss.trigger_mode"),
            ("environment", "vpss.environment"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "vpss.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "vpss.as_of_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vpss.snapshot_id, vpss.snapshot_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vppr.promotion_code,
            vppmr.monitor_code AS post_promotion_monitor_code,
            vpss.as_of_at, vpss.as_of_date,
            vpss.requested_by, vpss.trigger_mode,
            vpss.environment, vpss.monitor_scope,
            vpss.status, vpss.stability_role,
            vpss.lookback_hours, vpss.capacity_window_days,
            vpss.dataset_count, vpss.primary_dataset_count,
            vpss.healthy_dataset_count, vpss.warning_dataset_count,
            vpss.critical_dataset_count, vpss.blocked_dataset_count,
            vpss.no_primary_dataset_count,
            vpss.api_request_count, vpss.api_failed_count,
            vpss.api_error_rate, vpss.api_success_rate,
            vpss.api_timeout_count, vpss.api_timeout_rate,
            vpss.api_latency_p95_ms, vpss.rows_returned_count,
            vpss.cost_units, vpss.worker_run_count,
            vpss.worker_failed_count, vpss.worker_warning_count,
            vpss.scheduler_lag_minutes, vpss.backlog_count,
            vpss.post_promotion_monitor_count,
            vpss.post_promotion_no_applied_count,
            vpss.post_promotion_rollback_recommended_count,
            vpss.open_capacity_alert_count,
            vpss.open_critical_capacity_alert_count,
            vpss.stability_score, vpss.blocking_issues,
            vpss.required_actions, vpss.error_message,
            vpss.started_at, vpss.finished_at,
            vpss.duration_ms, vpss.created_at,
            vpss.updated_at
        FROM qmeta.vendor_primary_stability_snapshot vpss
        JOIN qmeta.source_system ss ON ss.source_id = vpss.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vpss.primary_source_id
        LEFT JOIN qmeta.vendor_primary_promotion_run vppr ON vppr.promotion_id = vpss.promotion_id
        LEFT JOIN qmeta.vendor_post_promotion_monitor_run vppmr ON vppmr.monitor_id = vpss.post_promotion_monitor_id
        {where}
        ORDER BY vpss.as_of_at DESC, vpss.snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_primary_stability_datasets(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "vpss.snapshot_code"),
            ("dataset_snapshot_code", "vpsds.dataset_snapshot_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vpsds.status"),
            ("stability_role", "vpsds.stability_role"),
            ("monitor_scope", "vpsds.monitor_scope"),
            ("entitlement_status", "vpsds.entitlement_status"),
            ("allowed_role", "vpsds.allowed_role"),
            ("current_primary_source_code", "vpsds.current_primary_source_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vpsds.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vpsds.dataset_snapshot_id,
            vpss.snapshot_code,
            vpsds.dataset_snapshot_code,
            ss.source_code, ps.source_code AS primary_source_code,
            dc.dataset_code, vpsds.as_of_date,
            vpsds.monitor_scope, vpsds.status,
            vpsds.stability_role, vpsds.entitlement_status,
            vpsds.allowed_role, vpsds.production_use_allowed,
            vpsds.schema_status, vpsds.current_primary_source_code,
            vpsds.current_priority, vpsds.is_primary_route,
            vpsds.promotion_status, vpsds.promotion_result_status,
            vpsds.post_promotion_status,
            vpsds.api_request_count, vpsds.api_failed_count,
            vpsds.api_error_rate, vpsds.api_success_rate,
            vpsds.api_timeout_count, vpsds.api_timeout_rate,
            vpsds.api_latency_p95_ms, vpsds.rows_returned_count,
            vpsds.cost_units, vpsds.stability_score,
            vpsds.blocking_issues, vpsds.required_actions,
            vpsds.error_message, vpsds.created_at,
            vpsds.updated_at
        FROM qmeta.vendor_primary_stability_dataset_snapshot vpsds
        JOIN qmeta.vendor_primary_stability_snapshot vpss ON vpss.snapshot_id = vpsds.snapshot_id
        JOIN qmeta.source_system ss ON ss.source_id = vpsds.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vpsds.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vpsds.primary_source_id
        {where}
        ORDER BY vpsds.created_at DESC, vpsds.dataset_snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_sigma5_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    if isinstance(rows, dict):
        data_rows = rows.get("results") if resource in {"datasets", "results"} else [rows]
    else:
        data_rows = rows
    data_rows = list(data_rows or [])
    lines = [f"sigma5 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_stability_inputs(
    postgres_dsn: str,
    *,
    as_of_date: date,
    source_code: str,
    primary_source_code: str,
    dataset_codes: list[str],
) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        WITH selected_datasets AS (
            SELECT dc.dataset_id, dc.dataset_code
            FROM qmeta.dataset_catalog dc
            WHERE dc.dataset_code = ANY(%s::text[])
              AND dc.is_active IS TRUE
        ),
        vendor_source AS (
            SELECT source_id, source_code
            FROM qmeta.source_system
            WHERE source_code = %s
        ),
        baseline_source AS (
            SELECT source_id, source_code
            FROM qmeta.source_system
            WHERE source_code = %s
        ),
        latest_promotion AS (
            SELECT vppr.*
            FROM qmeta.vendor_primary_promotion_run vppr
            JOIN qmeta.source_system ss ON ss.source_id = vppr.source_id
            LEFT JOIN qmeta.source_system ps ON ps.source_id = vppr.primary_source_id
            WHERE ss.source_code = %s
              AND (ps.source_code = %s OR vppr.primary_source_id IS NULL)
            ORDER BY
                CASE WHEN vppr.status = 'applied' AND vppr.routing_change_applied IS TRUE THEN 0 ELSE 1 END,
                vppr.started_at DESC,
                vppr.promotion_id DESC
            LIMIT 1
        ),
        latest_promotion_result AS (
            SELECT DISTINCT ON (vppdr.dataset_id)
                vppdr.*
            FROM qmeta.vendor_primary_promotion_dataset_result vppdr
            JOIN latest_promotion lp ON lp.promotion_id = vppdr.promotion_id
            ORDER BY vppdr.dataset_id, vppdr.created_at DESC, vppdr.result_id DESC
        ),
        latest_post_result AS (
            SELECT DISTINCT ON (vppdm.dataset_id)
                vppdm.dataset_id, vppdm.status AS post_promotion_status
            FROM qmeta.vendor_post_promotion_dataset_monitor vppdm
            JOIN vendor_source vs ON vs.source_id = vppdm.source_id
            ORDER BY vppdm.dataset_id, vppdm.created_at DESC, vppdm.result_id DESC
        )
        SELECT
            vs.source_id, vs.source_code,
            bs.source_id AS primary_source_id,
            bs.source_code AS primary_source_code,
            sd.dataset_id, sd.dataset_code,
            vcde.entitlement_status,
            vcde.allowed_role,
            COALESCE(vcde.production_use_allowed, FALSE) AS production_use_allowed,
            vcde.schema_status,
            lp.promotion_id,
            lp.promotion_code,
            lp.status AS promotion_status,
            lpr.status AS promotion_result_status,
            current_priority.priority_id AS current_priority_id,
            current_priority.source_code AS current_primary_source_code,
            current_priority.priority AS current_priority,
            lpr.routing_change_applied AS promotion_result_routing_change_applied,
            lpr.promotion_role,
            lpr.routing_change_allowed,
            lpr.target_priority,
            lpost.post_promotion_status
        FROM selected_datasets sd
        CROSS JOIN vendor_source vs
        LEFT JOIN baseline_source bs ON TRUE
        LEFT JOIN qmeta.vendor_contract_dataset_entitlement vcde
            ON vcde.source_id = vs.source_id
           AND vcde.dataset_id = sd.dataset_id
           AND vcde.status = 'active'
        LEFT JOIN latest_promotion lp ON TRUE
        LEFT JOIN latest_promotion_result lpr ON lpr.dataset_id = sd.dataset_id
        LEFT JOIN latest_post_result lpost ON lpost.dataset_id = sd.dataset_id
        LEFT JOIN LATERAL (
            SELECT sp.priority_id, ssp.source_code, sp.priority
            FROM qmeta.source_priority sp
            JOIN qmeta.source_system ssp ON ssp.source_id = sp.source_id
            WHERE sp.dataset_id = sd.dataset_id
              AND sp.effective_date <= %s
              AND (sp.end_date IS NULL OR sp.end_date >= %s)
            ORDER BY sp.priority ASC, sp.effective_date DESC, sp.priority_id DESC
            LIMIT 1
        ) current_priority ON TRUE
        ORDER BY vs.source_code, sd.dataset_code
        """,
        [dataset_codes, source_code, primary_source_code, source_code, primary_source_code, as_of_date, as_of_date],
    )


def _load_dataset_api_metrics(postgres_dsn: str, *, lookback_hours: int, dataset_codes: list[str]) -> dict[str, dict[str, Any]]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        WITH scoped AS (
            SELECT
                COALESCE(
                    NULLIF(request_summary->>'dataset_code', ''),
                    NULLIF(request_summary->>'dataset', ''),
                    NULLIF(request_summary #>> '{query,dataset_code,0}', ''),
                    NULLIF(request_summary #>> '{query,dataset,0}', '')
                ) AS dataset_code,
                status,
                row_count,
                duration_ms,
                cost_units,
                error_message
            FROM qmeta.api_request_audit
            WHERE started_at >= now() - make_interval(hours => %s)
        )
        SELECT
            dataset_code,
            COUNT(*) AS api_request_count,
            COUNT(*) FILTER (WHERE status = 'failed') AS api_failed_count,
            COUNT(*) FILTER (WHERE COALESCE(error_message, '') ILIKE '%%timeout%%') AS api_timeout_count,
            COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY COALESCE(duration_ms, 0)), 0) AS api_latency_p95_ms,
            COALESCE(SUM(row_count), 0) AS rows_returned_count,
            COALESCE(SUM(cost_units), 0) AS cost_units
        FROM scoped
        WHERE dataset_code = ANY(%s::text[])
        GROUP BY dataset_code
        """,
        [lookback_hours, dataset_codes],
    )
    return {str(row["dataset_code"]): row for row in rows}


def _load_api_metrics(postgres_dsn: str, *, lookback_hours: int) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            COUNT(*) AS api_request_count,
            COUNT(*) FILTER (WHERE status = 'failed') AS api_failed_count,
            COUNT(*) FILTER (WHERE COALESCE(error_message, '') ILIKE '%%timeout%%') AS api_timeout_count,
            COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY COALESCE(duration_ms, 0)), 0) AS api_latency_p95_ms,
            COALESCE(SUM(row_count), 0) AS rows_returned_count,
            COALESCE(SUM(cost_units), 0) AS cost_units
        FROM qmeta.api_request_audit
        WHERE started_at >= now() - make_interval(hours => %s)
        """,
        [lookback_hours],
    )
    return rows[0] if rows else {}


def _load_worker_metrics(postgres_dsn: str, *, lookback_hours: int) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            COUNT(*) AS worker_run_count,
            COUNT(*) FILTER (WHERE status = 'failed') AS worker_failed_count,
            COUNT(*) FILTER (WHERE status = 'warning') AS worker_warning_count
        FROM qmeta.worker_task_run
        WHERE task_name IN ('vendor_primary_promotion_review', 'vendor_post_promotion_monitor', 'vendor_primary_stability_monitor')
          AND started_at >= now() - make_interval(hours => %s)
        """,
        [lookback_hours],
    )
    return rows[0] if rows else {}


def _load_scheduler_metrics(postgres_dsn: str) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            COALESCE(MAX(GREATEST(0, EXTRACT(EPOCH FROM (now() - next_run_at)) / 60)) FILTER (WHERE status = 'active' AND next_run_at < now()), 0)::integer AS scheduler_lag_minutes,
            COUNT(*) FILTER (WHERE status = 'active' AND next_run_at < now()) AS backlog_count
        FROM qmeta.worker_schedule
        WHERE task_name IN ('vendor_primary_promotion_review', 'vendor_post_promotion_monitor', 'vendor_primary_stability_monitor')
        """,
        [],
    )
    return rows[0] if rows else {}


def _load_post_promotion_metrics(postgres_dsn: str, *, source_code: str, lookback_hours: int) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        WITH scoped AS (
            SELECT vppmr.*
            FROM qmeta.vendor_post_promotion_monitor_run vppmr
            JOIN qmeta.source_system ss ON ss.source_id = vppmr.source_id
            WHERE ss.source_code = %s
              AND vppmr.started_at >= now() - make_interval(hours => %s)
        ),
        latest AS (
            SELECT *
            FROM qmeta.vendor_post_promotion_monitor_run vppmr
            JOIN qmeta.source_system ss ON ss.source_id = vppmr.source_id
            WHERE ss.source_code = %s
            ORDER BY vppmr.started_at DESC, vppmr.monitor_id DESC
            LIMIT 1
        )
        SELECT
            COUNT(scoped.*) AS post_promotion_monitor_count,
            COALESCE(SUM(scoped.no_applied_dataset_count), 0) AS post_promotion_no_applied_count,
            COALESCE(SUM(scoped.rollback_recommended_count), 0) AS post_promotion_rollback_recommended_count,
            (SELECT monitor_id FROM latest) AS latest_post_promotion_monitor_id,
            (SELECT promotion_id FROM latest) AS latest_post_promotion_promotion_id,
            (SELECT status FROM latest) AS latest_post_promotion_status
        FROM scoped
        """,
        [source_code, lookback_hours, source_code],
    )
    return rows[0] if rows else {}


def _load_capacity_metrics(postgres_dsn: str, *, capacity_window_days: int) -> dict[str, Any]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'open') AS open_capacity_alert_count,
            COUNT(*) FILTER (WHERE status = 'open' AND severity = 'critical') AS open_critical_capacity_alert_count
        FROM qmeta.capacity_alert
        WHERE last_seen_at >= now() - make_interval(days => %s)
        """,
        [capacity_window_days],
    )
    return rows[0] if rows else {}


def _insert_stability_snapshot(postgres_dsn: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, str(snapshot["source_code"]))
            primary_source_id = _lookup_source_id(cursor, str(snapshot["primary_source_code"])) if snapshot.get("primary_source_code") else None
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_primary_stability_snapshot (
                    snapshot_code, source_id, primary_source_id,
                    promotion_id, post_promotion_monitor_id,
                    as_of_date, requested_by, trigger_mode,
                    environment, monitor_scope, status,
                    stability_role, lookback_hours,
                    capacity_window_days, min_success_rate,
                    max_error_rate, max_latency_p95_ms,
                    max_timeout_rate, max_cost_units,
                    max_scheduler_lag_minutes, max_backlog_count,
                    max_post_promotion_no_applied_count,
                    dataset_count, primary_dataset_count,
                    healthy_dataset_count, warning_dataset_count,
                    critical_dataset_count, blocked_dataset_count,
                    no_primary_dataset_count, api_request_count,
                    api_failed_count, api_error_rate,
                    api_success_rate, api_timeout_count,
                    api_timeout_rate, api_latency_p95_ms,
                    rows_returned_count, cost_units,
                    worker_run_count, worker_failed_count,
                    worker_warning_count, scheduler_lag_minutes,
                    backlog_count, post_promotion_monitor_count,
                    post_promotion_no_applied_count,
                    post_promotion_rollback_recommended_count,
                    open_capacity_alert_count,
                    open_critical_capacity_alert_count,
                    stability_score, blocking_issues,
                    required_actions, request_payload,
                    response_payload, evidence, details,
                    error_message, started_at, finished_at,
                    duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s, %s,
                    %s, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    snapshot["snapshot_code"],
                    source_id,
                    primary_source_id,
                    snapshot.get("promotion_id"),
                    snapshot.get("post_promotion_monitor_id"),
                    snapshot["as_of_date"],
                    snapshot["requested_by"],
                    snapshot["trigger_mode"],
                    snapshot["environment"],
                    snapshot["monitor_scope"],
                    snapshot["status"],
                    snapshot["stability_role"],
                    snapshot["lookback_hours"],
                    snapshot["capacity_window_days"],
                    snapshot["min_success_rate"],
                    snapshot["max_error_rate"],
                    snapshot["max_latency_p95_ms"],
                    snapshot["max_timeout_rate"],
                    snapshot["max_cost_units"],
                    snapshot["max_scheduler_lag_minutes"],
                    snapshot["max_backlog_count"],
                    snapshot["max_post_promotion_no_applied_count"],
                    snapshot["dataset_count"],
                    snapshot["primary_dataset_count"],
                    snapshot["healthy_dataset_count"],
                    snapshot["warning_dataset_count"],
                    snapshot["critical_dataset_count"],
                    snapshot["blocked_dataset_count"],
                    snapshot["no_primary_dataset_count"],
                    snapshot["api_request_count"],
                    snapshot["api_failed_count"],
                    snapshot["api_error_rate"],
                    snapshot["api_success_rate"],
                    snapshot["api_timeout_count"],
                    snapshot["api_timeout_rate"],
                    snapshot["api_latency_p95_ms"],
                    snapshot["rows_returned_count"],
                    snapshot["cost_units"],
                    snapshot["worker_run_count"],
                    snapshot["worker_failed_count"],
                    snapshot["worker_warning_count"],
                    snapshot["scheduler_lag_minutes"],
                    snapshot["backlog_count"],
                    snapshot["post_promotion_monitor_count"],
                    snapshot["post_promotion_no_applied_count"],
                    snapshot["post_promotion_rollback_recommended_count"],
                    snapshot["open_capacity_alert_count"],
                    snapshot["open_critical_capacity_alert_count"],
                    snapshot["stability_score"],
                    snapshot["blocking_issues"],
                    snapshot["required_actions"],
                    _json(snapshot["request_payload"]),
                    _json(snapshot["response_payload"]),
                    _json(snapshot["evidence"]),
                    _json(snapshot["details"]),
                    snapshot.get("error_message"),
                    snapshot["started_at"],
                    snapshot["finished_at"],
                    snapshot["duration_ms"],
                ),
            )
            stored = normalize_rows([dict(cursor.fetchone())])[0]
            stored["source_code"] = snapshot["source_code"]
            stored["primary_source_code"] = snapshot.get("primary_source_code")
            stored["promotion_code"] = snapshot.get("promotion_code")
            return stored


def _insert_dataset_snapshots(postgres_dsn: str, snapshot: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for result in results:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_primary_stability_dataset_snapshot (
                        dataset_snapshot_code, snapshot_id,
                        source_id, dataset_id, primary_source_id,
                        current_priority_id, as_of_date,
                        monitor_scope, status, stability_role,
                        entitlement_status, allowed_role,
                        production_use_allowed, schema_status,
                        current_primary_source_code, current_priority,
                        is_primary_route, promotion_status,
                        promotion_result_status, post_promotion_status,
                        api_request_count, api_failed_count,
                        api_error_rate, api_success_rate,
                        api_timeout_count, api_timeout_rate,
                        api_latency_p95_ms, rows_returned_count,
                        cost_units, stability_score,
                        blocking_issues, required_actions,
                        evidence, error_message, updated_at
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s::jsonb, %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        result["dataset_snapshot_code"],
                        snapshot["snapshot_id"],
                        result["source_id"],
                        result["dataset_id"],
                        result.get("primary_source_id"),
                        result.get("current_priority_id"),
                        result["as_of_date"],
                        result["monitor_scope"],
                        result["status"],
                        result["stability_role"],
                        result.get("entitlement_status"),
                        result.get("allowed_role"),
                        result["production_use_allowed"],
                        result.get("schema_status"),
                        result.get("current_primary_source_code"),
                        result.get("current_priority"),
                        result["is_primary_route"],
                        result.get("promotion_status"),
                        result.get("promotion_result_status"),
                        result.get("post_promotion_status"),
                        result["api_request_count"],
                        result["api_failed_count"],
                        result["api_error_rate"],
                        result["api_success_rate"],
                        result["api_timeout_count"],
                        result["api_timeout_rate"],
                        result["api_latency_p95_ms"],
                        result["rows_returned_count"],
                        result["cost_units"],
                        result["stability_score"],
                        result["blocking_issues"],
                        result["required_actions"],
                        _json(result["evidence"]),
                        result.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row["snapshot_code"] = snapshot["snapshot_code"]
                row["source_code"] = result.get("source_code")
                row["dataset_code"] = result.get("dataset_code")
                row["primary_source_code"] = result.get("primary_source_code")
                inserted.append(row)
    return inserted


def _dataset_evidence(row: dict[str, Any], metrics: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "entitlement": {
            "status": row.get("entitlement_status"),
            "allowed_role": row.get("allowed_role"),
            "production_use_allowed": bool(row.get("production_use_allowed")),
            "schema_status": row.get("schema_status"),
        },
        "routing": {
            "promoted_source_code": row.get("source_code"),
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": _int_or_none(row.get("current_priority")),
            "is_primary_route": bool(evaluation.get("is_primary_route")),
        },
        "promotion": {
            "promotion_code": row.get("promotion_code"),
            "promotion_status": row.get("promotion_status"),
            "promotion_result_status": row.get("promotion_result_status"),
            "post_promotion_status": row.get("post_promotion_status"),
        },
        "api_metrics": metrics,
    }


def _global_issues(
    *,
    request_count: int,
    success_rate: float,
    error_rate: float,
    timeout_rate: float,
    latency_p95: float,
    cost_units: float,
    min_success_rate: float,
    max_error_rate: float,
    max_timeout_rate: float,
    max_latency_p95_ms: float,
    max_cost_units: float,
    worker_failed_count: int,
    worker_warning_count: int,
    scheduler_lag_minutes: int,
    backlog_count: int,
    max_scheduler_lag_minutes: int,
    max_backlog_count: int,
    post_promotion_no_applied_count: int,
    post_promotion_rollback_recommended_count: int,
    max_post_promotion_no_applied_count: int,
    open_capacity_alert_count: int,
    open_critical_capacity_alert_count: int,
) -> list[str]:
    issues: list[str] = []
    if request_count:
        if success_rate < min_success_rate:
            issues.append(f"success_rate_below_sla:{success_rate}")
        if error_rate > max_error_rate:
            issues.append(f"error_rate_high:{error_rate}")
        if timeout_rate > max_timeout_rate:
            issues.append(f"timeout_rate_high:{timeout_rate}")
        if latency_p95 > max_latency_p95_ms:
            issues.append(f"latency_p95_high:{latency_p95}")
    if cost_units > max_cost_units:
        issues.append(f"cost_units_high:{cost_units}")
    if worker_failed_count:
        issues.append(f"worker_failed_count:{worker_failed_count}")
    if worker_warning_count:
        issues.append(f"worker_warning_count:{worker_warning_count}")
    if scheduler_lag_minutes > max_scheduler_lag_minutes:
        issues.append(f"scheduler_lag_minutes_high:{scheduler_lag_minutes}")
    if backlog_count > max_backlog_count:
        issues.append(f"scheduler_backlog_high:{backlog_count}")
    if post_promotion_no_applied_count > max_post_promotion_no_applied_count:
        issues.append(f"rho5_no_applied_promotion_pending:{post_promotion_no_applied_count}")
    if post_promotion_rollback_recommended_count:
        issues.append(f"rho5_rollback_recommended:{post_promotion_rollback_recommended_count}")
    if open_critical_capacity_alert_count:
        issues.append(f"capacity_alert_open_critical:{open_critical_capacity_alert_count}")
    elif open_capacity_alert_count:
        issues.append(f"capacity_alert_open:{open_capacity_alert_count}")
    return _dedupe(issues)


def _aggregate_status(dataset_statuses: list[str], global_issues: list[str]) -> str:
    global_text = " ".join(global_issues)
    if any(token in global_text for token in ["success_rate_below_sla", "error_rate_high", "timeout_rate_high", "latency_p95_high", "rho5_rollback_recommended", "capacity_alert_open_critical"]):
        return "critical"
    unique = set(dataset_statuses)
    if unique and unique <= {"no_primary_promotion"}:
        return "no_primary_promotion"
    if "critical" in unique:
        return "critical"
    if "blocked" in unique:
        return "blocked"
    if global_issues or "warning" in unique or "no_primary_promotion" in unique:
        return "warning"
    if unique <= {"healthy"} and unique:
        return "healthy"
    return "blocked"


def _snapshot_role(status: str, primary_dataset_count: int, dataset_count: int) -> str:
    if status == "blocked":
        return "blocked"
    if dataset_count and primary_dataset_count == dataset_count and status in {"healthy", "warning"}:
        return "primary"
    if primary_dataset_count:
        return "degraded"
    return "watch"


def _average_score(results: list[dict[str, Any]], status: str) -> float:
    if not results:
        return _status_score(status)
    return round(sum(float(result.get("stability_score") or 0) for result in results) / len(results), 4)


def _status_score(status: str) -> float:
    return {
        "healthy": 100.0,
        "warning": 70.0,
        "critical": 35.0,
        "blocked": 0.0,
        "no_primary_promotion": 0.0,
    }.get(status, 0.0)


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
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _report_keys(row: dict[str, Any]) -> list[str]:
    preferred = [
        "snapshot_code",
        "dataset_snapshot_code",
        "source_code",
        "dataset_code",
        "primary_source_code",
        "status",
        "stability_role",
        "monitor_scope",
        "dataset_count",
        "primary_dataset_count",
        "healthy_dataset_count",
        "warning_dataset_count",
        "critical_dataset_count",
        "blocked_dataset_count",
        "no_primary_dataset_count",
        "api_request_count",
        "api_success_rate",
        "api_error_rate",
        "api_latency_p95_ms",
        "cost_units",
        "scheduler_lag_minutes",
        "backlog_count",
        "post_promotion_no_applied_count",
        "post_promotion_rollback_recommended_count",
        "stability_score",
    ]
    return [key for key in preferred if key in row] + [key for key in row.keys() if key not in preferred]


def _snapshot_code(source_code: str, monitor_scope: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{monitor_scope}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"sigma5-primary-stability-{source_code}-{monitor_scope}-{status}-{digest}"[:180]


def _dataset_snapshot_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"sigma5-primary-stability-dataset-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    monitor_scope: str,
    lookback_hours: int,
    capacity_window_days: int,
    min_success_rate: float,
    max_error_rate: float,
    max_latency_p95_ms: float,
    max_timeout_rate: float,
    max_cost_units: float,
    max_scheduler_lag_minutes: int,
    max_backlog_count: int,
    max_post_promotion_no_applied_count: int,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, once, smoke, api")
    if monitor_scope not in MONITOR_SCOPES:
        raise QDataValidationError("monitor_scope must be one of: primary_source, all_datasets, full_market")
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    if capacity_window_days <= 0:
        raise QDataValidationError("capacity_window_days must be greater than 0")
    if not 0 <= min_success_rate <= 1:
        raise QDataValidationError("min_success_rate must be between 0 and 1")
    if not 0 <= max_error_rate <= 1:
        raise QDataValidationError("max_error_rate must be between 0 and 1")
    if max_latency_p95_ms < 0:
        raise QDataValidationError("max_latency_p95_ms must be greater than or equal to 0")
    if not 0 <= max_timeout_rate <= 1:
        raise QDataValidationError("max_timeout_rate must be between 0 and 1")
    if max_cost_units < 0:
        raise QDataValidationError("max_cost_units must be greater than or equal to 0")
    if max_scheduler_lag_minutes < 0:
        raise QDataValidationError("max_scheduler_lag_minutes must be greater than or equal to 0")
    if max_backlog_count < 0:
        raise QDataValidationError("max_backlog_count must be greater than or equal to 0")
    if max_post_promotion_no_applied_count < 0:
        raise QDataValidationError("max_post_promotion_no_applied_count must be greater than or equal to 0")


def _normalize_optional_codes(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = _dedupe(str(value).strip() for value in values if str(value).strip())
    return normalized or None


def _as_of_date(value: str | date | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        return parse_date(value, "as_of_date")
    return datetime.now(timezone.utc).date()


def _first_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _int_or_zero(value: Any) -> int:
    parsed = _int_or_none(value)
    return 0 if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return 0.0 if parsed is None else parsed


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _lookup_source_id(cursor, source_code: str) -> int:
    cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = %s", (source_code,))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"source not found: {source_code}")
    return int(row["source_id"])


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required")
    return postgres_dsn


def _connect_required(postgres_dsn: str | None):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Sigma-5 primary stability monitor") from exc
    return psycopg.connect(_require_dsn(postgres_dsn), row_factory=dict_row)
