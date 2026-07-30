from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import os
from statistics import median
from typing import Any, Callable, Iterable, Mapping

from qdata.backend_utils import date_range, normalize_rows
from qdata.eta import (
    BenchmarkReport,
    VendorQualityScore,
    _ensure_dataset,
    _ensure_source,
    _json,
    record_benchmark_report,
    run_provider_benchmark,
    score_vendor_quality,
)
from qdata.exceptions import QDataValidationError
from qdata.fusion import DAILY_COMPARE_FIELDS
from qdata.sources.field_mapping import FieldMappingRule, rules_to_mapping
from qdata.sources.registry import create_provider


DEFAULT_DAILY_BAR_FIELD_MAPPINGS = [
    FieldMappingRule("symbol", "symbol", priority=1, is_required=True),
    FieldMappingRule("ts_code", "symbol", priority=2, is_required=True),
    FieldMappingRule("code", "symbol", priority=3, is_required=True),
    FieldMappingRule("trade_date", "trade_date", priority=1, is_required=True),
    FieldMappingRule("date", "trade_date", "date_yyyymmdd", priority=2, is_required=True),
    FieldMappingRule("tradeDate", "trade_date", "date_yyyymmdd", priority=3, is_required=True),
    FieldMappingRule("open", "open"),
    FieldMappingRule("high", "high"),
    FieldMappingRule("low", "low"),
    FieldMappingRule("close", "close"),
    FieldMappingRule("pre_close", "pre_close"),
    FieldMappingRule("previous_close", "pre_close"),
    FieldMappingRule("volume", "volume", unit_to="share"),
    FieldMappingRule("vol", "volume", "volume_hand_to_share", unit_from="hand", unit_to="share"),
    FieldMappingRule("amount", "amount", unit_to="yuan"),
    FieldMappingRule("turnover_amount", "amount", unit_to="yuan"),
    FieldMappingRule("amount_thousand", "amount", "amount_thousand_to_yuan", unit_from="thousand_yuan", unit_to="yuan"),
    FieldMappingRule("amount_wan", "amount", "amount_wan_to_yuan", unit_from="wan_yuan", unit_to="yuan"),
    FieldMappingRule("vwap", "vwap"),
    FieldMappingRule("turnover_rate", "turnover_rate"),
    FieldMappingRule("turnover_ratio", "turnover_rate"),
    FieldMappingRule("turnover_pct", "turnover_rate", "pct_to_ratio", unit_from="pct", unit_to="ratio"),
    FieldMappingRule("limit_up", "limit_up"),
    FieldMappingRule("limit_down", "limit_down"),
    FieldMappingRule("is_suspended", "is_suspended"),
    FieldMappingRule("factor_forward", "factor_forward"),
    FieldMappingRule("factor_backward", "factor_backward"),
    FieldMappingRule("ex_right_type", "ex_right_type"),
]

DEFAULT_ADJUSTMENT_FACTOR_FIELD_MAPPINGS = [
    FieldMappingRule("symbol", "symbol", priority=1, is_required=True),
    FieldMappingRule("ts_code", "symbol", priority=2, is_required=True),
    FieldMappingRule("code", "symbol", priority=3, is_required=True),
    FieldMappingRule("trade_date", "trade_date", priority=1, is_required=True),
    FieldMappingRule("date", "trade_date", "date_yyyymmdd", priority=2, is_required=True),
    FieldMappingRule("factor_forward", "factor_forward", is_required=True),
    FieldMappingRule("adj_factor", "factor_forward"),
    FieldMappingRule("factor_backward", "factor_backward"),
    FieldMappingRule("hfq_factor", "factor_backward"),
    FieldMappingRule("ex_right_type", "ex_right_type"),
]

DEFAULT_LIMIT_PRICE_FIELD_MAPPINGS = [
    FieldMappingRule("symbol", "symbol", priority=1, is_required=True),
    FieldMappingRule("ts_code", "symbol", priority=2, is_required=True),
    FieldMappingRule("code", "symbol", priority=3, is_required=True),
    FieldMappingRule("trade_date", "trade_date", priority=1, is_required=True),
    FieldMappingRule("date", "trade_date", "date_yyyymmdd", priority=2, is_required=True),
    FieldMappingRule("limit_up", "limit_up", is_required=True),
    FieldMappingRule("up_limit", "limit_up"),
    FieldMappingRule("limit_down", "limit_down", is_required=True),
    FieldMappingRule("down_limit", "limit_down"),
    FieldMappingRule("limit_rule", "limit_rule"),
    FieldMappingRule("is_st", "is_st"),
    FieldMappingRule("is_new_listing", "is_new_listing"),
]

