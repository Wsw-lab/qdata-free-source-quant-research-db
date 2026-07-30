from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Iterable

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.pi_readiness import ReadinessThresholds, generate_vendor_readiness_review
from qdata.theta import (
    load_active_field_mapping,
    load_vendor_runtime_config,
    record_benchmark_suite_report,
    redacted_vendor_config,
    run_sharded_provider_benchmark,
    vendor_provider_kwargs,
)


DEFAULT_WINDOWS = (5, 20, 60)
DEFAULT_SOURCE_CODE = "vendor_http"
DEFAULT_DATASET_CODE = "daily_bar"
DEFAULT_PRIMARY_SOURCE_CODE = "csv"
TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
GATE_STATUSES = {"planned", "success", "warning", "failed", "blocked", "skipped"}
RUN_MODES = {"blocked", "plan", "live"}


def run_vendor_live_gate(
    postgres_dsn: str,
    *,
    dataset_code: str = DEFAULT_DATASET_CODE,
    source_code: str = DEFAULT_SOURCE_CODE,
    primary_source_code: str = DEFAULT_PRIMARY_SOURCE_CODE,
    start_date: str,
    end_date: str,
    windows: Iterable[int] = DEFAULT_WINDOWS,
    symbols: list[str] | None = None,
    fields: list[str] | None = None,
    shard_size: int = 500,
    max_symbols: int | None = None,
    requested_by: str = "epsilon3",
    trigger_mode: str = "manual",
    allow_live: bool = False,
    require_live: bool = False,
    require_active_profile: bool = True,
    require_contract: bool = True,
    run_benchmarks: bool = False,
    use_db_field_mapping: bool = True,
    min_coverage_rate: float = 0.95,
    max_conflict_rate: float = 0.005,
    max_failure_rate: float = 0.01,
    max_p95_latency_ms: float = 5000,
    min_rows_per_second: float = 0,
) -> dict[str, Any]:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    if shard_size <= 0:
        raise QDataValidationError("shard_size must be greater than 0")
    if max_symbols is not None and max_symbols <= 0:
        raise QDataValidationError("max_symbols must be greater than 0")
    start, end = date_range(start_date, end_date)
    normalized_windows = _normalize_windows(windows)
    started_at = datetime.now(timezone.utc)
    profile = _fetch_vendor_profile(postgres_dsn, source_code, dataset_code)
    config = _apply_profile_auth_default(load_vendor_runtime_config(source_code), profile)
    live_issues = _live_config_issues(config)
    blocking_issues: list[str] = []
    suite_ids: list[int] = []
    suite_codes: list[str] = []
    executed_windows: list[int] = []
    review: dict[str, Any] | None = None
    error_message: str | None = None
    status = "blocked"
    run_mode = "blocked"

    if not allow_live:
        blocking_issues.append("external_vendor_live_disabled")
    elif live_issues:
        blocking_issues.extend(live_issues)
    else:
        run_mode = "live"
        if run_benchmarks:
            try:
                suite_ids, suite_codes, executed_windows = _run_live_benchmark_windows(
                    postgres_dsn,
                    config=config,
                    primary_source_code=primary_source_code,
                    source_code=source_code,
                    dataset_code=dataset_code,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    windows=normalized_windows,
                    symbols=symbols,
                    fields=fields,
                    shard_size=shard_size,
                    max_symbols=max_symbols,
                    use_db_field_mapping=use_db_field_mapping,
                )
            except Exception as exc:
                status = "failed"
                error_message = str(exc)
                blocking_issues.append(f"live benchmark failed: {exc}")

    if status != "failed" and allow_live and not live_issues:
        review = generate_vendor_readiness_review(
            postgres_dsn,
            dataset_code=dataset_code,
            source_code=source_code,
            primary_source_code=primary_source_code,
            required_windows=normalized_windows,
            thresholds=ReadinessThresholds(
                min_coverage_rate=min_coverage_rate,
                max_conflict_rate=max_conflict_rate,
                max_failure_rate=max_failure_rate,
                max_p95_latency_ms=max_p95_latency_ms,
                min_rows_per_second=min_rows_per_second,
            ),
            review_date=end.isoformat(),
            require_live_endpoint=require_live,
            require_active_profile=require_active_profile,
            require_contract=require_contract,
            write_db=True,
        )
        blocking_issues.extend(review.get("blocking_issues") or [])
        status = _status_from_review(review)
    elif status != "failed":
        review = _fetch_latest_readiness_review(postgres_dsn, dataset_code, source_code, primary_source_code)
        status = "blocked"
        error_message = "; ".join(blocking_issues) if blocking_issues else None

    if require_live and status == "blocked":
        error_message = error_message or "vendor live gate blocked"

    finished_at = datetime.now(timezone.utc)
    gate = _insert_gate_run(
        postgres_dsn,
        dataset_code=dataset_code,
        source_code=source_code,
        primary_source_code=primary_source_code,
        profile=profile,
        review=review,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        run_mode=run_mode,
        status=status,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        windows=normalized_windows,
        executed_windows=executed_windows,
        shard_size=shard_size,
        max_symbols=max_symbols,
        symbol_count=len(symbols or []) if symbols else None,
        allow_live=allow_live,
        require_live=require_live,
        require_active_profile=require_active_profile,
        require_contract=require_contract,
        run_benchmarks=run_benchmarks,
        config=config,
        suite_ids=suite_ids,
        suite_codes=suite_codes,
        blocking_issues=_dedupe(blocking_issues),
        next_actions=_next_actions(status, review),
        error_message=error_message,
        started_at=started_at,
        finished_at=finished_at,
    )
    if require_live and gate.get("status") == "blocked":
        raise QDataValidationError(error_message or "vendor live gate blocked")
    return gate


