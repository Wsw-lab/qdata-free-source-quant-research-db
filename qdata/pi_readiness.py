from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


DEFAULT_WINDOWS = (5, 20, 60)


@dataclass(frozen=True)
class ReadinessThresholds:
    min_coverage_rate: float = 0.95
    max_conflict_rate: float = 0.005
    max_failure_rate: float = 0.01
    max_p95_latency_ms: float = 5000
    min_rows_per_second: float = 0


def build_readiness_review(
    suite_rows: list[dict[str, Any]],
    *,
    dataset_code: str,
    source_code: str,
    primary_source_code: str = "csv",
    required_windows: Iterable[int] = DEFAULT_WINDOWS,
    thresholds: ReadinessThresholds | None = None,
    review_date: str | date | None = None,
    profile: dict[str, Any] | None = None,
    require_live_endpoint: bool = False,
    require_active_profile: bool = False,
    require_contract: bool = False,
) -> dict[str, Any]:
    thresholds = thresholds or ReadinessThresholds()
    windows = _normalize_windows(required_windows)
    current_date = _coerce_date(review_date, "review_date") if review_date else date.today()
    latest_by_window = _latest_suite_by_window(suite_rows, windows)
    profile = profile or {}
    runtime_mode = _runtime_mode(profile)
    profile_status = profile.get("profile_status")

    window_rows = [
        evaluate_readiness_window(window, latest_by_window.get(window), thresholds)
        for window in windows
    ]
    suite_count = sum(1 for row in window_rows if row.get("suite_id"))
    passed_count = sum(1 for row in window_rows if row["status"] == "pass")
    warning_count = sum(1 for row in window_rows if row["status"] == "warning")
    failed_count = sum(1 for row in window_rows if row["status"] == "failed")
    missing_count = sum(1 for row in window_rows if row["status"] == "missing")
    blocking_issues: list[str] = []
    for row in window_rows:
        blocking_issues.extend(row.get("blocking_issues") or [])
    blocking_issues.extend(_profile_blocking_issues(profile, runtime_mode, require_live_endpoint, require_active_profile, require_contract))

    status, recommendation, role, next_actions = _aggregate_recommendation(
        missing_count=missing_count,
        failed_count=failed_count,
        warning_count=warning_count,
        profile_blocked=len(blocking_issues) > sum(len(row.get("blocking_issues") or []) for row in window_rows),
    )
    return {
        "review_code": _review_code(source_code, dataset_code, current_date, windows),
        "dataset_code": dataset_code,
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "review_date": current_date.isoformat(),
        "required_windows": windows,
        "suite_count": suite_count,
        "passed_window_count": passed_count,
        "warning_window_count": warning_count,
        "failed_window_count": failed_count,
        "missing_window_count": missing_count,
        "status": status,
        "recommendation": recommendation,
        "recommended_role": role,
        **asdict(thresholds),
        "observed_min_coverage_rate": _min_metric(window_rows, "coverage_rate"),
        "observed_max_conflict_rate": _max_metric(window_rows, "conflict_rate"),
        "observed_max_failure_rate": _max_metric(window_rows, "failure_rate"),
        "observed_max_p95_latency_ms": _max_metric(window_rows, "p95_latency_ms"),
        "observed_min_rows_per_second": _min_metric(window_rows, "rows_per_second"),
        "profile_status": profile_status,
        "runtime_mode": runtime_mode,
        "blocking_issues": blocking_issues,
        "next_actions": next_actions,
        "windows": window_rows,
        "details": {
            "profile": _profile_public_details(profile),
            "thresholds": asdict(thresholds),
        },
    }


