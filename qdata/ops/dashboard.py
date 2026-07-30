from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from typing import Any, Iterable

from qdata.backend_utils import date_range, normalize_rows
from qdata.exceptions import QDataValidationError


def build_ops_dashboard(
    postgres_dsn: str,
    start_date: str,
    end_date: str,
    job_code: str | None = None,
    dataset_code: str | None = None,
) -> dict[str, Any]:
    date_range(start_date, end_date)
    with _connect(postgres_dsn) as connection:
        runs = _fetch_pipeline_runs(connection, start_date, end_date, job_code, dataset_code)
        repairs = _fetch_repair_items(connection, start_date, end_date, job_code, dataset_code)
        watermarks = _fetch_watermarks(connection, job_code, dataset_code)
        quality_checks = _fetch_quality_checks(connection, start_date, end_date, dataset_code)
        multi_source = _fetch_multi_source_quality(connection, start_date, end_date, dataset_code)
        conflicts = _fetch_conflict_rollup(connection, start_date, end_date, dataset_code)
        api_audits = _fetch_api_audit_rollup(connection, start_date, end_date)
        alerts = _fetch_alerts(connection, start_date, end_date, job_code, dataset_code)

    pipeline_summary = build_pipeline_summary(runs, repairs, watermarks)
    quality_summary = build_quality_summary(quality_checks, multi_source, conflicts)
    api_summary = build_api_summary(api_audits)
    alert_summary = build_alert_summary(alerts)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "job_code": job_code,
        "dataset_code": dataset_code,
        "pipeline": pipeline_summary,
        "quality": quality_summary,
        "api": api_summary,
        "alerts": alert_summary,
        "raw": {
            "runs": runs,
            "repairs": repairs,
            "watermarks": watermarks,
            "quality_checks": quality_checks,
            "multi_source": multi_source,
            "conflicts": conflicts,
            "api_audits": api_audits,
            "alerts": alerts,
        },
    }