DEFAULT_SECURITY_MASTER_FIELD_MAPPINGS = [
    FieldMappingRule("symbol", "symbol", priority=1, is_required=True),
    FieldMappingRule("ts_code", "symbol", priority=2, is_required=True),
    FieldMappingRule("code", "symbol", priority=3, is_required=True),
    FieldMappingRule("name", "name", is_required=True),
    FieldMappingRule("stock_name", "name"),
    FieldMappingRule("asset_type", "asset_type"),
    FieldMappingRule("currency", "currency"),
    FieldMappingRule("list_date", "list_date", "date_yyyymmdd"),
    FieldMappingRule("ipo_date", "list_date", "date_yyyymmdd"),
    FieldMappingRule("delist_date", "delist_date", "date_yyyymmdd"),
    FieldMappingRule("status", "status"),
]

DEFAULT_FIELD_MAPPINGS_BY_DATASET = {
    "daily_bar": DEFAULT_DAILY_BAR_FIELD_MAPPINGS,
    "adjustment_factor": DEFAULT_ADJUSTMENT_FACTOR_FIELD_MAPPINGS,
    "limit_price_daily": DEFAULT_LIMIT_PRICE_FIELD_MAPPINGS,
    "security_master": DEFAULT_SECURITY_MASTER_FIELD_MAPPINGS,
}


@dataclass(frozen=True)
class VendorRuntimeConfig:
    provider_name: str = "vendor_http"
    source_code: str = "vendor_http"
    base_url: str | None = None
    daily_path: str = "/daily"
    token: str | None = None
    auth_mode: str = "none"
    api_key_header: str = "X-API-Key"
    query_token_param: str = "token"
    username: str | None = None
    password: str | None = None
    timeout: float = 30
    retry_limit: int = 2
    retry_sleep_seconds: float = 0
    rate_limit_per_min: int | None = None
    response_rows_key: str = "data"


@dataclass(frozen=True)
class BenchmarkShardResult:
    trade_date: str
    shard_index: int
    symbol_count: int
    status: str
    benchmark_code: str
    primary_rows: int
    secondary_rows: int
    matched_count: int
    conflict_count: int
    request_count: int
    failure_count: int
    p95_latency_ms: float | None


@dataclass(frozen=True)
class BenchmarkSuiteReport:
    suite_code: str
    dataset_code: str
    primary_provider: str
    secondary_provider: str
    start_date: str
    end_date: str
    target_trade_days: int | None
    shard_size: int
    max_symbols: int | None
    symbol_count: int
    shard_count: int
    benchmark_count: int
    primary_row_count: int
    secondary_row_count: int
    matched_count: int
    conflict_count: int
    request_count: int
    failure_count: int
    coverage_rate: float | None
    conflict_rate: float | None
    failure_rate: float | None
    p95_latency_ms: float | None
    rows_per_second: float
    status: str
    shard_results: list[BenchmarkShardResult]
    benchmark_reports: list[BenchmarkReport] = field(default_factory=list)


@dataclass(frozen=True)
class VendorDecision:
    source_code: str
    dataset_code: str
    score_date: str
    total_score: float | None
    rating: str | None
    recommendation: str
    recommended_role: str
    rationale: str
    blocking_issues: list[str]
    next_actions: list[str]
    details: dict[str, Any] = field(default_factory=dict)


