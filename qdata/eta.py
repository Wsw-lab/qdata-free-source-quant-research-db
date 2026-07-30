from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import json
from statistics import median
from time import perf_counter
from typing import Any, Callable, Iterable

from qdata.backend_utils import date_range, normalize_rows
from qdata.exceptions import QDataValidationError
from qdata.fusion import DAILY_COMPARE_FIELDS, FusionReport, compare_daily_bundles, record_fusion_report
from qdata.sources.registry import create_provider


@dataclass(frozen=True)
class BenchmarkDayResult:
    trade_date: str
    status: str
    primary_count: int = 0
    secondary_count: int = 0
    matched_count: int = 0
    conflict_count: int = 0
    coverage_rate: float | None = None
    conflict_rate: float | None = None
    duration_ms: float = 0
    request_count: int = 0
    error_message: str | None = None


@dataclass(frozen=True)
class ProviderErrorRecord:
    provider_name: str
    error_stage: str
    error_type: str
    retryable: bool
    error_message: str
    trade_date: str | None = None
    symbol: str | None = None
    attempt: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkReport:
    benchmark_code: str
    dataset_code: str
    primary_provider: str
    secondary_provider: str
    start_date: str
    end_date: str
    symbol_count: int
    date_count: int
    primary_row_count: int
    secondary_row_count: int
    matched_count: int
    conflict_count: int
    request_count: int
    failure_count: int
    coverage_rate: float | None
    conflict_rate: float | None
    failure_rate: float | None
    total_duration_ms: float
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    rows_per_second: float
    status: str
    day_results: list[BenchmarkDayResult]
    fusion_reports: list[FusionReport] = field(default_factory=list)
    errors: list[ProviderErrorRecord] = field(default_factory=list)


@dataclass(frozen=True)
class VendorQualityScore:
    source_code: str
    dataset_code: str
    score_date: str
    coverage_rate: float | None
    conflict_rate: float | None
    failure_rate: float | None
    latency_ms: float | None
    coverage_score: float
    conflict_score: float
    stability_score: float
    latency_score: float
    cost_score: float
    license_risk_score: float
    total_score: float
    rating: str