def build_pipeline_summary(
    runs: list[dict[str, Any]],
    repairs: list[dict[str, Any]] | None = None,
    watermarks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status_counts = _counter(row.get("status") for row in runs)
    repair_status_counts = _counter(row.get("status") for row in repairs or [])
    missing_total = sum(int(row.get("missing_count") or 0) for row in runs)
    open_repairs = sum(1 for row in repairs or [] if row.get("status") == "open")
    completeness_values = [
        float(row["completeness_rate"])
        for row in runs
        if row.get("completeness_rate") is not None
    ]
    duration_values = [
        int(row["duration_ms"])
        for row in runs
        if row.get("duration_ms") is not None
    ]
    return {
        "run_count": len(runs),
        "status_counts": status_counts,
        "latest_status": runs[-1]["status"] if runs else None,
        "missing_total": missing_total,
        "min_completeness": min(completeness_values) if completeness_values else None,
        "median_duration_ms": _median(duration_values),
        "repair_status_counts": repair_status_counts,
        "open_repair_count": open_repairs,
        "watermarks": watermarks or [],
    }


def build_quality_summary(
    quality_checks: list[dict[str, Any]],
    multi_source: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    severity_counts = _counter(row.get("severity") for row in quality_checks)
    check_status_counts = _counter(row.get("status") for row in quality_checks)
    conflict_status_counts = _weighted_counter(conflicts, "status", "count")
    conflict_severity_counts = _weighted_counter(conflicts, "severity", "count")
    conflict_count = sum(int(row.get("count") or 0) for row in conflicts)
    max_conflict_rate = max(
        (float(row["conflict_rate"]) for row in multi_source if row.get("conflict_rate") is not None),
        default=None,
    )
    min_coverage_rate = min(
        (float(row["coverage_rate"]) for row in multi_source if row.get("coverage_rate") is not None),
        default=None,
    )
    warning_days = sorted({
        row["trade_date"]
        for row in multi_source
        if row.get("status") in {"warning", "failed"}
    })
    return {
        "quality_check_count": len(quality_checks),
        "quality_status_counts": check_status_counts,
        "quality_severity_counts": severity_counts,
        "multi_source_count": len(multi_source),
        "max_conflict_rate": max_conflict_rate,
        "min_coverage_rate": min_coverage_rate,
        "multi_source_warning_days": warning_days,
        "conflict_count": conflict_count,
        "conflict_status_counts": conflict_status_counts,
        "conflict_severity_counts": conflict_severity_counts,
    }


def build_api_summary(api_audits: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(int(row.get("count") or 0) for row in api_audits)
    failed = sum(int(row.get("count") or 0) for row in api_audits if row.get("status") == "failed")
    by_api = defaultdict(int)
    by_status = defaultdict(int)
    slowest = []
    for row in api_audits:
        count = int(row.get("count") or 0)
        by_api[row.get("api_name") or "unknown"] += count
        by_status[row.get("status") or "unknown"] += count
        if row.get("max_duration_ms") is not None:
            slowest.append(
                {
                    "api_name": row.get("api_name"),
                    "max_duration_ms": int(row["max_duration_ms"]),
                    "date": row.get("request_date"),
                }
            )
    slowest.sort(key=lambda item: item["max_duration_ms"], reverse=True)
    return {
        "request_count": total,
        "failed_count": failed,
        "error_rate": round(failed / total, 8) if total else 0,
        "api_counts": dict(sorted(by_api.items())),
        "status_counts": dict(sorted(by_status.items())),
        "slowest": slowest[:5],
    }


def build_alert_summary(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "alert_count": len(alerts),
        "open_alert_count": sum(1 for row in alerts if row.get("status") == "open"),
        "status_counts": _counter(row.get("status") for row in alerts),
        "severity_counts": _counter(row.get("severity") for row in alerts),
        "type_counts": _counter(row.get("alert_type") for row in alerts),
    }


def evaluate_sla_records(
    policies: list[dict[str, Any]],
    pipeline_runs: list[dict[str, Any]],
    multi_source_quality: list[dict[str, Any]],
    api_summary_by_date: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    vendor_quality_scores: list[dict[str, Any]] | None = None,
    provider_error_counts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    date_range(start_date, end_date)
    runs_by_job_date = {
        (row.get("job_id"), row.get("trade_date")): row
        for row in pipeline_runs
        if row.get("job_id") is not None and row.get("trade_date")
    }
    conflict_by_dataset_date = {
        (row.get("dataset_id"), row.get("trade_date")): row
        for row in multi_source_quality
        if row.get("dataset_id") is not None and row.get("trade_date")
    }
    api_by_date = {row.get("request_date"): row for row in api_summary_by_date}
    vendor_quality_by_source_dataset_date = {
        (row.get("source_id"), row.get("dataset_id"), row.get("score_date")): row
        for row in vendor_quality_scores or []
        if row.get("source_id") is not None and row.get("dataset_id") is not None and row.get("score_date")
    }
    provider_errors_by_source_dataset_date = {
        (row.get("source_id"), row.get("dataset_id"), row.get("trade_date")): row
        for row in provider_error_counts or []
        if row.get("source_id") is not None and row.get("dataset_id") is not None and row.get("trade_date")
    }
    alerts: list[dict[str, Any]] = []
    for policy in policies:
        if policy.get("is_active") is False:
            continue
        for current_date in _iter_dates(start_date, end_date):
            trade_date = current_date.isoformat()
            alerts.extend(_evaluate_pipeline_policy(policy, runs_by_job_date, trade_date))
            alerts.extend(_evaluate_conflict_policy(policy, conflict_by_dataset_date, trade_date))
            alerts.extend(_evaluate_api_policy(policy, api_by_date, trade_date))
            alerts.extend(_evaluate_vendor_quality_policy(policy, vendor_quality_by_source_dataset_date, trade_date))
            alerts.extend(_evaluate_provider_error_policy(policy, provider_errors_by_source_dataset_date, trade_date))
    return alerts


def ensure_sla_policy(
    postgres_dsn: str,
    *,
    policy_code: str,
    policy_name: str,
    dataset_code: str | None = None,
    job_code: str | None = None,
    source_code: str | None = None,
    target_finish_time: str | None = None,
    min_completeness: float | None = None,
    max_conflict_rate: float | None = None,
    max_api_error_rate: float | None = None,
    max_duration_ms: int | None = None,
    min_vendor_score: float | None = None,
    max_vendor_conflict_rate: float | None = None,
    max_vendor_failure_rate: float | None = None,
    max_vendor_latency_ms: float | None = None,
    max_provider_error_count: int | None = None,
    alert_severity: str = "high",
    owner: str | None = "qdata",
    description: str | None = None,
) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        dataset_id = _lookup_id(connection, "dataset", dataset_code)
        job_id = _lookup_id(connection, "job", job_code)
        source_id = _lookup_id(connection, "source", source_code)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.sla_policy (
                    policy_code, policy_name, dataset_id, job_id, source_id,
                    target_finish_time, min_completeness, max_conflict_rate,
                    max_api_error_rate, max_duration_ms, min_vendor_score,
                    max_vendor_conflict_rate, max_vendor_failure_rate,
                    max_vendor_latency_ms, max_provider_error_count,
                    alert_severity, owner, description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (policy_code) DO UPDATE SET
                    policy_name = EXCLUDED.policy_name,
                    dataset_id = EXCLUDED.dataset_id,
                    job_id = EXCLUDED.job_id,
                    source_id = EXCLUDED.source_id,
                    target_finish_time = EXCLUDED.target_finish_time,
                    min_completeness = EXCLUDED.min_completeness,
                    max_conflict_rate = EXCLUDED.max_conflict_rate,
                    max_api_error_rate = EXCLUDED.max_api_error_rate,
                    max_duration_ms = EXCLUDED.max_duration_ms,
                    min_vendor_score = EXCLUDED.min_vendor_score,
                    max_vendor_conflict_rate = EXCLUDED.max_vendor_conflict_rate,
                    max_vendor_failure_rate = EXCLUDED.max_vendor_failure_rate,
                    max_vendor_latency_ms = EXCLUDED.max_vendor_latency_ms,
                    max_provider_error_count = EXCLUDED.max_provider_error_count,
                    alert_severity = EXCLUDED.alert_severity,
                    owner = EXCLUDED.owner,
                    description = EXCLUDED.description,
                    is_active = TRUE,
                    updated_at = now()
                RETURNING *
                """,
                (
                    policy_code,
                    policy_name,
                    dataset_id,
                    job_id,
                    source_id,
                    target_finish_time,
                    min_completeness,
                    max_conflict_rate,
                    max_api_error_rate,
                    max_duration_ms,
                    min_vendor_score,
                    max_vendor_conflict_rate,
                    max_vendor_failure_rate,
                    max_vendor_latency_ms,
                    max_provider_error_count,
                    alert_severity,
                    owner,
                    description,
                ),
            )
            row = dict(cursor.fetchone())
    return _normalize(row)


def evaluate_sla(
    postgres_dsn: str,
    start_date: str,
    end_date: str,
    policy_code: str | None = None,
    job_code: str | None = None,
    dataset_code: str | None = None,
) -> list[dict[str, Any]]:
    date_range(start_date, end_date)
    with _connect(postgres_dsn) as connection:
        policies = _fetch_sla_policies(connection, policy_code, job_code, dataset_code)
        runs = _fetch_pipeline_runs(connection, start_date, end_date, job_code, dataset_code)
        multi_source = _fetch_multi_source_quality(connection, start_date, end_date, dataset_code)
        api_by_date = _fetch_api_daily_summary(connection, start_date, end_date)
        vendor_quality = _fetch_vendor_quality_scores(connection, start_date, end_date, dataset_code)
        provider_errors = _fetch_provider_error_counts(connection, start_date, end_date, dataset_code)
    return evaluate_sla_records(
        policies,
        runs,
        multi_source,
        api_by_date,
        start_date,
        end_date,
        vendor_quality_scores=vendor_quality,
        provider_error_counts=provider_errors,
    )


def write_alert_events(postgres_dsn: str, alerts: list[dict[str, Any]]) -> int:
    if not alerts:
        return 0
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for alert in alerts:
                cursor.execute(
                    """
                    INSERT INTO qmeta.alert_event (
                        alert_key, policy_id, dataset_id, job_id, source_id, trade_date,
                        alert_type, severity, status, metric_name, metric_value,
                        threshold_value, message, details, last_seen_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s, %s, %s::jsonb, now(), now())
                    ON CONFLICT (alert_key) DO UPDATE SET
                        severity = EXCLUDED.severity,
                        status = 'open',
                        metric_name = EXCLUDED.metric_name,
                        metric_value = EXCLUDED.metric_value,
                        threshold_value = EXCLUDED.threshold_value,
                        message = EXCLUDED.message,
                        details = EXCLUDED.details,
                        last_seen_at = now(),
                        updated_at = now()
                    """,
                    (
                        alert["alert_key"],
                        alert.get("policy_id"),
                        alert.get("dataset_id"),
                        alert.get("job_id"),
                        alert.get("source_id"),
                        alert.get("trade_date"),
                        alert["alert_type"],
                        alert["severity"],
                        alert.get("metric_name"),
                        alert.get("metric_value"),
                        alert.get("threshold_value"),
                        alert["message"],
                        _json(alert.get("details") or {}),
                    ),
                )
    return len(alerts)


def record_dashboard_snapshot(
    postgres_dsn: str,
    dashboard: dict[str, Any],
    snapshot_code: str | None = None,
) -> dict[str, Any]:
    snapshot_code = snapshot_code or _snapshot_code(dashboard)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.ops_dashboard_snapshot (
                    snapshot_code, window_start, window_end, job_code, dataset_code,
                    pipeline_summary, quality_summary, sla_summary, api_summary, details
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
                ON CONFLICT (snapshot_code) DO UPDATE SET
                    pipeline_summary = EXCLUDED.pipeline_summary,
                    quality_summary = EXCLUDED.quality_summary,
                    sla_summary = EXCLUDED.sla_summary,
                    api_summary = EXCLUDED.api_summary,
                    details = EXCLUDED.details,
                    created_at = now()
                RETURNING snapshot_id, snapshot_code, created_at
                """,
                (
                    snapshot_code,
                    dashboard["start_date"],
                    dashboard["end_date"],
                    dashboard.get("job_code"),
                    dashboard.get("dataset_code"),
                    _json(dashboard["pipeline"]),
                    _json(dashboard["quality"]),
                    _json(dashboard["alerts"]),
                    _json(dashboard["api"]),
                    _json({"raw_counts": {key: len(value) for key, value in dashboard.get("raw", {}).items()}}),
                ),
            )
            row = dict(cursor.fetchone())
    return _normalize(row)


def format_ops_dashboard(dashboard: dict[str, Any]) -> str:
    pipeline = dashboard["pipeline"]
    quality = dashboard["quality"]
    api = dashboard["api"]
    alerts = dashboard["alerts"]
    lines = [
        f"ops_dashboard start={dashboard['start_date']} end={dashboard['end_date']} job={dashboard.get('job_code') or 'all'} dataset={dashboard.get('dataset_code') or 'all'}",
        f"pipeline runs={pipeline['run_count']} statuses={pipeline['status_counts']} missing_total={pipeline['missing_total']} open_repairs={pipeline['open_repair_count']} min_completeness={pipeline['min_completeness']}",
        f"quality checks={quality['quality_check_count']} quality_statuses={quality['quality_status_counts']} conflicts={quality['conflict_count']} max_conflict_rate={quality['max_conflict_rate']} min_coverage={quality['min_coverage_rate']}",
        f"api requests={api['request_count']} failed={api['failed_count']} error_rate={api['error_rate']} statuses={api['status_counts']}",
        f"alerts total={alerts['alert_count']} open={alerts['open_alert_count']} severity={alerts['severity_counts']} types={alerts['type_counts']}",
    ]
    return "\n".join(lines)


def _evaluate_pipeline_policy(policy: dict[str, Any], runs_by_job_date, trade_date: str) -> list[dict[str, Any]]:
    alerts = []
    job_id = policy.get("job_id")
    if job_id is None:
        return alerts
    run = runs_by_job_date.get((job_id, trade_date))
    if not run:
        return [
            _alert(
                policy,
                trade_date,
                "missing_run",
                "pipeline_status",
                None,
                None,
                f"SLA missing pipeline run for {policy.get('job_code') or job_id} on {trade_date}",
            )
        ]
    if run.get("status") not in {"success", "skipped"}:
        alerts.append(
            _alert(
                policy,
                trade_date,
                "pipeline_status",
                "pipeline_status",
                None,
                None,
                f"Pipeline {policy.get('job_code') or job_id} status is {run.get('status')} on {trade_date}",
                {"run_id": run.get("run_id"), "status": run.get("status")},
            )
        )
    min_completeness = policy.get("min_completeness")
    completeness = run.get("completeness_rate")
    if min_completeness is not None and completeness is not None and float(completeness) < float(min_completeness):
        alerts.append(
            _alert(
                policy,
                trade_date,
                "completeness_below_sla",
                "completeness_rate",
                completeness,
                min_completeness,
                f"Completeness {float(completeness):.6f} below SLA {float(min_completeness):.6f}",
                {"run_id": run.get("run_id"), "missing_symbols": run.get("missing_symbols") or []},
            )
        )
    max_duration_ms = policy.get("max_duration_ms")
    duration_ms = run.get("duration_ms")
    if max_duration_ms is not None and duration_ms is not None and int(duration_ms) > int(max_duration_ms):
        alerts.append(
            _alert(
                policy,
                trade_date,
                "duration_above_sla",
                "duration_ms",
                duration_ms,
                max_duration_ms,
                f"Pipeline duration {duration_ms}ms above SLA {max_duration_ms}ms",
                {"run_id": run.get("run_id")},
            )
        )
    target_finish_time = policy.get("target_finish_time")
    finished_at = run.get("finished_at")
    if target_finish_time and finished_at and _time_text(finished_at) > str(target_finish_time):
        alerts.append(
            _alert(
                policy,
                trade_date,
                "pipeline_late",
                "target_finish_time",
                None,
                None,
                f"Pipeline finished at {_time_text(finished_at)} after SLA {target_finish_time}",
                {"run_id": run.get("run_id"), "finished_at": str(finished_at)},
            )
        )
    return alerts


def _evaluate_conflict_policy(policy: dict[str, Any], conflict_by_dataset_date, trade_date: str) -> list[dict[str, Any]]:
    max_conflict_rate = policy.get("max_conflict_rate")
    dataset_id = policy.get("dataset_id")
    if max_conflict_rate is None or dataset_id is None:
        return []
    row = conflict_by_dataset_date.get((dataset_id, trade_date))
    if not row or row.get("conflict_rate") is None:
        return []
    if float(row["conflict_rate"]) <= float(max_conflict_rate):
        return []
    return [
        _alert(
            policy,
            trade_date,
            "conflict_rate_above_sla",
            "conflict_rate",
            row["conflict_rate"],
            max_conflict_rate,
            f"Multi-source conflict rate {float(row['conflict_rate']):.6f} above SLA {float(max_conflict_rate):.6f}",
            {
                "primary_source_code": row.get("primary_source_code"),
                "secondary_source_code": row.get("secondary_source_code"),
                "conflict_count": row.get("conflict_count"),
            },
        )
    ]


def _evaluate_api_policy(policy: dict[str, Any], api_by_date, trade_date: str) -> list[dict[str, Any]]:
    max_api_error_rate = policy.get("max_api_error_rate")
    if max_api_error_rate is None:
        return []
    row = api_by_date.get(trade_date)
    if not row:
        return []
    total = int(row.get("request_count") or 0)
    failed = int(row.get("failed_count") or 0)
    error_rate = failed / total if total else 0
    if error_rate <= float(max_api_error_rate):
        return []
    return [
        _alert(
            policy,
            trade_date,
            "api_error_rate_above_sla",
            "api_error_rate",
            error_rate,
            max_api_error_rate,
            f"API error rate {error_rate:.6f} above SLA {float(max_api_error_rate):.6f}",
            {"request_count": total, "failed_count": failed},
        )
    ]


def _evaluate_vendor_quality_policy(policy: dict[str, Any], vendor_quality_by_source_dataset_date, trade_date: str) -> list[dict[str, Any]]:
    dataset_id = policy.get("dataset_id")
    source_id = policy.get("source_id")
    if dataset_id is None or source_id is None:
        return []
    thresholds = {
        "min_vendor_score": policy.get("min_vendor_score"),
        "max_vendor_conflict_rate": policy.get("max_vendor_conflict_rate"),
        "max_vendor_failure_rate": policy.get("max_vendor_failure_rate"),
        "max_vendor_latency_ms": policy.get("max_vendor_latency_ms"),
    }
    if all(value is None for value in thresholds.values()):
        return []
    row = vendor_quality_by_source_dataset_date.get((source_id, dataset_id, trade_date))
    if not row:
        return []
    alerts = []
    if thresholds["min_vendor_score"] is not None and row.get("total_score") is not None and float(row["total_score"]) < float(thresholds["min_vendor_score"]):
        alerts.append(
            _alert(
                policy,
                trade_date,
                "vendor_score_below_sla",
                "vendor_score",
                row["total_score"],
                thresholds["min_vendor_score"],
                f"Vendor score {float(row['total_score']):.4f} below SLA {float(thresholds['min_vendor_score']):.4f}",
                {"source_code": row.get("source_code"), "rating": row.get("rating")},
            )
        )
    if thresholds["max_vendor_conflict_rate"] is not None and row.get("conflict_rate") is not None and float(row["conflict_rate"]) > float(thresholds["max_vendor_conflict_rate"]):
        alerts.append(
            _alert(
                policy,
                trade_date,
                "vendor_conflict_rate_above_sla",
                "vendor_conflict_rate",
                row["conflict_rate"],
                thresholds["max_vendor_conflict_rate"],
                f"Vendor conflict rate {float(row['conflict_rate']):.6f} above SLA {float(thresholds['max_vendor_conflict_rate']):.6f}",
                {"source_code": row.get("source_code"), "rating": row.get("rating")},
            )
        )
    if thresholds["max_vendor_failure_rate"] is not None and row.get("failure_rate") is not None and float(row["failure_rate"]) > float(thresholds["max_vendor_failure_rate"]):
        alerts.append(
            _alert(
                policy,
                trade_date,
                "vendor_failure_rate_above_sla",
                "vendor_failure_rate",
                row["failure_rate"],
                thresholds["max_vendor_failure_rate"],
                f"Vendor failure rate {float(row['failure_rate']):.6f} above SLA {float(thresholds['max_vendor_failure_rate']):.6f}",
                {"source_code": row.get("source_code"), "rating": row.get("rating")},
            )
        )
    if thresholds["max_vendor_latency_ms"] is not None and row.get("latency_ms") is not None and float(row["latency_ms"]) > float(thresholds["max_vendor_latency_ms"]):
        alerts.append(
            _alert(
                policy,
                trade_date,
                "vendor_latency_above_sla",
                "vendor_latency_ms",
                row["latency_ms"],
                thresholds["max_vendor_latency_ms"],
                f"Vendor p95 latency {float(row['latency_ms']):.2f}ms above SLA {float(thresholds['max_vendor_latency_ms']):.2f}ms",
                {"source_code": row.get("source_code"), "rating": row.get("rating")},
            )
        )
    return alerts


def _evaluate_provider_error_policy(policy: dict[str, Any], provider_errors_by_source_dataset_date, trade_date: str) -> list[dict[str, Any]]:
    max_provider_error_count = policy.get("max_provider_error_count")
    dataset_id = policy.get("dataset_id")
    source_id = policy.get("source_id")
    if max_provider_error_count is None or dataset_id is None or source_id is None:
        return []
    row = provider_errors_by_source_dataset_date.get((source_id, dataset_id, trade_date))
    error_count = int(row.get("error_count") or 0) if row else 0
    if error_count <= int(max_provider_error_count):
        return []
    return [
        _alert(
            policy,
            trade_date,
            "provider_error_count_above_sla",
            "provider_error_count",
            error_count,
            max_provider_error_count,
            f"Provider errors {error_count} above SLA {int(max_provider_error_count)}",
            {
                "source_code": row.get("source_code") if row else None,
                "error_type_counts": row.get("error_type_counts") if row else {},
            },
        )
    ]


def _alert(
    policy: dict[str, Any],
    trade_date: str,
    alert_type: str,
    metric_name: str,
    metric_value,
    threshold_value,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key_parts = [
        policy.get("policy_code") or str(policy.get("policy_id") or "adhoc"),
        alert_type,
        trade_date,
        metric_name,
        str(policy.get("job_id") or "all-jobs"),
        str(policy.get("dataset_id") or "all-datasets"),
    ]
    return {
        "alert_key": ":".join(key_parts),
        "policy_id": policy.get("policy_id"),
        "policy_code": policy.get("policy_code"),
        "dataset_id": policy.get("dataset_id"),
        "job_id": policy.get("job_id"),
        "source_id": policy.get("source_id"),
        "trade_date": trade_date,
        "alert_type": alert_type,
        "severity": policy.get("alert_severity") or "high",
        "metric_name": metric_name,
        "metric_value": metric_value,
        "threshold_value": threshold_value,
        "message": message,
        "details": details or {},
    }


def _fetch_pipeline_runs(connection, start_date: str, end_date: str, job_code: str | None, dataset_code: str | None):
    where = ["r.trade_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if job_code:
        where.append("j.job_code = %s")
        params.append(job_code)
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                r.run_id, r.job_id, j.job_code, dc.dataset_id, dc.dataset_code,
                ss.source_id, ss.source_code, r.trade_date, r.attempt, r.status,
                r.started_at, r.finished_at, r.duration_ms, r.row_count,
                r.expected_row_count, r.missing_count, r.missing_symbols,
                r.completeness_rate, r.repair_status, r.error_count, r.warning_count,
                r.error_message
            FROM qmeta.pipeline_run r
            JOIN qmeta.pipeline_job j ON j.job_id = r.job_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = j.dataset_id
            JOIN qmeta.source_system ss ON ss.source_id = j.source_id
            WHERE {' AND '.join(where)}
              AND r.run_id = (
                  SELECT r2.run_id
                  FROM qmeta.pipeline_run r2
                  WHERE r2.job_id = r.job_id
                    AND r2.trade_date = r.trade_date
                  ORDER BY r2.attempt DESC, r2.run_id DESC
                  LIMIT 1
              )
            ORDER BY r.trade_date, j.job_code
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_repair_items(connection, start_date: str, end_date: str, job_code: str | None, dataset_code: str | None):
    where = ["rq.trade_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if job_code:
        where.append("j.job_code = %s")
        params.append(job_code)
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                rq.repair_id, rq.job_id, j.job_code, dc.dataset_id, dc.dataset_code,
                rq.trade_date, rq.reason, rq.status, rq.missing_count,
                rq.completeness_rate, rq.created_at, rq.updated_at, rq.resolved_at
            FROM qmeta.pipeline_repair_queue rq
            JOIN qmeta.pipeline_job j ON j.job_id = rq.job_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = rq.dataset_id
            WHERE {' AND '.join(where)}
            ORDER BY rq.trade_date, rq.updated_at
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_watermarks(connection, job_code: str | None, dataset_code: str | None):
    where = ["TRUE"]
    params: list[Any] = []
    if job_code:
        where.append("j.job_code = %s")
        params.append(job_code)
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                w.job_id, j.job_code, dc.dataset_code,
                w.last_success_trade_date, w.last_attempt_trade_date,
                w.consecutive_failures, w.updated_at
            FROM qmeta.pipeline_watermark w
            JOIN qmeta.pipeline_job j ON j.job_id = w.job_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = j.dataset_id
            WHERE {' AND '.join(where)}
            ORDER BY j.job_code
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_quality_checks(connection, start_date: str, end_date: str, dataset_code: str | None):
    where = ["qr.check_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                dc.dataset_id, dc.dataset_code, qr.check_date, qr.check_name,
                qr.status, qr.severity, qr.affected_rows, qr.details
            FROM qmeta.data_quality_check_result qr
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = qr.dataset_id
            WHERE {' AND '.join(where)}
            ORDER BY qr.check_date, dc.dataset_code, qr.severity DESC
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_multi_source_quality(connection, start_date: str, end_date: str, dataset_code: str | None):
    where = ["mq.trade_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                dc.dataset_id, dc.dataset_code, mq.trade_date,
                ps.source_code AS primary_source_code,
                ss.source_code AS secondary_source_code,
                mq.primary_count, mq.secondary_count, mq.matched_count,
                mq.conflict_count, mq.coverage_rate, mq.conflict_rate, mq.status
            FROM qmeta.multi_source_quality_daily mq
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = mq.dataset_id
            JOIN qmeta.source_system ps ON ps.source_id = mq.primary_source_id
            JOIN qmeta.source_system ss ON ss.source_id = mq.secondary_source_id
            WHERE {' AND '.join(where)}
            ORDER BY mq.trade_date, dc.dataset_code
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_conflict_rollup(connection, start_date: str, end_date: str, dataset_code: str | None):
    where = ["c.trade_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                dc.dataset_code, c.trade_date, c.field_name, c.severity, c.status,
                COUNT(*) AS count
            FROM qmeta.data_conflict_daily c
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = c.dataset_id
            WHERE {' AND '.join(where)}
            GROUP BY dc.dataset_code, c.trade_date, c.field_name, c.severity, c.status
            ORDER BY c.trade_date, count DESC, c.field_name
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_api_audit_rollup(connection, start_date: str, end_date: str):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                started_at::date AS request_date,
                api_name,
                status,
                response_format,
                COUNT(*) AS count,
                COALESCE(SUM(row_count), 0) AS row_count,
                MAX(duration_ms) AS max_duration_ms,
                AVG(duration_ms) AS avg_duration_ms
            FROM qmeta.api_request_audit
            WHERE started_at::date BETWEEN %s AND %s
            GROUP BY started_at::date, api_name, status, response_format
            ORDER BY request_date, api_name, status
            """,
            (start_date, end_date),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_api_daily_summary(connection, start_date: str, end_date: str):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                started_at::date AS request_date,
                COUNT(*) AS request_count,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed_count
            FROM qmeta.api_request_audit
            WHERE started_at::date BETWEEN %s AND %s
            GROUP BY started_at::date
            ORDER BY request_date
            """,
            (start_date, end_date),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_vendor_quality_scores(connection, start_date: str, end_date: str, dataset_code: str | None):
    where = ["vq.score_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                vq.source_id, ss.source_code, vq.dataset_id, dc.dataset_code,
                vq.score_date, vq.coverage_rate, vq.conflict_rate, vq.failure_rate,
                vq.latency_ms, vq.total_score, vq.rating
            FROM qmeta.vendor_quality_score_daily vq
            JOIN qmeta.source_system ss ON ss.source_id = vq.source_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vq.dataset_id
            WHERE {' AND '.join(where)}
            ORDER BY vq.score_date, dc.dataset_code, ss.source_code
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_provider_error_counts(connection, start_date: str, end_date: str, dataset_code: str | None):
    where = ["pee.trade_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                pee.source_id, ss.source_code, pee.dataset_id, dc.dataset_code,
                pee.trade_date, COUNT(*) AS error_count,
                jsonb_object_agg(pee.error_type, type_count ORDER BY pee.error_type) AS error_type_counts
            FROM (
                SELECT source_id, dataset_id, trade_date, error_type, COUNT(*) AS type_count
                FROM qmeta.provider_error_event
                WHERE trade_date BETWEEN %s AND %s
                GROUP BY source_id, dataset_id, trade_date, error_type
            ) pee
            JOIN qmeta.source_system ss ON ss.source_id = pee.source_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = pee.dataset_id
            WHERE {' AND '.join(where)}
            GROUP BY pee.source_id, ss.source_code, pee.dataset_id, dc.dataset_code, pee.trade_date
            ORDER BY pee.trade_date, dc.dataset_code, ss.source_code
            """,
            tuple([start_date, end_date] + params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_alerts(connection, start_date: str, end_date: str, job_code: str | None, dataset_code: str | None):
    where = ["(ae.trade_date IS NULL OR ae.trade_date BETWEEN %s AND %s)"]
    params: list[Any] = [start_date, end_date]
    if job_code:
        where.append("j.job_code = %s")
        params.append(job_code)
    if dataset_code:
        where.append("dc.dataset_code = %s")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                ae.alert_id, ae.alert_key, ae.alert_type, ae.severity, ae.status,
                ae.trade_date, ae.metric_name, ae.metric_value, ae.threshold_value,
                ae.message, ae.details, sp.policy_code, j.job_code, dc.dataset_code,
                ae.first_seen_at, ae.last_seen_at, ae.resolved_at
            FROM qmeta.alert_event ae
            LEFT JOIN qmeta.sla_policy sp ON sp.policy_id = ae.policy_id
            LEFT JOIN qmeta.pipeline_job j ON j.job_id = ae.job_id
            LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = ae.dataset_id
            WHERE {' AND '.join(where)}
            ORDER BY ae.status, ae.severity DESC, ae.last_seen_at DESC
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _fetch_sla_policies(connection, policy_code: str | None, job_code: str | None, dataset_code: str | None):
    where = ["sp.is_active = TRUE"]
    params: list[Any] = []
    if policy_code:
        where.append("sp.policy_code = %s")
        params.append(policy_code)
    if job_code:
        where.append("(j.job_code = %s OR sp.job_id IS NULL)")
        params.append(job_code)
    if dataset_code:
        where.append("(dc.dataset_code = %s OR sp.dataset_id IS NULL)")
        params.append(dataset_code)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                sp.*, dc.dataset_code, j.job_code, ss.source_code
            FROM qmeta.sla_policy sp
            LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = sp.dataset_id
            LEFT JOIN qmeta.pipeline_job j ON j.job_id = sp.job_id
            LEFT JOIN qmeta.source_system ss ON ss.source_id = sp.source_id
            WHERE {' AND '.join(where)}
            ORDER BY sp.policy_code
            """,
            tuple(params),
        )
        return [_normalize(dict(row)) for row in cursor.fetchall()]


def _lookup_id(connection, kind: str, code: str | None) -> int | None:
    if not code:
        return None
    sql_map = {
        "dataset": ("SELECT dataset_id AS id FROM qmeta.dataset_catalog WHERE dataset_code = %s", "dataset not found"),
        "job": ("SELECT job_id AS id FROM qmeta.pipeline_job WHERE job_code = %s", "pipeline job not found"),
        "source": ("SELECT source_id AS id FROM qmeta.source_system WHERE source_code = %s", "source not found"),
    }
    sql, message = sql_map[kind]
    with connection.cursor() as cursor:
        cursor.execute(sql, (code,))
        row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"{message}: {code}")
    return int(row["id"])


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for ops dashboard") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _counter(values: Iterable[Any]) -> dict[str, int]:
    counter = Counter(str(value) for value in values if value is not None)
    return dict(sorted(counter.items()))


def _weighted_counter(rows: list[dict[str, Any]], key: str, count_key: str) -> dict[str, int]:
    counter = defaultdict(int)
    for row in rows:
        if row.get(key) is None:
            continue
        counter[str(row[key])] += int(row.get(count_key) or 0)
    return dict(sorted(counter.items()))


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[index]
    return int((ordered[index - 1] + ordered[index]) / 2)


def _iter_dates(start_date: str, end_date: str):
    start, end = date_range(start_date, end_date)
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _time_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.time().isoformat(timespec="seconds")
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[1][:8]
    if " " in text:
        return text.split(" ", 1)[1][:8]
    return text[:8]


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default, sort_keys=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([row])[0]


def _snapshot_code(dashboard: dict[str, Any]) -> str:
    parts = [
        "ops",
        dashboard["start_date"],
        dashboard["end_date"],
        dashboard.get("job_code") or "all-jobs",
        dashboard.get("dataset_code") or "all-datasets",
        datetime.now().strftime("%Y%m%d%H%M%S"),
    ]
    return "-".join(parts)
