from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from qdata.backend_utils import normalize_row, normalize_rows
from qdata.exceptions import QDataValidationError


NU_CHECKS = ("postgres", "migration", "clickhouse", "api", "scheduler", "kappa")
HEALTH_STATUSES = {"success", "warning", "failed", "skipped"}


@dataclass(frozen=True)
class NuHealthCheckResult:
    check_name: str
    component: str
    status: str
    duration_ms: int
    details: dict[str, Any]
    error_message: str | None = None


@dataclass(frozen=True)
class NuHealthReport:
    snapshot_code: str
    environment: str
    status: str
    checked_at: datetime
    duration_ms: int
    checks: list[NuHealthCheckResult]
    snapshot_id: int | None = None
    release_id: int | None = None

    @property
    def success_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "success")

    @property
    def warning_count(self) -> int:
        return sum(1 for check in self.checks if check.status in {"warning", "skipped"})

    @property
    def failed_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "failed")


def run_nu_health_check(
    postgres_dsn: str | None,
    *,
    clickhouse_dsn: str | None = None,
    api_base_url: str | None = None,
    api_token: str | None = None,
    environment: str = "local",
    release_code: str | None = None,
    version_label: str | None = None,
    git_ref: str | None = None,
    write_db: bool = False,
    require_live_scheduler: bool = False,
    check_names: list[str] | None = None,
) -> NuHealthReport:
    selected_checks = normalize_check_names(check_names)
    snapshot_code = f"nu-health-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    started_at = datetime.now(timezone.utc)
    checks: list[NuHealthCheckResult] = []
    for check_name in selected_checks:
        if check_name == "postgres":
            checks.append(_timed_check("postgres", "postgres", lambda: _check_postgres(postgres_dsn)))
        elif check_name == "migration":
            checks.append(_timed_check("migration", "migration", lambda: _check_migrations(postgres_dsn)))
        elif check_name == "clickhouse":
            checks.append(_timed_check("clickhouse", "clickhouse", lambda: _check_clickhouse(clickhouse_dsn)))
        elif check_name == "api":
            checks.append(_timed_check("api_health", "api", lambda: _check_api(api_base_url, api_token)))
        elif check_name == "scheduler":
            checks.append(_timed_check("scheduler_state", "scheduler", lambda: _check_scheduler(postgres_dsn, require_live_scheduler)))
        elif check_name == "kappa":
            checks.append(_timed_check("kappa_overview", "kappa", lambda: _check_kappa(postgres_dsn)))
    report = NuHealthReport(
        snapshot_code=snapshot_code,
        environment=environment,
        status=overall_health_status(checks),
        checked_at=started_at,
        duration_ms=_duration_ms(started_at),
        checks=checks,
    )
    if write_db:
        return persist_health_report(
            postgres_dsn,
            report,
            release_code=release_code,
            version_label=version_label,
            git_ref=git_ref,
        )
    return report


def normalize_check_names(check_names: list[str] | None) -> list[str]:
    if not check_names:
        return list(NU_CHECKS)
    normalized: list[str] = []
    seen: set[str] = set()
    for check_name in check_names:
        if check_name not in NU_CHECKS:
            raise QDataValidationError(f"unknown Nu health check: {check_name}")
        if check_name in seen:
            continue
        seen.add(check_name)
        normalized.append(check_name)
    return normalized


def overall_health_status(checks: list[NuHealthCheckResult]) -> str:
    if any(check.status == "failed" for check in checks):
        return "failed"
    if any(check.status in {"warning", "skipped"} for check in checks):
        return "warning"
    return "success"


def format_nu_health_report(report: NuHealthReport) -> str:
    lines = [
        (
            f"nu_health snapshot_code={report.snapshot_code} environment={report.environment} status={report.status} "
            f"checks={len(report.checks)} success={report.success_count} warning={report.warning_count} "
            f"failed={report.failed_count} duration_ms={report.duration_ms}"
        )
    ]
    if report.snapshot_id is not None:
        lines[0] += f" snapshot_id={report.snapshot_id}"
    for check in report.checks:
        lines.append(
            f"check name={check.check_name} component={check.component} status={check.status} "
            f"duration_ms={check.duration_ms}"
        )
        if check.error_message:
            lines.append(f"check_error name={check.check_name} message={check.error_message}")
    return "\n".join(lines)


def report_to_dict(report: NuHealthReport) -> dict[str, Any]:
    return {
        "snapshot_code": report.snapshot_code,
        "snapshot_id": report.snapshot_id,
        "release_id": report.release_id,
        "environment": report.environment,
        "status": report.status,
        "checked_at": report.checked_at.isoformat(),
        "duration_ms": report.duration_ms,
        "check_count": len(report.checks),
        "success_count": report.success_count,
        "warning_count": report.warning_count,
        "failed_count": report.failed_count,
        "checks": [
            {
                "check_name": check.check_name,
                "component": check.component,
                "status": check.status,
                "duration_ms": check.duration_ms,
                "details": check.details,
                "error_message": check.error_message,
            }
            for check in report.checks
        ],
    }


