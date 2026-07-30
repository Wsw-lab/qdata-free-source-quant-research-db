from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Callable
from urllib.request import Request, urlopen

from qdata.backend_utils import date_range, normalize_rows
from qdata.exceptions import QDataValidationError
from qdata.theta import (
    record_benchmark_suite_report,
    run_sharded_provider_benchmark,
)


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
DATASET_SCOPE_BY_ENDPOINT = {
    "health": None,
    "price": "daily_bar",
    "matrix": "daily_bar",
    "constraints": "limit_price_daily",
    "tradable-universe": "tradable_universe",
}


@dataclass(frozen=True)
class DatasetAccessDecision:
    allowed: bool
    dataset_code: str
    access_level: str
    field_allowlist: list[str]
    field_denylist: list[str]
    reason: str | None = None
    effective_scope: str = "none"
    effective_access_level: str | None = None
    access_id: int | None = None
    dataset_id: int | None = None
    denied_fields: list[str] | None = None


def ensure_iota_security_context(
    postgres_dsn: str,
    *,
    tenant_code: str,
    tenant_name: str,
    project_code: str,
    project_name: str,
    principal_code: str,
    principal_name: str,
    token: str,
    token_name: str,
    datasets: list[str],
    scopes: list[str] | None = None,
    quota_per_min: int = 120,
    role: str = "researcher",
    cost_center: str | None = None,
) -> dict[str, Any]:
    if not datasets:
        raise QDataValidationError("datasets are required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            tenant_id = _upsert_tenant(cursor, tenant_code, tenant_name)
            project_id = _upsert_project(cursor, tenant_id, project_code, project_name)
            principal_id = _upsert_principal(cursor, tenant_id, principal_code, principal_name)
            _upsert_project_member(cursor, project_id, principal_id, role)
            token_id = _upsert_api_token(
                cursor,
                token,
                token_name,
                principal_name,
                scopes or ["read"],
                quota_per_min,
                tenant_id,
                project_id,
                principal_id,
                cost_center,
            )
            access_count = 0
            for dataset_code in datasets:
                dataset_id = _ensure_dataset(cursor, dataset_code)
                _upsert_dataset_access(cursor, tenant_id, project_id, principal_id, dataset_id)
                access_count += 1
    return {
        "tenant_code": tenant_code,
        "project_code": project_code,
        "principal_code": principal_code,
        "token_id": token_id,
        "access_count": access_count,
    }


def authorize_dataset_access(
    postgres_dsn: str | None,
    *,
    tenant_id: int | None,
    project_id: int | None,
    principal_id: int | None,
    dataset_code: str,
    access_level: str = "read",
    fields: list[str] | None = None,
    token_id: int | None = None,
    api_name: str = "manual",
    request_id: str | None = None,
    write_audit: bool = False,
    audit_details: dict[str, Any] | None = None,
) -> DatasetAccessDecision:
    if not postgres_dsn or not (tenant_id or project_id or principal_id):
        return DatasetAccessDecision(True, dataset_code, access_level, [], [], effective_scope="compat", effective_access_level=access_level)
    requested_fields = fields or []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = %s", (dataset_code,))
            dataset_row = cursor.fetchone()
            dataset_id = int(dataset_row["dataset_id"]) if dataset_row else None
            cursor.execute(
                """
                SELECT
                    dap.access_id, dap.tenant_id, dap.project_id, dap.principal_id,
                    dap.access_level, dap.field_allowlist, dap.field_denylist,
                    dc.dataset_id
                FROM qmeta.dataset_access_policy dap
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = dap.dataset_id
                WHERE dc.dataset_code = %s
                  AND dap.status = 'active'
                  AND (dap.expires_at IS NULL OR dap.expires_at > now())
                  AND (
                      (dap.principal_id IS NOT NULL AND dap.principal_id = %s)
                      OR (dap.principal_id IS NULL AND dap.project_id IS NOT NULL AND dap.project_id = %s)
                      OR (dap.principal_id IS NULL AND dap.project_id IS NULL AND dap.tenant_id IS NOT NULL AND dap.tenant_id = %s)
                  )
                ORDER BY
                    CASE
                        WHEN dap.principal_id = %s THEN 1
                        WHEN dap.principal_id IS NULL AND dap.project_id = %s THEN 2
                        WHEN dap.principal_id IS NULL AND dap.project_id IS NULL AND dap.tenant_id = %s THEN 3
                        ELSE 4
                    END
                LIMIT 1
                """,
                (dataset_code, principal_id, project_id, tenant_id, principal_id, project_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                decision = DatasetAccessDecision(False, dataset_code, access_level, [], [], "dataset access denied", dataset_id=dataset_id)
                _maybe_record_access_decision(cursor, decision, token_id, tenant_id, project_id, principal_id, api_name, request_id, requested_fields, audit_details, write_audit)
                return decision
            dataset_id = int(row["dataset_id"])
            effective_scope = _policy_scope(row, tenant_id, project_id, principal_id)
            allowlist = list(row["field_allowlist"] or [])
            denylist = list(row["field_denylist"] or [])
            if not _access_level_allows(row["access_level"], access_level):
                decision = DatasetAccessDecision(
                    False,
                    dataset_code,
                    access_level,
                    allowlist,
                    denylist,
                    "dataset access level denied",
                    effective_scope=effective_scope,
                    effective_access_level=row["access_level"],
                    access_id=int(row["access_id"]),
                    dataset_id=dataset_id,
                )
                _maybe_record_access_decision(cursor, decision, token_id, tenant_id, project_id, principal_id, api_name, request_id, requested_fields, audit_details, write_audit)
                return decision
            if requested_fields and allowlist:
                denied = [field for field in requested_fields if field not in allowlist]
                if denied:
                    decision = DatasetAccessDecision(
                        False,
                        dataset_code,
                        access_level,
                        allowlist,
                        denylist,
                        f"fields not allowed: {','.join(denied)}",
                        effective_scope=effective_scope,
                        effective_access_level=row["access_level"],
                        access_id=int(row["access_id"]),
                        dataset_id=dataset_id,
                        denied_fields=denied,
                    )
                    _maybe_record_access_decision(cursor, decision, token_id, tenant_id, project_id, principal_id, api_name, request_id, requested_fields, audit_details, write_audit)
                    return decision
            if requested_fields and denylist:
                denied = [field for field in requested_fields if field in denylist]
                if denied:
                    decision = DatasetAccessDecision(
                        False,
                        dataset_code,
                        access_level,
                        allowlist,
                        denylist,
                        f"fields denied: {','.join(denied)}",
                        effective_scope=effective_scope,
                        effective_access_level=row["access_level"],
                        access_id=int(row["access_id"]),
                        dataset_id=dataset_id,
                        denied_fields=denied,
                    )
                    _maybe_record_access_decision(cursor, decision, token_id, tenant_id, project_id, principal_id, api_name, request_id, requested_fields, audit_details, write_audit)
                    return decision
            decision = DatasetAccessDecision(
                True,
                dataset_code,
                access_level,
                allowlist,
                denylist,
                effective_scope=effective_scope,
                effective_access_level=row["access_level"],
                access_id=int(row["access_id"]),
                dataset_id=dataset_id,
            )
            _maybe_record_access_decision(cursor, decision, token_id, tenant_id, project_id, principal_id, api_name, request_id, requested_fields, audit_details, write_audit)
            return decision


def _policy_scope(row: dict[str, Any], tenant_id: int | None, project_id: int | None, principal_id: int | None) -> str:
    if row.get("principal_id") is not None:
        return "principal" if row.get("principal_id") == principal_id else "none"
    if row.get("project_id") is not None:
        return "project" if row.get("project_id") == project_id else "none"
    if row.get("tenant_id") is not None:
        return "tenant" if row.get("tenant_id") == tenant_id else "none"
    return "none"


def _maybe_record_access_decision(
    cursor: Any,
    decision: DatasetAccessDecision,
    token_id: int | None,
    tenant_id: int | None,
    project_id: int | None,
    principal_id: int | None,
    api_name: str,
    request_id: str | None,
    requested_fields: list[str],
    audit_details: dict[str, Any] | None,
    write_audit: bool,
) -> None:
    if not write_audit:
        return
    cursor.execute("SAVEPOINT chi_access_decision_audit")
    try:
        decision_code = _access_decision_code(request_id, token_id, decision.dataset_code, api_name)
        cursor.execute(
            """
            INSERT INTO qmeta.access_decision_audit (
                decision_code, request_id, token_id, tenant_id, project_id, principal_id,
                dataset_id, access_id, api_name, dataset_code, decision,
                required_access_level, effective_access_level, effective_scope,
                requested_fields, denied_fields, reason, details
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            ON CONFLICT (decision_code) DO UPDATE SET
                decision = EXCLUDED.decision,
                effective_access_level = EXCLUDED.effective_access_level,
                effective_scope = EXCLUDED.effective_scope,
                requested_fields = EXCLUDED.requested_fields,
                denied_fields = EXCLUDED.denied_fields,
                reason = EXCLUDED.reason,
                details = EXCLUDED.details,
                evaluated_at = now()
            """,
            (
                decision_code,
                request_id,
                token_id,
                tenant_id,
                project_id,
                principal_id,
                decision.dataset_id,
                decision.access_id,
                api_name,
                decision.dataset_code,
                "allow" if decision.allowed else "deny",
                decision.access_level,
                decision.effective_access_level,
                decision.effective_scope,
                requested_fields,
                decision.denied_fields or [],
                decision.reason,
                _json(audit_details or {}),
            ),
        )
        cursor.execute("RELEASE SAVEPOINT chi_access_decision_audit")
    except Exception:
        cursor.execute("ROLLBACK TO SAVEPOINT chi_access_decision_audit")
        cursor.execute("RELEASE SAVEPOINT chi_access_decision_audit")


def _access_decision_code(request_id: str | None, token_id: int | None, dataset_code: str, api_name: str) -> str:
    base = f"{request_id or ''}:{token_id or ''}:{dataset_code}:{api_name}:{datetime.now(timezone.utc).isoformat()}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"chi-access-{stamp}-{digest}"


def ensure_notification_channel(
    postgres_dsn: str,
    *,
    channel_code: str,
    channel_name: str,
    channel_type: str,
    endpoint: str | None = None,
    min_severity: str = "low",
    is_active: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if channel_type not in {"stdout", "webhook", "email", "feishu"}:
        raise QDataValidationError("channel_type must be one of: stdout, webhook, email, feishu")
    if min_severity not in SEVERITY_ORDER:
        raise QDataValidationError("min_severity must be one of: low, medium, high, critical")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.notification_channel (
                    channel_code, channel_name, channel_type, endpoint,
                    is_active, min_severity, config
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (channel_code) DO UPDATE SET
                    channel_name = EXCLUDED.channel_name,
                    channel_type = EXCLUDED.channel_type,
                    endpoint = EXCLUDED.endpoint,
                    is_active = EXCLUDED.is_active,
                    min_severity = EXCLUDED.min_severity,
                    config = EXCLUDED.config,
                    updated_at = now()
                RETURNING channel_id, channel_code, channel_type, is_active, min_severity
                """,
                (channel_code, channel_name, channel_type, endpoint, is_active, min_severity, _json(config or {})),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def dispatch_alert_notifications(
    postgres_dsn: str,
    *,
    channel_code: str | None = None,
    limit: int = 50,
    dry_run: bool = False,
    request_func: Callable[[Request, float], Any] | None = None,
) -> list[dict[str, Any]]:
    request_func = request_func or _default_request
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            channels = _fetch_channels(cursor, channel_code)
            alerts = _fetch_open_alerts(cursor, limit)
            deliveries = []
            for alert in alerts:
                for channel in channels:
                    if not _severity_allows(alert["severity"], channel["min_severity"]):
                        continue
                    delivery_mode = "dry-run" if dry_run else "send"
                    delivery_key = f"{alert['alert_id']}:{channel['channel_id']}:{alert['last_seen_at']}:{delivery_mode}"
                    status, response, error = _send_notification(channel, alert, dry_run, request_func)
                    _record_delivery(cursor, alert["alert_id"], channel["channel_id"], delivery_key, status, response, error, dry_run)
                    deliveries.append(
                        {
                            "alert_id": alert["alert_id"],
                            "channel_code": channel["channel_code"],
                            "status": status,
                            "alert_type": alert["alert_type"],
                            "severity": alert["severity"],
                        }
                    )
    return deliveries


def rollup_api_usage_daily(
    postgres_dsn: str,
    start_date: str,
    end_date: str,
    *,
    cost_per_request: float = 1.0,
    cost_per_1000_rows: float = 0.1,
) -> list[dict[str, Any]]:
    date_range(start_date, end_date)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.api_request_audit
                SET cost_units = %s + COALESCE(row_count, 0) / 1000.0 * %s
                WHERE started_at::date BETWEEN %s AND %s
                """,
                (cost_per_request, cost_per_1000_rows, start_date, end_date),
            )
            cursor.execute(
                """
                SELECT
                    started_at::date AS usage_date,
                    tenant_id, project_id, principal_id, token_id, api_name,
                    COUNT(*) AS request_count,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                    COALESCE(SUM(row_count), 0) AS row_count,
                    COALESCE(SUM(duration_ms), 0) AS duration_ms,
                    COALESCE(SUM(cost_units), 0) AS cost_units
                FROM qmeta.api_request_audit
                WHERE started_at::date BETWEEN %s AND %s
                GROUP BY started_at::date, tenant_id, project_id, principal_id, token_id, api_name
                ORDER BY usage_date, api_name
                """,
                (start_date, end_date),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                cursor.execute(
                    """
                    UPDATE qmeta.api_usage_daily
                    SET request_count = %s,
                        failed_count = %s,
                        row_count = %s,
                        duration_ms = %s,
                        cost_units = %s,
                        updated_at = now()
                    WHERE usage_date = %s
                      AND tenant_id IS NOT DISTINCT FROM %s
                      AND project_id IS NOT DISTINCT FROM %s
                      AND principal_id IS NOT DISTINCT FROM %s
                      AND token_id IS NOT DISTINCT FROM %s
                      AND api_name = %s
                    """,
                    (
                        row["request_count"],
                        row["failed_count"],
                        row["row_count"],
                        row["duration_ms"],
                        row["cost_units"],
                        row["usage_date"],
                        row["tenant_id"],
                        row["project_id"],
                        row["principal_id"],
                        row["token_id"],
                        row["api_name"],
                    ),
                )
                if cursor.rowcount:
                    continue
                cursor.execute(
                    """
                    INSERT INTO qmeta.api_usage_daily (
                        usage_date, tenant_id, project_id, principal_id, token_id, api_name,
                        request_count, failed_count, row_count, duration_ms, cost_units, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
                    """,
                    (
                        row["usage_date"],
                        row["tenant_id"],
                        row["project_id"],
                        row["principal_id"],
                        row["token_id"],
                        row["api_name"],
                        row["request_count"],
                        row["failed_count"],
                        row["row_count"],
                        row["duration_ms"],
                        row["cost_units"],
                    ),
                )
    return normalize_rows(rows)


def fetch_api_usage_daily(
    postgres_dsn: str,
    start_date: str,
    end_date: str,
    project_code: str | None = None,
) -> list[dict[str, Any]]:
    where = ["aud.usage_date BETWEEN %s AND %s"]
    params: list[Any] = [start_date, end_date]
    if project_code:
        where.append("p.project_code = %s")
        params.append(project_code)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    aud.usage_date, t.tenant_code, p.project_code, pr.principal_code,
                    at.token_name, aud.api_name, aud.request_count, aud.failed_count,
                    aud.row_count, aud.duration_ms, aud.cost_units
                FROM qmeta.api_usage_daily aud
                LEFT JOIN qmeta.tenant t ON t.tenant_id = aud.tenant_id
                LEFT JOIN qmeta.project p ON p.project_id = aud.project_id
                LEFT JOIN qmeta.principal pr ON pr.principal_id = aud.principal_id
                LEFT JOIN qmeta.api_token at ON at.token_id = aud.token_id
                WHERE {' AND '.join(where)}
                ORDER BY aud.usage_date, p.project_code, aud.api_name
                """,
                tuple(params),
            )
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def ensure_vendor_benchmark_schedule(
    postgres_dsn: str,
    *,
    schedule_code: str,
    dataset_code: str,
    primary_source_code: str,
    secondary_source_code: str,
    start_date: str,
    end_date: str,
    target_trade_days: int | None = None,
    shard_size: int = 500,
    max_symbols: int | None = None,
    cadence: str = "manual",
    next_run_at: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    date_range(start_date, end_date)
    if cadence not in {"manual", "daily", "weekly", "monthly"}:
        raise QDataValidationError("cadence must be one of: manual, daily, weekly, monthly")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            dataset_id = _ensure_dataset(cursor, dataset_code)
            primary_source_id = _ensure_source(cursor, primary_source_code)
            secondary_source_id = _ensure_source(cursor, secondary_source_code)
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_benchmark_schedule (
                    schedule_code, dataset_id, primary_source_id, secondary_source_id,
                    start_date, end_date, target_trade_days, shard_size, max_symbols,
                    cadence, next_run_at, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (schedule_code) DO UPDATE SET
                    dataset_id = EXCLUDED.dataset_id,
                    primary_source_id = EXCLUDED.primary_source_id,
                    secondary_source_id = EXCLUDED.secondary_source_id,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    target_trade_days = EXCLUDED.target_trade_days,
                    shard_size = EXCLUDED.shard_size,
                    max_symbols = EXCLUDED.max_symbols,
                    cadence = EXCLUDED.cadence,
                    next_run_at = EXCLUDED.next_run_at,
                    details = EXCLUDED.details,
                    status = 'active',
                    updated_at = now()
                RETURNING schedule_id, schedule_code, cadence, status, next_run_at
                """,
                (
                    schedule_code,
                    dataset_id,
                    primary_source_id,
                    secondary_source_id,
                    start_date,
                    end_date,
                    target_trade_days,
                    shard_size,
                    max_symbols,
                    cadence,
                    next_run_at,
                    _json(details or {}),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def run_vendor_benchmark_schedule(
    postgres_dsn: str,
    schedule_code: str,
    *,
    write_db: bool = True,
) -> dict[str, Any]:
    schedule = _fetch_schedule(postgres_dsn, schedule_code)
    details = schedule.get("details") or {}
    symbols = details.get("symbols")
    secondary_kwargs = details.get("secondary_kwargs") or {}
    suite = run_sharded_provider_benchmark(
        primary_provider=schedule["primary_source_code"],
        secondary_provider=schedule["secondary_source_code"],
        start_date=schedule["start_date"],
        end_date=schedule["end_date"],
        symbols=symbols,
        shard_size=schedule["shard_size"],
        max_symbols=schedule["max_symbols"],
        target_trade_days=schedule["target_trade_days"],
        dataset_code=schedule["dataset_code"],
        secondary_kwargs=secondary_kwargs,
    )
    db_result = record_benchmark_suite_report(postgres_dsn, suite) if write_db else None
    if write_db and db_result:
        _mark_schedule_run(postgres_dsn, schedule["schedule_id"], db_result["suite_id"], schedule["cadence"])
    return {
        "schedule_code": schedule_code,
        "suite_code": suite.suite_code,
        "status": suite.status,
        "db_result": db_result,
    }


def format_usage_report(rows: list[dict[str, Any]]) -> str:
    lines = [f"api_usage rows={len(rows)}"]
    for row in rows:
        lines.append(
            f"usage date={row['usage_date']} project={row.get('project_code') or 'none'} api={row['api_name']} "
            f"requests={row['request_count']} failed={row['failed_count']} rows={row['row_count']} cost={row['cost_units']}"
        )
    return "\n".join(lines)


def _upsert_tenant(cursor, tenant_code: str, tenant_name: str) -> int:
    cursor.execute(
        """
        INSERT INTO qmeta.tenant (tenant_code, tenant_name)
        VALUES (%s, %s)
        ON CONFLICT (tenant_code) DO UPDATE SET tenant_name = EXCLUDED.tenant_name, status = 'active', updated_at = now()
        RETURNING tenant_id
        """,
        (tenant_code, tenant_name),
    )
    return int(cursor.fetchone()["tenant_id"])


def _upsert_project(cursor, tenant_id: int, project_code: str, project_name: str) -> int:
    cursor.execute(
        """
        INSERT INTO qmeta.project (tenant_id, project_code, project_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, project_code) DO UPDATE SET project_name = EXCLUDED.project_name, status = 'active', updated_at = now()
        RETURNING project_id
        """,
        (tenant_id, project_code, project_name),
    )
    return int(cursor.fetchone()["project_id"])


def _upsert_principal(cursor, tenant_id: int, principal_code: str, principal_name: str) -> int:
    cursor.execute(
        """
        INSERT INTO qmeta.principal (tenant_id, principal_code, principal_name, principal_type)
        VALUES (%s, %s, %s, 'service_account')
        ON CONFLICT (tenant_id, principal_code) DO UPDATE SET principal_name = EXCLUDED.principal_name, status = 'active', updated_at = now()
        RETURNING principal_id
        """,
        (tenant_id, principal_code, principal_name),
    )
    return int(cursor.fetchone()["principal_id"])


def _upsert_project_member(cursor, project_id: int, principal_id: int, role: str) -> None:
    cursor.execute(
        """
        INSERT INTO qmeta.project_member (project_id, principal_id, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (project_id, principal_id) DO UPDATE SET role = EXCLUDED.role, status = 'active', updated_at = now()
        """,
        (project_id, principal_id, role),
    )


def _upsert_api_token(cursor, token: str, token_name: str, owner: str, scopes: list[str], quota_per_min: int, tenant_id: int, project_id: int, principal_id: int, cost_center: str | None) -> int:
    cursor.execute(
        """
        INSERT INTO qmeta.api_token (
            token_hash, token_name, owner, scopes, quota_per_min,
            tenant_id, project_id, principal_id, cost_center
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (token_hash) DO UPDATE SET
            token_name = EXCLUDED.token_name,
            owner = EXCLUDED.owner,
            scopes = EXCLUDED.scopes,
            quota_per_min = EXCLUDED.quota_per_min,
            tenant_id = EXCLUDED.tenant_id,
            project_id = EXCLUDED.project_id,
            principal_id = EXCLUDED.principal_id,
            cost_center = EXCLUDED.cost_center,
            is_active = TRUE
        RETURNING token_id
        """,
        (_hash_token(token), token_name, owner, scopes, quota_per_min, tenant_id, project_id, principal_id, cost_center),
    )
    return int(cursor.fetchone()["token_id"])


def _upsert_dataset_access(cursor, tenant_id: int, project_id: int, principal_id: int, dataset_id: int) -> None:
    cursor.execute(
        """
        UPDATE qmeta.dataset_access_policy
        SET access_level = 'read',
            status = 'active',
            updated_at = now()
        WHERE tenant_id = %s
          AND project_id = %s
          AND principal_id = %s
          AND dataset_id = %s
        """,
        (tenant_id, project_id, principal_id, dataset_id),
    )
    if cursor.rowcount:
        return
    cursor.execute(
        """
        INSERT INTO qmeta.dataset_access_policy (
            tenant_id, project_id, principal_id, dataset_id, access_level
        ) VALUES (%s, %s, %s, %s, 'read')
        """,
        (tenant_id, project_id, principal_id, dataset_id),
    )


def _ensure_dataset(cursor, dataset_code: str) -> int:
    cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = %s", (dataset_code,))
    row = cursor.fetchone()
    if row:
        return int(row["dataset_id"])
    cursor.execute(
        """
        INSERT INTO qmeta.dataset_catalog (dataset_code, dataset_name, storage_layer, pit_required)
        VALUES (%s, %s, 'postgresql', FALSE)
        ON CONFLICT (dataset_code) DO UPDATE SET dataset_name = EXCLUDED.dataset_name
        RETURNING dataset_id
        """,
        (dataset_code, dataset_code),
    )
    return int(cursor.fetchone()["dataset_id"])


def _ensure_source(cursor, source_code: str) -> int:
    cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = %s", (source_code,))
    row = cursor.fetchone()
    if row:
        return int(row["source_id"])
    cursor.execute(
        """
        INSERT INTO qmeta.source_system (source_code, source_name, source_type, license_scope)
        VALUES (%s, %s, %s, 'created by Iota schedule')
        ON CONFLICT (source_code) DO UPDATE SET source_name = EXCLUDED.source_name
        RETURNING source_id
        """,
        (source_code, source_code, "internal" if source_code in {"csv", "csv_mirror"} else "vendor"),
    )
    return int(cursor.fetchone()["source_id"])


def _access_level_allows(actual: str, required: str) -> bool:
    order = {"read": 1, "write": 2, "admin": 3}
    return order.get(actual, 0) >= order.get(required, 1)


def _severity_allows(alert_severity: str, min_severity: str) -> bool:
    return SEVERITY_ORDER.get(alert_severity, 0) >= SEVERITY_ORDER.get(min_severity, 0)


def _fetch_channels(cursor, channel_code: str | None) -> list[dict[str, Any]]:
    where = ["is_active = TRUE"]
    params: list[Any] = []
    if channel_code:
        where.append("channel_code = %s")
        params.append(channel_code)
    cursor.execute(
        f"""
        SELECT channel_id, channel_code, channel_type, endpoint, min_severity, config
        FROM qmeta.notification_channel
        WHERE {' AND '.join(where)}
        ORDER BY channel_code
        """,
        tuple(params),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_open_alerts(cursor, limit: int) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT alert_id, alert_key, alert_type, severity, status, trade_date,
               metric_name, metric_value, threshold_value, message, details, last_seen_at
        FROM qmeta.alert_event
        WHERE status = 'open'
        ORDER BY last_seen_at DESC, alert_id DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _send_notification(channel: dict[str, Any], alert: dict[str, Any], dry_run: bool, request_func: Callable[[Request, float], Any]) -> tuple[str, str | None, str | None]:
    payload = {
        "channel": channel["channel_code"],
        "alert_type": alert["alert_type"],
        "severity": alert["severity"],
        "trade_date": str(alert.get("trade_date") or ""),
        "message": alert["message"],
        "metric_name": alert.get("metric_name"),
        "metric_value": str(alert.get("metric_value")),
        "threshold_value": str(alert.get("threshold_value")),
    }
    if dry_run or channel["channel_type"] == "stdout":
        return "sent" if not dry_run else "skipped", json.dumps(payload, ensure_ascii=False, sort_keys=True), None
    if channel["channel_type"] in {"webhook", "feishu"} and channel.get("endpoint"):
        try:
            request = Request(
                channel["endpoint"],
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            response = request_func(request, 10)
            code = getattr(response, "status", None) or getattr(response, "code", None) or 200
            return "sent", f"http_status={code}", None
        except Exception as exc:
            return "failed", None, str(exc)
    return "skipped", f"unsupported channel_type={channel['channel_type']} without endpoint", None


def _record_delivery(cursor, alert_id: int, channel_id: int, delivery_key: str, status: str, response: str | None, error: str | None, dry_run: bool) -> None:
    cursor.execute(
        """
        INSERT INTO qmeta.alert_notification_delivery (
            alert_id, channel_id, delivery_key, status, attempt_count,
            last_attempt_at, delivered_at, response_summary, error_message, details
        ) VALUES (%s, %s, %s, %s, %s, now(), CASE WHEN %s = 'sent' THEN now() ELSE NULL END, %s, %s, %s::jsonb)
        ON CONFLICT (delivery_key) DO UPDATE SET
            status = EXCLUDED.status,
            attempt_count = qmeta.alert_notification_delivery.attempt_count + 1,
            last_attempt_at = now(),
            delivered_at = EXCLUDED.delivered_at,
            response_summary = EXCLUDED.response_summary,
            error_message = EXCLUDED.error_message,
            details = EXCLUDED.details,
            updated_at = now()
        """,
        (alert_id, channel_id, delivery_key, status, 0 if dry_run else 1, status, response, error, _json({"dry_run": dry_run})),
    )


def _fetch_schedule(postgres_dsn: str, schedule_code: str) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    vbs.schedule_id, vbs.schedule_code, dc.dataset_code,
                    ps.source_code AS primary_source_code,
                    ss.source_code AS secondary_source_code,
                    vbs.start_date, vbs.end_date, vbs.target_trade_days,
                    vbs.shard_size, vbs.max_symbols, vbs.cadence, vbs.details
                FROM qmeta.vendor_benchmark_schedule vbs
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vbs.dataset_id
                JOIN qmeta.source_system ps ON ps.source_id = vbs.primary_source_id
                JOIN qmeta.source_system ss ON ss.source_id = vbs.secondary_source_id
                WHERE vbs.schedule_code = %s
                  AND vbs.status = 'active'
                """,
                (schedule_code,),
            )
            row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"vendor benchmark schedule not found: {schedule_code}")
    return normalize_rows([dict(row)])[0]


def _mark_schedule_run(postgres_dsn: str, schedule_id: int, suite_id: int, cadence: str) -> None:
    next_run = _next_run_at(cadence)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.vendor_benchmark_schedule
                SET last_suite_id = %s, last_run_at = now(), next_run_at = %s, updated_at = now()
                WHERE schedule_id = %s
                """,
                (suite_id, next_run, schedule_id),
            )


def _next_run_at(cadence: str):
    if cadence == "manual":
        return None
    now = datetime.now(timezone.utc)
    if cadence == "daily":
        return now + timedelta(days=1)
    if cadence == "weekly":
        return now + timedelta(days=7)
    return now + timedelta(days=30)


def _default_request(request: Request, timeout: float):
    return urlopen(request, timeout=timeout)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Iota production operations") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