def list_vendor_live_gate_runs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("gate_code", "vlgr.gate_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vlgr.status"),
            ("run_mode", "vlgr.run_mode"),
            ("requested_by", "vlgr.requested_by"),
            ("trigger_mode", "vlgr.trigger_mode"),
            ("review_code", "vlgr.review_code"),
            ("recommendation", "vlgr.recommendation"),
            ("recommended_role", "vlgr.recommended_role"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vlgr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vlgr.gate_id, vlgr.gate_code, dc.dataset_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vlgr.requested_by, vlgr.trigger_mode, vlgr.run_mode,
            vlgr.status, vlgr.start_date, vlgr.end_date,
            vlgr.required_windows, vlgr.executed_windows,
            vlgr.shard_size, vlgr.max_symbols, vlgr.symbol_count,
            vlgr.allow_live, vlgr.require_live, vlgr.require_active_profile,
            vlgr.require_contract, vlgr.run_benchmarks,
            vlgr.live_base_url_env, vlgr.live_token_env,
            vlgr.live_base_url_present, vlgr.live_token_present,
            vlgr.profile_status, vlgr.runtime_mode,
            vlgr.review_code, vlgr.readiness_status,
            vlgr.recommendation, vlgr.recommended_role,
            vlgr.suite_ids, vlgr.suite_codes,
            vlgr.blocking_issues, vlgr.next_actions,
            vlgr.error_message, vlgr.started_at, vlgr.finished_at,
            vlgr.duration_ms, vlgr.created_at, vlgr.updated_at
        FROM qmeta.vendor_live_gate_run vlgr
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vlgr.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = vlgr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vlgr.primary_source_id
        {where}
        ORDER BY vlgr.started_at DESC, vlgr.gate_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_epsilon3_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"epsilon3 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _run_live_benchmark_windows(
    postgres_dsn: str,
    *,
    config,
    primary_source_code: str,
    source_code: str,
    dataset_code: str,
    start_date: str,
    end_date: str,
    windows: list[int],
    symbols: list[str] | None,
    fields: list[str] | None,
    shard_size: int,
    max_symbols: int | None,
    use_db_field_mapping: bool,
) -> tuple[list[int], list[str], list[int]]:
    field_mapping = field_transforms = None
    if use_db_field_mapping:
        field_mapping, field_transforms = load_active_field_mapping(postgres_dsn, source_code, dataset_code)
    secondary_kwargs = vendor_provider_kwargs(config, field_mapping=field_mapping, field_transforms=field_transforms)
    suite_ids: list[int] = []
    suite_codes: list[str] = []
    executed_windows: list[int] = []
    for window in windows:
        suite = run_sharded_provider_benchmark(
            primary_provider=primary_source_code,
            secondary_provider=source_code,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            fields=fields or ["open", "high", "low", "close", "volume", "amount"],
            secondary_kwargs=secondary_kwargs,
            shard_size=shard_size,
            max_symbols=max_symbols,
            target_trade_days=window,
            dataset_code=dataset_code,
        )
        db_result = record_benchmark_suite_report(postgres_dsn, suite)
        suite_ids.append(int(db_result["suite_id"]))
        suite_codes.append(str(db_result["suite_code"]))
        executed_windows.append(window)
    return suite_ids, suite_codes, executed_windows


