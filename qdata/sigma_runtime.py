from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import re
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


METRIC_STATUSES = {"normal", "warning", "critical"}
LOG_SEVERITIES = {"debug", "info", "warning", "error", "critical"}
DAILY_REPORT_STATUSES = {"success", "warning", "critical"}
CAPACITY_ALERT_SEVERITIES = {"low", "medium", "high", "critical"}
CAPACITY_ALERT_STATUSES = {"open", "acknowledged", "resolved", "ignored"}

RATIO_QUANT = Decimal("0.00000001")
METRIC_QUANT = Decimal("0.000000000001")
AMOUNT_QUANT = Decimal("0.00000001")


def runtime_metric_status(
    metric_value: Decimal | int | float | str,
    *,
    warning_threshold: Decimal | int | float | str | None = None,
    critical_threshold: Decimal | int | float | str | None = None,
) -> str:
    value = _metric_decimal(metric_value)
    warning = _optional_metric_decimal(warning_threshold)
    critical = _optional_metric_decimal(critical_threshold)
    if warning is not None and critical is not None and critical < warning:
        raise QDataValidationError("critical_threshold must be greater than or equal to warning_threshold")
    if critical is not None and value >= critical:
        return "critical"
    if warning is not None and value >= warning:
        return "warning"
    return "normal"


def daily_report_status(
    *,
    api_error_rate: Decimal | int | float | str,
    worker_failed_count: int = 0,
    deployment_health_status: str | None = None,
    open_capacity_alert_count: int = 0,
    open_critical_capacity_alert_count: int = 0,
) -> str:
    error_rate = _ratio(api_error_rate)
    deployment_status = (deployment_health_status or "").lower()
    if (
        error_rate >= Decimal("0.05000000")
        or worker_failed_count > 0
        or deployment_status == "failed"
        or open_critical_capacity_alert_count > 0
    ):
        return "critical"
    if error_rate > 0 or deployment_status in {"warning", "degraded", "skipped"} or open_capacity_alert_count > 0:
        return "warning"
    return "success"


def capacity_alert_payload(metric_row: dict[str, Any]) -> dict[str, Any] | None:
    status = str(metric_row.get("status") or "").lower()
    if status not in {"warning", "critical"}:
        return None
    threshold = metric_row.get("critical_threshold") if status == "critical" else metric_row.get("warning_threshold")
    if threshold is None:
        return None
    environment = str(metric_row.get("environment") or "local")
    component = str(metric_row.get("component") or "runtime")
    metric_name = str(metric_row.get("metric_name") or "runtime_metric")
    metric_value = _metric_decimal(metric_row.get("metric_value") or 0)
    threshold_value = _metric_decimal(threshold)
    observed_at = _coerce_datetime(metric_row.get("metric_time"), "metric_time") or datetime.now(timezone.utc)
    alert_type = "runtime_capacity_critical" if status == "critical" else "runtime_capacity_warning"
    severity = "critical" if status == "critical" else "medium"
    alert_key = _capacity_alert_key(environment, component, metric_name)
    message = (
        f"{environment}/{component}/{metric_name}={metric_value} {metric_row.get('unit') or 'count'} "
        f"reached {status} threshold {threshold_value}"
    )
    return {
        "alert_key": alert_key,
        "environment": environment,
        "component": component,
        "metric_name": metric_name,
        "severity": severity,
        "status": "open",
        "alert_type": alert_type,
        "metric_value": metric_value,
        "threshold_value": threshold_value,
        "unit": metric_row.get("unit") or "count",
        "message": message,
        "observed_at": observed_at,
        "details": {
            "source": "sigma_runtime",
            "metric_id": metric_row.get("metric_id"),
            "metric_code": metric_row.get("metric_code"),
            "metric_status": status,
            "warning_threshold": metric_row.get("warning_threshold"),
            "critical_threshold": metric_row.get("critical_threshold"),
        },
    }


