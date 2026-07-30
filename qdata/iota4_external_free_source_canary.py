from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Iterable

from qdata.iota3_free_source_fabric import (
    DEFAULT_CANARY_SYMBOLS,
    run_free_source_fabric,
)


DEFAULT_IOTA4_DATASETS = ("daily_bar", "security_master", "trading_calendar")
DEFAULT_IOTA4_SOURCE_CODES = ("akshare",)
DEFAULT_IOTA4_COMPARE_SOURCE_CODES = ("csv", "csv_mirror", "akshare")
IOTA4_PASS_FABRIC_STATUSES = {"success", "warning"}


def run_external_free_source_canary(
    postgres_dsn: str,
    *,
    mode: str = "live-only",
    source_codes: Iterable[str] | None = None,
    dataset_codes: Iterable[str] = DEFAULT_IOTA4_DATASETS,
    start_date: str,
    end_date: str,
    canary_symbols: Iterable[str] = DEFAULT_CANARY_SYMBOLS,
    requested_by: str = "iota4",
    trigger_mode: str = "smoke",
    environment: str = "local",
    min_source_count: int | None = None,
    min_coverage_rate: float = 0.95,
    max_conflict_rate_bps: float = 100000.0,
    require_commercial_clearance: bool = False,
) -> dict[str, Any]:
    normalized_mode = _normalize_mode(mode)
    normalized_sources = list(source_codes) if source_codes is not None else default_source_codes(normalized_mode)
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
        require_external=True,
        require_commercial_clearance=require_commercial_clearance,
        min_source_count=min_source_count if min_source_count is not None else default_min_source_count(normalized_mode),
        min_coverage_rate=min_coverage_rate,
        max_conflict_rate_bps=max_conflict_rate_bps,
    )
    return with_iota4_evaluation(
        row,
        mode=normalized_mode,
        min_coverage_rate=min_coverage_rate,
        required_datasets=normalized_datasets,
    )


def with_iota4_evaluation(
    row: dict[str, Any],
    *,
    mode: str = "live-only",
    min_coverage_rate: float = 0.95,
    required_datasets: Iterable[str] = DEFAULT_IOTA4_DATASETS,
) -> dict[str, Any]:
    evaluation = evaluate_external_free_source_canary(
        row,
        mode=mode,
        min_coverage_rate=min_coverage_rate,
        required_datasets=required_datasets,
    )
    enriched = dict(row)
    enriched["iota4_canary_status"] = evaluation["status"]
    enriched["iota4_external_executed_source_count"] = evaluation["external_executed_source_count"]
    enriched["iota4_commercial_clearance"] = evaluation["commercial_clearance"]
    enriched["iota4_blocking_issues"] = evaluation["blocking_issues"]
    enriched["iota4_warnings"] = evaluation["warnings"]
    enriched["iota4_evaluation"] = evaluation
    return enriched


def evaluate_external_free_source_canary(
    row: dict[str, Any],
    *,
    mode: str = "live-only",
    min_coverage_rate: float = 0.95,
    required_datasets: Iterable[str] = DEFAULT_IOTA4_DATASETS,
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

    blocking_issues: list[str] = []
    if fabric_status not in IOTA4_PASS_FABRIC_STATUSES:
        blocking_issues.append(f"fabric_status_not_pass:{fabric_status}")
    if external_executed <= 0:
        blocking_issues.append("external_free_source_not_executed")
    if coverage_rate < min_coverage_rate:
        blocking_issues.append(f"coverage_below_threshold:{min_coverage_rate}")
    if missing_datasets:
        blocking_issues.append(f"missing_dataset:{','.join(missing_datasets)}")

    warnings: list[str] = []
    commercial_clearance = "blocked" if commercial_blocker_count or license_review_required_count else "clear"
    if commercial_clearance == "blocked":
        warnings.append("free_source_requires_license_review_before_commercial_use")
    if str(row.get("recommendation") or "") == "research_only":
        warnings.append("free_source_recommendation_is_research_only")

    return {
        "status": "ok" if not blocking_issues else "failed",
        "mode": _normalize_mode(mode),
        "fabric_status": fabric_status,
        "fabric_code": row.get("fabric_code"),
        "external_executed_source_count": external_executed,
        "coverage_rate": coverage_rate,
        "dataset_result_count": _int(row.get("dataset_result_count")),
        "source_count": _int(row.get("source_count")),
        "baseline_source_code": row.get("baseline_source_code"),
        "recommendation": row.get("recommendation"),
        "risk_level": row.get("risk_level"),
        "commercial_clearance": commercial_clearance,
        "commercial_blocker_count": commercial_blocker_count,
        "license_review_required_count": license_review_required_count,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }


def format_iota4_canary(row: dict[str, Any]) -> str:
    evaluation = row.get("iota4_evaluation") or evaluate_external_free_source_canary(row)
    fields = [
        ("iota4_external_free_source_canary", evaluation.get("status")),
        ("mode", evaluation.get("mode")),
        ("fabric_status", evaluation.get("fabric_status")),
        ("fabric_code", evaluation.get("fabric_code")),
        ("dataset_count", evaluation.get("dataset_result_count")),
        ("source_count", evaluation.get("source_count")),
        ("external_executed", evaluation.get("external_executed_source_count")),
        ("coverage_rate", _format_float(evaluation.get("coverage_rate"))),
        ("recommendation", evaluation.get("recommendation")),
        ("risk_level", evaluation.get("risk_level")),
        ("commercial_clearance", evaluation.get("commercial_clearance")),
    ]
    if evaluation.get("blocking_issues"):
        fields.append(("blocking_issues", ",".join(evaluation["blocking_issues"])))
    if evaluation.get("warnings"):
        fields.append(("warnings", ",".join(evaluation["warnings"])))
    return " ".join(f"{key}={value}" for key, value in fields if value not in (None, "", [], {}))


def default_source_codes(mode: str) -> list[str]:
    normalized_mode = _normalize_mode(mode)
    if normalized_mode == "compare-local":
        return list(DEFAULT_IOTA4_COMPARE_SOURCE_CODES)
    return list(DEFAULT_IOTA4_SOURCE_CODES)


def default_min_source_count(mode: str) -> int:
    return 2 if _normalize_mode(mode) == "compare-local" else 1


def _normalize_mode(mode: str) -> str:
    normalized = str(mode).strip().lower().replace("_", "-")
    if normalized not in {"live-only", "compare-local"}:
        raise ValueError("mode must be one of: live-only, compare-local")
    return normalized


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