def load_vendor_runtime_config(
    provider_name: str = "vendor_http",
    environ: Mapping[str, str] | None = None,
    prefix: str = "QDATA_VENDOR",
) -> VendorRuntimeConfig:
    env = environ or os.environ
    return VendorRuntimeConfig(
        provider_name=provider_name,
        source_code=env.get(f"{prefix}_SOURCE_CODE", provider_name),
        base_url=_blank_to_none(env.get(f"{prefix}_BASE_URL")),
        daily_path=env.get(f"{prefix}_DAILY_PATH", "/daily"),
        token=_blank_to_none(env.get(f"{prefix}_TOKEN")),
        auth_mode=env.get(f"{prefix}_AUTH_MODE", "none"),
        api_key_header=env.get(f"{prefix}_API_KEY_HEADER", "X-API-Key"),
        query_token_param=env.get(f"{prefix}_QUERY_TOKEN_PARAM", "token"),
        username=_blank_to_none(env.get(f"{prefix}_USERNAME")),
        password=_blank_to_none(env.get(f"{prefix}_PASSWORD")),
        timeout=_float_env(env, f"{prefix}_TIMEOUT_SECONDS", 30),
        retry_limit=_int_env(env, f"{prefix}_RETRY_LIMIT", 2),
        retry_sleep_seconds=_float_env(env, f"{prefix}_RETRY_SLEEP_SECONDS", 0),
        rate_limit_per_min=_int_env(env, f"{prefix}_RATE_LIMIT_PER_MIN", None),
        response_rows_key=env.get(f"{prefix}_RESPONSE_ROWS_KEY", "data"),
    )