def _insert_gate_run(
    postgres_dsn: str,
    *,
    dataset_code: str,
    source_code: str,
    primary_source_code: str,
    profile: dict[str, Any],
    review: dict[str, Any] | None,
    requested_by: str,
    trigger_mode: str,
    run_mode: str,
    status: str,
    start_date: str,
    end_date: str,
    windows: list[int],
    executed_windows: list[int],
    shard_size: int,
    max_symbols: int | None,
    symbol_count: int | None,
    allow_live: bool,
    require_live: bool,
    require_active_profile: bool,
    require_contract: bool,
    run_benchmarks: bool,
    config,
    suite_ids: list[int],
    suite_codes: list[str],
    blocking_issues: list[str],
    next_actions: list[str],
    error_message: str | None,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    if status not in GATE_STATUSES:
        raise QDataValidationError(f"unknown gate status: {status}")
    if run_mode not in RUN_MODES:
        raise QDataValidationError(f"unknown run_mode: {run_mode}")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            dataset_id = _lookup_dataset_id(cursor, dataset_code)
            source_id = _lookup_source_id(cursor, source_code)
            primary_source_id = _lookup_source_id(cursor, primary_source_code) if primary_source_code else None
            gate_code = _gate_code(source_code, dataset_code, status)
            evidence = {
                "config": redacted_vendor_config(config),
                "live_env": _live_env_evidence(config),
                "token_storage": "env_var_only",
                "profile_id": profile.get("profile_id"),
                "review_id": review.get("review_id") if review else None,
                "suite_ids": suite_ids,
                "suite_codes": suite_codes,
            }
            request_payload = {
                "dataset_code": dataset_code,
                "source_code": source_code,
                "primary_source_code": primary_source_code,
                "start_date": start_date,
                "end_date": end_date,
                "required_windows": windows,
                "symbols": symbols_summary(symbol_count),
                "shard_size": shard_size,
                "max_symbols": max_symbols,
                "allow_live": allow_live,
                "run_benchmarks": run_benchmarks,
            }
            response_payload = {
                "status": status,
                "run_mode": run_mode,
                "review_status": review.get("status") if review else None,
                "recommendation": review.get("recommendation") if review else None,
                "executed_windows": executed_windows,
                "external_side_effect": bool(run_mode == "live" and run_benchmarks and executed_windows),
            }
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_live_gate_run (
                    gate_code, dataset_id, source_id, primary_source_id, profile_id, review_id,
                    requested_by, trigger_mode, run_mode, status, start_date, end_date,
                    required_windows, executed_windows, shard_size, max_symbols, symbol_count,
                    allow_live, require_live, require_active_profile, require_contract, run_benchmarks,
                    live_base_url_env, live_token_env, live_base_url_present, live_token_present,
                    profile_status, runtime_mode, review_code, readiness_status, recommendation,
                    recommended_role, suite_ids, suite_codes, blocking_issues, next_actions,
                    request_payload, response_payload, evidence, error_message,
                    started_at, finished_at, duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    'QDATA_VENDOR_BASE_URL', 'QDATA_VENDOR_TOKEN', %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s, now()
                )
                RETURNING *
                """,
                (
                    gate_code,
                    dataset_id,
                    source_id,
                    primary_source_id,
                    profile.get("profile_id"),
                    review.get("review_id") if review else None,
                    requested_by,
                    trigger_mode,
                    run_mode,
                    status,
                    start_date,
                    end_date,
                    windows,
                    executed_windows,
                    shard_size,
                    max_symbols,
                    symbol_count,
                    allow_live,
                    require_live,
                    require_active_profile,
                    require_contract,
                    run_benchmarks,
                    bool(config.base_url),
                    _token_present(config),
                    profile.get("profile_status"),
                    _runtime_mode(profile, config),
                    review.get("review_code") if review else None,
                    review.get("status") if review else None,
                    review.get("recommendation") if review else None,
                    review.get("recommended_role") if review else None,
                    suite_ids,
                    suite_codes,
                    blocking_issues,
                    next_actions,
                    _json(request_payload),
                    _json(response_payload),
                    _json(evidence),
                    error_message,
                    started_at,
                    finished_at,
                    _duration_ms(started_at, finished_at),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def symbols_summary(symbol_count: int | None) -> dict[str, Any]:
    return {"explicit_symbol_count": symbol_count} if symbol_count is not None else {"mode": "provider_or_primary_universe"}


def _fetch_vendor_profile(postgres_dsn: str, source_code: str, dataset_code: str) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    vip.profile_id, ss.source_code, vip.provider_name, vip.auth_mode,
                    vip.endpoint_base, vip.enabled_datasets, vip.rate_limit_per_min,
                    vip.retry_limit, vip.timeout_ms, vip.license_scope,
                    vip.redistribution_allowed, vip.commercial_contract_ref,
                    vip.status AS profile_status, vip.owner, vip.details
                FROM qmeta.source_system ss
                LEFT JOIN qmeta.vendor_integration_profile vip ON vip.source_id = ss.source_id
                WHERE ss.source_code = %s
                ORDER BY
                    CASE WHEN vip.enabled_datasets @> ARRAY[%s]::text[] THEN 0 ELSE 1 END,
                    vip.updated_at DESC NULLS LAST
                LIMIT 1
                """,
                (source_code, dataset_code),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"source not found: {source_code}")
            return dict(row)


