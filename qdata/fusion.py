from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Callable, Iterable

from qdata.exceptions import QDataValidationError
from qdata.sources.models import DailyMarketBundle
from qdata.sources.registry import create_provider


DAILY_COMPARE_FIELDS = ("open", "high", "low", "close", "volume", "amount")


@dataclass(frozen=True)
class SourcePriority:
    source_code: str
    priority: int
    is_fallback: bool = True
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConflictRecord:
    symbol: str
    trade_date: str
    field_name: str
    primary_value: Any
    secondary_value: Any
    absolute_diff: float | None
    relative_diff: float | None
    severity: str


@dataclass(frozen=True)
class FusionReport:
    dataset_code: str
    trade_date: str
    primary_source_code: str
    secondary_source_code: str
    primary_count: int
    secondary_count: int
    matched_count: int
    conflict_count: int
    coverage_rate: float | None
    conflict_rate: float | None
    conflicts: list[ConflictRecord]
    missing_from_primary: list[str] = field(default_factory=list)
    missing_from_secondary: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.coverage_rate is not None and self.coverage_rate < 0.98:
            return "failed"
        if self.conflict_count or self.missing_from_primary or self.missing_from_secondary:
            return "warning"
        return "pass"


@dataclass(frozen=True)
class FallbackAttempt:
    source_code: str
    priority: int
    status: str
    row_count: int = 0
    error_message: str | None = None


@dataclass(frozen=True)
class FallbackSelection:
    bundle: DailyMarketBundle
    source_code: str
    attempts: list[FallbackAttempt]


