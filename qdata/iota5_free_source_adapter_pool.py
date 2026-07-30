from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Iterable

from qdata.iota3_free_source_fabric import (
    DEFAULT_CANARY_SYMBOLS,
    run_free_source_fabric,
)


DEFAULT_IOTA5_DATASETS = ("daily_bar", "security_master", "trading_calendar")
DEFAULT_IOTA5_SOURCE_CODES = ("akshare", "baostock", "tushare_free", "sse_public", "szse_public", "cninfo_public")
IOTA5_PASS_FABRIC_STATUSES = {"success", "warning"}
IOTA5_DEGRADED_FABRIC_STATUSES = {"blocked"}


def run_free_source_adapter_pool(
    postgres_dsn: str,
    *,
    source_codes: Iterable[str] = DEFAULT_IOTA5_SOURCE_CODES,
    dataset_codes: Iterable[str] = DEFAULT_IOTA5_DATASETS,
    start_date: str,
    end_date: str,
    canary_symbols: Iterable[str] = DEFAULT_CANARY_SYMBOLS,
    requested_by: str = "iota5",
    trigger_mode: str = "smoke",
    environment: str = "local",
    min_source_count: int = 2,
    min_external_successful: int = 2,
    min_coverage_rate: float = 0.95,
    max_conflict_rate_bps: float = 100000.0,
    require_commercial_clearance: bool = False,
    provider_kwargs_by_source: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_sources = [str(item).strip() for item in source_codes if str(item).strip()]
    normalized_datasets = [str(item).strip() for item in dataset_codes if str(item).strip()]
    row = run_free_source_fabric(
        postgres_dsn,
        source_codes=normalized_sources,
        dataset_codes=normalized_datasets,
        start_date=start_date,
        end_date=end_date,
        canary_symbols=canary_symbols,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        fabric_scope="canary",
        allow_external=True,
        require_external=False,
        require_commercial_clearance=require_commercial_clearance,
        min_source_count=min_source_count,
        min_coverage_rate=min_coverage_rate,
        max_conflict_rate_bps=max_conflict_rate_bps,
        provider_kwargs_by_source=provider_kwargs_by_source or {},
    )
    return with_iota5_evaluation(
        row,
        min_external_successful=min_external_successful,
        min_coverage_rate=min_coverage_rate,
        required_datasets=normalized_datasets,
    )


def with_iota5_evaluation(
    row: dict[str, Any],
    *,
    min_external_successful: int = 2,
    min_coverage_rate: float = 0.95,
    required_datasets: Iterable[str] = DEFAULT_IOTA5_DATASETS,
) -> dict[str, Any]:
    evaluation = evaluate_free_source_adapter_pool(
        row,
        min_external_successful=min_external_successful,
        min_coverage_rate=min_coverage_rate,
        required_datasets=required_datasets,
    )
    enriched = dict(row)
    enriched["iota5_pool_status"] = evaluation["status"]
    enriched["iota5_external_executed_source_count"] = evaluation["external_executed_source_count"]
    enriched["iota5_degraded_reasons"] = evaluation["degraded_reasons"]
    enriched["iota5_blocking_issues"] = evaluation["blocking_issues"]
    enriched["iota5_evaluation"] = evaluation
    return enriched


def evaluate_free_source_adapter_pool(
    row: dict[str, Any],
    *,
    min_external_successful: int = 2,
    min_coverage_rate: float = 0.95,
    required_datasets: Iterable[str] = DEFAULT_IOTA5_DATASETS,
) -> dict[str, Any]:
    evidence = _json_object(row.get("evidence"))
    source_summary = _json_object(evidence.get("source_summary"))
    external_executed = _int(source_summary.get("external_executed_source_count"))
    coverage_rate = _float(row.get("coverage_rate", source_summary.get("coverage_rate")))
    fabric_status = str(row.get("status") or "unknown")
    dataset_codes = set(_string_list(row.get("dataset_codes")))
    missing_datasets = sorted(set(required_datasets) - dataset_codes)
    commercial_blocker_count = _int(row.get("commercial_blocker_count"))
    license_review_required_count = _int(row.get("license_review_required_count"))
    issues = _string_list(row.get("blocking_issues"))

    blocking_issues: list[str] = []
    degraded_reasons: list[str] = []
    if fabric_status in IOTA5_DEGRADED_FABRIC_STATUSES and external_executed > 0:
        degraded_reasons.append(f"fabric_status_degraded:{fabric_status}")
    elif fabric_status == "failed" and external_executed > 0:
        degraded_reasons.append("fabric_status_degraded:failed")
    elif fabric_status not in IOTA5_PASS_FABRIC_STATUSES:
        blocking_issues.append(f"fabric_status_not_pass:{fabric_status}")
    if external_executed <= 0:
        blocking_issues.append("external_free_source_not_executed")
    elif external_executed < min_external_successful:
        degraded_reasons.append(f"external_successful_sources_below_target:{external_executed}/{min_external_successful}")
    if coverage_rate < min_coverage_rate:
        degraded_reasons.append(f"coverage_below_threshold:{min_coverage_rate}")
    if missing_datasets:
        degraded_reasons.append(f"missing_dataset:{','.join(missing_datasets)}")
    if any("official_public_adapter_scaffold_only" in issue for issue in issues):
        degraded_reasons.append("official_public_scaffold_pending")
    if any("QDATA_TUSHARE_TOKEN is required" in issue for issue in issues):
        degraded_reasons.append("tushare_token_missing")
    if any("baostock" in issue and ("timed out" in issue or "connection failed" in issue) for issue in issues):
        degraded_reasons.append("baostock_network_unreachable")
    if any("source_failed:baostock" in issue for issue in issues):
        degraded_reasons.append("baostock_source_failed")

    if blocking_issues:
        status = "failed"
    elif degraded_reasons:
        status = "degraded"
    else:
        status = "ok"

    commercial_clearance = "blocked" if commercial_blocker_count or license_review_required_count else "clear"
    return {
        "status": status,
        "fabric_status": fabric_status,
        "fabric_code": row.get("fabric_code"),
        "external_executed_source_count": external_executed,
        "source_count": _int(row.get("source_count")),
        "dataset_result_count": _int(row.get("dataset_result_count")),
        "usable_source_count": _int(row.get("usable_source_count")),
        "coverage_rate": coverage_rate,
        "conflict_rate_bps": _float(row.get("conflict_rate_bps")),
        "recommendation": row.get("recommendation"),
        "risk_level": row.get("risk_level"),
        "commercial_clearance": commercial_clearance,
        "commercial_blocker_count": commercial_blocker_count,
        "license_review_required_count": license_review_required_count,
        "degraded_reasons": _dedupe(degraded_reasons),
        "blocking_issues": _dedupe(blocking_issues),
    }


def format_iota5_pool(row: dict[str, Any]) -> str:
    evaluation = row.get("iota5_evaluation") or evaluate_free_source_adapter_pool(row)
    fields = [
        ("iota5_free_source_adapter_pool", evaluation.get("status")),
        ("fabric_status", evaluation.get("fabric_status")),
        ("fabric_code", evaluation.get("fabric_code")),
        ("dataset_count", evaluation.get("dataset_result_count")),
        ("source_count", evaluation.get("source_count")),
        ("usable_source_count", evaluation.get("usable_source_count")),
        ("external_executed", evaluation.get("external_executed_source_count")),
        ("coverage_rate", _format_float(evaluation.get("coverage_rate"))),
        ("conflict_rate_bps", _format_float(evaluation.get("conflict_rate_bps"))),
        ("recommendation", evaluation.get("recommendation")),
        ("risk_level", evaluation.get("risk_level")),
        ("commercial_clearance", evaluation.get("commercial_clearance")),
    ]
    if evaluation.get("degraded_reasons"):
        fields.append(("degraded_reasons", ",".join(evaluation["degraded_reasons"])))
    if evaluation.get("blocking_issues"):
        fields.append(("blocking_issues", ",".join(evaluation["blocking_issues"])))
    return " ".join(f"{key}={value}" for key, value in fields if value not in (None, "", [], {}))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def _int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _format_float(value: Any) -> str:
    return f"{_float(value):.6f}"


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))