def vendor_provider_kwargs(
    config: VendorRuntimeConfig,
    field_mapping: dict[str, str] | None = None,
    field_transforms: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not config.base_url:
        raise QDataValidationError("QDATA_VENDOR_BASE_URL is required for production vendor_http mode")
    return {
        "source_code": config.source_code,
        "base_url": config.base_url,
        "daily_path": config.daily_path,
        "token": config.token,
        "auth_mode": config.auth_mode,
        "api_key_header": config.api_key_header,
        "query_token_param": config.query_token_param,
        "username": config.username,
        "password": config.password,
        "timeout": config.timeout,
        "retry_limit": config.retry_limit,
        "retry_sleep_seconds": config.retry_sleep_seconds,
        "rate_limit_per_min": config.rate_limit_per_min,
        "response_rows_key": config.response_rows_key,
        "field_mapping": field_mapping,
        "field_transforms": field_transforms,
    }


def redacted_vendor_config(config: VendorRuntimeConfig) -> dict[str, Any]:
    data = asdict(config)
    for key in ("token", "username", "password"):
        if data.get(key):
            data[key] = "***"
    return data


def ensure_default_field_mappings(
    postgres_dsn: str,
    source_code: str,
    dataset_code: str = "daily_bar",
    rules: list[FieldMappingRule] | None = None,
) -> int:
    rules = rules or DEFAULT_FIELD_MAPPINGS_BY_DATASET.get(dataset_code, DEFAULT_DAILY_BAR_FIELD_MAPPINGS)
    with _connect(postgres_dsn) as connection:
        source_id = _ensure_source(connection, source_code, source_code, "vendor field mapping")
        dataset_id = _ensure_dataset(connection, dataset_code, source_id)
        with connection.cursor() as cursor:
            for rule in rules:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_field_mapping (
                        source_id, dataset_id, external_field, internal_field, transform_rule,
                        unit_from, unit_to, is_required, priority, status, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', '{}'::jsonb)
                    ON CONFLICT (source_id, dataset_id, external_field) DO UPDATE SET
                        internal_field = EXCLUDED.internal_field,
                        transform_rule = EXCLUDED.transform_rule,
                        unit_from = EXCLUDED.unit_from,
                        unit_to = EXCLUDED.unit_to,
                        is_required = EXCLUDED.is_required,
                        priority = EXCLUDED.priority,
                        status = 'active',
                        updated_at = now()
                    """,
                    (
                        source_id,
                        dataset_id,
                        rule.external_field,
                        rule.internal_field,
                        rule.transform_rule,
                        rule.unit_from,
                        rule.unit_to,
                        rule.is_required,
                        rule.priority,
                    ),
                )
    return len(rules)


def load_active_field_mapping(
    postgres_dsn: str,
    source_code: str,
    dataset_code: str = "daily_bar",
) -> tuple[dict[str, str], dict[str, str]]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_field, internal_field, transform_rule, unit_from, unit_to,
                       is_required, priority
                FROM qmeta.vendor_field_mapping vfm
                JOIN qmeta.source_system ss ON ss.source_id = vfm.source_id
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vfm.dataset_id
                WHERE ss.source_code = %s
                  AND dc.dataset_code = %s
                  AND vfm.status = 'active'
                ORDER BY priority, external_field
                """,
                (source_code, dataset_code),
            )
            rules = [
                FieldMappingRule(
                    external_field=row["external_field"],
                    internal_field=row["internal_field"],
                    transform_rule=row["transform_rule"],
                    unit_from=row["unit_from"],
                    unit_to=row["unit_to"],
                    is_required=row["is_required"],
                    priority=row["priority"],
                )
                for row in cursor.fetchall()
            ]
    return rules_to_mapping(rules)


def update_vendor_profile_status(
    postgres_dsn: str,
    source_code: str,
    provider_name: str,
    status: str,
) -> dict[str, Any]:
    if status not in {"testing", "active", "paused", "retired"}:
        raise QDataValidationError("status must be one of: testing, active, paused, retired")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.vendor_integration_profile vip
                SET status = %s, updated_at = now()
                FROM qmeta.source_system ss
                WHERE ss.source_id = vip.source_id
                  AND ss.source_code = %s
                  AND vip.provider_name = %s
                RETURNING vip.profile_id, ss.source_code, vip.provider_name, vip.status, vip.updated_at
                """,
                (status, source_code, provider_name),
            )
            row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"vendor profile not found: {source_code}/{provider_name}")
    return normalize_rows([dict(row)])[0]


def run_sharded_provider_benchmark(
    primary_provider: str,
    secondary_provider: str,
    start_date: str,
    end_date: str,
    symbols: list[str] | None = None,
    primary_kwargs: dict[str, Any] | None = None,
    secondary_kwargs: dict[str, Any] | None = None,
    fields: Iterable[str] = DAILY_COMPARE_FIELDS,
    shard_size: int = 500,
    max_symbols: int | None = None,
    target_trade_days: int | None = None,
    absolute_tolerance: float = 1e-8,
    relative_tolerance: float | None = None,
    dataset_code: str = "daily_bar",
    provider_factory: Callable[..., Any] = create_provider,
) -> BenchmarkSuiteReport:
    if shard_size <= 0:
        raise QDataValidationError("shard_size must be greater than 0")
    if max_symbols is not None and max_symbols <= 0:
        raise QDataValidationError("max_symbols must be greater than 0")
    if target_trade_days is not None and target_trade_days <= 0:
        raise QDataValidationError("target_trade_days must be greater than 0")
    fields = tuple(fields)
    symbols = _resolve_symbols(
        primary_provider,
        secondary_provider,
        start_date,
        end_date,
        symbols,
        primary_kwargs or {},
        secondary_kwargs or {},
        max_symbols,
        provider_factory,
    )
    dates = _resolve_trade_dates(
        primary_provider,
        start_date,
        end_date,
        target_trade_days,
        primary_kwargs or {},
        provider_factory,
    )
    shards = list(_shards(symbols, shard_size))
    reports: list[BenchmarkReport] = []
    shard_results: list[BenchmarkShardResult] = []
    for trade_date in dates:
        for index, shard_symbols in enumerate(shards, start=1):
            report = run_provider_benchmark(
                primary_provider=primary_provider,
                secondary_provider=secondary_provider,
                start_date=trade_date,
                end_date=trade_date,
                symbols=shard_symbols,
                primary_kwargs=primary_kwargs,
                secondary_kwargs=secondary_kwargs,
                fields=fields,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                dataset_code=dataset_code,
                provider_factory=provider_factory,
            )
            reports.append(report)
            shard_results.append(
                BenchmarkShardResult(
                    trade_date=trade_date,
                    shard_index=index,
                    symbol_count=len(shard_symbols),
                    status=report.status,
                    benchmark_code=report.benchmark_code,
                    primary_rows=report.primary_row_count,
                    secondary_rows=report.secondary_row_count,
                    matched_count=report.matched_count,
                    conflict_count=report.conflict_count,
                    request_count=report.request_count,
                    failure_count=report.failure_count,
                    p95_latency_ms=report.p95_latency_ms,
                )
            )
    return _aggregate_suite(
        primary_provider,
        secondary_provider,
        start_date,
        end_date,
        target_trade_days,
        shard_size,
        max_symbols,
        len(symbols),
        len(shards),
        fields,
        dataset_code,
        reports,
        shard_results,
    )


def record_benchmark_suite_report(
    postgres_dsn: str,
    suite: BenchmarkSuiteReport,
    write_child_benchmarks: bool = True,
    cost_score: float = 80,
    license_risk_score: float = 80,
) -> dict[str, Any]:
    if write_child_benchmarks:
        for report in suite.benchmark_reports:
            record_benchmark_report(
                postgres_dsn,
                report,
                score_vendor_quality(report, cost_score=cost_score, license_risk_score=license_risk_score),
            )
    aggregate_score = score_vendor_quality(
        _suite_to_benchmark_report(suite),
        cost_score=cost_score,
        license_risk_score=license_risk_score,
    )
    with _connect(postgres_dsn) as connection:
        primary_source_id = _ensure_source(connection, suite.primary_provider, suite.primary_provider, "benchmark source")
        secondary_source_id = _ensure_source(connection, suite.secondary_provider, suite.secondary_provider, "benchmark source")
        dataset_id = _ensure_dataset(connection, suite.dataset_code, primary_source_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.provider_benchmark_suite_run (
                    suite_code, dataset_id, primary_source_id, secondary_source_id,
                    start_date, end_date, target_trade_days, shard_size, max_symbols,
                    symbol_count, shard_count, benchmark_count, primary_row_count,
                    secondary_row_count, matched_count, conflict_count, request_count,
                    failure_count, coverage_rate, conflict_rate, failure_rate,
                    p95_latency_ms, rows_per_second, status, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (suite_code) DO UPDATE SET
                    primary_row_count = EXCLUDED.primary_row_count,
                    secondary_row_count = EXCLUDED.secondary_row_count,
                    matched_count = EXCLUDED.matched_count,
                    conflict_count = EXCLUDED.conflict_count,
                    request_count = EXCLUDED.request_count,
                    failure_count = EXCLUDED.failure_count,
                    coverage_rate = EXCLUDED.coverage_rate,
                    conflict_rate = EXCLUDED.conflict_rate,
                    failure_rate = EXCLUDED.failure_rate,
                    p95_latency_ms = EXCLUDED.p95_latency_ms,
                    rows_per_second = EXCLUDED.rows_per_second,
                    status = EXCLUDED.status,
                    details = EXCLUDED.details
                RETURNING suite_id
                """,
                (
                    suite.suite_code,
                    dataset_id,
                    primary_source_id,
                    secondary_source_id,
                    suite.start_date,
                    suite.end_date,
                    suite.target_trade_days,
                    suite.shard_size,
                    suite.max_symbols,
                    suite.symbol_count,
                    suite.shard_count,
                    suite.benchmark_count,
                    suite.primary_row_count,
                    suite.secondary_row_count,
                    suite.matched_count,
                    suite.conflict_count,
                    suite.request_count,
                    suite.failure_count,
                    suite.coverage_rate,
                    suite.conflict_rate,
                    suite.failure_rate,
                    suite.p95_latency_ms,
                    suite.rows_per_second,
                    suite.status,
                    _json(
                        {
                            "shards": [asdict(item) for item in suite.shard_results],
                            "benchmark_codes": [report.benchmark_code for report in suite.benchmark_reports],
                        }
                    ),
                ),
            )
            suite_id = int(cursor.fetchone()["suite_id"])
            _upsert_vendor_quality_score(cursor, secondary_source_id, dataset_id, None, aggregate_score, {"suite_code": suite.suite_code, "suite_id": suite_id})
    return {
        "suite_id": suite_id,
        "suite_code": suite.suite_code,
        "score": aggregate_score.total_score,
        "rating": aggregate_score.rating,
    }