def persist_health_report(
    postgres_dsn: str | None,
    report: NuHealthReport,
    *,
    release_code: str | None = None,
    version_label: str | None = None,
    git_ref: str | None = None,
) -> NuHealthReport:
    dsn = _require_dsn(postgres_dsn)
    with _connect_required(dsn) as connection:
        with connection.cursor() as cursor:
            release_id = _ensure_release(cursor, release_code, report.environment, version_label, git_ref) if release_code else None
            cursor.execute(
                """
                INSERT INTO qmeta.deployment_health_snapshot (
                    snapshot_code, release_id, environment, status, checked_at, duration_ms,
                    check_count, success_count, warning_count, failed_count, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING snapshot_id
                """,
                (
                    report.snapshot_code,
                    release_id,
                    report.environment,
                    report.status,
                    report.checked_at,
                    report.duration_ms,
                    len(report.checks),
                    report.success_count,
                    report.warning_count,
                    report.failed_count,
                    _json({"source": "check_nu_health"}),
                ),
            )
            snapshot_id = int(cursor.fetchone()["snapshot_id"])
            for check in report.checks:
                cursor.execute(
                    """
                    INSERT INTO qmeta.deployment_health_check (
                        snapshot_id, check_name, component, status, duration_ms, details, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        snapshot_id,
                        check.check_name,
                        check.component,
                        check.status,
                        check.duration_ms,
                        _json(check.details),
                        check.error_message,
                    ),
                )
            if release_id is not None:
                release_status = {"success": "healthy", "warning": "degraded", "failed": "failed"}[report.status]
                cursor.execute(
                    """
                    UPDATE qmeta.deployment_release
                    SET status = %s,
                        health_snapshot_id = %s,
                        started_at = COALESCE(started_at, %s),
                        finished_at = now(),
                        details = details || %s::jsonb,
                        updated_at = now()
                    WHERE release_id = %s
                    """,
                    (release_status, snapshot_id, report.checked_at, _json({"latest_health_status": report.status}), release_id),
                )
            _insert_event(
                cursor,
                release_id,
                report.environment,
                "health_check",
                "failed" if report.status == "failed" else "warning" if report.status == "warning" else "success",
                f"Nu health check {report.status}",
                {"snapshot_code": report.snapshot_code, "snapshot_id": snapshot_id},
            )
    return NuHealthReport(
        snapshot_code=report.snapshot_code,
        environment=report.environment,
        status=report.status,
        checked_at=report.checked_at,
        duration_ms=report.duration_ms,
        checks=report.checks,
        snapshot_id=snapshot_id,
        release_id=release_id,
    )


def _timed_check(check_name: str, component: str, fn) -> NuHealthCheckResult:
    started_at = datetime.now(timezone.utc)
    try:
        status, details = fn()
        if status not in HEALTH_STATUSES:
            raise QDataValidationError(f"unknown Nu health status: {status}")
        return NuHealthCheckResult(check_name, component, status, _duration_ms(started_at), details)
    except Exception as exc:
        return NuHealthCheckResult(check_name, component, "failed", _duration_ms(started_at), {}, str(exc))


def _check_postgres(postgres_dsn: str | None) -> tuple[str, dict[str, Any]]:
    dsn = _require_dsn(postgres_dsn)
    with _connect_required(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_database() AS database_name,
                       current_user AS user_name,
                       to_regnamespace('qmeta') IS NOT NULL AS qmeta_exists,
                       to_regnamespace('qpit') IS NOT NULL AS qpit_exists
                """
            )
            row = normalize_row(dict(cursor.fetchone()))
    status = "success" if row["qmeta_exists"] and row["qpit_exists"] else "failed"
    return status, row


def _check_migrations(postgres_dsn: str | None) -> tuple[str, dict[str, Any]]:
    dsn = _require_dsn(postgres_dsn)
    expected_tables = [
        "qmeta.worker_schedule",
        "qmeta.worker_schedule_tick",
        "qmeta.deployment_release",
        "qmeta.deployment_health_snapshot",
        "qmeta.deployment_health_check",
        "qmeta.deployment_event",
    ]
    with _connect_required(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT item AS table_name, to_regclass(item) IS NOT NULL AS exists FROM unnest(%s::text[]) AS item ORDER BY item",
                (expected_tables,),
            )
            rows = normalize_rows([dict(row) for row in cursor.fetchall()])
    missing = [row["table_name"] for row in rows if not row["exists"]]
    return ("failed" if missing else "success"), {"expected_tables": rows, "missing_tables": missing}


