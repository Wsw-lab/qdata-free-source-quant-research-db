from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omicron5_vendor_contract import DEFAULT_VENDOR_DATASETS, DEFAULT_VENDOR_SOURCE_CODES


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
OPTIMIZATION_SCOPES = {"primary_source", "all_datasets", "full_market"}
COST_STATUSES = {"optimized", "watch", "over_budget", "quota_risk", "blocked", "no_primary_promotion"}
OPTIMIZATION_ROLES = {"primary_mix", "cost_watch", "budget_guard", "blocked", "watch"}
PLAN_ROLES = {"primary", "backup_mix", "validator_only", "blocked", "watch"}
DEFAULT_STRESS_MULTIPLIERS = (1.0, 5.0, 10.0)


def run_vendor_cost_optimizer(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    source_code: str = DEFAULT_VENDOR_SOURCE_CODES[0],
    primary_source_code: str = "csv",
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "tau5",
    trigger_mode: str = "manual",
    environment: str = "local",
    optimization_scope: str = "primary_source",
    lookback_hours: int = 24,
    forecast_window_days: int = 30,
    monthly_budget_amount: float = 10000.0,
    max_budget_usage_pct: float = 0.85,
    max_daily_quota_usage_pct: float = 0.85,
    max_monthly_quota_usage_pct: float = 0.85,
    min_stability_score: float = 70.0,
    cost_safety_margin_pct: float = 0.15,
    default_unit_cost: float = 0.01,
    stress_multipliers: Iterable[float] | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    multipliers = _normalize_stress_multipliers(stress_multipliers)
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        optimization_scope=optimization_scope,
        lookback_hours=lookback_hours,
        forecast_window_days=forecast_window_days,
        monthly_budget_amount=monthly_budget_amount,
        max_budget_usage_pct=max_budget_usage_pct,
        max_daily_quota_usage_pct=max_daily_quota_usage_pct,
        max_monthly_quota_usage_pct=max_monthly_quota_usage_pct,
        min_stability_score=min_stability_score,
        cost_safety_margin_pct=cost_safety_margin_pct,
        default_unit_cost=default_unit_cost,
        stress_multipliers=multipliers,
    )
    snapshot_date = _as_of_date(as_of_date)
    datasets = _normalize_optional_codes(dataset_codes) or list(DEFAULT_VENDOR_DATASETS)
    dsn = _require_dsn(postgres_dsn)
    started_at = datetime.now(timezone.utc)
    rows = _load_optimization_inputs(
        dsn,
        as_of_date=snapshot_date,
        source_code=source_code,
        primary_source_code=primary_source_code,
        dataset_codes=datasets,
    )
    dataset_api_metrics = _load_dataset_api_metrics(dsn, lookback_hours=lookback_hours, dataset_codes=datasets)
    plans = build_vendor_route_weight_plans(
        rows,
        dataset_api_metrics=dataset_api_metrics,
        as_of_date=snapshot_date,
        optimization_scope=optimization_scope,
        lookback_hours=lookback_hours,
        forecast_window_days=forecast_window_days,
        monthly_budget_amount=monthly_budget_amount,
        max_budget_usage_pct=max_budget_usage_pct,
        max_daily_quota_usage_pct=max_daily_quota_usage_pct,
        max_monthly_quota_usage_pct=max_monthly_quota_usage_pct,
        min_stability_score=min_stability_score,
        cost_safety_margin_pct=cost_safety_margin_pct,
        default_unit_cost=default_unit_cost,
    )
    finished_at = datetime.now(timezone.utc)
    snapshot = build_vendor_cost_optimization_snapshot(
        plans,
        source_code=source_code,
        primary_source_code=primary_source_code,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        optimization_scope=optimization_scope,
        lookback_hours=lookback_hours,
        forecast_window_days=forecast_window_days,
        monthly_budget_amount=monthly_budget_amount,
        max_budget_usage_pct=max_budget_usage_pct,
        max_daily_quota_usage_pct=max_daily_quota_usage_pct,
        max_monthly_quota_usage_pct=max_monthly_quota_usage_pct,
        min_stability_score=min_stability_score,
        cost_safety_margin_pct=cost_safety_margin_pct,
        default_unit_cost=default_unit_cost,
        stress_multipliers=multipliers,
        stability_snapshot_id=_first_value(plans, "stability_snapshot_id"),
        started_at=started_at,
        finished_at=finished_at,
    )
    stress_rows = build_vendor_budget_stress_snapshots(
        plans,
        as_of_date=snapshot_date,
        stress_multipliers=multipliers,
        max_budget_usage_pct=max_budget_usage_pct,
        max_daily_quota_usage_pct=max_daily_quota_usage_pct,
        max_monthly_quota_usage_pct=max_monthly_quota_usage_pct,
    )
    if not write_db:
        snapshot["route_plans"] = normalize_rows(plans)
        snapshot["stress_snapshots"] = normalize_rows(stress_rows)
        return normalize_rows([snapshot])[0]
    stored = _insert_optimization_snapshot(dsn, snapshot)
    stored_plans = _insert_route_weight_plans(dsn, stored, plans)
    stored_stress = _insert_budget_stress_snapshots(dsn, stored, stored_plans, stress_rows)
    stored["route_plans"] = stored_plans
    stored["stress_snapshots"] = stored_stress
    return stored