def record_runtime_log(
    postgres_dsn: str | None,
    *,
    environment: str = "local",
    component: str,
    message: str,
    service_name: str | None = None,
    severity: str = "info",
    event_type: str = "runtime_event",
    log_time: datetime | str | None = None,
    log_code: str | None = None,
    release_id: int | None = None,
    worker_run_id: int | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_enum(severity, LOG_SEVERITIES, "severity")
    observed_at = _coerce_datetime(log_time, "log_time") or datetime.now(timezone.utc)
    row = {
        "log_code": log_code or _code("sigma-log", environment, component, event_type, observed_at),
        "environment": environment,
        "component": component,
        "service_name": service_name,
        "release_id": release_id,
        "worker_run_id": worker_run_id,
        "log_time": observed_at,
        "severity": severity,
        "event_type": event_type,
        "message": message,
        "trace_id": trace_id,
        "request_id": request_id,
        "details": details or {},
    }
    if not write_db:
        return _public(row)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.runtime_log (
                    log_code, environment, component, service_name, release_id, worker_run_id,
                    log_time, severity, event_type, message, trace_id, request_id, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (log_code) DO UPDATE SET
                    severity = EXCLUDED.severity,
                    event_type = EXCLUDED.event_type,
                    message = EXCLUDED.message,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING *
                """,
                (
                    row["log_code"],
                    environment,
                    component,
                    service_name,
                    release_id,
                    worker_run_id,
                    observed_at,
                    severity,
                    event_type,
                    message,
                    trace_id,
                    request_id,
                    _json(row["details"]),
                ),
            )
            return _public(dict(cursor.fetchone()))


def record_runtime_metric(
    postgres_dsn: str | None,
    *,
    environment: str = "local",
    component: str,
    metric_name: str,
    metric_value: Decimal | int | float | str,
    unit: str = "count",
    warning_threshold: Decimal | int | float | str | None = None,
    critical_threshold: Decimal | int | float | str | None = None,
    service_name: str | None = None,
    metric_time: datetime | str | None = None,
    metric_code: str | None = None,
    details: dict[str, Any] | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    observed_at = _coerce_datetime(metric_time, "metric_time") or datetime.now(timezone.utc)
    value = _metric_decimal(metric_value)
    warning = _optional_metric_decimal(warning_threshold)
    critical = _optional_metric_decimal(critical_threshold)
    status = runtime_metric_status(value, warning_threshold=warning, critical_threshold=critical)
    row = {
        "metric_code": metric_code or _code("sigma-metric", environment, component, metric_name, observed_at),
        "environment": environment,
        "component": component,
        "service_name": service_name,
        "metric_name": metric_name,
        "metric_time": observed_at,
        "metric_value": value,
        "unit": unit,
        "status": status,
        "warning_threshold": warning,
        "critical_threshold": critical,
        "details": details or {},
    }
    if not write_db:
        return _public(row)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.runtime_metric_snapshot (
                    metric_code, environment, component, service_name, metric_name, metric_time,
                    metric_value, unit, status, warning_threshold, critical_threshold, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (metric_code) DO UPDATE SET
                    metric_value = EXCLUDED.metric_value,
                    unit = EXCLUDED.unit,
                    status = EXCLUDED.status,
                    warning_threshold = EXCLUDED.warning_threshold,
                    critical_threshold = EXCLUDED.critical_threshold,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING *
                """,
                (
                    row["metric_code"],
                    environment,
                    component,
                    service_name,
                    metric_name,
                    observed_at,
                    value,
                    unit,
                    status,
                    warning,
                    critical,
                    _json(row["details"]),
                ),
            )
            return _public(dict(cursor.fetchone()))


def evaluate_capacity_alerts(
    postgres_dsn: str | None,
    *,
    environment: str = "local",
    metric_rows: list[dict[str, Any]] | None = None,
    write_db: bool = True,
) -> list[dict[str, Any]]:
    rows = metric_rows if metric_rows is not None else _fetch_latest_alert_metrics(postgres_dsn, environment)
    alerts: list[dict[str, Any]] = []
    if not write_db:
        return [_public(alert) for row in rows if (alert := capacity_alert_payload(row))]
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for row in rows:
                alert = capacity_alert_payload(row)
                if alert is None:
                    _resolve_capacity_alert(cursor, row)
                    continue
                db_alert = _upsert_capacity_alert(cursor, alert)
                alerts.append(_public(db_alert))
    return alerts


def generate_runtime_daily_report(
    postgres_dsn: str | None,
    *,
    environment: str = "local",
    report_date: str | date | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    current = _coerce_date(report_date, "report_date") or date.today()
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            api = _fetch_api_report(cursor, current)
            workers = _fetch_worker_report(cursor, current)
            deployment_status = _fetch_latest_deployment_status(cursor, environment, current)
            vendor_watch = _fetch_vendor_watch_count(cursor, current)
            invoice_outstanding = _fetch_invoice_outstanding(cursor, current)
            customer_risk = _fetch_customer_risk_count(cursor, current)
            capacity = _fetch_capacity_report(cursor, environment, current)
            error_rate = _ratio(Decimal(api["api_failed_count"]) / Decimal(api["api_request_count"]) if api["api_request_count"] else 0)
            status = daily_report_status(
                api_error_rate=error_rate,
                worker_failed_count=int(workers["worker_failed_count"]),
                deployment_health_status=deployment_status,
                open_capacity_alert_count=int(capacity["open_capacity_alert_count"]),
                open_critical_capacity_alert_count=int(capacity["open_critical_capacity_alert_count"]),
            )
            report = {
                "report_code": f"sigma-runtime-{_slug(environment)}-{current.strftime('%Y%m%d')}",
                "environment": environment,
                "report_date": current,
                "status": status,
                "api_request_count": int(api["api_request_count"]),
                "api_failed_count": int(api["api_failed_count"]),
                "api_error_rate": error_rate,
                "api_slowest_duration_ms": int(api["api_slowest_duration_ms"]),
                "worker_run_count": int(workers["worker_run_count"]),
                "worker_failed_count": int(workers["worker_failed_count"]),
                "worker_warning_count": int(workers["worker_warning_count"]),
                "deployment_health_status": deployment_status,
                "vendor_readiness_watch_count": int(vendor_watch),
                "invoice_outstanding_amount": _amount(invoice_outstanding),
                "customer_health_risk_count": int(customer_risk),
                "capacity_alert_count": int(capacity["capacity_alert_count"]),
                "open_capacity_alert_count": int(capacity["open_capacity_alert_count"]),
                "details": {
                    "source": "sigma_runtime_daily_report",
                    "open_critical_capacity_alert_count": int(capacity["open_critical_capacity_alert_count"]),
                    "status_inputs": {
                        "api_error_rate": str(error_rate),
                        "worker_failed_count": int(workers["worker_failed_count"]),
                        "deployment_health_status": deployment_status,
                        "open_capacity_alert_count": int(capacity["open_capacity_alert_count"]),
                    },
                },
            }
            if not write_db:
                return _public(report)
            cursor.execute(
                """
                INSERT INTO qmeta.runtime_daily_report (
                    report_code, environment, report_date, status,
                    api_request_count, api_failed_count, api_error_rate, api_slowest_duration_ms,
                    worker_run_count, worker_failed_count, worker_warning_count,
                    deployment_health_status, vendor_readiness_watch_count,
                    invoice_outstanding_amount, customer_health_risk_count,
                    capacity_alert_count, open_capacity_alert_count, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (environment, report_date) DO UPDATE SET
                    report_code = EXCLUDED.report_code,
                    status = EXCLUDED.status,
                    api_request_count = EXCLUDED.api_request_count,
                    api_failed_count = EXCLUDED.api_failed_count,
                    api_error_rate = EXCLUDED.api_error_rate,
                    api_slowest_duration_ms = EXCLUDED.api_slowest_duration_ms,
                    worker_run_count = EXCLUDED.worker_run_count,
                    worker_failed_count = EXCLUDED.worker_failed_count,
                    worker_warning_count = EXCLUDED.worker_warning_count,
                    deployment_health_status = EXCLUDED.deployment_health_status,
                    vendor_readiness_watch_count = EXCLUDED.vendor_readiness_watch_count,
                    invoice_outstanding_amount = EXCLUDED.invoice_outstanding_amount,
                    customer_health_risk_count = EXCLUDED.customer_health_risk_count,
                    capacity_alert_count = EXCLUDED.capacity_alert_count,
                    open_capacity_alert_count = EXCLUDED.open_capacity_alert_count,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING *
                """,
                (
                    report["report_code"],
                    environment,
                    current,
                    status,
                    report["api_request_count"],
                    report["api_failed_count"],
                    error_rate,
                    report["api_slowest_duration_ms"],
                    report["worker_run_count"],
                    report["worker_failed_count"],
                    report["worker_warning_count"],
                    deployment_status,
                    report["vendor_readiness_watch_count"],
                    report["invoice_outstanding_amount"],
                    report["customer_health_risk_count"],
                    report["capacity_alert_count"],
                    report["open_capacity_alert_count"],
                    _json(report["details"]),
                ),
            )
            return _public(dict(cursor.fetchone()))


def collect_sigma_runtime(
    postgres_dsn: str | None,
    *,
    environment: str = "local",
    report_date: str | date | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    current = _coerce_date(report_date, "report_date") or date.today()
    observed_at = datetime.combine(current, time(12, 0, tzinfo=timezone.utc))
    raw_metrics = _fetch_collection_metrics(postgres_dsn, current)
    log = record_runtime_log(
        postgres_dsn,
        environment=environment,
        component="sigma",
        service_name="qdata-runtime",
        severity="info",
        event_type="runtime_collection",
        message="Sigma runtime collection completed",
        log_time=observed_at,
        details={"source": "collect_sigma_runtime", "report_date": current.isoformat()},
        write_db=write_db,
    )
    metric_specs = _collection_metric_specs(raw_metrics)
    metric_rows = [
        record_runtime_metric(
            postgres_dsn,
            environment=environment,
            component=spec["component"],
            service_name=spec.get("service_name"),
            metric_name=spec["metric_name"],
            metric_value=spec["metric_value"],
            unit=spec["unit"],
            warning_threshold=spec.get("warning_threshold"),
            critical_threshold=spec.get("critical_threshold"),
            metric_time=observed_at,
            details=spec["details"],
            write_db=write_db,
        )
        for spec in metric_specs
    ]
    capacity_alerts = evaluate_capacity_alerts(postgres_dsn, environment=environment, metric_rows=metric_rows, write_db=write_db)
    daily_report = generate_runtime_daily_report(
        postgres_dsn,
        environment=environment,
        report_date=current,
        write_db=write_db,
    )
    return {
        "environment": environment,
        "report_date": current.isoformat(),
        "log": log,
        "metrics": metric_rows,
        "capacity_alerts": capacity_alerts,
        "daily_report": daily_report,
    }


def format_runtime_collection(result: dict[str, Any]) -> str:
    daily = result.get("daily_report") or {}
    lines = [
        (
            f"sigma_runtime environment={result.get('environment')} report_date={result.get('report_date')} "
            f"metrics={len(result.get('metrics') or [])} capacity_alerts={len(result.get('capacity_alerts') or [])} "
            f"daily_status={daily.get('status')}"
        )
    ]
    for metric in result.get("metrics") or []:
        threshold = metric.get("critical_threshold") if metric.get("status") == "critical" else metric.get("warning_threshold")
        bits = [
            f"metric component={metric.get('component')}",
            f"name={metric.get('metric_name')}",
            f"value={metric.get('metric_value')}",
            f"unit={metric.get('unit')}",
            f"status={metric.get('status')}",
        ]
        if threshold not in (None, ""):
            bits.append(f"threshold={threshold}")
        lines.append(" ".join(bits))
    for alert in result.get("capacity_alerts") or []:
        lines.append(
            f"capacity_alert key={alert.get('alert_key')} severity={alert.get('severity')} "
            f"metric={alert.get('metric_name')} value={alert.get('metric_value')} threshold={alert.get('threshold_value')}"
        )
    return "\n".join(lines)


def format_runtime_daily_report(report: dict[str, Any]) -> str:
    return (
        f"sigma_daily report_code={report.get('report_code')} environment={report.get('environment')} "
        f"report_date={report.get('report_date')} status={report.get('status')} "
        f"api_requests={report.get('api_request_count')} api_failed={report.get('api_failed_count')} "
        f"api_error_rate={report.get('api_error_rate')} worker_failed={report.get('worker_failed_count')} "
        f"open_capacity_alerts={report.get('open_capacity_alert_count')}"
    )


def format_capacity_alerts(alerts: list[dict[str, Any]]) -> str:
    lines = [f"sigma_capacity_alerts rows={len(alerts)}"]
    for alert in alerts:
        lines.append(
            f"alert_key={alert.get('alert_key')} environment={alert.get('environment')} "
            f"component={alert.get('component')} metric={alert.get('metric_name')} "
            f"severity={alert.get('severity')} status={alert.get('status')} "
            f"value={alert.get('metric_value')} threshold={alert.get('threshold_value')}"
        )
    return "\n".join(lines)


def _collection_metric_specs(raw: dict[str, Any]) -> list[dict[str, Any]]:
    api_request_count = int(raw["api_request_count_7d"])
    api_failed_count = int(raw["api_failed_count_7d"])
    api_error_rate = _ratio(Decimal(api_failed_count) / Decimal(api_request_count) if api_request_count else 0)
    return [
        {
            "component": "api",
            "service_name": "qdata-api",
            "metric_name": "api_request_count_7d",
            "metric_value": api_request_count,
            "unit": "requests",
            "warning_threshold": Decimal("200"),
            "critical_threshold": Decimal("1000"),
            "details": {"window": "7d", "source": "api_request_audit"},
        },
        {
            "component": "api",
            "service_name": "qdata-api",
            "metric_name": "api_error_rate_7d",
            "metric_value": api_error_rate,
            "unit": "ratio",
            "warning_threshold": Decimal("0.01000000"),
            "critical_threshold": Decimal("0.05000000"),
            "details": {"window": "7d", "failed_count": api_failed_count, "request_count": api_request_count},
        },
        {
            "component": "api",
            "service_name": "qdata-api",
            "metric_name": "api_slowest_duration_ms_7d",
            "metric_value": raw["api_slowest_duration_ms_7d"],
            "unit": "ms",
            "warning_threshold": Decimal("2000"),
            "critical_threshold": Decimal("5000"),
            "details": {"window": "7d", "source": "api_request_audit"},
        },
        {
            "component": "worker",
            "service_name": "lambda-worker",
            "metric_name": "worker_failed_count_7d",
            "metric_value": raw["worker_failed_count_7d"],
            "unit": "runs",
            "warning_threshold": Decimal("1"),
            "critical_threshold": Decimal("3"),
            "details": {"window": "7d", "source": "worker_run"},
        },
        {
            "component": "alerting",
            "service_name": "zeta-alerts",
            "metric_name": "open_alert_count",
            "metric_value": raw["open_alert_count"],
            "unit": "alerts",
            "warning_threshold": Decimal("5"),
            "critical_threshold": Decimal("10"),
            "details": {"source": "alert_event"},
        },
        {
            "component": "billing",
            "service_name": "omicron-billing",
            "metric_name": "invoice_outstanding_amount",
            "metric_value": raw["invoice_outstanding_amount"],
            "unit": "CNY",
            "warning_threshold": Decimal("100000"),
            "critical_threshold": Decimal("1000000"),
            "details": {"source": "invoice", "period": "current_month"},
        },
        {
            "component": "revenue",
            "service_name": "rho-revenue",
            "metric_name": "customer_health_risk_count",
            "metric_value": raw["customer_health_risk_count"],
            "unit": "customers",
            "warning_threshold": Decimal("1"),
            "critical_threshold": Decimal("5"),
            "details": {"source": "customer_health_snapshot", "latest_as_of_date": raw.get("customer_health_as_of_date")},
        },
        {
            "component": "postgres",
            "service_name": "qdata-postgres",
            "metric_name": "postgres_qmeta_table_count",
            "metric_value": raw["postgres_qmeta_table_count"],
            "unit": "tables",
            "details": {"source": "information_schema.tables"},
        },
    ]


def _fetch_collection_metrics(postgres_dsn: str | None, report_date: date) -> dict[str, Any]:
    start_date = report_date - timedelta(days=6)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM qmeta.api_request_audit WHERE started_at::date BETWEEN %s AND %s) AS api_request_count_7d,
                    (SELECT COUNT(*) FROM qmeta.api_request_audit WHERE started_at::date BETWEEN %s AND %s AND status = 'failed') AS api_failed_count_7d,
                    (SELECT COALESCE(MAX(duration_ms), 0) FROM qmeta.api_request_audit WHERE started_at::date BETWEEN %s AND %s) AS api_slowest_duration_ms_7d,
                    (SELECT COUNT(*) FROM qmeta.worker_run WHERE started_at::date BETWEEN %s AND %s AND status = 'failed') AS worker_failed_count_7d,
                    (SELECT COUNT(*) FROM qmeta.alert_event WHERE status = 'open') AS open_alert_count,
                    (
                        SELECT COALESCE(SUM(outstanding_amount), 0)
                        FROM qmeta.invoice
                        WHERE invoice_date >= date_trunc('month', %s::date)::date
                          AND invoice_date <= %s
                          AND status <> 'void'
                    ) AS invoice_outstanding_amount,
                    (
                        SELECT COUNT(*)
                        FROM qmeta.customer_health_snapshot
                        WHERE as_of_date = (SELECT MAX(as_of_date) FROM qmeta.customer_health_snapshot WHERE as_of_date <= %s)
                          AND status IN ('at_risk', 'dormant', 'churned')
                    ) AS customer_health_risk_count,
                    (SELECT MAX(as_of_date) FROM qmeta.customer_health_snapshot WHERE as_of_date <= %s) AS customer_health_as_of_date,
                    (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'qmeta') AS postgres_qmeta_table_count
                """,
                (
                    start_date,
                    report_date,
                    start_date,
                    report_date,
                    start_date,
                    report_date,
                    start_date,
                    report_date,
                    report_date,
                    report_date,
                    report_date,
                    report_date,
                ),
            )
            return dict(cursor.fetchone())


def _fetch_api_report(cursor, report_date: date) -> dict[str, int]:
    cursor.execute(
        """
        SELECT
            COUNT(*) AS api_request_count,
            COUNT(*) FILTER (WHERE status = 'failed') AS api_failed_count,
            COALESCE(MAX(duration_ms), 0) AS api_slowest_duration_ms
        FROM qmeta.api_request_audit
        WHERE started_at::date = %s
        """,
        (report_date,),
    )
    return dict(cursor.fetchone())


def _fetch_worker_report(cursor, report_date: date) -> dict[str, int]:
    cursor.execute(
        """
        SELECT
            COUNT(*) AS worker_run_count,
            COUNT(*) FILTER (WHERE status = 'failed') AS worker_failed_count,
            COUNT(*) FILTER (WHERE status = 'warning') AS worker_warning_count
        FROM qmeta.worker_run
        WHERE started_at::date = %s
        """,
        (report_date,),
    )
    return dict(cursor.fetchone())


def _fetch_latest_deployment_status(cursor, environment: str, report_date: date) -> str | None:
    cursor.execute(
        """
        SELECT status
        FROM qmeta.deployment_health_snapshot
        WHERE environment = %s
          AND checked_at < (%s::date + INTERVAL '1 day')
        ORDER BY checked_at DESC, snapshot_id DESC
        LIMIT 1
        """,
        (environment, report_date),
    )
    row = cursor.fetchone()
    return row["status"] if row else None


def _fetch_vendor_watch_count(cursor, report_date: date) -> int:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM qmeta.vendor_readiness_review
        WHERE review_date = %s
          AND status = 'watch'
        """,
        (report_date,),
    )
    return int(cursor.fetchone()["count"])


def _fetch_invoice_outstanding(cursor, report_date: date) -> Decimal:
    cursor.execute(
        """
        SELECT COALESCE(SUM(outstanding_amount), 0) AS amount
        FROM qmeta.invoice
        WHERE invoice_date >= date_trunc('month', %s::date)::date
          AND invoice_date <= %s
          AND status <> 'void'
        """,
        (report_date, report_date),
    )
    return _amount(cursor.fetchone()["amount"])


def _fetch_customer_risk_count(cursor, report_date: date) -> int:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM qmeta.customer_health_snapshot
        WHERE as_of_date = (SELECT MAX(as_of_date) FROM qmeta.customer_health_snapshot WHERE as_of_date <= %s)
          AND status IN ('at_risk', 'dormant', 'churned')
        """,
        (report_date,),
    )
    return int(cursor.fetchone()["count"])


def _fetch_capacity_report(cursor, environment: str, report_date: date) -> dict[str, int]:
    cursor.execute(
        """
        SELECT
            COUNT(*) AS capacity_alert_count,
            COUNT(*) FILTER (WHERE status = 'open') AS open_capacity_alert_count,
            COUNT(*) FILTER (WHERE status = 'open' AND severity = 'critical') AS open_critical_capacity_alert_count
        FROM qmeta.capacity_alert
        WHERE environment = %s
          AND observed_at::date = %s
        """,
        (environment, report_date),
    )
    return dict(cursor.fetchone())


def _fetch_latest_alert_metrics(postgres_dsn: str | None, environment: str) -> list[dict[str, Any]]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (environment, component, metric_name) *
                FROM qmeta.runtime_metric_snapshot
                WHERE environment = %s
                  AND status IN ('warning', 'critical')
                ORDER BY environment, component, metric_name, metric_time DESC, metric_id DESC
                """,
                (environment,),
            )
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _upsert_capacity_alert(cursor, alert: dict[str, Any]) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.alert_event (
            alert_key, trade_date, alert_type, severity, status, metric_name,
            metric_value, threshold_value, message, details, last_seen_at, updated_at
        ) VALUES (%s, %s, %s, %s, 'open', %s, %s, %s, %s, %s::jsonb, %s, now())
        ON CONFLICT (alert_key) DO UPDATE SET
            alert_type = EXCLUDED.alert_type,
            severity = EXCLUDED.severity,
            status = 'open',
            metric_name = EXCLUDED.metric_name,
            metric_value = EXCLUDED.metric_value,
            threshold_value = EXCLUDED.threshold_value,
            message = EXCLUDED.message,
            details = EXCLUDED.details,
            last_seen_at = EXCLUDED.last_seen_at,
            resolved_at = NULL,
            updated_at = now()
        RETURNING alert_id
        """,
        (
            alert["alert_key"],
            alert["observed_at"].date(),
            alert["alert_type"],
            alert["severity"],
            alert["metric_name"],
            alert["metric_value"],
            alert["threshold_value"],
            alert["message"],
            _json(alert["details"]),
            alert["observed_at"],
        ),
    )
    alert_id = int(cursor.fetchone()["alert_id"])
    cursor.execute(
        """
        INSERT INTO qmeta.capacity_alert (
            alert_key, alert_id, environment, component, metric_name, severity, status,
            metric_value, threshold_value, unit, message, observed_at, details, last_seen_at,
            resolved_at
        ) VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s, %s, %s, %s, %s::jsonb, %s, NULL)
        ON CONFLICT (alert_key) DO UPDATE SET
            alert_id = EXCLUDED.alert_id,
            severity = EXCLUDED.severity,
            status = 'open',
            metric_value = EXCLUDED.metric_value,
            threshold_value = EXCLUDED.threshold_value,
            unit = EXCLUDED.unit,
            message = EXCLUDED.message,
            observed_at = EXCLUDED.observed_at,
            details = EXCLUDED.details,
            last_seen_at = EXCLUDED.last_seen_at,
            resolved_at = NULL,
            updated_at = now()
        RETURNING *
        """,
        (
            alert["alert_key"],
            alert_id,
            alert["environment"],
            alert["component"],
            alert["metric_name"],
            alert["severity"],
            alert["metric_value"],
            alert["threshold_value"],
            alert["unit"],
            alert["message"],
            alert["observed_at"],
            _json({**alert["details"], "alert_id": alert_id}),
            alert["observed_at"],
        ),
    )
    return dict(cursor.fetchone())


def _resolve_capacity_alert(cursor, metric_row: dict[str, Any]) -> None:
    alert_key = _capacity_alert_key(
        str(metric_row.get("environment") or "local"),
        str(metric_row.get("component") or "runtime"),
        str(metric_row.get("metric_name") or "runtime_metric"),
    )
    cursor.execute(
        """
        UPDATE qmeta.capacity_alert
        SET status = 'resolved',
            resolved_at = now(),
            last_seen_at = now(),
            updated_at = now()
        WHERE alert_key = %s
          AND status IN ('open', 'acknowledged')
        """,
        (alert_key,),
    )
    cursor.execute(
        """
        UPDATE qmeta.alert_event
        SET status = 'resolved',
            resolved_at = now(),
            last_seen_at = now(),
            updated_at = now()
        WHERE alert_key = %s
          AND status IN ('open', 'acknowledged')
        """,
        (alert_key,),
    )


def _capacity_alert_key(environment: str, component: str, metric_name: str) -> str:
    return f"sigma-capacity-{_slug(environment)}-{_slug(component)}-{_slug(metric_name)}"[:256]


def _code(prefix: str, environment: str, component: str, name: str, observed_at: datetime) -> str:
    timestamp = observed_at.strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}-{_slug(environment)}-{_slug(component)}-{_slug(name)}-{timestamp}"[:220]


def _validate_enum(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise QDataValidationError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default"


def _coerce_datetime(value: datetime | str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QDataValidationError(f"{field_name} must use ISO datetime format") from exc
    return parsed


def _coerce_date(value: str | date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return parse_date(value, field_name)


def _metric_decimal(value: Decimal | int | float | str | None) -> Decimal:
    return _decimal(value).quantize(METRIC_QUANT, rounding=ROUND_HALF_UP)


def _optional_metric_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    return _metric_decimal(value)


def _ratio(value: Decimal | int | float | str) -> Decimal:
    return _decimal(value).quantize(RATIO_QUANT, rounding=ROUND_HALF_UP)


def _amount(value: Decimal | int | float | str | None) -> Decimal:
    return _decimal(value).quantize(AMOUNT_QUANT, rounding=ROUND_HALF_UP)


def _decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([{key: _stringify(value) for key, value in row.items()}])[0]


def _stringify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify(item) for item in value]
    return value


def _connect(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Sigma runtime reporting")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Sigma runtime reporting") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