def run_provider_benchmark(
    primary_provider: str,
    secondary_provider: str,
    start_date: str,
    end_date: str,
    symbols: list[str],
    primary_kwargs: dict[str, Any] | None = None,
    secondary_kwargs: dict[str, Any] | None = None,
    fields: Iterable[str] = DAILY_COMPARE_FIELDS,
    absolute_tolerance: float = 1e-8,
    relative_tolerance: float | None = None,
    dataset_code: str = "daily_bar",
    provider_factory: Callable[..., Any] = create_provider,
) -> BenchmarkReport:
    date_range(start_date, end_date)
    if not symbols:
        raise QDataValidationError("symbols are required for provider benchmark")
    fields = tuple(fields)
    day_results: list[BenchmarkDayResult] = []
    errors: list[ProviderErrorRecord] = []
    fusion_reports: list[FusionReport] = []
    latencies: list[float] = []
    request_count = 0
    started_all = perf_counter()

    for trade_date in _iter_dates(start_date, end_date):
        started_day = perf_counter()
        primary = provider_factory(primary_provider, **(primary_kwargs or {}))
        secondary = provider_factory(secondary_provider, **(secondary_kwargs or {}))
        try:
            primary_bundle = primary.fetch_daily_market(trade_date, symbols=symbols)
            secondary_bundle = secondary.fetch_daily_market(trade_date, symbols=symbols)
            report = compare_daily_bundles(
                primary_bundle,
                secondary_bundle,
                fields=fields,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                dataset_code=dataset_code,
            )
            fusion_reports.append(report)
            status = report.status
            error_message = None
        except Exception as exc:
            report = None
            status = "failed"
            error_message = str(exc)
            errors.append(
                ProviderErrorRecord(
                    provider_name=secondary_provider,
                    error_stage="benchmark",
                    error_type="unknown",
                    retryable=False,
                    error_message=str(exc),
                    trade_date=trade_date,
                )
            )
        finally:
            request_count += int(getattr(primary, "request_count", 0) or 0)
            request_count += int(getattr(secondary, "request_count", 0) or 0)
            errors.extend(_provider_errors(primary))
            errors.extend(_provider_errors(secondary))

        duration_ms = (perf_counter() - started_day) * 1000
        latencies.append(duration_ms)
        day_results.append(
            BenchmarkDayResult(
                trade_date=trade_date,
                status=status,
                primary_count=report.primary_count if report else 0,
                secondary_count=report.secondary_count if report else 0,
                matched_count=report.matched_count if report else 0,
                conflict_count=report.conflict_count if report else 0,
                coverage_rate=report.coverage_rate if report else None,
                conflict_rate=report.conflict_rate if report else None,
                duration_ms=duration_ms,
                request_count=int(getattr(primary, "request_count", 0) or 0) + int(getattr(secondary, "request_count", 0) or 0),
                error_message=error_message,
            )
        )

    total_duration_ms = (perf_counter() - started_all) * 1000
    primary_row_count = sum(report.primary_count for report in fusion_reports)
    secondary_row_count = sum(report.secondary_count for report in fusion_reports)
    matched_count = sum(report.matched_count for report in fusion_reports)
    conflict_count = sum(report.conflict_count for report in fusion_reports)
    failure_count = sum(1 for result in day_results if result.status == "failed")
    comparable_fields = matched_count * len(fields)
    coverage_rate = _safe_rate(matched_count, primary_row_count)
    conflict_rate = _safe_rate(conflict_count, comparable_fields)
    failure_rate = _safe_rate(failure_count, len(day_results))
    rows_per_second = (primary_row_count + secondary_row_count) / (total_duration_ms / 1000) if total_duration_ms else 0
    status = _benchmark_status(failure_rate, conflict_count)
    return BenchmarkReport(
        benchmark_code=_benchmark_code(primary_provider, secondary_provider, start_date, end_date),
        dataset_code=dataset_code,
        primary_provider=primary_provider,
        secondary_provider=secondary_provider,
        start_date=start_date,
        end_date=end_date,
        symbol_count=len(set(symbols)),
        date_count=len(day_results),
        primary_row_count=primary_row_count,
        secondary_row_count=secondary_row_count,
        matched_count=matched_count,
        conflict_count=conflict_count,
        request_count=request_count,
        failure_count=failure_count,
        coverage_rate=coverage_rate,
        conflict_rate=conflict_rate,
        failure_rate=failure_rate,
        total_duration_ms=total_duration_ms,
        p50_latency_ms=median(latencies) if latencies else None,
        p95_latency_ms=_percentile(latencies, 0.95),
        rows_per_second=rows_per_second,
        status=status,
        day_results=day_results,
        fusion_reports=fusion_reports,
        errors=errors,
    )


def score_vendor_quality(
    report: BenchmarkReport,
    latency_target_ms: float = 5000,
    cost_score: float = 80,
    license_risk_score: float = 80,
) -> VendorQualityScore:
    coverage = report.coverage_rate if report.coverage_rate is not None else 0
    conflict = report.conflict_rate if report.conflict_rate is not None else 1
    failure = report.failure_rate if report.failure_rate is not None else 1
    latency = report.p95_latency_ms
    coverage_score = _clamp(coverage * 100)
    conflict_score = _clamp((1 - conflict) * 100)
    stability_score = _clamp((1 - failure) * 100)
    latency_score = _clamp((1 - ((latency or latency_target_ms) / latency_target_ms)) * 100)
    total_score = round(
        coverage_score * 0.35
        + conflict_score * 0.25
        + stability_score * 0.20
        + latency_score * 0.10
        + _clamp(cost_score) * 0.05
        + _clamp(license_risk_score) * 0.05,
        4,
    )
    return VendorQualityScore(
        source_code=report.secondary_provider,
        dataset_code=report.dataset_code,
        score_date=report.end_date,
        coverage_rate=report.coverage_rate,
        conflict_rate=report.conflict_rate,
        failure_rate=report.failure_rate,
        latency_ms=report.p95_latency_ms,
        coverage_score=round(coverage_score, 4),
        conflict_score=round(conflict_score, 4),
        stability_score=round(stability_score, 4),
        latency_score=round(latency_score, 4),
        cost_score=round(_clamp(cost_score), 4),
        license_risk_score=round(_clamp(license_risk_score), 4),
        total_score=total_score,
        rating=_rating(total_score),
    )