def fetch_latest_vendor_scores(
    postgres_dsn: str,
    dataset_code: str,
    source_code: str | None = None,
) -> list[dict[str, Any]]:
    where = ["dc.dataset_code = %s"]
    params: list[Any] = [dataset_code]
    if source_code:
        where.append("ss.source_code = %s")
        params.append(source_code)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT DISTINCT ON (vq.source_id, vq.dataset_id)
                    vq.*, ss.source_code, dc.dataset_code
                FROM qmeta.vendor_quality_score_daily vq
                JOIN qmeta.source_system ss ON ss.source_id = vq.source_id
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vq.dataset_id
                WHERE {' AND '.join(where)}
                ORDER BY vq.source_id, vq.dataset_id, vq.score_date DESC, vq.created_at DESC
                """,
                tuple(params),
            )
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def build_vendor_decision(score_row: dict[str, Any]) -> VendorDecision:
    total_score = _float_or_none(score_row.get("total_score"))
    conflict_rate = _float_or_none(score_row.get("conflict_rate"))
    failure_rate = _float_or_none(score_row.get("failure_rate"))
    latency_ms = _float_or_none(score_row.get("latency_ms"))
    license_risk_score = _float_or_none(score_row.get("license_risk_score"))
    blocking: list[str] = []
    if conflict_rate is not None and conflict_rate > 0.005:
        blocking.append(f"conflict_rate={conflict_rate:.6f} above primary threshold 0.005")
    if failure_rate is not None and failure_rate > 0.01:
        blocking.append(f"failure_rate={failure_rate:.6f} above primary threshold 0.01")
    if latency_ms is not None and latency_ms > 5000:
        blocking.append(f"p95_latency_ms={latency_ms:.2f} above primary threshold 5000")
    if license_risk_score is not None and license_risk_score < 70:
        blocking.append(f"license_risk_score={license_risk_score:.2f} below primary threshold 70")

    rating = score_row.get("rating")
    if total_score is None:
        recommendation = "reject"
        role = "none"
        rationale = "No vendor score is available."
    elif total_score >= 90 and rating == "A" and not blocking:
        recommendation = "approve_primary"
        role = "primary"
        rationale = "Vendor quality, stability, latency and license risk meet primary-source thresholds."
    elif total_score >= 75 and (failure_rate is None or failure_rate <= 0.05):
        recommendation = "approve_backup"
        role = "backup"
        rationale = "Vendor is usable as a backup source, but one or more primary-source thresholds still need work."
    elif total_score >= 60:
        recommendation = "watch"
        role = "research_only"
        rationale = "Vendor is useful for research comparison, but production use needs more validation."
    else:
        recommendation = "reject"
        role = "none"
        rationale = "Vendor score is below the minimum production watch threshold."

    next_actions = _decision_next_actions(recommendation, blocking)
    return VendorDecision(
        source_code=score_row["source_code"],
        dataset_code=score_row["dataset_code"],
        score_date=score_row["score_date"],
        total_score=total_score,
        rating=rating,
        recommendation=recommendation,
        recommended_role=role,
        rationale=rationale,
        blocking_issues=blocking,
        next_actions=next_actions,
        details={
            "coverage_rate": score_row.get("coverage_rate"),
            "conflict_rate": score_row.get("conflict_rate"),
            "failure_rate": score_row.get("failure_rate"),
            "latency_ms": score_row.get("latency_ms"),
        },
    )


def generate_vendor_decision_reports(
    postgres_dsn: str,
    dataset_code: str,
    source_code: str | None = None,
    write_db: bool = False,
) -> list[VendorDecision]:
    scores = fetch_latest_vendor_scores(postgres_dsn, dataset_code, source_code)
    decisions = [build_vendor_decision(row) for row in scores]
    if write_db:
        record_vendor_decisions(postgres_dsn, decisions)
    return decisions


def record_vendor_decisions(postgres_dsn: str, decisions: list[VendorDecision]) -> int:
    if not decisions:
        return 0
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for decision in decisions:
                source_id = _lookup_source_id(cursor, decision.source_code)
                dataset_id = _lookup_dataset_id(cursor, decision.dataset_code)
                report_code = _decision_report_code(decision)
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_decision_report (
                        report_code, source_id, dataset_id, score_date, total_score,
                        rating, recommendation, recommended_role, rationale,
                        blocking_issues, next_actions, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (report_code) DO UPDATE SET
                        total_score = EXCLUDED.total_score,
                        rating = EXCLUDED.rating,
                        recommendation = EXCLUDED.recommendation,
                        recommended_role = EXCLUDED.recommended_role,
                        rationale = EXCLUDED.rationale,
                        blocking_issues = EXCLUDED.blocking_issues,
                        next_actions = EXCLUDED.next_actions,
                        details = EXCLUDED.details,
                        updated_at = now()
                    """,
                    (
                        report_code,
                        source_id,
                        dataset_id,
                        decision.score_date,
                        decision.total_score,
                        decision.rating,
                        decision.recommendation,
                        decision.recommended_role,
                        decision.rationale,
                        decision.blocking_issues,
                        decision.next_actions,
                        _json(decision.details),
                    ),
                )
    return len(decisions)