def _fetch_latest_readiness_review(postgres_dsn: str, dataset_code: str, source_code: str, primary_source_code: str) -> dict[str, Any] | None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    vrr.review_id, vrr.review_code, dc.dataset_code,
                    ss.source_code, ps.source_code AS primary_source_code,
                    vrr.review_date, vrr.status, vrr.recommendation,
                    vrr.recommended_role, vrr.blocking_issues, vrr.next_actions
                FROM qmeta.vendor_readiness_review vrr
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrr.dataset_id
                JOIN qmeta.source_system ss ON ss.source_id = vrr.source_id
                LEFT JOIN qmeta.source_system ps ON ps.source_id = vrr.primary_source_id
                WHERE dc.dataset_code = %s
                  AND ss.source_code = %s
                  AND (%s = '' OR ps.source_code = %s)
                ORDER BY vrr.review_date DESC, vrr.updated_at DESC
                LIMIT 1
                """,
                (dataset_code, source_code, primary_source_code or "", primary_source_code or ""),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def _live_config_issues(config) -> list[str]:
    issues: list[str] = []
    if not config.base_url:
        issues.append("missing_env:QDATA_VENDOR_BASE_URL")
    if config.auth_mode in {"bearer", "header", "query"} and not config.token:
        issues.append("missing_env:QDATA_VENDOR_TOKEN")
    if config.auth_mode == "basic" and (not config.username or not config.password):
        issues.append("missing_env:QDATA_VENDOR_USERNAME_OR_PASSWORD")
    return issues


def _apply_profile_auth_default(config, profile: dict[str, Any]):
    if os.environ.get("QDATA_VENDOR_AUTH_MODE"):
        return config
    profile_auth_mode = profile.get("auth_mode")
    if profile_auth_mode and profile_auth_mode != config.auth_mode:
        return replace(config, auth_mode=str(profile_auth_mode))
    return config


def _live_env_evidence(config) -> dict[str, Any]:
    return {
        "base_url_env": "QDATA_VENDOR_BASE_URL",
        "base_url_present": bool(config.base_url),
        "token_env": "QDATA_VENDOR_TOKEN",
        "token_present": _token_present(config),
        "auth_mode": config.auth_mode,
        "daily_path": config.daily_path,
    }


def _token_present(config) -> bool:
    if config.auth_mode == "none":
        return True
    if config.auth_mode == "basic":
        return bool(config.username and config.password)
    return bool(config.token)


def _runtime_mode(profile: dict[str, Any], config) -> str:
    if config.base_url and _token_present(config):
        return "live"
    if profile.get("profile_status"):
        return "fixture"
    return "unknown"


def _status_from_review(review: dict[str, Any]) -> str:
    status = review.get("status")
    recommendation = review.get("recommendation")
    if status == "ready" and recommendation == "approve_primary":
        return "success"
    if status in {"watch", "incomplete"}:
        return "warning"
    if status == "rejected":
        return "failed"
    return "warning"


def _next_actions(status: str, review: dict[str, Any] | None) -> list[str]:
    if review and review.get("next_actions"):
        return list(review.get("next_actions") or [])
    if status == "blocked":
        return [
            "configure QDATA_VENDOR_BASE_URL and QDATA_VENDOR_TOKEN",
            "rerun epsilon3 live gate with --allow-live",
            "run 5/20/60 benchmark windows before production promotion",
        ]
    if status == "failed":
        return ["fix benchmark errors", "rerun live gate", "keep vendor role research_only"]
    return ["review vendor readiness", "keep provider SLA monitor enabled"]


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "runs": [
            "gate_code",
            "dataset_code",
            "source_code",
            "primary_source_code",
            "run_mode",
            "status",
            "start_date",
            "end_date",
            "required_windows",
            "executed_windows",
            "live_base_url_present",
            "live_token_present",
            "readiness_status",
            "recommendation",
            "recommended_role",
            "error_message",
        ],
        "run": [
            "gate_code",
            "dataset_code",
            "source_code",
            "run_mode",
            "status",
            "live_base_url_present",
            "live_token_present",
            "readiness_status",
            "recommendation",
            "recommended_role",
            "error_message",
        ],
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _where_equal(params: dict[str, list[str]], fields: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for param_name, column_name in fields:
        value = _param(params, param_name)
        if value in (None, ""):
            continue
        clauses.append(f"{column_name} = %s")
        values.append(value)
    if not clauses:
        return "", values
    return "WHERE " + " AND ".join(clauses), values


def _append_date_filter(where: str, values: list[Any], params: dict[str, list[str]], column: str) -> tuple[str, list[Any]]:
    start = _param(params, "start_date")
    end = _param(params, "end_date")
    if start and end:
        date_range(start, end)
        return _append_where(where, values, f"{column}::date BETWEEN %s AND %s", start, end)
    if start:
        parse_date(start, "start_date")
        return _append_where(where, values, f"{column}::date >= %s", start)
    if end:
        parse_date(end, "end_date")
        return _append_where(where, values, f"{column}::date <= %s", end)
    return where, values


def _append_where(where: str, values: list[Any], clause: str, *new_values: Any) -> tuple[str, list[Any]]:
    prefix = " AND " if where else "WHERE "
    return f"{where}{prefix}{clause}", values + list(new_values)


def _normalize_windows(windows: Iterable[int]) -> list[int]:
    result = sorted({int(window) for window in windows})
    if not result or any(window <= 0 for window in result):
        raise QDataValidationError("windows must contain positive integers")
    return result


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _gate_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"epsilon3-live-gate-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _lookup_source_id(cursor, source_code: str) -> int:
    cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = %s", (source_code,))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"source not found: {source_code}")
    return int(row["source_id"])


def _lookup_dataset_id(cursor, dataset_code: str) -> int:
    cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = %s", (dataset_code,))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"dataset not found: {dataset_code}")
    return int(row["dataset_id"])


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Epsilon-3 vendor live gate") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Epsilon-3 vendor live gate")
    return _connect(postgres_dsn)