def ensure_vendor_profile(
    postgres_dsn: str,
    *,
    source_code: str,
    source_name: str,
    provider_name: str,
    auth_mode: str = "none",
    endpoint_base: str | None = None,
    enabled_datasets: list[str] | None = None,
    rate_limit_per_min: int | None = None,
    retry_limit: int = 2,
    timeout_ms: int = 30000,
    license_scope: str | None = None,
    redistribution_allowed: bool | None = None,
    commercial_contract_ref: str | None = None,
    status: str = "testing",
    owner: str | None = "qdata",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        source_id = _ensure_source(connection, source_code, source_name, license_scope or "commercial contract required")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_integration_profile (
                    source_id, provider_name, auth_mode, endpoint_base, enabled_datasets,
                    rate_limit_per_min, retry_limit, timeout_ms, license_scope,
                    redistribution_allowed, commercial_contract_ref, status, owner, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (source_id, provider_name) DO UPDATE SET
                    auth_mode = EXCLUDED.auth_mode,
                    endpoint_base = EXCLUDED.endpoint_base,
                    enabled_datasets = EXCLUDED.enabled_datasets,
                    rate_limit_per_min = EXCLUDED.rate_limit_per_min,
                    retry_limit = EXCLUDED.retry_limit,
                    timeout_ms = EXCLUDED.timeout_ms,
                    license_scope = EXCLUDED.license_scope,
                    redistribution_allowed = EXCLUDED.redistribution_allowed,
                    commercial_contract_ref = EXCLUDED.commercial_contract_ref,
                    status = EXCLUDED.status,
                    owner = EXCLUDED.owner,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING profile_id, source_id, provider_name, status, created_at, updated_at
                """,
                (
                    source_id,
                    provider_name,
                    auth_mode,
                    endpoint_base,
                    enabled_datasets or [],
                    rate_limit_per_min,
                    retry_limit,
                    timeout_ms,
                    license_scope,
                    redistribution_allowed,
                    commercial_contract_ref,
                    status,
                    owner,
                    json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
            return _normalize(dict(cursor.fetchone()))


def record_benchmark_report(
    postgres_dsn: str,
    report: BenchmarkReport,
    score: VendorQualityScore | None = None,
    write_fusion_days: bool = True,
) -> dict[str, Any]:
    score = score or score_vendor_quality(report)
    if write_fusion_days:
        record_daily_fusion_reports(
            postgres_dsn,
            report.fusion_reports,
            details={"benchmark_code": report.benchmark_code, "stage": "eta_benchmark"},
        )
    with _connect(postgres_dsn) as connection:
        primary_source_id = _ensure_source(connection, report.primary_provider, report.primary_provider, "benchmark source")
        secondary_source_id = _ensure_source(connection, report.secondary_provider, report.secondary_provider, "benchmark source")
        dataset_id = _ensure_dataset(connection, report.dataset_code, primary_source_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.provider_benchmark_run (
                    benchmark_code, dataset_id, primary_source_id, secondary_source_id,
                    start_date, end_date, symbol_count, date_count, primary_row_count,
                    secondary_row_count, matched_count, conflict_count, request_count,
                    failure_count, coverage_rate, conflict_rate, failure_rate,
                    total_duration_ms, p50_latency_ms, p95_latency_ms, rows_per_second,
                    status, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (benchmark_code) DO UPDATE SET
                    primary_row_count = EXCLUDED.primary_row_count,
                    secondary_row_count = EXCLUDED.secondary_row_count,
                    matched_count = EXCLUDED.matched_count,
                    conflict_count = EXCLUDED.conflict_count,
                    request_count = EXCLUDED.request_count,
                    failure_count = EXCLUDED.failure_count,
                    coverage_rate = EXCLUDED.coverage_rate,
                    conflict_rate = EXCLUDED.conflict_rate,
                    failure_rate = EXCLUDED.failure_rate,
                    total_duration_ms = EXCLUDED.total_duration_ms,
                    p50_latency_ms = EXCLUDED.p50_latency_ms,
                    p95_latency_ms = EXCLUDED.p95_latency_ms,
                    rows_per_second = EXCLUDED.rows_per_second,
                    status = EXCLUDED.status,
                    details = EXCLUDED.details
                RETURNING benchmark_id
                """,
                (
                    report.benchmark_code,
                    dataset_id,
                    primary_source_id,
                    secondary_source_id,
                    report.start_date,
                    report.end_date,
                    report.symbol_count,
                    report.date_count,
                    report.primary_row_count,
                    report.secondary_row_count,
                    report.matched_count,
                    report.conflict_count,
                    report.request_count,
                    report.failure_count,
                    report.coverage_rate,
                    report.conflict_rate,
                    report.failure_rate,
                    round(report.total_duration_ms),
                    report.p50_latency_ms,
                    report.p95_latency_ms,
                    report.rows_per_second,
                    report.status,
                    _json({"day_results": [asdict(item) for item in report.day_results]}),
                ),
            )
            benchmark_id = cursor.fetchone()["benchmark_id"]
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_quality_score_daily (
                    source_id, dataset_id, score_date, benchmark_id, coverage_rate,
                    conflict_rate, failure_rate, latency_ms, coverage_score,
                    conflict_score, stability_score, latency_score, cost_score,
                    license_risk_score, total_score, rating, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (source_id, dataset_id, score_date) DO UPDATE SET
                    benchmark_id = EXCLUDED.benchmark_id,
                    coverage_rate = EXCLUDED.coverage_rate,
                    conflict_rate = EXCLUDED.conflict_rate,
                    failure_rate = EXCLUDED.failure_rate,
                    latency_ms = EXCLUDED.latency_ms,
                    coverage_score = EXCLUDED.coverage_score,
                    conflict_score = EXCLUDED.conflict_score,
                    stability_score = EXCLUDED.stability_score,
                    latency_score = EXCLUDED.latency_score,
                    cost_score = EXCLUDED.cost_score,
                    license_risk_score = EXCLUDED.license_risk_score,
                    total_score = EXCLUDED.total_score,
                    rating = EXCLUDED.rating,
                    details = EXCLUDED.details
                """,
                (
                    secondary_source_id,
                    dataset_id,
                    score.score_date,
                    benchmark_id,
                    score.coverage_rate,
                    score.conflict_rate,
                    score.failure_rate,
                    score.latency_ms,
                    score.coverage_score,
                    score.conflict_score,
                    score.stability_score,
                    score.latency_score,
                    score.cost_score,
                    score.license_risk_score,
                    score.total_score,
                    score.rating,
                    _json({"benchmark_code": report.benchmark_code}),
                ),
            )
            for error in report.errors:
                cursor.execute(
                    """
                    INSERT INTO qmeta.provider_error_event (
                        source_id, dataset_id, provider_name, trade_date, symbol,
                        error_stage, error_type, retryable, attempt, error_message, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        secondary_source_id if error.provider_name == report.secondary_provider else primary_source_id,
                        dataset_id,
                        error.provider_name,
                        error.trade_date,
                        error.symbol,
                        error.error_stage,
                        error.error_type,
                        error.retryable,
                        error.attempt,
                        error.error_message[:1000],
                        _json(error.details),
                    ),
                )
    return {"benchmark_code": report.benchmark_code, "rating": score.rating, "total_score": score.total_score}


def record_daily_fusion_reports(
    postgres_dsn: str,
    reports: list[FusionReport],
    details: dict[str, Any] | None = None,
) -> int:
    for report in reports:
        record_fusion_report(postgres_dsn, report, details=details)
    return len(reports)


def format_benchmark_report(report: BenchmarkReport, score: VendorQualityScore) -> str:
    return (
        f"vendor_benchmark code={report.benchmark_code} primary={report.primary_provider} secondary={report.secondary_provider} "
        f"start={report.start_date} end={report.end_date} symbols={report.symbol_count} dates={report.date_count} "
        f"primary_rows={report.primary_row_count} secondary_rows={report.secondary_row_count} matched={report.matched_count} "
        f"conflicts={report.conflict_count} coverage_rate={report.coverage_rate} conflict_rate={report.conflict_rate} "
        f"failure_rate={report.failure_rate} p50_ms={_round_or_none(report.p50_latency_ms)} p95_ms={_round_or_none(report.p95_latency_ms)} "
        f"rows_per_second={report.rows_per_second:.2f} status={report.status} score={score.total_score:.2f} rating={score.rating}"
    )


def _provider_errors(provider) -> list[ProviderErrorRecord]:
    result = []
    for event in getattr(provider, "error_events", []) or []:
        result.append(
            ProviderErrorRecord(
                provider_name=event.provider_name,
                error_stage=event.error_stage,
                error_type=event.error_type,
                retryable=event.retryable,
                error_message=event.error_message,
                trade_date=event.trade_date,
                symbol=event.symbol,
                attempt=event.attempt,
                details=event.details or {},
            )
        )
    return result


def _iter_dates(start_date: str, end_date: str):
    start, end = date_range(start_date, end_date)
    current = start
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 8)


