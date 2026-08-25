from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.sources.registry import create_provider


STATUSES = {"planned", "success", "warning", "failed", "blocked", "skipped"}
TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
FABRIC_SCOPES = {"canary", "full_market"}
RECOMMENDATIONS = {"reject", "research_only", "backup", "primary_candidate"}
RISK_LEVELS = {"unknown", "low", "medium", "high", "critical"}
LICENSE_STATUSES = {"unknown", "local_smoke", "official_public", "research_only", "review_required", "blocked"}

DEFAULT_SOURCE_CODES = ("csv", "csv_mirror")
DEFAULT_CANARY_SYMBOLS = ("600519.SH", "000001.SZ")
DEFAULT_DATASETS = ("daily_bar", "security_master", "trading_calendar", "adjustment_factor", "limit_price_daily")


@dataclass(frozen=True)
class FreeSourceCandidate:
    source_code: str
    provider_name: str
    external: bool
    license_status: str
    commercial_allowed: bool
    supported_datasets: tuple[str, ...]
    notes: str


FREE_SOURCE_CANDIDATES: dict[str, FreeSourceCandidate] = {
    "csv": FreeSourceCandidate(
        source_code="csv",
        provider_name="csv",
        external=False,
        license_status="local_smoke",
        commercial_allowed=False,
        supported_datasets=DEFAULT_DATASETS + ("suspension_history",),
        notes="Local fixture used to verify the fabric without external calls.",
    ),
    "csv_mirror": FreeSourceCandidate(
        source_code="csv_mirror",
        provider_name="csv_mirror",
        external=False,
        license_status="local_smoke",
        commercial_allowed=False,
        supported_datasets=DEFAULT_DATASETS + ("suspension_history",),
        notes="Local mirror fixture used for deterministic cross-source comparison.",
    ),
    "akshare": FreeSourceCandidate(
        source_code="akshare",
        provider_name="akshare",
        external=True,
        license_status="research_only",
        commercial_allowed=False,
        supported_datasets=DEFAULT_DATASETS + ("minute_bar", "suspension_history"),
        notes="Open-source public-web adapter; upstream terms must be checked before commercial use.",
    ),
    "baostock": FreeSourceCandidate(
        source_code="baostock",
        provider_name="baostock",
        external=True,
        license_status="research_only",
        commercial_allowed=False,
        supported_datasets=("daily_bar", "security_master", "trading_calendar", "financial_metric_pit", "financial_statement_pit"),
        notes="Free research candidate; Iota-5 adapter supports explicit-symbol daily canaries with socket timeout guard.",
    ),
    "tushare_free": FreeSourceCandidate(
        source_code="tushare_free",
        provider_name="tushare_free",
        external=True,
        license_status="review_required",
        commercial_allowed=False,
        supported_datasets=DEFAULT_DATASETS + ("financial_metric_pit", "financial_statement_pit"),
        notes="Free quota/token tier candidate; frequency, points, and commercial rights need review.",
    ),
    "cninfo_public": FreeSourceCandidate(
        source_code="cninfo_public",
        provider_name="cninfo_public",
        external=True,
        license_status="review_required",
        commercial_allowed=False,
        supported_datasets=("announcement", "financial_statement_pit", "financial_metric_pit", "security_master"),
        notes="Official public announcement candidate; raw redistribution terms need review.",
    ),
    "sse_public": FreeSourceCandidate(
        source_code="sse_public",
        provider_name="sse_public",
        external=True,
        license_status="official_public",
        commercial_allowed=False,
        supported_datasets=("security_master", "trading_calendar", "daily_bar", "announcement"),
        notes="Official public exchange candidate; reuse and caching terms need review.",
    ),
    "szse_public": FreeSourceCandidate(
        source_code="szse_public",
        provider_name="szse_public",
        external=True,
        license_status="official_public",
        commercial_allowed=False,
        supported_datasets=("security_master", "trading_calendar", "daily_bar", "announcement"),
        notes="Official public exchange candidate; reuse and caching terms need review.",
    ),
    "nbs_public": FreeSourceCandidate(
        source_code="nbs_public",
        provider_name="nbs_public",
        external=True,
        license_status="official_public",
        commercial_allowed=False,
        supported_datasets=("macro_indicator",),
        notes="Official public macro candidate; data terms and attribution need review.",
    ),
}