def format_benchmark_suite_report(suite: BenchmarkSuiteReport, score: VendorQualityScore | None = None) -> str:
    score_text = f" score={score.total_score:.2f} rating={score.rating}" if score else ""
    return (
        f"vendor_benchmark_suite code={suite.suite_code} primary={suite.primary_provider} secondary={suite.secondary_provider} "
        f"start={suite.start_date} end={suite.end_date} target_days={suite.target_trade_days} symbols={suite.symbol_count} "
        f"shards={suite.shard_count} benchmarks={suite.benchmark_count} primary_rows={suite.primary_row_count} "
        f"secondary_rows={suite.secondary_row_count} matched={suite.matched_count} conflicts={suite.conflict_count} "
        f"coverage_rate={suite.coverage_rate} conflict_rate={suite.conflict_rate} failure_rate={suite.failure_rate} "
        f"p95_ms={_round_or_none(suite.p95_latency_ms)} rows_per_second={suite.rows_per_second:.2f} status={suite.status}{score_text}"
    )


def format_decision_reports(decisions: list[VendorDecision]) -> str:
    lines = [f"vendor_decisions rows={len(decisions)}"]
    for decision in decisions:
        issues = "; ".join(decision.blocking_issues) if decision.blocking_issues else "none"
        lines.append(
            f"decision source={decision.source_code} dataset={decision.dataset_code} score={decision.total_score} "
            f"rating={decision.rating} recommendation={decision.recommendation} role={decision.recommended_role} issues={issues}"
        )
    return "\n".join(lines)