def evaluate_readiness_window(window_days: int, suite: dict[str, Any] | None, thresholds: ReadinessThresholds) -> dict[str, Any]:
    if not suite:
        return {
            "window_days": window_days,
            "suite_id": None,
            "suite_code": None,
            "status": "missing",
            "coverage_rate": None,
            "conflict_rate": None,
            "failure_rate": None,
            "p95_latency_ms": None,
            "rows_per_second": None,
            "symbol_count": 0,
            "benchmark_count": 0,
            "blocking_issues": [f"missing {window_days}d benchmark suite"],
            "details": {},
        }
    issues: list[str] = []
    warnings: list[str] = []
    coverage = _float_or_none(suite.get("coverage_rate"))
    conflict = _float_or_none(suite.get("conflict_rate"))
    failure = _float_or_none(suite.get("failure_rate"))
    latency = _float_or_none(suite.get("p95_latency_ms"))
    rows_per_second = _float_or_none(suite.get("rows_per_second"))
    if suite.get("status") == "failed":
        issues.append(f"{window_days}d suite status=failed")
    if coverage is None or coverage < thresholds.min_coverage_rate:
        issues.append(f"{window_days}d coverage_rate={_fmt_metric(coverage)} below {thresholds.min_coverage_rate:.6f}")
    if failure is not None and failure > thresholds.max_failure_rate:
        issues.append(f"{window_days}d failure_rate={failure:.6f} above {thresholds.max_failure_rate:.6f}")
    if conflict is not None and conflict > thresholds.max_conflict_rate:
        warnings.append(f"{window_days}d conflict_rate={conflict:.6f} above {thresholds.max_conflict_rate:.6f}")
    if latency is not None and latency > thresholds.max_p95_latency_ms:
        warnings.append(f"{window_days}d p95_latency_ms={latency:.2f} above {thresholds.max_p95_latency_ms:.2f}")
    if rows_per_second is not None and rows_per_second < thresholds.min_rows_per_second:
        warnings.append(f"{window_days}d rows_per_second={rows_per_second:.2f} below {thresholds.min_rows_per_second:.2f}")
    if issues:
        status = "failed"
    elif warnings:
        status = "warning"
    else:
        status = "pass"
    return {
        "window_days": window_days,
        "suite_id": suite.get("suite_id"),
        "suite_code": suite.get("suite_code"),
        "status": status,
        "coverage_rate": coverage,
        "conflict_rate": conflict,
        "failure_rate": failure,
        "p95_latency_ms": latency,
        "rows_per_second": rows_per_second,
        "symbol_count": int(suite.get("symbol_count") or 0),
        "benchmark_count": int(suite.get("benchmark_count") or 0),
        "blocking_issues": issues + warnings,
        "details": {
            "suite_status": suite.get("status"),
            "start_date": suite.get("start_date"),
            "end_date": suite.get("end_date"),
            "target_trade_days": suite.get("target_trade_days"),
        },
    }


def generate_vendor_readiness_review(
    postgres_dsn: str,
    *,
    dataset_code: str = "daily_bar",
    source_code: str = "vendor_http",
    primary_source_code: str = "csv",
    required_windows: Iterable[int] = DEFAULT_WINDOWS,
    thresholds: ReadinessThresholds | None = None,
    review_date: str | date | None = None,
    require_live_endpoint: bool = False,
    require_active_profile: bool = False,
    require_contract: bool = False,
    write_db: bool = True,
) -> dict[str, Any]:
    windows = _normalize_windows(required_windows)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            suite_rows = _fetch_latest_suites(cursor, dataset_code, source_code, primary_source_code, windows)
            profile = _fetch_vendor_profile(cursor, source_code, dataset_code)
            review = build_readiness_review(
                suite_rows,
                dataset_code=dataset_code,
                source_code=source_code,
                primary_source_code=primary_source_code,
                required_windows=windows,
                thresholds=thresholds,
                review_date=review_date,
                profile=profile,
                require_live_endpoint=require_live_endpoint,
                require_active_profile=require_active_profile,
                require_contract=require_contract,
            )
            if write_db:
                _write_review(cursor, review)
            return _public_review(review)


def format_readiness_review(review: dict[str, Any]) -> str:
    lines = [
        (
            f"vendor_readiness review={review['review_code']} source={review['source_code']} dataset={review['dataset_code']} "
            f"status={review['status']} recommendation={review['recommendation']} role={review['recommended_role']} "
            f"suites={review['suite_count']} pass={review['passed_window_count']} warning={review['warning_window_count']} "
            f"failed={review['failed_window_count']} missing={review['missing_window_count']}"
        )
    ]
    for window in review.get("windows") or []:
        lines.append(
            f"window days={window['window_days']} status={window['status']} suite={window.get('suite_code') or 'none'} "
            f"coverage={window.get('coverage_rate')} conflict={window.get('conflict_rate')} failure={window.get('failure_rate')} "
            f"p95_ms={window.get('p95_latency_ms')} rows_per_second={window.get('rows_per_second')}"
        )
    if review.get("blocking_issues"):
        lines.append("blocking=" + "; ".join(review["blocking_issues"]))
    return "\n".join(lines)