def run_free_source_fabric(
    postgres_dsn: str,
    *,
    source_codes: Iterable[str] = DEFAULT_SOURCE_CODES,
    dataset_codes: Iterable[str] = DEFAULT_DATASETS,
    start_date: str,
    end_date: str,
    canary_symbols: Iterable[str] = DEFAULT_CANARY_SYMBOLS,
    requested_by: str = "iota3",
    trigger_mode: str = "manual",
    environment: str = "local",
    fabric_scope: str = "canary",
    allow_external: bool = False,
    require_external: bool = False,
    require_commercial_clearance: bool = False,
    min_source_count: int = 2,
    min_coverage_rate: float = 0.95,
    max_conflict_rate_bps: float = 5.0,
    provider_kwargs_by_source: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    if fabric_scope not in FABRIC_SCOPES:
        raise QDataValidationError("fabric_scope must be one of: canary, full_market")
    if min_source_count <= 0:
        raise QDataValidationError("min_source_count must be greater than 0")
    if min_coverage_rate < 0 or min_coverage_rate > 1:
        raise QDataValidationError("min_coverage_rate must be between 0 and 1")
    if max_conflict_rate_bps < 0:
        raise QDataValidationError("max_conflict_rate_bps must be greater than or equal to 0")

    start, end = date_range(start_date, end_date)
    normalized_sources = _normalize_codes(source_codes, "source_codes")
    normalized_datasets = _normalize_codes(dataset_codes, "dataset_codes")
    symbols = _normalize_symbols(canary_symbols)
    started_at = datetime.now(timezone.utc)
    provider_kwargs_by_source = provider_kwargs_by_source or {}

    dataset_results = [
        _build_dataset_result(
            dataset_code=dataset_code,
            source_codes=normalized_sources,
            start=start,
            end=end,
            symbols=symbols,
            allow_external=allow_external,
            require_commercial_clearance=require_commercial_clearance,
            min_source_count=min_source_count,
            min_coverage_rate=min_coverage_rate,
            max_conflict_rate_bps=max_conflict_rate_bps,
            provider_kwargs_by_source=provider_kwargs_by_source,
            started_at=started_at,
        )
        for dataset_code in normalized_datasets
    ]

    source_summary = _source_summary(normalized_sources, dataset_results)
    global_issues = _global_blocking_issues(
        require_external=require_external,
        require_commercial_clearance=require_commercial_clearance,
        source_summary=source_summary,
        dataset_results=dataset_results,
    )
    status = _run_status(dataset_results, global_issues)
    recommendation, recommended_role = _run_recommendation(status, dataset_results)
    risk_level = _risk_level(status)
    finished_at = datetime.now(timezone.utc)
    counts = _status_counts(dataset_results)
    blocking_issues = _dedupe(global_issues + _dataset_issues(dataset_results))
    next_actions = _next_actions(status, blocking_issues, dataset_results)
    run_row = _insert_fabric_run(
        postgres_dsn,
        fabric_code=_run_code(normalized_sources, status),
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        fabric_scope=fabric_scope,
        status=status,
        recommendation=recommendation,
        recommended_role=recommended_role,
        risk_level=risk_level,
        dataset_codes=normalized_datasets,
        source_codes=normalized_sources,
        canary_symbols=symbols,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        allow_external=allow_external,
        require_external=require_external,
        require_commercial_clearance=require_commercial_clearance,
        min_source_count=min_source_count,
        min_coverage_rate=min_coverage_rate,
        max_conflict_rate_bps=max_conflict_rate_bps,
        source_summary=source_summary,
        dataset_results=dataset_results,
        counts=counts,
        blocking_issues=blocking_issues,
        next_actions=next_actions,
        started_at=started_at,
        finished_at=finished_at,
    )
    _insert_dataset_results(postgres_dsn, run_row, dataset_results)
    if require_external and status in {"blocked", "failed"}:
        raise QDataValidationError(run_row.get("error_message") or "free source fabric external requirement blocked")
    if require_commercial_clearance and status in {"blocked", "failed"}:
        raise QDataValidationError(run_row.get("error_message") or "free source fabric commercial clearance blocked")
    return run_row


def list_free_source_fabric_runs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("fabric_code", "fsfr.fabric_code"),
            ("run_code", "fsfr.fabric_code"),
            ("status", "fsfr.status"),
            ("fabric_scope", "fsfr.fabric_scope"),
            ("recommendation", "fsfr.recommendation"),
            ("recommended_role", "fsfr.recommended_role"),
            ("risk_level", "fsfr.risk_level"),
            ("baseline_source_code", "fsfr.baseline_source_code"),
            ("requested_by", "fsfr.requested_by"),
            ("trigger_mode", "fsfr.trigger_mode"),
            ("environment", "fsfr.environment"),
        ],
    )
    dataset_code = _param(params, "dataset_code")
    if dataset_code:
        where, values = _append_where(where, values, "%s = ANY(fsfr.dataset_codes)", dataset_code)
    source_code = _param(params, "source_code")
    if source_code:
        where, values = _append_where(where, values, "%s = ANY(fsfr.source_codes)", source_code)
    where, values = _append_date_filter(where, values, params, "fsfr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsfr.fabric_id, fsfr.fabric_code, fsfr.requested_by,
            fsfr.trigger_mode, fsfr.environment, fsfr.fabric_scope,
            fsfr.status, fsfr.recommendation, fsfr.recommended_role,
            fsfr.risk_level, fsfr.baseline_source_code,
            fsfr.dataset_codes, fsfr.source_codes, fsfr.canary_symbols,
            fsfr.start_date, fsfr.end_date, fsfr.allow_external,
            fsfr.require_external, fsfr.require_commercial_clearance,
            fsfr.min_source_count, fsfr.min_coverage_rate,
            fsfr.max_conflict_rate_bps, fsfr.source_count,
            fsfr.executable_source_count, fsfr.external_source_count,
            fsfr.usable_source_count, fsfr.dataset_result_count,
            fsfr.dataset_success_count, fsfr.dataset_warning_count,
            fsfr.dataset_blocked_count, fsfr.dataset_failed_count,
            fsfr.license_review_required_count, fsfr.commercial_blocker_count,
            fsfr.coverage_rate, fsfr.conflict_rate_bps,
            fsfr.blocking_issues, fsfr.next_actions, fsfr.error_message,
            fsfr.started_at, fsfr.finished_at, fsfr.duration_ms,
            fsfr.created_at, fsfr.updated_at
        FROM qmeta.free_source_fabric_run fsfr
        {where}
        ORDER BY fsfr.started_at DESC, fsfr.fabric_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_free_source_fabric_results(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("fabric_code", "fsfr.fabric_code"),
            ("run_code", "fsfr.fabric_code"),
            ("result_code", "fsfdr.result_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "fsfdr.status"),
            ("coverage_status", "fsfdr.coverage_status"),
            ("consistency_status", "fsfdr.consistency_status"),
            ("license_status", "fsfdr.license_status"),
            ("freshness_status", "fsfdr.freshness_status"),
            ("recommendation", "fsfdr.recommendation"),
            ("recommended_role", "fsfdr.recommended_role"),
            ("risk_level", "fsfdr.risk_level"),
            ("baseline_source_code", "fsfdr.baseline_source_code"),
        ],
    )
    source_code = _param(params, "source_code")
    if source_code:
        where, values = _append_where(where, values, "%s = ANY(fsfdr.source_codes)", source_code)
    where, values = _append_date_filter(where, values, params, "fsfdr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsfdr.result_id, fsfr.fabric_code, fsfdr.result_code,
            dc.dataset_code, fsfdr.status, fsfdr.coverage_status,
            fsfdr.consistency_status, fsfdr.license_status,
            fsfdr.freshness_status, fsfdr.recommendation,
            fsfdr.recommended_role, fsfdr.risk_level,
            fsfdr.baseline_source_code, fsfdr.source_codes,
            fsfdr.executed_sources, fsfdr.blocked_sources,
            fsfdr.missing_sources, fsfdr.license_blocking_sources,
            fsfdr.source_count, fsfdr.usable_source_count,
            fsfdr.expected_row_count, fsfdr.baseline_row_count,
            fsfdr.row_count, fsfdr.coverage_rate,
            fsfdr.conflict_rate_bps, fsfdr.max_abs_value_diff,
            fsfdr.blocking_issues, fsfdr.next_actions,
            fsfdr.error_message, fsfdr.started_at, fsfdr.finished_at,
            fsfdr.duration_ms, fsfdr.created_at, fsfdr.updated_at
        FROM qmeta.free_source_fabric_dataset_result fsfdr
        JOIN qmeta.free_source_fabric_run fsfr ON fsfr.fabric_id = fsfdr.fabric_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsfdr.dataset_id
        {where}
        ORDER BY fsfdr.started_at DESC, fsfdr.result_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_iota3_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"iota3 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def free_source_catalog() -> list[dict[str, Any]]:
    return [
        {
            "source_code": item.source_code,
            "provider_name": item.provider_name,
            "external": item.external,
            "license_status": item.license_status,
            "commercial_allowed": item.commercial_allowed,
            "supported_datasets": list(item.supported_datasets),
            "notes": item.notes,
        }
        for item in FREE_SOURCE_CANDIDATES.values()
    ]


def _build_dataset_result(
    *,
    dataset_code: str,
    source_codes: list[str],
    start: date,
    end: date,
    symbols: list[str],
    allow_external: bool,
    require_commercial_clearance: bool,
    min_source_count: int,
    min_coverage_rate: float,
    max_conflict_rate_bps: float,
    provider_kwargs_by_source: dict[str, dict[str, Any]],
    started_at: datetime,
) -> dict[str, Any]:
    observations = [
        _observe_source_dataset(
            source_code=source_code,
            dataset_code=dataset_code,
            start=start,
            end=end,
            symbols=symbols,
            allow_external=allow_external,
            provider_kwargs=provider_kwargs_by_source.get(source_code, {}),
        )
        for source_code in source_codes
    ]
    successful = [observation for observation in observations if observation["status"] == "success"]
    baseline = successful[0] if successful else None
    baseline_source_code = str(baseline["source_code"]) if baseline else None
    row_count = max([int(observation.get("row_count") or 0) for observation in observations] or [0])
    baseline_row_count = int(baseline.get("row_count") or 0) if baseline else None
    expected_row_count = _expected_row_count(dataset_code, symbols, start, end, observations)
    coverage_rate = _coverage_rate(row_count, expected_row_count)
    consistency = _compare_successful_observations(dataset_code, successful)
    license_status = _aggregate_license_status(observations)
    coverage_status = _coverage_status(len(successful), min_source_count, coverage_rate, min_coverage_rate)
    consistency_status = _consistency_status(len(successful), consistency["conflict_rate_bps"], max_conflict_rate_bps)
    freshness_status = "success" if successful else "skipped"
    blocking_issues = _dataset_blocking_issues(
        observations=observations,
        coverage_status=coverage_status,
        consistency_status=consistency_status,
        license_status=license_status,
        require_commercial_clearance=require_commercial_clearance,
        min_source_count=min_source_count,
        min_coverage_rate=min_coverage_rate,
        max_conflict_rate_bps=max_conflict_rate_bps,
    )
    status = _dataset_status(coverage_status, consistency_status, license_status, blocking_issues)
    recommendation, recommended_role = _dataset_recommendation(status, license_status)
    finished_at = datetime.now(timezone.utc)
    result = {
        "dataset_code": dataset_code,
        "result_code": _result_code(dataset_code, status),
        "status": status,
        "coverage_status": coverage_status,
        "consistency_status": consistency_status,
        "license_status": license_status,
        "freshness_status": freshness_status,
        "recommendation": recommendation,
        "recommended_role": recommended_role,
        "risk_level": _risk_level(status),
        "baseline_source_code": baseline_source_code,
        "source_codes": source_codes,
        "executed_sources": [str(item["source_code"]) for item in observations if item["status"] == "success"],
        "blocked_sources": [str(item["source_code"]) for item in observations if item["status"] in {"blocked", "failed"}],
        "missing_sources": [str(item["source_code"]) for item in observations if item["status"] != "success"],
        "license_blocking_sources": [
            str(item["source_code"])
            for item in observations
            if item.get("license_status") in {"research_only", "review_required", "blocked"}
        ],
        "source_count": len(source_codes),
        "usable_source_count": len(successful),
        "expected_row_count": expected_row_count,
        "baseline_row_count": baseline_row_count,
        "row_count": row_count,
        "coverage_rate": coverage_rate,
        "conflict_rate_bps": consistency["conflict_rate_bps"],
        "max_abs_value_diff": consistency["max_abs_value_diff"],
        "blocking_issues": blocking_issues,
        "next_actions": _dataset_next_actions(status, blocking_issues, license_status),
        "evidence": {
            "source_observations": [_redact_observation(item) for item in observations],
            "comparison": consistency,
            "thresholds": {
                "min_source_count": min_source_count,
                "min_coverage_rate": min_coverage_rate,
                "max_conflict_rate_bps": max_conflict_rate_bps,
            },
            "raw_rows_persisted": False,
            "external_calls_allowed": allow_external,
        },
        "error_message": "; ".join(blocking_issues) if status in {"blocked", "failed"} and blocking_issues else None,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
    }
    return result


def _observe_source_dataset(
    *,
    source_code: str,
    dataset_code: str,
    start: date,
    end: date,
    symbols: list[str],
    allow_external: bool,
    provider_kwargs: dict[str, Any],
) -> dict[str, Any]:
    candidate = FREE_SOURCE_CANDIDATES.get(source_code)
    if not candidate:
        return _observation(source_code, dataset_code, "blocked", "unknown", False, [], "unknown_free_source")
    if dataset_code not in set(candidate.supported_datasets):
        return _observation(
            source_code,
            dataset_code,
            "skipped",
            candidate.license_status,
            candidate.external,
            [],
            f"dataset_not_supported:{dataset_code}",
        )
    if candidate.external and not allow_external:
        return _observation(
            source_code,
            dataset_code,
            "blocked",
            candidate.license_status,
            True,
            [],
            "external_free_source_disabled",
        )
    try:
        provider = create_provider(candidate.provider_name, **_provider_kwargs(source_code, provider_kwargs))
        rows = _dataset_rows(provider, dataset_code, start, end, symbols)
    except ValueError:
        return _observation(
            source_code,
            dataset_code,
            "blocked",
            candidate.license_status,
            candidate.external,
            [],
            f"provider_not_implemented:{candidate.provider_name}",
        )
    except QDataValidationError as exc:
        return _observation(source_code, dataset_code, "blocked", candidate.license_status, candidate.external, [], str(exc))
    except Exception as exc:
        return _observation(source_code, dataset_code, "failed", candidate.license_status, candidate.external, [], str(exc))
    if not rows:
        return _observation(source_code, dataset_code, "blocked", candidate.license_status, candidate.external, [], "no_rows")
    return _observation(source_code, dataset_code, "success", candidate.license_status, candidate.external, rows, None)


def _dataset_rows(provider: Any, dataset_code: str, start: date, end: date, symbols: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade_date in _date_strings(start, end):
        if dataset_code in {"daily_bar", "security_master", "trading_calendar"}:
            bundle = provider.fetch_daily_market(trade_date=trade_date, symbols=symbols)
            if dataset_code == "daily_bar":
                rows.extend(_daily_bar_rows(bundle.daily_bars))
            elif dataset_code == "security_master":
                rows.extend(_security_rows(bundle.securities))
            else:
                rows.extend(_calendar_rows(bundle.calendars))
            continue
        if dataset_code in {"adjustment_factor", "limit_price_daily", "suspension_history"}:
            if not hasattr(provider, "fetch_market_constraints"):
                raise QDataValidationError(f"provider does not support market constraints for {dataset_code}")
            bundle = provider.fetch_market_constraints(trade_date=trade_date, symbols=symbols)
            if dataset_code == "adjustment_factor":
                rows.extend(_adjustment_rows(bundle.adjustment_factors))
            elif dataset_code == "limit_price_daily":
                rows.extend(_limit_price_rows(bundle.limit_prices))
            else:
                rows.extend(_suspension_rows(bundle.suspensions))
            continue
        raise QDataValidationError(f"dataset not implemented in free source fabric: {dataset_code}")
    return _dedupe_rows(dataset_code, rows)


def _daily_bar_rows(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": record.symbol,
            "trade_date": record.trade_date,
            "open": record.open,
            "high": record.high,
            "low": record.low,
            "close": record.close,
            "volume": record.volume,
            "amount": record.amount,
        }
        for record in records
    ]


def _security_rows(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": record.symbol,
            "name": record.name,
            "asset_type": record.asset_type,
            "currency": record.currency,
            "list_date": record.list_date,
            "delist_date": record.delist_date,
            "status": record.status,
            "status_effective_date": record.status_effective_date,
            "security_id": record.security_id,
            "identifier_effective_date": record.identifier_effective_date,
            "name_effective_date": record.name_effective_date,
        }
        for record in records
    ]


def _calendar_rows(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "exchange": record.exchange,
            "trade_date": record.trade_date,
            "is_open": record.is_open,
            "session_type": record.session_type,
        }
        for record in records
    ]