def _aggregate_suite(
    primary_provider: str,
    secondary_provider: str,
    start_date: str,
    end_date: str,
    target_trade_days: int | None,
    shard_size: int,
    max_symbols: int | None,
    symbol_count: int,
    shard_count: int,
    fields: tuple[str, ...],
    dataset_code: str,
    reports: list[BenchmarkReport],
    shard_results: list[BenchmarkShardResult],
) -> BenchmarkSuiteReport:
    primary_rows = sum(report.primary_row_count for report in reports)
    secondary_rows = sum(report.secondary_row_count for report in reports)
    matched_count = sum(report.matched_count for report in reports)
    conflict_count = sum(report.conflict_count for report in reports)
    request_count = sum(report.request_count for report in reports)
    failure_count = sum(report.failure_count for report in reports)
    total_duration_ms = sum(report.total_duration_ms for report in reports)
    p95_values = [report.p95_latency_ms for report in reports if report.p95_latency_ms is not None]
    benchmark_count = len(reports)
    failure_rate = _safe_rate(failure_count, benchmark_count)
    comparable_fields = matched_count * len(fields)
    status = _suite_status(failure_rate, conflict_count)
    return BenchmarkSuiteReport(
        suite_code=_suite_code(primary_provider, secondary_provider, start_date, end_date),
        dataset_code=dataset_code,
        primary_provider=primary_provider,
        secondary_provider=secondary_provider,
        start_date=start_date,
        end_date=end_date,
        target_trade_days=target_trade_days,
        shard_size=shard_size,
        max_symbols=max_symbols,
        symbol_count=symbol_count,
        shard_count=shard_count,
        benchmark_count=benchmark_count,
        primary_row_count=primary_rows,
        secondary_row_count=secondary_rows,
        matched_count=matched_count,
        conflict_count=conflict_count,
        request_count=request_count,
        failure_count=failure_count,
        coverage_rate=_safe_rate(matched_count, primary_rows),
        conflict_rate=_safe_rate(conflict_count, comparable_fields),
        failure_rate=failure_rate,
        p95_latency_ms=_percentile(p95_values, 0.95),
        rows_per_second=(primary_rows + secondary_rows) / (total_duration_ms / 1000) if total_duration_ms else 0,
        status=status,
        shard_results=shard_results,
        benchmark_reports=reports,
    )