def build_vendor_route_weight_plans(
    rows: list[dict[str, Any]],
    *,
    dataset_api_metrics: dict[str, dict[str, Any]] | None = None,
    as_of_date: str | date | None = None,
    optimization_scope: str = "primary_source",
    lookback_hours: int = 24,
    forecast_window_days: int = 30,
    monthly_budget_amount: float = 10000.0,
    max_budget_usage_pct: float = 0.85,
    max_daily_quota_usage_pct: float = 0.85,
    max_monthly_quota_usage_pct: float = 0.85,
    min_stability_score: float = 70.0,
    cost_safety_margin_pct: float = 0.15,
    default_unit_cost: float = 0.01,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    if optimization_scope not in OPTIMIZATION_SCOPES:
        raise QDataValidationError("optimization_scope must be one of: primary_source, all_datasets, full_market")
    metric_map = dataset_api_metrics or {}
    dataset_count = max(len(rows), 1)
    allocated_budget_amount = monthly_budget_amount / dataset_count
    plans: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        dataset_code = str(row.get("dataset_code") or "unknown")
        metrics = metric_map.get(dataset_code, {})
        merged = {
            **row,
            "api_request_count": _int_or_zero(metrics.get("api_request_count")),
            "api_row_count": _int_or_zero(metrics.get("row_count")),
            "api_cost_units": _float_or_zero(metrics.get("cost_units")),
        }
        evaluation = evaluate_vendor_route_weight(
            merged,
            dataset_count=dataset_count,
            allocated_budget_amount=allocated_budget_amount,
            lookback_hours=lookback_hours,
            forecast_window_days=forecast_window_days,
            max_budget_usage_pct=max_budget_usage_pct,
            max_daily_quota_usage_pct=max_daily_quota_usage_pct,
            max_monthly_quota_usage_pct=max_monthly_quota_usage_pct,
            min_stability_score=min_stability_score,
            cost_safety_margin_pct=cost_safety_margin_pct,
            default_unit_cost=default_unit_cost,
        )
        plan = {
            "plan_code": _plan_code(str(row.get("source_code") or "unknown"), dataset_code, evaluation["status"]),
            "source_id": row["source_id"],
            "source_code": row.get("source_code"),
            "dataset_id": row["dataset_id"],
            "dataset_code": dataset_code,
            "primary_source_id": row.get("primary_source_id"),
            "primary_source_code": row.get("primary_source_code"),
            "backup_source_id": row.get("backup_source_id"),
            "backup_source_code": row.get("backup_source_code"),
            "current_priority_id": row.get("current_priority_id"),
            "stability_snapshot_id": row.get("stability_snapshot_id"),
            "stability_snapshot_code": row.get("stability_snapshot_code"),
            "as_of_date": snapshot_date.isoformat(),
            "status": evaluation["status"],
            "plan_role": evaluation["plan_role"],
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": _int_or_none(row.get("current_priority")),
            "is_primary_route": evaluation["is_primary_route"],
            "stability_status": row.get("stability_status"),
            "stability_score": evaluation["stability_score"],
            "contract_status": row.get("contract_status"),
            "entitlement_status": row.get("entitlement_status"),
            "production_use_allowed": evaluation["production_use_allowed"],
            "billing_model": row.get("billing_model") or "unknown",
            "billing_currency": row.get("billing_currency") or "CNY",
            "unit_cost": evaluation["unit_cost"],
            "monthly_fee_allocated": evaluation["monthly_fee_allocated"],
            "current_request_count": evaluation["current_request_count"],
            "forecast_request_count": evaluation["forecast_request_count"],
            "forecast_row_count": evaluation["forecast_row_count"],
            "current_cost_units": evaluation["current_cost_units"],
            "forecast_cost_units": evaluation["forecast_cost_units"],
            "allocated_budget_amount": round(allocated_budget_amount, 8),
            "projected_budget_usage_pct": evaluation["projected_budget_usage_pct"],
            "daily_quota": evaluation["daily_quota"],
            "monthly_quota": evaluation["monthly_quota"],
            "projected_daily_request_count": evaluation["projected_daily_request_count"],
            "projected_monthly_request_count": evaluation["projected_monthly_request_count"],
            "projected_daily_quota_usage_pct": evaluation["projected_daily_quota_usage_pct"],
            "projected_monthly_quota_usage_pct": evaluation["projected_monthly_quota_usage_pct"],
            "quota_exhaustion_days": evaluation["quota_exhaustion_days"],
            "recommended_primary_weight_pct": evaluation["recommended_primary_weight_pct"],
            "recommended_backup_weight_pct": evaluation["recommended_backup_weight_pct"],
            "recommended_free_source_weight_pct": evaluation["recommended_free_source_weight_pct"],
            "routing_change_allowed": evaluation["routing_change_allowed"],
            "optimization_score": evaluation["optimization_score"],
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": build_vendor_cost_required_actions(evaluation["blocking_issues"], evaluation["status"]),
            "evidence": _plan_evidence(row, metrics, evaluation),
            "error_message": "; ".join(evaluation["blocking_issues"]) if evaluation["status"] in {"blocked", "over_budget", "quota_risk", "no_primary_promotion"} and evaluation["blocking_issues"] else None,
        }
        plans.append(plan)
    return plans


def evaluate_vendor_route_weight(
    row: dict[str, Any],
    *,
    dataset_count: int = 1,
    allocated_budget_amount: float = 10000.0,
    lookback_hours: int = 24,
    forecast_window_days: int = 30,
    max_budget_usage_pct: float = 0.85,
    max_daily_quota_usage_pct: float = 0.85,
    max_monthly_quota_usage_pct: float = 0.85,
    min_stability_score: float = 70.0,
    cost_safety_margin_pct: float = 0.15,
    default_unit_cost: float = 0.01,
) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    budget_issues: list[str] = []
    quota_issues: list[str] = []
    source_code = str(row.get("source_code") or "")
    current_primary_source_code = row.get("current_primary_source_code")
    current_priority = _int_or_none(row.get("current_priority"))
    is_primary_route = current_primary_source_code == source_code and current_priority == 0
    stability_status = row.get("stability_status") or "missing"
    stability_score = _float_or_zero(row.get("stability_score"))
    if stability_status == "no_primary_promotion" or not is_primary_route:
        issues.append(f"sigma5_primary_route_not_active:{stability_status}/{current_primary_source_code or 'missing'}")
    elif stability_status in {"critical", "blocked"}:
        issues.append(f"sigma5_stability_blocking:{stability_status}")
    elif stability_score < min_stability_score:
        warnings.append(f"stability_score_low:{stability_score}")

    contract_status = row.get("contract_status") or "none"
    procurement_status = row.get("procurement_status") or "review_required"
    contract_production_use_allowed = _bool(row.get("contract_production_use_allowed"))
    entitlement_status = row.get("entitlement_status") or "review_required"
    entitlement_allowed_role = row.get("allowed_role") or row.get("entitlement_allowed_role") or "validator"
    entitlement_production_use_allowed = _bool(row.get("production_use_allowed"))
    production_use_allowed = contract_production_use_allowed and entitlement_production_use_allowed
    if contract_status != "active" or procurement_status != "active":
        warnings.append(f"contract_not_active:{procurement_status}/{contract_status}")
    if not production_use_allowed:
        warnings.append("production_use_not_allowed")
    if entitlement_status != "active":
        warnings.append(f"entitlement_not_active:{entitlement_status}")
    if entitlement_allowed_role not in {"primary_candidate", "primary", "backup"}:
        warnings.append(f"allowed_role_limited:{entitlement_allowed_role}")

    request_count = _int_or_zero(row.get("api_request_count"))
    row_count = _int_or_zero(row.get("api_row_count"))
    lookback_days = max(lookback_hours / 24.0, 1 / 24.0)
    daily_request_rate = request_count / lookback_days
    daily_row_rate = row_count / lookback_days
    forecast_request_count = int(math.ceil(daily_request_rate * forecast_window_days))
    forecast_row_count = int(math.ceil(daily_row_rate * forecast_window_days))
    current_cost_units = _float_or_zero(row.get("api_cost_units"))
    unit_cost_raw = _float_or_none(row.get("unit_cost"))
    unit_cost = default_unit_cost if unit_cost_raw is None else unit_cost_raw
    if unit_cost_raw is None:
        warnings.append(f"default_unit_cost_used:{default_unit_cost}")
    monthly_fee = _float_or_zero(row.get("monthly_fee"))
    monthly_fee_allocated = monthly_fee / max(dataset_count, 1)
    forecast_cost_units = round(forecast_request_count * unit_cost + monthly_fee_allocated, 8)
    budget_with_margin = allocated_budget_amount * max(0.0, 1.0 - cost_safety_margin_pct)
    projected_budget_usage_pct = _rate_float(forecast_cost_units, allocated_budget_amount)
    if forecast_cost_units > allocated_budget_amount:
        budget_issues.append(f"budget_overrun:{projected_budget_usage_pct}")
    elif forecast_cost_units > budget_with_margin or projected_budget_usage_pct > max_budget_usage_pct:
        warnings.append(f"budget_watch:{projected_budget_usage_pct}")

    daily_quota = _int_or_zero(row.get("entitlement_daily_quota") or row.get("contract_daily_quota"))
    monthly_quota = _int_or_zero(row.get("contract_monthly_quota"))
    projected_daily_request_count = int(math.ceil(daily_request_rate))
    projected_monthly_request_count = int(math.ceil(daily_request_rate * 30))
    projected_daily_quota_usage_pct = _rate_float(projected_daily_request_count, daily_quota) if daily_quota else 0.0
    projected_monthly_quota_usage_pct = _rate_float(projected_monthly_request_count, monthly_quota) if monthly_quota else 0.0
    quota_exhaustion_days = round(monthly_quota / daily_request_rate, 4) if monthly_quota and daily_request_rate > 0 else None
    if not daily_quota:
        warnings.append("daily_quota_missing")
    elif projected_daily_quota_usage_pct > max_daily_quota_usage_pct:
        quota_issues.append(f"daily_quota_pressure:{projected_daily_quota_usage_pct}")
    if not monthly_quota:
        warnings.append("monthly_quota_missing")
    elif projected_monthly_quota_usage_pct > max_monthly_quota_usage_pct:
        quota_issues.append(f"monthly_quota_pressure:{projected_monthly_quota_usage_pct}")

    if issues:
        status = "no_primary_promotion" if any(issue.startswith("sigma5_primary_route_not_active") for issue in issues) else "blocked"
    elif budget_issues:
        status = "over_budget"
    elif quota_issues:
        status = "quota_risk"
    elif warnings:
        status = "watch"
    else:
        status = "optimized"
    primary_weight, backup_weight, free_weight, plan_role = _recommended_weights(status)
    all_issues = _dedupe(issues + budget_issues + quota_issues + warnings)
    return {
        "status": status,
        "plan_role": plan_role,
        "is_primary_route": is_primary_route,
        "production_use_allowed": production_use_allowed,
        "stability_score": stability_score,
        "unit_cost": round(unit_cost, 8),
        "monthly_fee_allocated": round(monthly_fee_allocated, 8),
        "current_request_count": request_count,
        "forecast_request_count": forecast_request_count,
        "forecast_row_count": forecast_row_count,
        "current_cost_units": round(current_cost_units, 8),
        "forecast_cost_units": forecast_cost_units,
        "projected_budget_usage_pct": projected_budget_usage_pct,
        "daily_quota": daily_quota,
        "monthly_quota": monthly_quota,
        "projected_daily_request_count": projected_daily_request_count,
        "projected_monthly_request_count": projected_monthly_request_count,
        "projected_daily_quota_usage_pct": projected_daily_quota_usage_pct,
        "projected_monthly_quota_usage_pct": projected_monthly_quota_usage_pct,
        "quota_exhaustion_days": quota_exhaustion_days,
        "recommended_primary_weight_pct": primary_weight,
        "recommended_backup_weight_pct": backup_weight,
        "recommended_free_source_weight_pct": free_weight,
        "routing_change_allowed": status not in {"blocked", "no_primary_promotion"},
        "optimization_score": _status_score(status),
        "blocking_issues": all_issues,
    }


def build_vendor_cost_optimization_snapshot(
    plans: list[dict[str, Any]],
    *,
    source_code: str,
    primary_source_code: str,
    as_of_date: str | date | None = None,
    requested_by: str = "tau5",
    trigger_mode: str = "manual",
    environment: str = "local",
    optimization_scope: str = "primary_source",
    lookback_hours: int = 24,
    forecast_window_days: int = 30,
    monthly_budget_amount: float = 10000.0,
    max_budget_usage_pct: float = 0.85,
    max_daily_quota_usage_pct: float = 0.85,
    max_monthly_quota_usage_pct: float = 0.85,
    min_stability_score: float = 70.0,
    cost_safety_margin_pct: float = 0.15,
    default_unit_cost: float = 0.01,
    stress_multipliers: Iterable[float] | None = None,
    stability_snapshot_id: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot_date = _as_of_date(as_of_date)
    multipliers = _normalize_stress_multipliers(stress_multipliers)
    statuses = [str(plan.get("status")) for plan in plans]
    blocking_issues = _dedupe(issue for plan in plans for issue in plan.get("blocking_issues") or [])
    status = _aggregate_status(statuses)
    role = _optimization_role(status)
    started = started_at or datetime.now(timezone.utc)
    finished = finished_at or datetime.now(timezone.utc)
    dataset_count = len(plans)
    return {
        "optimization_code": _optimization_code(source_code, optimization_scope, status),
        "source_id": _first_value(plans, "source_id"),
        "source_code": source_code,
        "primary_source_id": _first_value(plans, "primary_source_id"),
        "primary_source_code": primary_source_code,
        "stability_snapshot_id": stability_snapshot_id,
        "stability_snapshot_code": _first_value(plans, "stability_snapshot_code"),
        "as_of_date": snapshot_date.isoformat(),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "optimization_scope": optimization_scope,
        "status": status,
        "optimization_role": role,
        "lookback_hours": lookback_hours,
        "forecast_window_days": forecast_window_days,
        "monthly_budget_amount": round(monthly_budget_amount, 8),
        "max_budget_usage_pct": max_budget_usage_pct,
        "max_daily_quota_usage_pct": max_daily_quota_usage_pct,
        "max_monthly_quota_usage_pct": max_monthly_quota_usage_pct,
        "min_stability_score": min_stability_score,
        "cost_safety_margin_pct": cost_safety_margin_pct,
        "default_unit_cost": default_unit_cost,
        "stress_multipliers": list(multipliers),
        "dataset_count": dataset_count,
        "optimized_dataset_count": sum(1 for plan in plans if plan.get("status") == "optimized"),
        "watch_dataset_count": sum(1 for plan in plans if plan.get("status") == "watch"),
        "over_budget_dataset_count": sum(1 for plan in plans if plan.get("status") == "over_budget"),
        "quota_risk_dataset_count": sum(1 for plan in plans if plan.get("status") == "quota_risk"),
        "blocked_dataset_count": sum(1 for plan in plans if plan.get("status") == "blocked"),
        "no_primary_dataset_count": sum(1 for plan in plans if plan.get("status") == "no_primary_promotion"),
        "current_request_count": sum(_int_or_zero(plan.get("current_request_count")) for plan in plans),
        "forecast_request_count": sum(_int_or_zero(plan.get("forecast_request_count")) for plan in plans),
        "forecast_row_count": sum(_int_or_zero(plan.get("forecast_row_count")) for plan in plans),
        "current_cost_units": round(sum(_float_or_zero(plan.get("current_cost_units")) for plan in plans), 8),
        "forecast_cost_units": round(sum(_float_or_zero(plan.get("forecast_cost_units")) for plan in plans), 8),
        "monthly_fee": round(sum(_float_or_zero(plan.get("monthly_fee_allocated")) for plan in plans), 8),
        "projected_monthly_cost": round(sum(_float_or_zero(plan.get("forecast_cost_units")) for plan in plans), 8),
        "projected_budget_usage_pct": _rate_float(sum(_float_or_zero(plan.get("forecast_cost_units")) for plan in plans), monthly_budget_amount),
        "daily_quota": sum(_int_or_zero(plan.get("daily_quota")) for plan in plans),
        "monthly_quota": sum(_int_or_zero(plan.get("monthly_quota")) for plan in plans),
        "projected_daily_request_count": sum(_int_or_zero(plan.get("projected_daily_request_count")) for plan in plans),
        "projected_monthly_request_count": sum(_int_or_zero(plan.get("projected_monthly_request_count")) for plan in plans),
        "projected_daily_quota_usage_pct": _rate_float(
            sum(_int_or_zero(plan.get("projected_daily_request_count")) for plan in plans),
            sum(_int_or_zero(plan.get("daily_quota")) for plan in plans),
        ),
        "projected_monthly_quota_usage_pct": _rate_float(
            sum(_int_or_zero(plan.get("projected_monthly_request_count")) for plan in plans),
            sum(_int_or_zero(plan.get("monthly_quota")) for plan in plans),
        ),
        "quota_exhaustion_days": _min_non_null(plan.get("quota_exhaustion_days") for plan in plans),
        "recommended_primary_weight_pct": _average(plans, "recommended_primary_weight_pct"),
        "recommended_backup_weight_pct": _average(plans, "recommended_backup_weight_pct"),
        "recommended_free_source_weight_pct": _average(plans, "recommended_free_source_weight_pct"),
        "optimization_score": _average(plans, "optimization_score") if plans else _status_score(status),
        "blocking_issues": blocking_issues,
        "required_actions": build_vendor_cost_required_actions(blocking_issues, status),
        "request_payload": {
            "source_code": source_code,
            "primary_source_code": primary_source_code,
            "dataset_codes": [plan.get("dataset_code") for plan in plans],
            "optimization_scope": optimization_scope,
            "lookback_hours": lookback_hours,
            "forecast_window_days": forecast_window_days,
            "thresholds": {
                "monthly_budget_amount": monthly_budget_amount,
                "max_budget_usage_pct": max_budget_usage_pct,
                "max_daily_quota_usage_pct": max_daily_quota_usage_pct,
                "max_monthly_quota_usage_pct": max_monthly_quota_usage_pct,
                "min_stability_score": min_stability_score,
                "cost_safety_margin_pct": cost_safety_margin_pct,
                "default_unit_cost": default_unit_cost,
                "stress_multipliers": list(multipliers),
            },
        },
        "response_payload": {
            "status": status,
            "optimization_role": role,
            "dataset_count": dataset_count,
            "recommended_primary_weight_pct": _average(plans, "recommended_primary_weight_pct"),
            "projected_budget_usage_pct": _rate_float(sum(_float_or_zero(plan.get("forecast_cost_units")) for plan in plans), monthly_budget_amount),
            "projected_monthly_quota_usage_pct": _rate_float(
                sum(_int_or_zero(plan.get("projected_monthly_request_count")) for plan in plans),
                sum(_int_or_zero(plan.get("monthly_quota")) for plan in plans),
            ),
        },
        "evidence": {
            "stability_snapshot_code": _first_value(plans, "stability_snapshot_code"),
            "policy": {
                "requires_sigma5_primary_route": True,
                "requires_active_contract_for_primary_expansion": True,
                "free_source_weight_cap_pct": 10,
                "dry_run_only": True,
            },
        },
        "details": {"status_distribution": {status_name: statuses.count(status_name) for status_name in sorted(COST_STATUSES)}},
        "error_message": "; ".join(blocking_issues) if status in {"blocked", "over_budget", "quota_risk", "no_primary_promotion"} and blocking_issues else None,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": _duration_ms(started, finished),
    }


def build_vendor_budget_stress_snapshots(
    plans: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    stress_multipliers: Iterable[float] | None = None,
    max_budget_usage_pct: float = 0.85,
    max_daily_quota_usage_pct: float = 0.85,
    max_monthly_quota_usage_pct: float = 0.85,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    rows: list[dict[str, Any]] = []
    for plan in plans:
        for multiplier in _normalize_stress_multipliers(stress_multipliers):
            status = _stress_status(
                str(plan.get("status") or "watch"),
                budget_pct=_float_or_zero(plan.get("projected_budget_usage_pct")) * multiplier,
                daily_quota_pct=_float_or_zero(plan.get("projected_daily_quota_usage_pct")) * multiplier,
                monthly_quota_pct=_float_or_zero(plan.get("projected_monthly_quota_usage_pct")) * multiplier,
                max_budget_usage_pct=max_budget_usage_pct,
                max_daily_quota_usage_pct=max_daily_quota_usage_pct,
                max_monthly_quota_usage_pct=max_monthly_quota_usage_pct,
            )
            forecast_request_count = int(math.ceil(_int_or_zero(plan.get("forecast_request_count")) * multiplier))
            forecast_cost_units = round(_float_or_zero(plan.get("forecast_cost_units")) * multiplier, 8)
            projected_daily = int(math.ceil(_int_or_zero(plan.get("projected_daily_request_count")) * multiplier))
            projected_monthly = int(math.ceil(_int_or_zero(plan.get("projected_monthly_request_count")) * multiplier))
            daily_quota = _int_or_zero(plan.get("daily_quota"))
            monthly_quota = _int_or_zero(plan.get("monthly_quota"))
            issues = _stress_issues(
                status,
                budget_pct=_float_or_zero(plan.get("projected_budget_usage_pct")) * multiplier,
                daily_quota_pct=_rate_float(projected_daily, daily_quota) if daily_quota else 0.0,
                monthly_quota_pct=_rate_float(projected_monthly, monthly_quota) if monthly_quota else 0.0,
            )
            rows.append(
                {
                    "stress_code": _stress_code(str(plan.get("source_code") or "unknown"), str(plan.get("dataset_code") or "unknown"), multiplier, status),
                    "plan_code": plan.get("plan_code"),
                    "source_id": plan["source_id"],
                    "source_code": plan.get("source_code"),
                    "dataset_id": plan["dataset_id"],
                    "dataset_code": plan.get("dataset_code"),
                    "as_of_date": snapshot_date.isoformat(),
                    "stress_multiplier": multiplier,
                    "status": status,
                    "forecast_request_count": forecast_request_count,
                    "forecast_cost_units": forecast_cost_units,
                    "projected_budget_usage_pct": round(_float_or_zero(plan.get("projected_budget_usage_pct")) * multiplier, 8),
                    "projected_daily_request_count": projected_daily,
                    "projected_monthly_request_count": projected_monthly,
                    "projected_daily_quota_usage_pct": _rate_float(projected_daily, daily_quota) if daily_quota else 0.0,
                    "projected_monthly_quota_usage_pct": _rate_float(projected_monthly, monthly_quota) if monthly_quota else 0.0,
                    "quota_exhaustion_days": (
                        round(_float_or_zero(plan.get("quota_exhaustion_days")) / multiplier, 4)
                        if plan.get("quota_exhaustion_days") is not None
                        else None
                    ),
                    "recommended_action": _stress_recommended_action(status),
                    "blocking_issues": issues,
                    "required_actions": build_vendor_cost_required_actions(_dedupe(list(plan.get("blocking_issues") or []) + issues), status),
                    "evidence": {
                        "base_plan_code": plan.get("plan_code"),
                        "base_status": plan.get("status"),
                        "base_primary_weight_pct": plan.get("recommended_primary_weight_pct"),
                        "stress_multiplier": multiplier,
                    },
                    "error_message": "; ".join(issues) if status in {"over_budget", "quota_risk", "blocked", "no_primary_promotion"} and issues else None,
                }
            )
    return rows


def build_vendor_cost_required_actions(issues: list[str], status: str) -> list[str]:
    issue_text = " ".join(issues)
    actions: list[str] = []
    if "sigma5_primary_route_not_active" in issue_text or status == "no_primary_promotion":
        actions.append("Wait for an applied Pi-5 promotion and healthy Sigma-5 primary route before assigning vendor primary cost weight.")
    if "sigma5_stability_blocking" in issue_text or "stability_score_low" in issue_text:
        actions.append("Keep vendor weight capped until Sigma-5 stability score and SLA evidence recover.")
    if "contract_not_active" in issue_text or "production_use_not_allowed" in issue_text or "entitlement_not_active" in issue_text:
        actions.append("Complete active contract, production-use rights and dataset entitlements before expanding paid vendor traffic.")
    if "default_unit_cost_used" in issue_text:
        actions.append("Record real unit_cost, monthly_fee, daily_quota and monthly_quota in Omicron-5 contract metadata.")
    if "budget_overrun" in issue_text or "budget_pressure" in issue_text or status == "over_budget":
        actions.append("Reduce paid primary weight, add cache/batch pulls, or raise the monthly vendor budget before scale-up.")
    if "quota_pressure" in issue_text or status == "quota_risk":
        actions.append("Throttle high-cost datasets, request larger quota, or shift validation traffic to backup/free sources.")
    if status == "optimized":
        actions.append("Keep Tau-5 schedule active and re-run stress after any contract, quota or route change.")
    elif status == "watch":
        actions.append("Review warning items before increasing primary vendor weight.")
    elif status == "blocked":
        actions.append("Do not apply route weight changes until blocking contract, stability or entitlement issues are resolved.")
    return _dedupe(actions)


def list_vendor_cost_optimizations(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("optimization_code", "vcos.optimization_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vcos.status"),
            ("optimization_role", "vcos.optimization_role"),
            ("optimization_scope", "vcos.optimization_scope"),
            ("requested_by", "vcos.requested_by"),
            ("trigger_mode", "vcos.trigger_mode"),
            ("environment", "vcos.environment"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "vcos.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "vcos.as_of_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vcos.optimization_id, vcos.optimization_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vpss.snapshot_code AS stability_snapshot_code,
            vcos.as_of_at, vcos.as_of_date,
            vcos.requested_by, vcos.trigger_mode,
            vcos.environment, vcos.optimization_scope,
            vcos.status, vcos.optimization_role,
            vcos.lookback_hours, vcos.forecast_window_days,
            vcos.monthly_budget_amount, vcos.max_budget_usage_pct,
            vcos.max_daily_quota_usage_pct, vcos.max_monthly_quota_usage_pct,
            vcos.dataset_count, vcos.optimized_dataset_count,
            vcos.watch_dataset_count, vcos.over_budget_dataset_count,
            vcos.quota_risk_dataset_count, vcos.blocked_dataset_count,
            vcos.no_primary_dataset_count, vcos.current_request_count,
            vcos.forecast_request_count, vcos.forecast_row_count,
            vcos.current_cost_units, vcos.forecast_cost_units,
            vcos.projected_monthly_cost, vcos.projected_budget_usage_pct,
            vcos.daily_quota, vcos.monthly_quota,
            vcos.projected_daily_request_count,
            vcos.projected_monthly_request_count,
            vcos.projected_daily_quota_usage_pct,
            vcos.projected_monthly_quota_usage_pct,
            vcos.quota_exhaustion_days,
            vcos.recommended_primary_weight_pct,
            vcos.recommended_backup_weight_pct,
            vcos.recommended_free_source_weight_pct,
            vcos.optimization_score,
            vcos.blocking_issues, vcos.required_actions,
            vcos.error_message, vcos.started_at,
            vcos.finished_at, vcos.duration_ms,
            vcos.created_at, vcos.updated_at
        FROM qmeta.vendor_cost_optimization_snapshot vcos
        JOIN qmeta.source_system ss ON ss.source_id = vcos.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vcos.primary_source_id
        LEFT JOIN qmeta.vendor_primary_stability_snapshot vpss ON vpss.snapshot_id = vcos.stability_snapshot_id
        {where}
        ORDER BY vcos.as_of_at DESC, vcos.optimization_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_route_weight_plans(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("optimization_code", "vcos.optimization_code"),
            ("plan_code", "vrwp.plan_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("primary_source_code", "ps.source_code"),
            ("backup_source_code", "bs.source_code"),
            ("status", "vrwp.status"),
            ("plan_role", "vrwp.plan_role"),
            ("current_primary_source_code", "vrwp.current_primary_source_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vrwp.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vrwp.plan_id, vcos.optimization_code,
            vrwp.plan_code, ss.source_code,
            dc.dataset_code, ps.source_code AS primary_source_code,
            bs.source_code AS backup_source_code,
            vrwp.as_of_date, vrwp.status, vrwp.plan_role,
            vrwp.current_primary_source_code, vrwp.current_priority,
            vrwp.is_primary_route, vrwp.stability_status,
            vrwp.stability_score, vrwp.contract_status,
            vrwp.entitlement_status, vrwp.production_use_allowed,
            vrwp.billing_model, vrwp.billing_currency,
            vrwp.unit_cost, vrwp.monthly_fee_allocated,
            vrwp.current_request_count, vrwp.forecast_request_count,
            vrwp.forecast_row_count, vrwp.current_cost_units,
            vrwp.forecast_cost_units, vrwp.allocated_budget_amount,
            vrwp.projected_budget_usage_pct, vrwp.daily_quota,
            vrwp.monthly_quota, vrwp.projected_daily_request_count,
            vrwp.projected_monthly_request_count,
            vrwp.projected_daily_quota_usage_pct,
            vrwp.projected_monthly_quota_usage_pct,
            vrwp.quota_exhaustion_days,
            vrwp.recommended_primary_weight_pct,
            vrwp.recommended_backup_weight_pct,
            vrwp.recommended_free_source_weight_pct,
            vrwp.routing_change_allowed, vrwp.optimization_score,
            vrwp.blocking_issues, vrwp.required_actions,
            vrwp.error_message, vrwp.created_at,
            vrwp.updated_at
        FROM qmeta.vendor_route_weight_plan vrwp
        JOIN qmeta.vendor_cost_optimization_snapshot vcos ON vcos.optimization_id = vrwp.optimization_id
        JOIN qmeta.source_system ss ON ss.source_id = vrwp.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrwp.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vrwp.primary_source_id
        LEFT JOIN qmeta.source_system bs ON bs.source_id = vrwp.backup_source_id
        {where}
        ORDER BY vrwp.created_at DESC, vrwp.plan_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_budget_stress_snapshots(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("optimization_code", "vcos.optimization_code"),
            ("stress_code", "vbsss.stress_code"),
            ("plan_code", "vrwp.plan_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vbsss.status"),
            ("recommended_action", "vbsss.recommended_action"),
        ],
    )
    multiplier = _param(params, "stress_multiplier")
    if multiplier:
        where, values = _append_where(where, values, "vbsss.stress_multiplier = %s", float(multiplier))
    where, values = _append_date_filter(where, values, params, "vbsss.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vbsss.stress_id, vcos.optimization_code,
            vrwp.plan_code, vbsss.stress_code,
            ss.source_code, dc.dataset_code,
            vbsss.as_of_date, vbsss.stress_multiplier,
            vbsss.status, vbsss.forecast_request_count,
            vbsss.forecast_cost_units,
            vbsss.projected_budget_usage_pct,
            vbsss.projected_daily_request_count,
            vbsss.projected_monthly_request_count,
            vbsss.projected_daily_quota_usage_pct,
            vbsss.projected_monthly_quota_usage_pct,
            vbsss.quota_exhaustion_days,
            vbsss.recommended_action,
            vbsss.blocking_issues, vbsss.required_actions,
            vbsss.error_message, vbsss.created_at,
            vbsss.updated_at
        FROM qmeta.vendor_budget_stress_dataset_snapshot vbsss
        JOIN qmeta.vendor_cost_optimization_snapshot vcos ON vcos.optimization_id = vbsss.optimization_id
        LEFT JOIN qmeta.vendor_route_weight_plan vrwp ON vrwp.plan_id = vbsss.plan_id
        JOIN qmeta.source_system ss ON ss.source_id = vbsss.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vbsss.dataset_id
        {where}
        ORDER BY vbsss.created_at DESC, vbsss.stress_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_tau5_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    if isinstance(rows, dict):
        data_rows = rows.get("route_plans") if resource in {"plans", "route-plans"} else rows.get("stress_snapshots") if resource in {"stress", "budget-stress"} else [rows]
    else:
        data_rows = rows
    data_rows = list(data_rows or [])
    lines = [f"tau5 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_optimization_inputs(
    postgres_dsn: str,
    *,
    as_of_date: date,
    source_code: str,
    primary_source_code: str,
    dataset_codes: list[str],
) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        WITH selected_datasets AS (
            SELECT dc.dataset_id, dc.dataset_code
            FROM qmeta.dataset_catalog dc
            WHERE dc.dataset_code = ANY(%s::text[])
              AND dc.is_active IS TRUE
        ),
        vendor_source AS (
            SELECT source_id, source_code
            FROM qmeta.source_system
            WHERE source_code = %s
        ),
        baseline_source AS (
            SELECT source_id, source_code
            FROM qmeta.source_system
            WHERE source_code = %s
        ),
        latest_contract AS (
            SELECT vcp.*
            FROM qmeta.vendor_contract_profile vcp
            JOIN vendor_source vs ON vs.source_id = vcp.source_id
            ORDER BY
                CASE WHEN vcp.procurement_status = 'active' AND vcp.contract_status = 'active' AND vcp.production_use_allowed IS TRUE THEN 0 ELSE 1 END,
                vcp.updated_at DESC,
                vcp.contract_id DESC
            LIMIT 1
        ),
        latest_stability AS (
            SELECT vpss.*
            FROM qmeta.vendor_primary_stability_snapshot vpss
            JOIN vendor_source vs ON vs.source_id = vpss.source_id
            LEFT JOIN baseline_source bs ON bs.source_id = vpss.primary_source_id
            WHERE (bs.source_code = %s OR vpss.primary_source_id IS NULL)
            ORDER BY vpss.as_of_at DESC, vpss.snapshot_id DESC
            LIMIT 1
        ),
        latest_stability_dataset AS (
            SELECT DISTINCT ON (vpsds.dataset_id)
                vpsds.*
            FROM qmeta.vendor_primary_stability_dataset_snapshot vpsds
            JOIN vendor_source vs ON vs.source_id = vpsds.source_id
            ORDER BY vpsds.dataset_id, vpsds.created_at DESC, vpsds.dataset_snapshot_id DESC
        )
        SELECT
            vs.source_id, vs.source_code,
            bs.source_id AS primary_source_id,
            bs.source_code AS primary_source_code,
            sd.dataset_id, sd.dataset_code,
            lc.contract_id, lc.contract_code,
            lc.procurement_status, lc.contract_status,
            lc.production_use_allowed AS contract_production_use_allowed,
            lc.billing_model, lc.billing_currency,
            lc.monthly_fee, lc.unit_cost,
            lc.daily_quota AS contract_daily_quota,
            lc.monthly_quota AS contract_monthly_quota,
            vcde.entitlement_id, vcde.entitlement_code,
            vcde.entitlement_status,
            vcde.allowed_role,
            COALESCE(vcde.production_use_allowed, FALSE) AS production_use_allowed,
            vcde.daily_quota AS entitlement_daily_quota,
            vcde.schema_status,
            current_priority.priority_id AS current_priority_id,
            current_priority.source_code AS current_primary_source_code,
            current_priority.priority AS current_priority,
            backup_priority.source_id AS backup_source_id,
            backup_priority.source_code AS backup_source_code,
            ls.snapshot_id AS stability_snapshot_id,
            ls.snapshot_code AS stability_snapshot_code,
            ls.status AS stability_status,
            COALESCE(lsd.stability_score, ls.stability_score, 0) AS stability_score
        FROM selected_datasets sd
        CROSS JOIN vendor_source vs
        LEFT JOIN baseline_source bs ON TRUE
        LEFT JOIN latest_contract lc ON TRUE
        LEFT JOIN qmeta.vendor_contract_dataset_entitlement vcde
            ON vcde.source_id = vs.source_id
           AND vcde.dataset_id = sd.dataset_id
           AND vcde.status = 'active'
        LEFT JOIN latest_stability ls ON TRUE
        LEFT JOIN latest_stability_dataset lsd ON lsd.dataset_id = sd.dataset_id
        LEFT JOIN LATERAL (
            SELECT sp.priority_id, ssp.source_code, sp.priority
            FROM qmeta.source_priority sp
            JOIN qmeta.source_system ssp ON ssp.source_id = sp.source_id
            WHERE sp.dataset_id = sd.dataset_id
              AND sp.effective_date <= %s
              AND (sp.end_date IS NULL OR sp.end_date >= %s)
            ORDER BY sp.priority ASC, sp.effective_date DESC, sp.priority_id DESC
            LIMIT 1
        ) current_priority ON TRUE
        LEFT JOIN LATERAL (
            SELECT ssp.source_id, ssp.source_code, sp.priority
            FROM qmeta.source_priority sp
            JOIN qmeta.source_system ssp ON ssp.source_id = sp.source_id
            WHERE sp.dataset_id = sd.dataset_id
              AND sp.effective_date <= %s
              AND (sp.end_date IS NULL OR sp.end_date >= %s)
              AND sp.priority > 0
            ORDER BY sp.priority ASC, sp.effective_date DESC, sp.priority_id DESC
            LIMIT 1
        ) backup_priority ON TRUE
        ORDER BY vs.source_code, sd.dataset_code
        """,
        [dataset_codes, source_code, primary_source_code, primary_source_code, as_of_date, as_of_date, as_of_date, as_of_date],
    )


def _load_dataset_api_metrics(postgres_dsn: str, *, lookback_hours: int, dataset_codes: list[str]) -> dict[str, dict[str, Any]]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        WITH scoped AS (
            SELECT
                COALESCE(
                    NULLIF(request_summary->>'dataset_code', ''),
                    NULLIF(request_summary->>'dataset', ''),
                    NULLIF(request_summary #>> '{query,dataset_code,0}', ''),
                    NULLIF(request_summary #>> '{query,dataset,0}', '')
                ) AS dataset_code,
                row_count,
                cost_units
            FROM qmeta.api_request_audit
            WHERE started_at >= now() - make_interval(hours => %s)
        )
        SELECT
            dataset_code,
            COUNT(*) AS api_request_count,
            COALESCE(SUM(row_count), 0) AS row_count,
            COALESCE(SUM(cost_units), 0) AS cost_units
        FROM scoped
        WHERE dataset_code = ANY(%s::text[])
        GROUP BY dataset_code
        """,
        [lookback_hours, dataset_codes],
    )
    return {str(row["dataset_code"]): row for row in rows}


def _insert_optimization_snapshot(postgres_dsn: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_cost_optimization_snapshot (
                    optimization_code, source_id, primary_source_id,
                    stability_snapshot_id, as_of_date, requested_by,
                    trigger_mode, environment, optimization_scope,
                    status, optimization_role, lookback_hours,
                    forecast_window_days, monthly_budget_amount,
                    max_budget_usage_pct, max_daily_quota_usage_pct,
                    max_monthly_quota_usage_pct, min_stability_score,
                    cost_safety_margin_pct, default_unit_cost,
                    stress_multipliers, dataset_count,
                    optimized_dataset_count, watch_dataset_count,
                    over_budget_dataset_count, quota_risk_dataset_count,
                    blocked_dataset_count, no_primary_dataset_count,
                    current_request_count, forecast_request_count,
                    forecast_row_count, current_cost_units,
                    forecast_cost_units, monthly_fee,
                    projected_monthly_cost, projected_budget_usage_pct,
                    daily_quota, monthly_quota,
                    projected_daily_request_count,
                    projected_monthly_request_count,
                    projected_daily_quota_usage_pct,
                    projected_monthly_quota_usage_pct,
                    quota_exhaustion_days,
                    recommended_primary_weight_pct,
                    recommended_backup_weight_pct,
                    recommended_free_source_weight_pct,
                    optimization_score, blocking_issues,
                    required_actions, request_payload,
                    response_payload, evidence, details,
                    error_message, started_at, finished_at,
                    duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s::jsonb, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s, %s,
                    %s, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    snapshot["optimization_code"],
                    snapshot["source_id"],
                    snapshot.get("primary_source_id"),
                    snapshot.get("stability_snapshot_id"),
                    snapshot["as_of_date"],
                    snapshot["requested_by"],
                    snapshot["trigger_mode"],
                    snapshot["environment"],
                    snapshot["optimization_scope"],
                    snapshot["status"],
                    snapshot["optimization_role"],
                    snapshot["lookback_hours"],
                    snapshot["forecast_window_days"],
                    snapshot["monthly_budget_amount"],
                    snapshot["max_budget_usage_pct"],
                    snapshot["max_daily_quota_usage_pct"],
                    snapshot["max_monthly_quota_usage_pct"],
                    snapshot["min_stability_score"],
                    snapshot["cost_safety_margin_pct"],
                    snapshot["default_unit_cost"],
                    _json(snapshot["stress_multipliers"]),
                    snapshot["dataset_count"],
                    snapshot["optimized_dataset_count"],
                    snapshot["watch_dataset_count"],
                    snapshot["over_budget_dataset_count"],
                    snapshot["quota_risk_dataset_count"],
                    snapshot["blocked_dataset_count"],
                    snapshot["no_primary_dataset_count"],
                    snapshot["current_request_count"],
                    snapshot["forecast_request_count"],
                    snapshot["forecast_row_count"],
                    snapshot["current_cost_units"],
                    snapshot["forecast_cost_units"],
                    snapshot["monthly_fee"],
                    snapshot["projected_monthly_cost"],
                    snapshot["projected_budget_usage_pct"],
                    snapshot["daily_quota"],
                    snapshot["monthly_quota"],
                    snapshot["projected_daily_request_count"],
                    snapshot["projected_monthly_request_count"],
                    snapshot["projected_daily_quota_usage_pct"],
                    snapshot["projected_monthly_quota_usage_pct"],
                    snapshot["quota_exhaustion_days"],
                    snapshot["recommended_primary_weight_pct"],
                    snapshot["recommended_backup_weight_pct"],
                    snapshot["recommended_free_source_weight_pct"],
                    snapshot["optimization_score"],
                    snapshot["blocking_issues"],
                    snapshot["required_actions"],
                    _json(snapshot["request_payload"]),
                    _json(snapshot["response_payload"]),
                    _json(snapshot["evidence"]),
                    _json(snapshot["details"]),
                    snapshot.get("error_message"),
                    snapshot["started_at"],
                    snapshot["finished_at"],
                    snapshot["duration_ms"],
                ),
            )
            stored = normalize_rows([dict(cursor.fetchone())])[0]
            stored["source_code"] = snapshot["source_code"]
            stored["primary_source_code"] = snapshot.get("primary_source_code")
            stored["stability_snapshot_code"] = snapshot.get("stability_snapshot_code")
            return stored


def _insert_route_weight_plans(postgres_dsn: str, snapshot: dict[str, Any], plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for plan in plans:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_route_weight_plan (
                        plan_code, optimization_id, source_id,
                        dataset_id, primary_source_id, backup_source_id,
                        current_priority_id, stability_snapshot_id,
                        as_of_date, status, plan_role,
                        current_primary_source_code, current_priority,
                        is_primary_route, stability_status,
                        stability_score, contract_status,
                        entitlement_status, production_use_allowed,
                        billing_model, billing_currency, unit_cost,
                        monthly_fee_allocated, current_request_count,
                        forecast_request_count, forecast_row_count,
                        current_cost_units, forecast_cost_units,
                        allocated_budget_amount, projected_budget_usage_pct,
                        daily_quota, monthly_quota,
                        projected_daily_request_count,
                        projected_monthly_request_count,
                        projected_daily_quota_usage_pct,
                        projected_monthly_quota_usage_pct,
                        quota_exhaustion_days,
                        recommended_primary_weight_pct,
                        recommended_backup_weight_pct,
                        recommended_free_source_weight_pct,
                        routing_change_allowed, optimization_score,
                        blocking_issues, required_actions,
                        evidence, error_message, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s, %s,
                        %s, %s,
                        %s::jsonb, %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        plan["plan_code"],
                        snapshot["optimization_id"],
                        plan["source_id"],
                        plan["dataset_id"],
                        plan.get("primary_source_id"),
                        plan.get("backup_source_id"),
                        plan.get("current_priority_id"),
                        plan.get("stability_snapshot_id"),
                        plan["as_of_date"],
                        plan["status"],
                        plan["plan_role"],
                        plan.get("current_primary_source_code"),
                        plan.get("current_priority"),
                        plan["is_primary_route"],
                        plan.get("stability_status"),
                        plan["stability_score"],
                        plan.get("contract_status"),
                        plan.get("entitlement_status"),
                        plan["production_use_allowed"],
                        plan.get("billing_model"),
                        plan.get("billing_currency"),
                        plan["unit_cost"],
                        plan["monthly_fee_allocated"],
                        plan["current_request_count"],
                        plan["forecast_request_count"],
                        plan["forecast_row_count"],
                        plan["current_cost_units"],
                        plan["forecast_cost_units"],
                        plan["allocated_budget_amount"],
                        plan["projected_budget_usage_pct"],
                        plan["daily_quota"],
                        plan["monthly_quota"],
                        plan["projected_daily_request_count"],
                        plan["projected_monthly_request_count"],
                        plan["projected_daily_quota_usage_pct"],
                        plan["projected_monthly_quota_usage_pct"],
                        plan.get("quota_exhaustion_days"),
                        plan["recommended_primary_weight_pct"],
                        plan["recommended_backup_weight_pct"],
                        plan["recommended_free_source_weight_pct"],
                        plan["routing_change_allowed"],
                        plan["optimization_score"],
                        plan["blocking_issues"],
                        plan["required_actions"],
                        _json(plan["evidence"]),
                        plan.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row["optimization_code"] = snapshot["optimization_code"]
                row["source_code"] = plan.get("source_code")
                row["dataset_code"] = plan.get("dataset_code")
                row["primary_source_code"] = plan.get("primary_source_code")
                row["backup_source_code"] = plan.get("backup_source_code")
                inserted.append(row)
    return inserted


def _insert_budget_stress_snapshots(postgres_dsn: str, snapshot: dict[str, Any], plans: list[dict[str, Any]], stress_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan_id_by_code = {str(plan.get("plan_code")): plan.get("plan_id") for plan in plans}
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for stress in stress_rows:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_budget_stress_dataset_snapshot (
                        stress_code, optimization_id, plan_id,
                        source_id, dataset_id, as_of_date,
                        stress_multiplier, status,
                        forecast_request_count, forecast_cost_units,
                        projected_budget_usage_pct,
                        projected_daily_request_count,
                        projected_monthly_request_count,
                        projected_daily_quota_usage_pct,
                        projected_monthly_quota_usage_pct,
                        quota_exhaustion_days,
                        recommended_action, blocking_issues,
                        required_actions, evidence,
                        error_message, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s, %s,
                        %s, %s::jsonb,
                        %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        stress["stress_code"],
                        snapshot["optimization_id"],
                        plan_id_by_code.get(str(stress.get("plan_code"))),
                        stress["source_id"],
                        stress["dataset_id"],
                        stress["as_of_date"],
                        stress["stress_multiplier"],
                        stress["status"],
                        stress["forecast_request_count"],
                        stress["forecast_cost_units"],
                        stress["projected_budget_usage_pct"],
                        stress["projected_daily_request_count"],
                        stress["projected_monthly_request_count"],
                        stress["projected_daily_quota_usage_pct"],
                        stress["projected_monthly_quota_usage_pct"],
                        stress.get("quota_exhaustion_days"),
                        stress["recommended_action"],
                        stress["blocking_issues"],
                        stress["required_actions"],
                        _json(stress["evidence"]),
                        stress.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row["optimization_code"] = snapshot["optimization_code"]
                row["plan_code"] = stress.get("plan_code")
                row["source_code"] = stress.get("source_code")
                row["dataset_code"] = stress.get("dataset_code")
                inserted.append(row)
    return inserted


def _plan_evidence(row: dict[str, Any], metrics: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": {
            "contract_code": row.get("contract_code"),
            "procurement_status": row.get("procurement_status"),
            "contract_status": row.get("contract_status"),
            "billing_model": row.get("billing_model"),
            "billing_currency": row.get("billing_currency"),
            "unit_cost": evaluation.get("unit_cost"),
            "monthly_fee": row.get("monthly_fee"),
            "daily_quota": evaluation.get("daily_quota"),
            "monthly_quota": evaluation.get("monthly_quota"),
        },
        "stability": {
            "snapshot_code": row.get("stability_snapshot_code"),
            "status": row.get("stability_status"),
            "score": evaluation.get("stability_score"),
        },
        "routing": {
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": _int_or_none(row.get("current_priority")),
            "backup_source_code": row.get("backup_source_code"),
            "is_primary_route": evaluation.get("is_primary_route"),
        },
        "api_metrics": metrics,
    }


def _stress_status(
    base_status: str,
    *,
    budget_pct: float,
    daily_quota_pct: float,
    monthly_quota_pct: float,
    max_budget_usage_pct: float,
    max_daily_quota_usage_pct: float,
    max_monthly_quota_usage_pct: float,
) -> str:
    if base_status in {"blocked", "no_primary_promotion"}:
        return base_status
    if budget_pct > 1.0:
        return "over_budget"
    if daily_quota_pct > 1.0 or monthly_quota_pct > 1.0:
        return "quota_risk"
    if budget_pct > max_budget_usage_pct or daily_quota_pct > max_daily_quota_usage_pct or monthly_quota_pct > max_monthly_quota_usage_pct:
        return "watch"
    return "optimized"


def _stress_issues(status: str, *, budget_pct: float, daily_quota_pct: float, monthly_quota_pct: float) -> list[str]:
    issues: list[str] = []
    if status == "over_budget":
        issues.append(f"budget_pressure:{round(budget_pct, 8)}")
    if status == "quota_risk":
        if daily_quota_pct:
            issues.append(f"daily_quota_pressure:{round(daily_quota_pct, 8)}")
        if monthly_quota_pct:
            issues.append(f"monthly_quota_pressure:{round(monthly_quota_pct, 8)}")
    if status == "no_primary_promotion":
        issues.append("sigma5_primary_route_not_active")
    if status == "blocked":
        issues.append("route_plan_blocked")
    return _dedupe(issues)


def _stress_recommended_action(status: str) -> str:
    return {
        "optimized": "keep_mix",
        "watch": "review_before_scale",
        "over_budget": "cap_paid_weight",
        "quota_risk": "increase_quota_or_shift_weight",
        "blocked": "hold_route_change",
        "no_primary_promotion": "wait_primary_promotion",
    }.get(status, "review")


def _aggregate_status(statuses: list[str]) -> str:
    unique = set(statuses)
    if unique and unique <= {"no_primary_promotion"}:
        return "no_primary_promotion"
    for status in ("blocked", "over_budget", "quota_risk", "watch", "no_primary_promotion"):
        if status in unique:
            return status
    if unique <= {"optimized"} and unique:
        return "optimized"
    return "watch"


def _optimization_role(status: str) -> str:
    return {
        "optimized": "primary_mix",
        "watch": "cost_watch",
        "over_budget": "budget_guard",
        "quota_risk": "budget_guard",
        "blocked": "blocked",
        "no_primary_promotion": "watch",
    }.get(status, "cost_watch")


def _recommended_weights(status: str) -> tuple[float, float, float, str]:
    if status == "optimized":
        return 90.0, 10.0, 0.0, "primary"
    if status == "watch":
        return 70.0, 30.0, 0.0, "backup_mix"
    if status == "quota_risk":
        return 60.0, 30.0, 10.0, "backup_mix"
    if status == "over_budget":
        return 40.0, 50.0, 10.0, "backup_mix"
    if status == "blocked":
        return 0.0, 100.0, 0.0, "blocked"
    return 0.0, 100.0, 0.0, "watch"


def _status_score(status: str) -> float:
    return {
        "optimized": 100.0,
        "watch": 70.0,
        "quota_risk": 50.0,
        "over_budget": 35.0,
        "blocked": 0.0,
        "no_primary_promotion": 0.0,
    }.get(status, 0.0)


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


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _report_keys(row: dict[str, Any]) -> list[str]:
    preferred = [
        "optimization_code",
        "plan_code",
        "stress_code",
        "source_code",
        "dataset_code",
        "primary_source_code",
        "backup_source_code",
        "status",
        "optimization_role",
        "plan_role",
        "optimization_scope",
        "dataset_count",
        "optimized_dataset_count",
        "watch_dataset_count",
        "over_budget_dataset_count",
        "quota_risk_dataset_count",
        "blocked_dataset_count",
        "no_primary_dataset_count",
        "recommended_primary_weight_pct",
        "recommended_backup_weight_pct",
        "recommended_free_source_weight_pct",
        "projected_budget_usage_pct",
        "projected_daily_quota_usage_pct",
        "projected_monthly_quota_usage_pct",
        "forecast_request_count",
        "forecast_cost_units",
        "stress_multiplier",
        "recommended_action",
        "optimization_score",
    ]
    return [key for key in preferred if key in row] + [key for key in row.keys() if key not in preferred]


def _optimization_code(source_code: str, optimization_scope: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{optimization_scope}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"tau5-cost-optimization-{source_code}-{optimization_scope}-{status}-{digest}"[:180]


def _plan_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"tau5-route-weight-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _stress_code(source_code: str, dataset_code: str, multiplier: float, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{multiplier}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"tau5-budget-stress-{source_code}-{dataset_code}-{multiplier:g}x-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    optimization_scope: str,
    lookback_hours: int,
    forecast_window_days: int,
    monthly_budget_amount: float,
    max_budget_usage_pct: float,
    max_daily_quota_usage_pct: float,
    max_monthly_quota_usage_pct: float,
    min_stability_score: float,
    cost_safety_margin_pct: float,
    default_unit_cost: float,
    stress_multipliers: tuple[float, ...],
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, once, smoke, api")
    if optimization_scope not in OPTIMIZATION_SCOPES:
        raise QDataValidationError("optimization_scope must be one of: primary_source, all_datasets, full_market")
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    if forecast_window_days <= 0:
        raise QDataValidationError("forecast_window_days must be greater than 0")
    if monthly_budget_amount <= 0:
        raise QDataValidationError("monthly_budget_amount must be greater than 0")
    if max_budget_usage_pct < 0 or max_daily_quota_usage_pct < 0 or max_monthly_quota_usage_pct < 0:
        raise QDataValidationError("usage thresholds must be greater than or equal to 0")
    if not 0 <= min_stability_score <= 100:
        raise QDataValidationError("min_stability_score must be between 0 and 100")
    if not 0 <= cost_safety_margin_pct <= 1:
        raise QDataValidationError("cost_safety_margin_pct must be between 0 and 1")
    if default_unit_cost < 0:
        raise QDataValidationError("default_unit_cost must be greater than or equal to 0")
    if not stress_multipliers:
        raise QDataValidationError("stress_multipliers must not be empty")


def _normalize_stress_multipliers(values: Iterable[float] | None) -> tuple[float, ...]:
    raw_values = values if values is not None else DEFAULT_STRESS_MULTIPLIERS
    normalized: list[float] = []
    for value in raw_values:
        parsed = float(value)
        if parsed <= 0:
            raise QDataValidationError("stress_multipliers must be greater than 0")
        if parsed not in normalized:
            normalized.append(parsed)
    return tuple(normalized)


def _normalize_optional_codes(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = _dedupe(str(value).strip() for value in values if str(value).strip())
    return normalized or None


def _as_of_date(value: str | date | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        return parse_date(value, "as_of_date")
    return datetime.now(timezone.utc).date()


def _first_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _average(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(_float_or_zero(row.get(key)) for row in rows) / len(rows), 4)


def _min_non_null(values: Iterable[Any]) -> float | None:
    parsed = [_float_or_zero(value) for value in values if value is not None]
    return round(min(parsed), 4) if parsed else None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _int_or_zero(value: Any) -> int:
    parsed = _int_or_none(value)
    return 0 if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return 0.0 if parsed is None else parsed


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _rate_float(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 8)


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required")
    return postgres_dsn


def _connect_required(postgres_dsn: str | None):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Tau-5 vendor cost optimizer") from exc
    return psycopg.connect(_require_dsn(postgres_dsn), row_factory=dict_row)