def _adjustment_rows(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": record.symbol,
            "trade_date": record.trade_date,
            "factor_forward": record.factor_forward,
            "factor_backward": record.factor_backward,
            "ex_right_type": record.ex_right_type,
        }
        for record in records
    ]


def _limit_price_rows(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": record.symbol,
            "trade_date": record.trade_date,
            "limit_up": record.limit_up,
            "limit_down": record.limit_down,
            "limit_rule": record.limit_rule,
            "is_st": record.is_st,
            "is_new_listing": record.is_new_listing,
        }
        for record in records
    ]


def _suspension_rows(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": record.symbol,
            "start_time": record.start_time,
            "end_time": record.end_time,
            "suspension_type": record.suspension_type,
            "reason": record.reason,
        }
        for record in records
    ]


def _compare_successful_observations(dataset_code: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    if len(observations) < 2:
        return {"conflict_rate_bps": 0.0, "max_abs_value_diff": 0.0, "compared_record_count": 0, "conflict_count": 0}
    baseline = observations[0]
    baseline_rows = {_record_key(dataset_code, row): row for row in baseline["rows"]}
    compared = 0
    conflicts = 0
    max_diff = 0.0
    max_bps = 0.0
    for observation in observations[1:]:
        rows = {_record_key(dataset_code, row): row for row in observation["rows"]}
        for key, baseline_row in baseline_rows.items():
            row = rows.get(key)
            if not row:
                continue
            compared += 1
            row_diff, row_bps, different = _row_diff(dataset_code, baseline_row, row)
            max_diff = max(max_diff, row_diff)
            max_bps = max(max_bps, row_bps)
            if different:
                conflicts += 1
    return {
        "conflict_rate_bps": round(max_bps, 6),
        "max_abs_value_diff": round(max_diff, 10),
        "compared_record_count": compared,
        "conflict_count": conflicts,
        "baseline_source_code": baseline["source_code"],
    }


def _row_diff(dataset_code: str, baseline: dict[str, Any], row: dict[str, Any]) -> tuple[float, float, bool]:
    numeric_fields_by_dataset = {
        "daily_bar": ("open", "high", "low", "close", "volume", "amount"),
        "adjustment_factor": ("factor_forward", "factor_backward"),
        "limit_price_daily": ("limit_up", "limit_down"),
    }
    text_fields_by_dataset = {
        "security_master": ("name", "asset_type", "currency", "status"),
        "trading_calendar": ("is_open", "session_type"),
        "limit_price_daily": ("limit_rule", "is_st", "is_new_listing"),
    }
    max_diff = 0.0
    max_bps = 0.0
    different = False
    for field in numeric_fields_by_dataset.get(dataset_code, ()):
        left = _float_or_none(baseline.get(field))
        right = _float_or_none(row.get(field))
        if left is None or right is None:
            continue
        diff = abs(left - right)
        bps = 0.0 if left == 0 else diff / abs(left) * 10_000
        max_diff = max(max_diff, diff)
        max_bps = max(max_bps, bps)
        if diff > 0:
            different = True
    for field in text_fields_by_dataset.get(dataset_code, ()):
        if str(baseline.get(field)) != str(row.get(field)):
            max_bps = max(max_bps, 10_000.0)
            different = True
    return max_diff, max_bps, different


def _record_key(dataset_code: str, row: dict[str, Any]) -> tuple[Any, ...]:
    if dataset_code == "security_master":
        return (row.get("symbol"),)
    if dataset_code == "trading_calendar":
        return (row.get("exchange"), row.get("trade_date"))
    if dataset_code == "suspension_history":
        return (row.get("symbol"), row.get("start_time"))
    return (row.get("symbol"), row.get("trade_date"))


def _expected_row_count(dataset_code: str, symbols: list[str], start: date, end: date, observations: list[dict[str, Any]]) -> int:
    if dataset_code == "security_master":
        return len(symbols)
    if dataset_code == "trading_calendar":
        return max(max([int(item.get("row_count") or 0) for item in observations] or [0]), 1)
    if dataset_code == "suspension_history":
        return max([int(item.get("row_count") or 0) for item in observations] or [0])
    return len(symbols) * len(list(_date_strings(start, end)))


def _coverage_rate(row_count: int, expected_row_count: int) -> float:
    if expected_row_count <= 0:
        return 1.0 if row_count == 0 else 1.0
    return round(min(1.0, row_count / expected_row_count), 6)


def _coverage_status(usable_source_count: int, min_source_count: int, coverage_rate: float, min_coverage_rate: float) -> str:
    if usable_source_count < min_source_count:
        return "blocked"
    if coverage_rate < min_coverage_rate:
        return "warning"
    return "success"


def _consistency_status(usable_source_count: int, conflict_rate_bps: float, max_conflict_rate_bps: float) -> str:
    if usable_source_count < 2:
        return "skipped"
    if conflict_rate_bps > max_conflict_rate_bps:
        return "warning"
    return "success"


def _dataset_status(coverage_status: str, consistency_status: str, license_status: str, blocking_issues: list[str]) -> str:
    if any(issue.startswith("source_failed") for issue in blocking_issues) and coverage_status == "blocked":
        return "failed"
    if coverage_status == "blocked" or license_status == "blocked":
        return "blocked"
    if consistency_status == "warning" or coverage_status == "warning":
        return "warning"
    if license_status in {"research_only", "review_required"}:
        return "warning"
    if coverage_status == "success":
        return "success"
    return "planned"


def _dataset_recommendation(status: str, license_status: str) -> tuple[str, str]:
    if status == "failed":
        return "reject", "reject"
    if status == "blocked":
        return "research_only", "research_only"
    if license_status in {"research_only", "review_required"}:
        return "research_only", "research_only"
    if status in {"success", "warning"}:
        return "backup", "backup"
    return "research_only", "research_only"


def _run_status(dataset_results: list[dict[str, Any]], global_issues: list[str]) -> str:
    if any(issue in {"external_free_source_required", "commercial_clearance_required"} for issue in global_issues):
        return "blocked"
    statuses = {str(result.get("status")) for result in dataset_results}
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if statuses <= {"success", "skipped"}:
        return "success"
    return "planned"


def _run_recommendation(status: str, dataset_results: list[dict[str, Any]]) -> tuple[str, str]:
    if status == "failed":
        return "reject", "reject"
    if status == "blocked":
        return "research_only", "research_only"
    recommendations = {str(result.get("recommendation")) for result in dataset_results}
    if recommendations == {"backup"} and status == "success":
        return "backup", "backup"
    if "backup" in recommendations and status in {"success", "warning"}:
        return "backup", "backup"
    return "research_only", "research_only"


def _risk_level(status: str) -> str:
    if status == "failed":
        return "critical"
    if status == "blocked":
        return "high"
    if status == "warning":
        return "medium"
    if status == "success":
        return "low"
    return "unknown"


def _dataset_blocking_issues(
    *,
    observations: list[dict[str, Any]],
    coverage_status: str,
    consistency_status: str,
    license_status: str,
    require_commercial_clearance: bool,
    min_source_count: int,
    min_coverage_rate: float,
    max_conflict_rate_bps: float,
) -> list[str]:
    issues: list[str] = []
    successful_count = sum(1 for observation in observations if observation["status"] == "success")
    if coverage_status == "blocked":
        issues.append(f"insufficient_successful_sources:{successful_count}/{min_source_count}")
    if coverage_status == "warning":
        issues.append(f"coverage_below_threshold:{min_coverage_rate}")
    if consistency_status == "warning":
        issues.append(f"conflict_rate_above_threshold:{max_conflict_rate_bps}")
    if require_commercial_clearance and license_status in {"research_only", "review_required", "blocked"}:
        issues.append("commercial_clearance_required")
    for observation in observations:
        if observation["status"] == "failed":
            issues.append(f"source_failed:{observation['source_code']}")
        if observation["status"] == "blocked" and observation.get("error_message"):
            issues.append(f"{observation['source_code']}:{observation['error_message']}")
    return _dedupe(issues)


def _global_blocking_issues(
    *,
    require_external: bool,
    require_commercial_clearance: bool,
    source_summary: dict[str, Any],
    dataset_results: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    if require_external and source_summary["external_executed_source_count"] <= 0:
        issues.append("external_free_source_required")
    if require_commercial_clearance and any(
        result["license_status"] in {"research_only", "review_required", "blocked"} for result in dataset_results
    ):
        issues.append("commercial_clearance_required")
    return issues


def _dataset_issues(dataset_results: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for result in dataset_results:
        for issue in result.get("blocking_issues") or []:
            issues.append(f"{result['dataset_code']}:{issue}")
    return _dedupe(issues)


def _next_actions(status: str, issues: list[str], dataset_results: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if any("external_free_source_required" in issue for issue in issues):
        actions.append("rerun with --allow-external and at least one external free source")
    if any("external_free_source_disabled" in issue for issue in issues):
        actions.append("enable --allow-external after confirming network and source terms")
    if any("provider_not_implemented" in issue for issue in issues):
        actions.append("implement missing free provider adapter or keep it as catalog-only")
    if any("commercial_clearance_required" in issue for issue in issues):
        actions.append("treat free sources as research/backup until legal clearance is documented")
    if any("conflict_rate_above_threshold" in issue for issue in issues):
        actions.append("inspect field-level conflicts and promote official source as tie-breaker")
    if any("insufficient_successful_sources" in issue for issue in issues):
        actions.append("add another successful free source for the blocked dataset")
    if status in {"success", "warning"} and any(result.get("recommendation") == "backup" for result in dataset_results):
        actions.append("use fabric as research/backup source and keep commercial primary separate")
    return _dedupe(actions or ["review free source fabric evidence"])


def _dataset_next_actions(status: str, issues: list[str], license_status: str) -> list[str]:
    actions: list[str] = []
    if any("insufficient_successful_sources" in issue for issue in issues):
        actions.append("add or repair a second source for this dataset")
    if any("external_free_source_disabled" in issue for issue in issues):
        actions.append("rerun with --allow-external if this source is approved")
    if any("provider_not_implemented" in issue for issue in issues):
        actions.append("build provider adapter before live evaluation")
    if license_status in {"research_only", "review_required"}:
        actions.append("keep dataset research_only until reuse terms are approved")
    if status in {"success", "warning"}:
        actions.append("include dataset in the next larger fabric run")
    return _dedupe(actions or ["review dataset fabric evidence"])


def _source_summary(source_codes: list[str], dataset_results: list[dict[str, Any]]) -> dict[str, Any]:
    all_observations = [
        observation
        for result in dataset_results
        for observation in result.get("evidence", {}).get("source_observations", [])
    ]
    successful = [item for item in all_observations if item.get("status") == "success"]
    successful_sources = {str(item.get("source_code")) for item in successful}
    external_successful = {
        str(item.get("source_code"))
        for item in successful
        if item.get("external") is True
    }
    external_sources = {
        source_code
        for source_code in source_codes
        if FREE_SOURCE_CANDIDATES.get(source_code) and FREE_SOURCE_CANDIDATES[source_code].external
    }
    license_review_required = sum(
        1
        for result in dataset_results
        if result.get("license_status") in {"research_only", "review_required"}
    )
    commercial_blockers = sum(len(result.get("license_blocking_sources") or []) for result in dataset_results)
    return {
        "source_count": len(source_codes),
        "executable_source_count": len(successful_sources),
        "external_source_count": len(external_sources),
        "external_executed_source_count": len(external_successful),
        "usable_source_count": max([int(result.get("usable_source_count") or 0) for result in dataset_results] or [0]),
        "license_review_required_count": license_review_required,
        "commercial_blocker_count": commercial_blockers,
        "coverage_rate": min([float(result.get("coverage_rate") or 0) for result in dataset_results] or [0]),
        "conflict_rate_bps": max([float(result.get("conflict_rate_bps") or 0) for result in dataset_results] or [0]),
        "baseline_source_code": next((result.get("baseline_source_code") for result in dataset_results if result.get("baseline_source_code")), None),
    }


def _aggregate_license_status(observations: list[dict[str, Any]]) -> str:
    statuses = {str(observation.get("license_status") or "unknown") for observation in observations}
    if "blocked" in statuses:
        return "blocked"
    if "review_required" in statuses:
        return "review_required"
    if "research_only" in statuses:
        return "research_only"
    if "official_public" in statuses:
        return "official_public"
    if statuses == {"local_smoke"}:
        return "local_smoke"
    return "unknown"


def _insert_fabric_run(
    postgres_dsn: str,
    *,
    fabric_code: str,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    fabric_scope: str,
    status: str,
    recommendation: str,
    recommended_role: str,
    risk_level: str,
    dataset_codes: list[str],
    source_codes: list[str],
    canary_symbols: list[str],
    start_date: str,
    end_date: str,
    allow_external: bool,
    require_external: bool,
    require_commercial_clearance: bool,
    min_source_count: int,
    min_coverage_rate: float,
    max_conflict_rate_bps: float,
    source_summary: dict[str, Any],
    dataset_results: list[dict[str, Any]],
    counts: dict[str, int],
    blocking_issues: list[str],
    next_actions: list[str],
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    request_payload = {
        "source_codes": source_codes,
        "dataset_codes": dataset_codes,
        "canary_symbols": canary_symbols,
        "start_date": start_date,
        "end_date": end_date,
        "allow_external": allow_external,
        "require_external": require_external,
        "require_commercial_clearance": require_commercial_clearance,
        "thresholds": {
            "min_source_count": min_source_count,
            "min_coverage_rate": min_coverage_rate,
            "max_conflict_rate_bps": max_conflict_rate_bps,
        },
    }
    response_payload = {
        "status": status,
        "recommendation": recommendation,
        "risk_level": risk_level,
        "dataset_status_counts": counts,
        "coverage_rate": source_summary["coverage_rate"],
        "conflict_rate_bps": source_summary["conflict_rate_bps"],
    }
    evidence = {
        "candidate_catalog": free_source_catalog(),
        "source_summary": source_summary,
        "external_side_effect": allow_external,
        "raw_rows_persisted": False,
    }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.free_source_fabric_run (
                    fabric_code, requested_by, trigger_mode, environment,
                    fabric_scope, status, recommendation, recommended_role,
                    risk_level, baseline_source_code, dataset_codes,
                    source_codes, canary_symbols, start_date, end_date,
                    allow_external, require_external, require_commercial_clearance,
                    min_source_count, min_coverage_rate, max_conflict_rate_bps,
                    source_count, executable_source_count, external_source_count,
                    usable_source_count, dataset_result_count,
                    dataset_success_count, dataset_warning_count,
                    dataset_blocked_count, dataset_failed_count,
                    license_review_required_count, commercial_blocker_count,
                    coverage_rate, conflict_rate_bps, blocking_issues,
                    next_actions, request_payload, response_payload,
                    evidence, error_message, started_at, finished_at,
                    duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    fabric_code,
                    requested_by,
                    trigger_mode,
                    environment,
                    fabric_scope,
                    status,
                    recommendation,
                    recommended_role,
                    risk_level,
                    source_summary.get("baseline_source_code"),
                    dataset_codes,
                    source_codes,
                    canary_symbols,
                    start_date,
                    end_date,
                    allow_external,
                    require_external,
                    require_commercial_clearance,
                    min_source_count,
                    min_coverage_rate,
                    max_conflict_rate_bps,
                    source_summary["source_count"],
                    source_summary["executable_source_count"],
                    source_summary["external_source_count"],
                    source_summary["usable_source_count"],
                    len(dataset_results),
                    counts.get("success", 0),
                    counts.get("warning", 0),
                    counts.get("blocked", 0),
                    counts.get("failed", 0),
                    source_summary["license_review_required_count"],
                    source_summary["commercial_blocker_count"],
                    source_summary["coverage_rate"],
                    source_summary["conflict_rate_bps"],
                    blocking_issues,
                    next_actions,
                    _json(request_payload),
                    _json(response_payload),
                    _json(evidence),
                    "; ".join(blocking_issues) if status in {"blocked", "failed"} and blocking_issues else None,
                    started_at,
                    finished_at,
                    _duration_ms(started_at, finished_at),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _insert_dataset_results(postgres_dsn: str, run_row: dict[str, Any], dataset_results: list[dict[str, Any]]) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for result in dataset_results:
                dataset_id = _lookup_dataset_id(cursor, str(result["dataset_code"]))
                cursor.execute(
                    """
                    INSERT INTO qmeta.free_source_fabric_dataset_result (
                        result_code, fabric_id, dataset_id, status,
                        coverage_status, consistency_status, license_status,
                        freshness_status, recommendation, recommended_role,
                        risk_level, baseline_source_code, source_codes,
                        executed_sources, blocked_sources, missing_sources,
                        license_blocking_sources, source_count, usable_source_count,
                        expected_row_count, baseline_row_count, row_count,
                        coverage_rate, conflict_rate_bps, max_abs_value_diff,
                        blocking_issues, next_actions, evidence, error_message,
                        started_at, finished_at, duration_ms, updated_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s::jsonb, %s,
                        %s, %s, %s, now()
                    )
                    ON CONFLICT (result_code) DO NOTHING
                    """,
                    (
                        result["result_code"],
                        run_row["fabric_id"],
                        dataset_id,
                        result["status"],
                        result["coverage_status"],
                        result["consistency_status"],
                        result["license_status"],
                        result["freshness_status"],
                        result["recommendation"],
                        result["recommended_role"],
                        result["risk_level"],
                        result["baseline_source_code"],
                        result["source_codes"],
                        result["executed_sources"],
                        result["blocked_sources"],
                        result["missing_sources"],
                        result["license_blocking_sources"],
                        result["source_count"],
                        result["usable_source_count"],
                        result["expected_row_count"],
                        result["baseline_row_count"],
                        result["row_count"],
                        result["coverage_rate"],
                        result["conflict_rate_bps"],
                        result["max_abs_value_diff"],
                        result["blocking_issues"],
                        result["next_actions"],
                        _json(result["evidence"]),
                        result.get("error_message"),
                        result["started_at"],
                        result["finished_at"],
                        result["duration_ms"],
                    ),
                )


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _observation(
    source_code: str,
    dataset_code: str,
    status: str,
    license_status: str,
    external: bool,
    rows: list[dict[str, Any]],
    error_message: str | None,
) -> dict[str, Any]:
    return {
        "source_code": source_code,
        "dataset_code": dataset_code,
        "status": status,
        "license_status": license_status if license_status in LICENSE_STATUSES else "unknown",
        "external": external,
        "row_count": len(rows),
        "rows": rows,
        "error_message": error_message,
    }


def _redact_observation(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_code": observation["source_code"],
        "dataset_code": observation["dataset_code"],
        "status": observation["status"],
        "license_status": observation["license_status"],
        "external": observation["external"],
        "row_count": observation["row_count"],
        "error_message": observation.get("error_message"),
    }


def _provider_kwargs(source_code: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    result = dict(kwargs)
    if source_code == "csv_mirror":
        result.setdefault("provider_name", "csv_mirror")
    return result


def _dedupe_rows(dataset_code: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        deduped[_record_key(dataset_code, row)] = row
    return list(deduped.values())


def _date_strings(start: date, end: date):
    current = start
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def _normalize_codes(values: Iterable[str], name: str) -> list[str]:
    result = _dedupe([str(value).strip() for value in values if str(value).strip()])
    if not result:
        raise QDataValidationError(f"{name} is required")
    return result


def _normalize_symbols(values: Iterable[str]) -> list[str]:
    return _normalize_codes([str(value).upper() for value in values], "canary_symbols")


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


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "runs": [
            "fabric_code",
            "status",
            "fabric_scope",
            "recommendation",
            "recommended_role",
            "risk_level",
            "baseline_source_code",
            "dataset_result_count",
            "usable_source_count",
            "coverage_rate",
            "conflict_rate_bps",
            "license_review_required_count",
            "commercial_blocker_count",
            "error_message",
        ],
        "run": [
            "fabric_code",
            "status",
            "recommendation",
            "risk_level",
            "dataset_result_count",
            "usable_source_count",
            "coverage_rate",
            "conflict_rate_bps",
            "error_message",
        ],
        "results": [
            "fabric_code",
            "result_code",
            "dataset_code",
            "status",
            "coverage_status",
            "consistency_status",
            "license_status",
            "recommendation",
            "risk_level",
            "baseline_source_code",
            "usable_source_count",
            "coverage_rate",
            "conflict_rate_bps",
            "error_message",
        ],
        "catalog": [
            "source_code",
            "provider_name",
            "external",
            "license_status",
            "commercial_allowed",
            "supported_datasets",
        ],
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _run_code(source_codes: list[str], status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{','.join(source_codes)}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"iota3-free-source-fabric-{status}-{digest}"[:180]


def _result_code(dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"iota3-free-source-result-{dataset_code}-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


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


def _lookup_dataset_id(cursor, dataset_code: str) -> int:
    cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = %s", (dataset_code,))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"dataset not found: {dataset_code}")
    return int(row["dataset_id"])


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Iota-3 free source fabric") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Iota-3 free source fabric")
    return _connect(postgres_dsn)