def compare_daily_bundles(
    primary_bundle: DailyMarketBundle,
    secondary_bundle: DailyMarketBundle,
    fields: Iterable[str] = DAILY_COMPARE_FIELDS,
    absolute_tolerance: float = 1e-8,
    relative_tolerance: float | None = None,
    dataset_code: str = "daily_bar",
) -> FusionReport:
    """Compare two normalized daily-market bundles by symbol/trade_date/field."""

    compare_fields = tuple(fields)
    primary_rows = _index_daily_rows(primary_bundle)
    secondary_rows = _index_daily_rows(secondary_bundle)
    primary_keys = set(primary_rows)
    secondary_keys = set(secondary_rows)
    matched_keys = sorted(primary_keys & secondary_keys)
    conflicts: list[ConflictRecord] = []

    for key in matched_keys:
        primary_record = primary_rows[key]
        secondary_record = secondary_rows[key]
        for field_name in compare_fields:
            primary_value = getattr(primary_record, field_name)
            secondary_value = getattr(secondary_record, field_name)
            conflict = _compare_value(
                symbol=key[0],
                trade_date=key[1],
                field_name=field_name,
                primary_value=primary_value,
                secondary_value=secondary_value,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
            if conflict:
                conflicts.append(conflict)

    coverage_rate = _safe_rate(len(matched_keys), len(primary_keys))
    denominator = len(matched_keys) * len(compare_fields)
    conflict_rate = _safe_rate(len(conflicts), denominator)
    return FusionReport(
        dataset_code=dataset_code,
        trade_date=primary_bundle.trade_date or secondary_bundle.trade_date,
        primary_source_code=primary_bundle.provider,
        secondary_source_code=secondary_bundle.provider,
        primary_count=len(primary_keys),
        secondary_count=len(secondary_keys),
        matched_count=len(matched_keys),
        conflict_count=len(conflicts),
        coverage_rate=coverage_rate,
        conflict_rate=conflict_rate,
        conflicts=conflicts,
        missing_from_primary=sorted(symbol for symbol, _ in secondary_keys - primary_keys),
        missing_from_secondary=sorted(symbol for symbol, _ in primary_keys - secondary_keys),
    )


def compare_provider_daily(
    primary_provider: str,
    secondary_provider: str,
    trade_date: str,
    symbols: list[str] | None = None,
    primary_kwargs: dict[str, Any] | None = None,
    secondary_kwargs: dict[str, Any] | None = None,
    fields: Iterable[str] = DAILY_COMPARE_FIELDS,
    absolute_tolerance: float = 1e-8,
    relative_tolerance: float | None = None,
    provider_factory: Callable[..., Any] = create_provider,
) -> FusionReport:
    primary = provider_factory(primary_provider, **(primary_kwargs or {}))
    secondary = provider_factory(secondary_provider, **(secondary_kwargs or {}))
    primary_bundle = primary.fetch_daily_market(trade_date, symbols=symbols)
    secondary_bundle = secondary.fetch_daily_market(trade_date, symbols=symbols)
    return compare_daily_bundles(
        primary_bundle,
        secondary_bundle,
        fields=fields,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    )


def select_daily_bundle_with_fallback(
    provider_specs: Iterable[SourcePriority | dict[str, Any] | str],
    trade_date: str,
    symbols: list[str] | None = None,
    provider_factory: Callable[..., Any] = create_provider,
) -> FallbackSelection:
    priorities = sorted(_normalize_provider_specs(provider_specs), key=lambda item: item.priority)
    if not priorities:
        raise QDataValidationError("at least one provider is required")

    attempts: list[FallbackAttempt] = []
    for item in priorities:
        try:
            provider = provider_factory(item.source_code, **item.kwargs)
            bundle = provider.fetch_daily_market(trade_date, symbols=symbols)
        except Exception as exc:
            attempts.append(
                FallbackAttempt(
                    source_code=item.source_code,
                    priority=item.priority,
                    status="failed",
                    error_message=str(exc),
                )
            )
            continue
        row_count = len(bundle.daily_bars)
        attempts.append(
            FallbackAttempt(
                source_code=item.source_code,
                priority=item.priority,
                status="success",
                row_count=row_count,
            )
        )
        if row_count:
            return FallbackSelection(bundle=bundle, source_code=item.source_code, attempts=attempts)

    errors = "; ".join(
        f"{attempt.source_code}:{attempt.status}:{attempt.error_message or 'empty'}"
        for attempt in attempts
    )
    raise QDataValidationError(f"all providers failed or returned empty daily bars: {errors}")


def record_fusion_report(
    postgres_dsn: str,
    report: FusionReport,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required to record fusion reports") from exc

    payload = {
        "missing_from_primary": report.missing_from_primary,
        "missing_from_secondary": report.missing_from_secondary,
        **(details or {}),
    }
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            primary_source_id = _ensure_source(cursor, report.primary_source_code)
            secondary_source_id = _ensure_source(cursor, report.secondary_source_code)
            dataset_id = _ensure_dataset(cursor, report.dataset_code, primary_source_id)
            _upsert_source_priority(cursor, dataset_id, primary_source_id, 0, False)
            _upsert_source_priority(cursor, dataset_id, secondary_source_id, 10, True)
            security_ids = _security_id_map(cursor, [conflict.symbol for conflict in report.conflicts])
            for conflict in report.conflicts:
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_conflict_daily (
                        dataset_id, primary_source_id, secondary_source_id, security_id, symbol,
                        trade_date, field_name, primary_value, secondary_value, absolute_diff,
                        relative_diff, severity, status, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s::jsonb)
                    ON CONFLICT (
                        dataset_id, primary_source_id, secondary_source_id, symbol, trade_date, field_name
                    ) DO UPDATE SET
                        security_id = EXCLUDED.security_id,
                        primary_value = EXCLUDED.primary_value,
                        secondary_value = EXCLUDED.secondary_value,
                        absolute_diff = EXCLUDED.absolute_diff,
                        relative_diff = EXCLUDED.relative_diff,
                        severity = EXCLUDED.severity,
                        details = EXCLUDED.details,
                        updated_at = now()
                    """,
                    (
                        dataset_id,
                        primary_source_id,
                        secondary_source_id,
                        security_ids.get(conflict.symbol),
                        conflict.symbol,
                        conflict.trade_date,
                        conflict.field_name,
                        _to_text(conflict.primary_value),
                        _to_text(conflict.secondary_value),
                        conflict.absolute_diff,
                        conflict.relative_diff,
                        conflict.severity,
                        _json(payload),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO qmeta.multi_source_quality_daily (
                    dataset_id, trade_date, primary_source_id, secondary_source_id,
                    primary_count, secondary_count, matched_count, conflict_count,
                    coverage_rate, conflict_rate, status, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (dataset_id, trade_date, primary_source_id, secondary_source_id)
                DO UPDATE SET
                    primary_count = EXCLUDED.primary_count,
                    secondary_count = EXCLUDED.secondary_count,
                    matched_count = EXCLUDED.matched_count,
                    conflict_count = EXCLUDED.conflict_count,
                    coverage_rate = EXCLUDED.coverage_rate,
                    conflict_rate = EXCLUDED.conflict_rate,
                    status = EXCLUDED.status,
                    details = EXCLUDED.details,
                    created_at = now()
                """,
                (
                    dataset_id,
                    report.trade_date,
                    primary_source_id,
                    secondary_source_id,
                    report.primary_count,
                    report.secondary_count,
                    report.matched_count,
                    report.conflict_count,
                    report.coverage_rate,
                    report.conflict_rate,
                    report.status,
                    _json(payload),
                ),
            )


def _index_daily_rows(bundle: DailyMarketBundle):
    return {(record.symbol, record.trade_date): record for record in bundle.daily_bars}


def _compare_value(
    symbol: str,
    trade_date: str,
    field_name: str,
    primary_value: Any,
    secondary_value: Any,
    absolute_tolerance: float,
    relative_tolerance: float | None,
) -> ConflictRecord | None:
    if primary_value == secondary_value:
        return None
    if primary_value is None and secondary_value is None:
        return None
    if _is_number(primary_value) and _is_number(secondary_value):
        primary_number = float(primary_value)
        secondary_number = float(secondary_value)
        absolute_diff = abs(primary_number - secondary_number)
        denominator = max(abs(primary_number), abs(secondary_number), 1.0)
        relative_diff = absolute_diff / denominator
        if absolute_diff <= absolute_tolerance:
            return None
        if relative_tolerance is not None and relative_diff <= relative_tolerance:
            return None
        severity = _numeric_severity(relative_diff)
    else:
        absolute_diff = None
        relative_diff = None
        severity = "medium"
    return ConflictRecord(
        symbol=symbol,
        trade_date=trade_date,
        field_name=field_name,
        primary_value=primary_value,
        secondary_value=secondary_value,
        absolute_diff=absolute_diff,
        relative_diff=relative_diff,
        severity=severity,
    )


def _normalize_provider_specs(provider_specs: Iterable[SourcePriority | dict[str, Any] | str]) -> list[SourcePriority]:
    result = []
    for index, spec in enumerate(provider_specs):
        if isinstance(spec, SourcePriority):
            result.append(spec)
        elif isinstance(spec, str):
            result.append(SourcePriority(source_code=spec, priority=index))
        else:
            kwargs = dict(spec.get("kwargs") or {})
            result.append(
                SourcePriority(
                    source_code=spec["provider"],
                    priority=int(spec.get("priority", index)),
                    is_fallback=bool(spec.get("is_fallback", True)),
                    kwargs=kwargs,
                )
            )
    return result


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 8)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_severity(relative_diff: float) -> str:
    if relative_diff < 0.00001:
        return "low"
    if relative_diff < 0.0001:
        return "medium"
    if relative_diff < 0.001:
        return "high"
    return "critical"