def _suite_to_benchmark_report(suite: BenchmarkSuiteReport) -> BenchmarkReport:
    latency_values = [item.p95_latency_ms for item in suite.shard_results if item.p95_latency_ms is not None]
    return BenchmarkReport(
        benchmark_code=suite.suite_code,
        dataset_code=suite.dataset_code,
        primary_provider=suite.primary_provider,
        secondary_provider=suite.secondary_provider,
        start_date=suite.start_date,
        end_date=suite.end_date,
        symbol_count=suite.symbol_count,
        date_count=max(1, len({item.trade_date for item in suite.shard_results})),
        primary_row_count=suite.primary_row_count,
        secondary_row_count=suite.secondary_row_count,
        matched_count=suite.matched_count,
        conflict_count=suite.conflict_count,
        request_count=suite.request_count,
        failure_count=suite.failure_count,
        coverage_rate=suite.coverage_rate,
        conflict_rate=suite.conflict_rate,
        failure_rate=suite.failure_rate,
        total_duration_ms=0,
        p50_latency_ms=median(latency_values) if latency_values else None,
        p95_latency_ms=suite.p95_latency_ms,
        rows_per_second=suite.rows_per_second,
        status=suite.status,
        day_results=[],
        fusion_reports=[],
        errors=[],
    )


def _upsert_vendor_quality_score(cursor, source_id: int, dataset_id: int, benchmark_id: int | None, score: VendorQualityScore, details: dict[str, Any]) -> None:
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
            source_id,
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
            _json(details),
        ),
    )


def _resolve_symbols(
    primary_provider: str,
    secondary_provider: str,
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    primary_kwargs: dict[str, Any],
    secondary_kwargs: dict[str, Any],
    max_symbols: int | None,
    provider_factory: Callable[..., Any],
) -> list[str]:
    if symbols:
        resolved = [item.strip().upper() for item in symbols if item.strip()]
    else:
        resolved = []
        for provider_name, kwargs in ((primary_provider, primary_kwargs), (secondary_provider, secondary_kwargs)):
            provider = provider_factory(provider_name, **kwargs)
            list_symbols = getattr(provider, "list_symbols", None)
            if not list_symbols:
                continue
            try:
                resolved = list_symbols(end_date)
            except TypeError:
                resolved = list_symbols()
            if resolved:
                break
    resolved = sorted(dict.fromkeys(symbol.upper() for symbol in resolved))
    if max_symbols:
        resolved = resolved[:max_symbols]
    if not resolved:
        raise QDataValidationError("symbols are required or provider must support list_symbols")
    return resolved


def _resolve_trade_dates(
    primary_provider: str,
    start_date: str,
    end_date: str,
    target_trade_days: int | None,
    primary_kwargs: dict[str, Any],
    provider_factory: Callable[..., Any],
) -> list[str]:
    start, end = date_range(start_date, end_date)
    provider = provider_factory(primary_provider, **primary_kwargs)
    dates: list[str] = []
    current = start
    while current <= end:
        text = current.isoformat()
        try:
            if provider.is_trade_date(text):
                dates.append(text)
        except Exception:
            dates.append(text)
        current += timedelta(days=1)
    if not dates:
        dates = [start.isoformat()]
    if target_trade_days:
        dates = dates[-target_trade_days:]
    return dates


def _shards(symbols: list[str], shard_size: int):
    for start in range(0, len(symbols), shard_size):
        yield symbols[start:start + shard_size]


def _suite_status(failure_rate: float | None, conflict_count: int) -> str:
    if failure_rate is not None and failure_rate > 0.5:
        return "failed"
    if conflict_count or (failure_rate is not None and failure_rate > 0):
        return "warning"
    return "success"


def _decision_next_actions(recommendation: str, blocking: list[str]) -> list[str]:
    if recommendation == "approve_primary":
        return ["promote profile to active", "run daily provider SLA monitor", "keep backup provider comparison enabled"]
    if recommendation == "approve_backup":
        return ["keep as backup source", "resolve primary blocking issues", "rerun 20/60 day full-market benchmark"]
    if recommendation == "watch":
        return ["use for research comparison only", "increase sample window", "review field mapping and license terms"]
    actions = ["do not use in production", "replace vendor or renegotiate data quality/license", "keep fixture fallback for regression tests"]
    return blocking + actions


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


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 8)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _suite_code(primary: str, secondary: str, start_date: str, end_date: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"suite-{primary}-{secondary}-{start_date}-{end_date}-{stamp}"


def _decision_report_code(decision: VendorDecision) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"decision-{decision.source_code}-{decision.dataset_code}-{decision.score_date}-{stamp}"


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _blank_to_none(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


def _int_env(env: Mapping[str, str], key: str, default: int | None) -> int | None:
    value = env.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _float_env(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or value == "":
        return default
    return float(value)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Theta vendor operations") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