def _benchmark_status(failure_rate: float | None, conflict_count: int) -> str:
    if failure_rate is not None and failure_rate > 0.5:
        return "failed"
    if conflict_count or (failure_rate is not None and failure_rate > 0):
        return "warning"
    return "success"


def _benchmark_code(primary: str, secondary: str, start_date: str, end_date: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"bench-{primary}-{secondary}-{start_date}-{end_date}-{stamp}"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _rating(total_score: float) -> str:
    if total_score >= 90:
        return "A"
    if total_score >= 75:
        return "B"
    if total_score >= 60:
        return "C"
    return "D"


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Eta benchmark metadata") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _ensure_source(connection, source_code: str, source_name: str, license_scope: str) -> int:
    source_type = "internal" if source_code in {"csv", "local_csv", "csv_mirror", "qdata", "qdata_api"} else "vendor"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO qmeta.source_system (
                source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner
            ) VALUES (%s, %s, %s, %s, 'daily', 'L4', 'qdata')
            ON CONFLICT (source_code) DO UPDATE SET
                source_name = EXCLUDED.source_name,
                source_type = EXCLUDED.source_type,
                license_scope = EXCLUDED.license_scope,
                updated_at = now()
            RETURNING source_id
            """,
            (source_code, source_name, source_type, license_scope),
        )
        return int(cursor.fetchone()["source_id"])


def _ensure_dataset(connection, dataset_code: str, primary_source_id: int) -> int:
    dataset_name, asset_type, frequency, storage_layer = {
        "daily_bar": ("日线行情", "stock", "1d", "clickhouse"),
        "minute_bar": ("分钟行情", "stock", "1m", "clickhouse"),
        "adjustment_factor": ("复权因子", "stock", "1d", "postgresql"),
        "limit_price_daily": ("涨跌停和交易约束", "stock", "1d", "postgresql"),
    }.get(dataset_code, (dataset_code, None, None, "postgresql"))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO qmeta.dataset_catalog (
                dataset_code, dataset_name, asset_type, frequency, storage_layer,
                primary_source_id, pit_required, description
            ) VALUES (%s, %s, %s, %s, %s, %s, FALSE, 'created by Eta benchmark')
            ON CONFLICT (dataset_code) DO UPDATE SET
                dataset_name = EXCLUDED.dataset_name,
                asset_type = EXCLUDED.asset_type,
                frequency = EXCLUDED.frequency,
                storage_layer = EXCLUDED.storage_layer,
                primary_source_id = EXCLUDED.primary_source_id,
                updated_at = now()
            RETURNING dataset_id
            """,
            (dataset_code, dataset_name, asset_type, frequency, storage_layer, primary_source_id),
        )
        return int(cursor.fetchone()["dataset_id"])


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([row])[0]