def _fetch_latest_suites(cursor, dataset_code: str, source_code: str, primary_source_code: str, windows: list[int]) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT DISTINCT ON (pbs.target_trade_days)
            pbs.suite_id, pbs.suite_code, dc.dataset_code,
            ps.source_code AS primary_source_code,
            ss.source_code AS source_code,
            pbs.start_date, pbs.end_date, pbs.target_trade_days,
            pbs.symbol_count, pbs.shard_count, pbs.benchmark_count,
            pbs.coverage_rate, pbs.conflict_rate, pbs.failure_rate,
            pbs.p95_latency_ms, pbs.rows_per_second, pbs.status,
            pbs.created_at
        FROM qmeta.provider_benchmark_suite_run pbs
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = pbs.dataset_id
        JOIN qmeta.source_system ps ON ps.source_id = pbs.primary_source_id
        JOIN qmeta.source_system ss ON ss.source_id = pbs.secondary_source_id
        WHERE dc.dataset_code = %s
          AND ss.source_code = %s
          AND ps.source_code = %s
          AND pbs.target_trade_days = ANY(%s::int[])
        ORDER BY pbs.target_trade_days, pbs.end_date DESC, pbs.created_at DESC
        """,
        (dataset_code, source_code, primary_source_code, windows),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_vendor_profile(cursor, source_code: str, dataset_code: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            ss.source_id, ss.source_code, ss.source_name, vip.provider_name,
            vip.auth_mode, vip.endpoint_base, vip.enabled_datasets,
            vip.rate_limit_per_min, vip.retry_limit, vip.timeout_ms,
            vip.license_scope, vip.redistribution_allowed,
            vip.commercial_contract_ref, vip.status AS profile_status,
            vip.details
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


def _write_review(cursor, review: dict[str, Any]) -> None:
    dataset_id = _lookup_dataset_id(cursor, review["dataset_code"])
    source_id = _lookup_source_id(cursor, review["source_code"])
    primary_source_id = _lookup_source_id(cursor, review["primary_source_code"]) if review.get("primary_source_code") else None
    cursor.execute(
        """
        INSERT INTO qmeta.vendor_readiness_review (
            review_code, dataset_id, source_id, primary_source_id, review_date,
            required_windows, suite_count, passed_window_count, warning_window_count,
            failed_window_count, missing_window_count, status, recommendation,
            recommended_role, min_coverage_rate, max_conflict_rate, max_failure_rate,
            max_p95_latency_ms, min_rows_per_second, observed_min_coverage_rate,
            observed_max_conflict_rate, observed_max_failure_rate, observed_max_p95_latency_ms,
            observed_min_rows_per_second, profile_status, runtime_mode, blocking_issues,
            next_actions, details
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s::jsonb
        )
        ON CONFLICT (review_code) DO UPDATE SET
            suite_count = EXCLUDED.suite_count,
            passed_window_count = EXCLUDED.passed_window_count,
            warning_window_count = EXCLUDED.warning_window_count,
            failed_window_count = EXCLUDED.failed_window_count,
            missing_window_count = EXCLUDED.missing_window_count,
            status = EXCLUDED.status,
            recommendation = EXCLUDED.recommendation,
            recommended_role = EXCLUDED.recommended_role,
            min_coverage_rate = EXCLUDED.min_coverage_rate,
            max_conflict_rate = EXCLUDED.max_conflict_rate,
            max_failure_rate = EXCLUDED.max_failure_rate,
            max_p95_latency_ms = EXCLUDED.max_p95_latency_ms,
            min_rows_per_second = EXCLUDED.min_rows_per_second,
            observed_min_coverage_rate = EXCLUDED.observed_min_coverage_rate,
            observed_max_conflict_rate = EXCLUDED.observed_max_conflict_rate,
            observed_max_failure_rate = EXCLUDED.observed_max_failure_rate,
            observed_max_p95_latency_ms = EXCLUDED.observed_max_p95_latency_ms,
            observed_min_rows_per_second = EXCLUDED.observed_min_rows_per_second,
            profile_status = EXCLUDED.profile_status,
            runtime_mode = EXCLUDED.runtime_mode,
            blocking_issues = EXCLUDED.blocking_issues,
            next_actions = EXCLUDED.next_actions,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING review_id
        """,
        (
            review["review_code"],
            dataset_id,
            source_id,
            primary_source_id,
            review["review_date"],
            review["required_windows"],
            review["suite_count"],
            review["passed_window_count"],
            review["warning_window_count"],
            review["failed_window_count"],
            review["missing_window_count"],
            review["status"],
            review["recommendation"],
            review["recommended_role"],
            review["min_coverage_rate"],
            review["max_conflict_rate"],
            review["max_failure_rate"],
            review["max_p95_latency_ms"],
            review["min_rows_per_second"],
            review["observed_min_coverage_rate"],
            review["observed_max_conflict_rate"],
            review["observed_max_failure_rate"],
            review["observed_max_p95_latency_ms"],
            review["observed_min_rows_per_second"],
            review.get("profile_status"),
            review["runtime_mode"],
            review["blocking_issues"],
            review["next_actions"],
            _json(review.get("details") or {}),
        ),
    )
    review_id = int(cursor.fetchone()["review_id"])
    review["review_id"] = review_id
    cursor.execute("DELETE FROM qmeta.vendor_readiness_window WHERE review_id = %s", (review_id,))
    for window in review.get("windows") or []:
        cursor.execute(
            """
            INSERT INTO qmeta.vendor_readiness_window (
                review_id, window_days, suite_id, status, coverage_rate,
                conflict_rate, failure_rate, p95_latency_ms, rows_per_second,
                symbol_count, benchmark_count, blocking_issues, details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                review_id,
                window["window_days"],
                window.get("suite_id"),
                window["status"],
                window.get("coverage_rate"),
                window.get("conflict_rate"),
                window.get("failure_rate"),
                window.get("p95_latency_ms"),
                window.get("rows_per_second"),
                window.get("symbol_count") or 0,
                window.get("benchmark_count") or 0,
                window.get("blocking_issues") or [],
                _json(window.get("details") or {}),
            ),
        )