def _check_clickhouse(clickhouse_dsn: str | None) -> tuple[str, dict[str, Any]]:
    if not clickhouse_dsn:
        return "skipped", {"reason": "clickhouse_dsn not provided"}
    parsed = urlparse(clickhouse_dsn)
    if parsed.scheme not in {"http", "https"}:
        raise QDataValidationError("clickhouse_dsn must use http or https for Nu health check")
    url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 8123}/"
    query = "SELECT 1 AS ok FORMAT JSON"
    headers = {"Content-Type": "text/plain"}
    if parsed.username:
        password = parsed.password or ""
        token = base64.b64encode(f"{parsed.username}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = Request(url, data=query.encode("utf-8"), headers=headers, method="POST")
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    ok = payload.get("data", [{}])[0].get("ok") == 1
    return ("success" if ok else "failed"), {"url": url, "ok": ok}


def _check_api(api_base_url: str | None, api_token: str | None) -> tuple[str, dict[str, Any]]:
    if not api_base_url:
        return "skipped", {"reason": "api_base_url not provided"}
    headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
    request = Request(f"{api_base_url.rstrip('/')}/health", headers=headers)
    with urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        payload = json.loads(body)
    ok = payload.get("status") == "success" and payload.get("data", [{}])[0].get("status") == "ok"
    return ("success" if ok else "failed"), {"base_url": api_base_url, "row_count": payload.get("meta", {}).get("row_count")}


def _check_scheduler(postgres_dsn: str | None, require_live_scheduler: bool) -> tuple[str, dict[str, Any]]:
    dsn = _require_dsn(postgres_dsn)
    with _connect_required(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM qmeta.worker_schedule WHERE status = 'active') AS active_schedule_count,
                    (SELECT COUNT(*) FROM qmeta.worker_heartbeat) AS heartbeat_count,
                    (SELECT COUNT(*) FROM qmeta.worker_heartbeat WHERE status = 'running' AND last_seen_at >= now() - INTERVAL '2 minutes') AS live_scheduler_count,
                    (SELECT COUNT(*) FROM qmeta.worker_lock WHERE expires_at <= now()) AS expired_lock_count,
                    (SELECT status FROM qmeta.worker_schedule_tick ORDER BY started_at DESC LIMIT 1) AS latest_tick_status
                """
            )
            row = normalize_row(dict(cursor.fetchone()))
    if row["active_schedule_count"] == 0:
        return "failed", row
    if require_live_scheduler and row["live_scheduler_count"] == 0:
        return "failed", row
    if row["expired_lock_count"] > 0:
        return "warning", row
    return "success", row


def _check_kappa(postgres_dsn: str | None) -> tuple[str, dict[str, Any]]:
    from qdata.kappa import fetch_kappa_overview

    overview = fetch_kappa_overview(postgres_dsn)
    required = ["active_tenant_count", "active_worker_schedule_count", "latest_scheduler_tick_status"]
    missing = [key for key in required if key not in overview]
    return ("failed" if missing else "success"), {"overview": overview, "missing_fields": missing}


def _ensure_release(cursor, release_code: str | None, environment: str, version_label: str | None, git_ref: str | None) -> int:
    code = release_code or f"nu-release-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    cursor.execute(
        """
        INSERT INTO qmeta.deployment_release (
            release_code, release_name, environment, version_label, git_ref, status, started_at, details
        ) VALUES (%s, %s, %s, %s, %s, 'deploying', now(), %s::jsonb)
        ON CONFLICT (release_code) DO UPDATE SET
            release_name = EXCLUDED.release_name,
            environment = EXCLUDED.environment,
            version_label = EXCLUDED.version_label,
            git_ref = EXCLUDED.git_ref,
            status = 'deploying',
            started_at = COALESCE(qmeta.deployment_release.started_at, now()),
            details = qmeta.deployment_release.details || EXCLUDED.details,
            updated_at = now()
        RETURNING release_id
        """,
        (code, code, environment, version_label, git_ref, _json({"source": "nu_health"})),
    )
    return int(cursor.fetchone()["release_id"])


def _insert_event(cursor, release_id: int | None, environment: str, event_type: str, status: str, message: str, details: dict[str, Any]) -> None:
    event_code = f"nu-event-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{uuid4().hex[:6]}"
    cursor.execute(
        """
        INSERT INTO qmeta.deployment_event (
            release_id, event_code, environment, event_type, status, message, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (release_id, event_code, environment, event_type, status, message, _json(details)),
    )


def _duration_ms(started_at: datetime) -> int:
    return int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Nu deployment health")
    return postgres_dsn


def _connect_required(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Nu deployment health") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