def _ensure_source(cursor, source_code: str) -> int:
    source_name = {
        "csv": "本地 CSV 导入",
        "local_csv": "本地 CSV 导入",
        "csv_mirror": "本地 CSV 备份源",
        "akshare": "AkShare 开源数据接口",
        "qdata": "QData 规则计算",
        "qdata_api": "QData REST 服务",
    }.get(source_code, source_code)
    source_type = "internal" if source_code in {"csv", "local_csv", "csv_mirror", "qdata", "qdata_api"} else "vendor"
    cursor.execute(
        """
        INSERT INTO qmeta.source_system (
            source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner
        ) VALUES (%s, %s, %s, 'fusion comparison', 'daily', 'L4', 'qdata')
        ON CONFLICT (source_code) DO UPDATE SET
            source_name = EXCLUDED.source_name,
            source_type = EXCLUDED.source_type,
            license_scope = EXCLUDED.license_scope,
            update_frequency = EXCLUDED.update_frequency,
            latency_level = EXCLUDED.latency_level,
            owner = EXCLUDED.owner,
            updated_at = now()
        RETURNING source_id
        """,
        (source_code, source_name, source_type),
    )
    return cursor.fetchone()["source_id"]


def _ensure_dataset(cursor, dataset_code: str, primary_source_id: int) -> int:
    dataset_name, asset_type, frequency, storage_layer = {
        "daily_bar": ("日线行情", "stock", "1d", "clickhouse"),
        "minute_bar": ("分钟行情", "stock", "1m", "clickhouse"),
        "limit_price_daily": ("涨跌停和交易约束", "stock", "1d", "postgresql"),
    }.get(dataset_code, (dataset_code, None, None, "postgresql"))
    cursor.execute(
        """
        INSERT INTO qmeta.dataset_catalog (
            dataset_code, dataset_name, asset_type, frequency, storage_layer,
            primary_source_id, pit_required, description
        ) VALUES (%s, %s, %s, %s, %s, %s, FALSE, 'created by fusion comparison')
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
    return cursor.fetchone()["dataset_id"]


def _upsert_source_priority(cursor, dataset_id: int, source_id: int, priority: int, is_fallback: bool) -> None:
    cursor.execute(
        """
        INSERT INTO qmeta.source_priority (dataset_id, source_id, priority, is_fallback)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (dataset_id, source_id, effective_date) DO UPDATE SET
            priority = EXCLUDED.priority,
            is_fallback = EXCLUDED.is_fallback,
            updated_at = now()
        """,
        (dataset_id, source_id, priority, is_fallback),
    )


def _security_id_map(cursor, symbols: list[str]) -> dict[str, int]:
    unique_symbols = sorted(set(symbols))
    if not unique_symbols:
        return {}
    cursor.execute(
        """
        SELECT current_symbol || '.' || exchange AS symbol, security_id
        FROM qmeta.security_master
        WHERE current_symbol || '.' || exchange = ANY(%s)
        """,
        (unique_symbols,),
    )
    return {row["symbol"]: row["security_id"] for row in cursor.fetchall()}


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