def _aggregate_recommendation(
    *,
    missing_count: int,
    failed_count: int,
    warning_count: int,
    profile_blocked: bool,
) -> tuple[str, str, str, list[str]]:
    if failed_count:
        return "rejected", "reject", "none", ["do not promote vendor", "fix failed benchmark windows", "rerun Pi readiness review"]
    if missing_count:
        return "incomplete", "watch", "research_only", ["complete all required 5/20/60 day benchmark windows", "rerun Pi readiness review"]
    if profile_blocked:
        return "watch", "watch", "research_only", ["complete vendor live endpoint/profile/contract checks", "rerun Pi readiness review"]
    if warning_count:
        return "watch", "approve_backup", "backup", ["keep vendor as backup", "resolve warning windows before primary promotion", "schedule daily provider SLA monitor"]
    return "ready", "approve_primary", "primary", ["promote profile to primary candidate", "enable daily provider SLA monitor", "keep backup comparison enabled"]


def _profile_blocking_issues(
    profile: dict[str, Any],
    runtime_mode: str,
    require_live_endpoint: bool,
    require_active_profile: bool,
    require_contract: bool,
) -> list[str]:
    issues: list[str] = []
    if require_live_endpoint and runtime_mode != "live":
        issues.append("vendor profile is not configured for live endpoint/auth")
    if require_active_profile and profile.get("profile_status") != "active":
        issues.append(f"vendor profile status={profile.get('profile_status') or 'none'} is not active")
    if require_contract and not profile.get("commercial_contract_ref"):
        issues.append("commercial_contract_ref is required for production readiness")
    return issues


def _runtime_mode(profile: dict[str, Any]) -> str:
    if profile.get("endpoint_base") and profile.get("auth_mode") and profile.get("auth_mode") != "none":
        return "live"
    if profile.get("profile_status"):
        return "fixture"
    return "unknown"


def _latest_suite_by_window(suite_rows: list[dict[str, Any]], windows: list[int]) -> dict[int, dict[str, Any]]:
    by_window: dict[int, dict[str, Any]] = {}
    for row in suite_rows:
        window = int(row.get("target_trade_days") or 0)
        if window in windows and window not in by_window:
            by_window[window] = dict(row)
    return by_window


def _normalize_windows(windows: Iterable[int]) -> list[int]:
    result = sorted({int(window) for window in windows})
    if not result or any(window <= 0 for window in result):
        raise QDataValidationError("required_windows must contain positive integers")
    return result


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


def _review_code(source_code: str, dataset_code: str, review_date: date, windows: list[int]) -> str:
    window_text = "-".join(str(window) for window in windows)
    return f"pi-readiness-{source_code}-{dataset_code}-{review_date:%Y%m%d}-{window_text}d"


def _profile_public_details(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_code": profile.get("source_code"),
        "provider_name": profile.get("provider_name"),
        "auth_mode": profile.get("auth_mode"),
        "endpoint_configured": bool(profile.get("endpoint_base")),
        "enabled_datasets": profile.get("enabled_datasets"),
        "rate_limit_per_min": profile.get("rate_limit_per_min"),
        "redistribution_allowed": profile.get("redistribution_allowed"),
        "commercial_contract_ref": profile.get("commercial_contract_ref"),
    }


def _public_review(review: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([{key: _stringify(value) for key, value in review.items()}])[0]


def _min_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_float_or_none(row.get(key)) for row in rows if row.get(key) is not None]
    values = [value for value in values if value is not None]
    return min(values) if values else None


def _max_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_float_or_none(row.get(key)) for row in rows if row.get(key) is not None]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _coerce_date(value: str | date, field_name: str) -> date:
    return parse_date(value, field_name) if isinstance(value, str) else value


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _fmt_metric(value: float | None) -> str:
    return "missing" if value is None else f"{value:.6f}"


def _stringify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Pi vendor readiness") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
