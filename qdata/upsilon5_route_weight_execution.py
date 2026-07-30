from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omicron5_vendor_contract import DEFAULT_VENDOR_DATASETS, DEFAULT_VENDOR_SOURCE_CODES
from qdata.tau5_vendor_cost_optimization import (
    _append_date_filter,
    _as_of_date,
    _average,
    _connect_required,
    _dedupe,
    _duration_ms,
    _fetch_rows,
    _float_or_zero,
    _int_or_none,
    _json,
    _normalize_optional_codes,
    _param,
    _require_dsn,
    _where_equal,
)


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
EXECUTION_SCOPES = {"primary_source", "all_datasets", "full_market"}
EXECUTION_MODES = {"review_only", "dry_run", "apply"}
APPROVAL_POLICIES = {"manual_required", "auto_if_optimized"}
APPROVAL_STATUSES = {"not_required", "pending", "approved", "rejected", "blocked"}
ROLLOUT_POLICIES = {"review_only", "canary", "gradual", "full"}
EXECUTION_STATUSES = {
    "pending_approval",
    "approved",
    "staged",
    "applied",
    "rollback_recommended",
    "rolled_back",
    "blocked",
    "no_primary_promotion",
    "review_required",
}
STAGE_STATUSES = {"pending", "ready", "applied", "skipped", "blocked", "rollback_recommended", "rolled_back"}
DEFAULT_ROLLOUT_STAGES = (10.0, 30.0, 60.0, 90.0)


def run_vendor_route_weight_execution(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    source_code: str = DEFAULT_VENDOR_SOURCE_CODES[0],
    primary_source_code: str = "csv",
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "upsilon5",
    trigger_mode: str = "manual",
    environment: str = "local",
    execution_scope: str = "primary_source",
    execution_mode: str = "review_only",
    approval_policy: str = "manual_required",
    approval_status: str = "pending",
    rollout_policy: str = "gradual",
    rollout_stages: Iterable[float] | None = None,
    current_stage_sequence: int = 1,
    max_initial_primary_weight_pct: float = 10.0,
    allow_over_budget: bool = False,
    allow_quota_risk: bool = False,
    rollback_requested: bool = False,
    write_db: bool = True,
) -> dict[str, Any]:
    stages = _normalize_rollout_stages(rollout_stages)
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        execution_scope=execution_scope,
        execution_mode=execution_mode,
        approval_policy=approval_policy,
        approval_status=approval_status,
        rollout_policy=rollout_policy,
        rollout_stages=stages,
        current_stage_sequence=current_stage_sequence,
        max_initial_primary_weight_pct=max_initial_primary_weight_pct,
    )
    snapshot_date = _as_of_date(as_of_date)
    datasets = _normalize_optional_codes(dataset_codes) or list(DEFAULT_VENDOR_DATASETS)
    dsn = _require_dsn(postgres_dsn)
    started_at = datetime.now(timezone.utc)
    rows = _load_execution_inputs(
        dsn,
        source_code=source_code,
        primary_source_code=primary_source_code,
        execution_scope=execution_scope,
        dataset_codes=datasets,
    )
    if not rows:
        rows = _fallback_dataset_rows(dsn, source_code=source_code, primary_source_code=primary_source_code, dataset_codes=datasets)
    dataset_results = build_route_weight_execution_datasets(
        rows,
        as_of_date=snapshot_date,
        execution_mode=execution_mode,
        approval_policy=approval_policy,
        approval_status=approval_status,
        rollout_policy=rollout_policy,
        rollout_stages=stages,
        current_stage_sequence=current_stage_sequence,
        max_initial_primary_weight_pct=max_initial_primary_weight_pct,
        allow_over_budget=allow_over_budget,
        allow_quota_risk=allow_quota_risk,
        rollback_requested=rollback_requested,
    )
    stage_rows = build_route_weight_rollout_stages(
        dataset_results,
        as_of_date=snapshot_date,
        rollout_stages=stages,
        current_stage_sequence=current_stage_sequence,
        execution_mode=execution_mode,
    )
    finished_at = datetime.now(timezone.utc)
    run = build_route_weight_execution_run(
        dataset_results,
        stage_rows,
        source_code=source_code,
        primary_source_code=primary_source_code,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        execution_scope=execution_scope,
        execution_mode=execution_mode,
        approval_policy=approval_policy,
        approval_status=approval_status,
        rollout_policy=rollout_policy,
        rollout_stages=stages,
        current_stage_sequence=current_stage_sequence,
        max_initial_primary_weight_pct=max_initial_primary_weight_pct,
        allow_over_budget=allow_over_budget,
        allow_quota_risk=allow_quota_risk,
        rollback_requested=rollback_requested,
        optimization_id=_first_value(dataset_results, "optimization_id"),
        stability_snapshot_id=_first_value(dataset_results, "stability_snapshot_id"),
        started_at=started_at,
        finished_at=finished_at,
    )
    if not write_db:
        run["datasets"] = normalize_rows(dataset_results)
        run["stages"] = normalize_rows(stage_rows)
        run["policies"] = []
        return normalize_rows([run])[0]
    stored = _insert_execution_run(dsn, run)
    stored_datasets = _insert_execution_datasets(dsn, stored, dataset_results)
    stored_stages = _insert_rollout_stages(dsn, stored, stored_datasets, stage_rows)
    stored_policies = _insert_source_route_weight_policies(dsn, stored, stored_datasets, stored_stages) if execution_mode == "apply" else []
    stored["datasets"] = stored_datasets
    stored["stages"] = stored_stages
    stored["policies"] = stored_policies
    return stored


def build_route_weight_execution_datasets(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    execution_mode: str = "review_only",
    approval_policy: str = "manual_required",
    approval_status: str = "pending",
    rollout_policy: str = "gradual",
    rollout_stages: Iterable[float] | None = None,
    current_stage_sequence: int = 1,
    max_initial_primary_weight_pct: float = 10.0,
    allow_over_budget: bool = False,
    allow_quota_risk: bool = False,
    rollback_requested: bool = False,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    stages = _normalize_rollout_stages(rollout_stages)
    results: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        evaluation = evaluate_route_weight_execution_dataset(
            row,
            execution_mode=execution_mode,
            approval_policy=approval_policy,
            approval_status=approval_status,
            rollout_policy=rollout_policy,
            rollout_stages=stages,
            current_stage_sequence=current_stage_sequence,
            max_initial_primary_weight_pct=max_initial_primary_weight_pct,
            allow_over_budget=allow_over_budget,
            allow_quota_risk=allow_quota_risk,
            rollback_requested=rollback_requested,
        )
        status = evaluation["status"]
        result = {
            "execution_dataset_code": _dataset_code(str(row.get("source_code") or "unknown"), str(row.get("dataset_code") or "unknown"), status),
            "optimization_id": row.get("optimization_id"),
            "optimization_code": row.get("optimization_code"),
            "plan_id": row.get("plan_id"),
            "plan_code": row.get("plan_code"),
            "source_id": row["source_id"],
            "source_code": row.get("source_code"),
            "dataset_id": row["dataset_id"],
            "dataset_code": row.get("dataset_code"),
            "primary_source_id": row.get("primary_source_id"),
            "primary_source_code": row.get("primary_source_code"),
            "backup_source_id": row.get("backup_source_id"),
            "backup_source_code": row.get("backup_source_code"),
            "current_priority_id": row.get("current_priority_id"),
            "stability_snapshot_id": row.get("stability_snapshot_id"),
            "stability_snapshot_code": row.get("stability_snapshot_code"),
            "as_of_date": snapshot_date.isoformat(),
            "status": status,
            "approval_status": evaluation["approval_status"],
            "rollout_policy": rollout_policy,
            "current_stage_sequence": evaluation["current_stage_sequence"],
            "stage_count": evaluation["stage_count"],
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": _int_or_none(row.get("current_priority")),
            "is_primary_route": bool(row.get("is_primary_route")),
            "tau5_status": row.get("tau5_status") or row.get("status"),
            "tau5_plan_role": row.get("tau5_plan_role") or row.get("plan_role"),
            "stability_status": row.get("stability_status"),
            "stability_score": _float_or_zero(row.get("stability_score")),
            "contract_status": row.get("contract_status"),
            "entitlement_status": row.get("entitlement_status"),
            "target_primary_weight_pct": evaluation["target_primary_weight_pct"],
            "target_backup_weight_pct": evaluation["target_backup_weight_pct"],
            "target_free_source_weight_pct": evaluation["target_free_source_weight_pct"],
            "applied_primary_weight_pct": evaluation["applied_primary_weight_pct"],
            "applied_backup_weight_pct": evaluation["applied_backup_weight_pct"],
            "applied_free_source_weight_pct": evaluation["applied_free_source_weight_pct"],
            "projected_budget_usage_pct": _float_or_zero(row.get("projected_budget_usage_pct")),
            "projected_monthly_quota_usage_pct": _float_or_zero(row.get("projected_monthly_quota_usage_pct")),
            "routing_change_allowed": evaluation["routing_change_allowed"],
            "routing_change_applied": evaluation["routing_change_applied"],
            "rollback_allowed": evaluation["rollback_allowed"],
            "rollback_applied": evaluation["rollback_applied"],
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": build_route_weight_execution_required_actions(evaluation["blocking_issues"], status),
            "evidence": _dataset_evidence(row, evaluation, stages),
            "error_message": "; ".join(evaluation["blocking_issues"]) if status in {"blocked", "rollback_recommended", "no_primary_promotion", "review_required"} and evaluation["blocking_issues"] else None,
        }
        results.append(result)
    return results


def evaluate_route_weight_execution_dataset(
    row: dict[str, Any],
    *,
    execution_mode: str = "review_only",
    approval_policy: str = "manual_required",
    approval_status: str = "pending",
    rollout_policy: str = "gradual",
    rollout_stages: Iterable[float] | None = None,
    current_stage_sequence: int = 1,
    max_initial_primary_weight_pct: float = 10.0,
    allow_over_budget: bool = False,
    allow_quota_risk: bool = False,
    rollback_requested: bool = False,
) -> dict[str, Any]:
    stages = _normalize_rollout_stages(rollout_stages)
    issues: list[str] = []
    warnings: list[str] = []
    tau_status = str(row.get("tau5_status") or row.get("status") or "missing")
    target_primary = _float_or_zero(row.get("recommended_primary_weight_pct"))
    target_backup = _float_or_zero(row.get("recommended_backup_weight_pct"))
    target_free = _float_or_zero(row.get("recommended_free_source_weight_pct"))
    is_primary_route = bool(row.get("is_primary_route"))
    if not row.get("plan_id"):
        issues.append("tau5_route_weight_plan_missing")
    if tau_status == "no_primary_promotion" or not is_primary_route or target_primary <= 0:
        issues.append(f"tau5_primary_weight_not_executable:{tau_status}/{row.get('current_primary_source_code') or 'missing'}")
    elif tau_status == "blocked":
        issues.append("tau5_route_weight_blocked")
    elif tau_status == "over_budget" and not allow_over_budget:
        warnings.append("tau5_over_budget_requires_manual_budget_approval")
    elif tau_status == "quota_risk" and not allow_quota_risk:
        warnings.append("tau5_quota_risk_requires_manual_quota_approval")
    elif tau_status == "watch":
        warnings.append("tau5_watch_requires_manual_review")

    if approval_status == "rejected":
        issues.append("approval_rejected")
    elif approval_status == "blocked":
        issues.append("approval_blocked")

    if rollback_requested:
        if approval_status not in {"approved", "not_required"}:
            status = "rollback_recommended"
            applied_primary, applied_backup, applied_free = 0.0, 100.0, 0.0
            approval = approval_status
            all_issues = _dedupe(issues + warnings + ["rollback_requested_requires_approved_apply"])
            return _execution_eval(
                status,
                approval,
                target_primary,
                target_backup,
                target_free,
                applied_primary,
                applied_backup,
                applied_free,
                current_stage_sequence=0,
                stage_count=0,
                routing_allowed=False,
                routing_applied=False,
                rollback_allowed=True,
                rollback_applied=False,
                issues=all_issues,
            )
        status = "rolled_back" if execution_mode == "apply" else "rollback_recommended"
        return _execution_eval(
            status,
            approval_status,
            target_primary,
            target_backup,
            target_free,
            0.0,
            100.0,
            0.0,
            current_stage_sequence=0,
            stage_count=0,
            routing_allowed=False,
            routing_applied=False,
            rollback_allowed=True,
            rollback_applied=execution_mode == "apply",
            issues=_dedupe(issues + warnings + ["rollback_requested"]),
        )

    if issues:
        status = "no_primary_promotion" if any(issue.startswith("tau5_primary_weight_not_executable") for issue in issues) else "blocked"
        approval = "blocked" if approval_status != "rejected" else "rejected"
        return _execution_eval(
            status,
            approval,
            target_primary,
            target_backup,
            target_free,
            0.0,
            100.0,
            0.0,
            current_stage_sequence=0,
            stage_count=0,
            routing_allowed=False,
            routing_applied=False,
            rollback_allowed=False,
            rollback_applied=False,
            issues=_dedupe(issues + warnings),
        )

    effective_approval = approval_status
    if approval_policy == "auto_if_optimized" and tau_status == "optimized" and not warnings and approval_status == "pending":
        effective_approval = "not_required"
    if warnings and effective_approval not in {"approved", "not_required"}:
        return _execution_eval(
            "review_required",
            effective_approval,
            target_primary,
            target_backup,
            target_free,
            0.0,
            100.0,
            0.0,
            current_stage_sequence=0,
            stage_count=0,
            routing_allowed=False,
            routing_applied=False,
            rollback_allowed=False,
            rollback_applied=False,
            issues=_dedupe(warnings),
        )
    if effective_approval == "pending":
        return _execution_eval(
            "pending_approval",
            effective_approval,
            target_primary,
            target_backup,
            target_free,
            0.0,
            100.0,
            0.0,
            current_stage_sequence=0,
            stage_count=len(_target_stages(target_primary, stages, rollout_policy)),
            routing_allowed=False,
            routing_applied=False,
            rollback_allowed=False,
            rollback_applied=False,
            issues=_dedupe(warnings + ["manual_approval_pending"]),
        )

    target_stage_values = _target_stages(target_primary, stages, rollout_policy)
    stage_count = len(target_stage_values)
    stage_sequence = min(max(current_stage_sequence, 1), max(stage_count, 1))
    staged_primary = _stage_primary_weight(target_primary, target_stage_values, stage_sequence, max_initial_primary_weight_pct, rollout_policy)
    staged_free = target_free if staged_primary >= target_primary else min(target_free, max(0.0, 100.0 - staged_primary))
    staged_backup = max(0.0, 100.0 - staged_primary - staged_free)
    if execution_mode == "review_only":
        status = "approved"
        applied_primary, applied_backup, applied_free = 0.0, 100.0, 0.0
        routing_applied = False
    elif execution_mode == "dry_run":
        status = "staged"
        applied_primary, applied_backup, applied_free = staged_primary, staged_backup, staged_free
        routing_applied = False
    else:
        status = "applied" if stage_sequence >= stage_count else "staged"
        applied_primary, applied_backup, applied_free = staged_primary, staged_backup, staged_free
        routing_applied = True
    return _execution_eval(
        status,
        effective_approval,
        target_primary,
        target_backup,
        target_free,
        applied_primary,
        applied_backup,
        applied_free,
        current_stage_sequence=stage_sequence,
        stage_count=stage_count,
        routing_allowed=True,
        routing_applied=routing_applied,
        rollback_allowed=routing_applied,
        rollback_applied=False,
        issues=_dedupe(warnings),
    )


def build_route_weight_rollout_stages(
    results: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    rollout_stages: Iterable[float] | None = None,
    current_stage_sequence: int = 1,
    execution_mode: str = "review_only",
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    stages = _normalize_rollout_stages(rollout_stages)
    rows: list[dict[str, Any]] = []
    for result in results:
        target_values = _target_stages(_float_or_zero(result.get("target_primary_weight_pct")), stages, str(result.get("rollout_policy") or "gradual"))
        if not target_values:
            target_values = [0.0]
        for index, target_primary in enumerate(target_values, start=1):
            status = _stage_status(result, index, current_stage_sequence, execution_mode)
            target_free = _float_or_zero(result.get("target_free_source_weight_pct")) if target_primary >= _float_or_zero(result.get("target_primary_weight_pct")) else 0.0
            target_backup = max(0.0, 100.0 - target_primary - target_free)
            issues = list(result.get("blocking_issues") or [])
            rows.append(
                {
                    "stage_code": _stage_code(str(result.get("source_code") or "unknown"), str(result.get("dataset_code") or "unknown"), index, status),
                    "execution_dataset_code": result.get("execution_dataset_code"),
                    "source_id": result["source_id"],
                    "source_code": result.get("source_code"),
                    "dataset_id": result["dataset_id"],
                    "dataset_code": result.get("dataset_code"),
                    "as_of_date": snapshot_date.isoformat(),
                    "stage_sequence": index,
                    "stage_label": f"{target_primary:g}pct",
                    "status": status,
                    "approval_required": result.get("approval_status") == "pending",
                    "approval_status": result.get("approval_status"),
                    "gate_status": "passed" if status in {"ready", "applied"} else "blocked" if status in {"blocked", "rollback_recommended", "rolled_back"} else "pending",
                    "target_primary_weight_pct": round(target_primary, 4),
                    "target_backup_weight_pct": round(target_backup, 4),
                    "target_free_source_weight_pct": round(target_free, 4),
                    "routing_change_allowed": bool(result.get("routing_change_allowed")) and status in {"ready", "applied"},
                    "routing_change_applied": bool(result.get("routing_change_applied")) and status == "applied",
                    "blocking_issues": issues,
                    "required_actions": build_route_weight_execution_required_actions(issues, str(result.get("status") or "blocked")),
                    "evidence": {"execution_dataset_code": result.get("execution_dataset_code"), "base_status": result.get("status")},
                    "error_message": "; ".join(issues) if status in {"blocked", "rollback_recommended", "rolled_back"} and issues else None,
                }
            )
    return rows


def build_route_weight_execution_run(
    results: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    *,
    source_code: str,
    primary_source_code: str,
    as_of_date: str | date | None = None,
    requested_by: str = "upsilon5",
    trigger_mode: str = "manual",
    environment: str = "local",
    execution_scope: str = "primary_source",
    execution_mode: str = "review_only",
    approval_policy: str = "manual_required",
    approval_status: str = "pending",
    rollout_policy: str = "gradual",
    rollout_stages: Iterable[float] | None = None,
    current_stage_sequence: int = 1,
    max_initial_primary_weight_pct: float = 10.0,
    allow_over_budget: bool = False,
    allow_quota_risk: bool = False,
    rollback_requested: bool = False,
    optimization_id: int | None = None,
    stability_snapshot_id: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot_date = _as_of_date(as_of_date)
    statuses = [str(result.get("status") or "blocked") for result in results]
    status = _aggregate_status(statuses)
    blocking_issues = _dedupe(issue for result in results for issue in result.get("blocking_issues") or [])
    started = started_at or datetime.now(timezone.utc)
    finished = finished_at or datetime.now(timezone.utc)
    return {
        "execution_code": _execution_code(source_code, execution_scope, status),
        "optimization_id": optimization_id,
        "optimization_code": _first_value(results, "optimization_code"),
        "source_id": _first_value(results, "source_id"),
        "source_code": source_code,
        "primary_source_id": _first_value(results, "primary_source_id"),
        "primary_source_code": primary_source_code,
        "stability_snapshot_id": stability_snapshot_id,
        "stability_snapshot_code": _first_value(results, "stability_snapshot_code"),
        "as_of_date": snapshot_date.isoformat(),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "execution_scope": execution_scope,
        "execution_mode": execution_mode,
        "approval_policy": approval_policy,
        "approval_status": _aggregate_approval_status(results, approval_status),
        "rollout_policy": rollout_policy,
        "status": status,
        "stage_count": max([_int_or_none(result.get("stage_count")) or 0 for result in results] or [0]),
        "current_stage_sequence": max([_int_or_none(result.get("current_stage_sequence")) or 0 for result in results] or [0]),
        "target_primary_weight_pct": _average(results, "target_primary_weight_pct"),
        "target_backup_weight_pct": _average(results, "target_backup_weight_pct"),
        "target_free_source_weight_pct": _average(results, "target_free_source_weight_pct"),
        "applied_primary_weight_pct": _average(results, "applied_primary_weight_pct"),
        "applied_backup_weight_pct": _average(results, "applied_backup_weight_pct"),
        "applied_free_source_weight_pct": _average(results, "applied_free_source_weight_pct"),
        "dataset_count": len(results),
        "pending_approval_dataset_count": statuses.count("pending_approval"),
        "approved_dataset_count": statuses.count("approved"),
        "staged_dataset_count": statuses.count("staged"),
        "applied_dataset_count": statuses.count("applied"),
        "rollback_recommended_count": statuses.count("rollback_recommended"),
        "rolled_back_dataset_count": statuses.count("rolled_back"),
        "blocked_dataset_count": statuses.count("blocked"),
        "no_primary_dataset_count": statuses.count("no_primary_promotion"),
        "routing_change_allowed": bool(results) and all(result.get("routing_change_allowed") for result in results),
        "routing_change_applied": bool(results) and any(result.get("routing_change_applied") for result in results),
        "rollback_allowed": bool(results) and any(result.get("rollback_allowed") for result in results),
        "rollback_applied": bool(results) and any(result.get("rollback_applied") for result in results),
        "blocking_issues": blocking_issues,
        "required_actions": build_route_weight_execution_required_actions(blocking_issues, status),
        "request_payload": {
            "source_code": source_code,
            "primary_source_code": primary_source_code,
            "dataset_codes": [result.get("dataset_code") for result in results],
            "execution_scope": execution_scope,
            "execution_mode": execution_mode,
            "approval_policy": approval_policy,
            "approval_status": approval_status,
            "rollout_policy": rollout_policy,
            "rollout_stages": list(_normalize_rollout_stages(rollout_stages)),
            "current_stage_sequence": current_stage_sequence,
            "max_initial_primary_weight_pct": max_initial_primary_weight_pct,
            "allow_over_budget": allow_over_budget,
            "allow_quota_risk": allow_quota_risk,
            "rollback_requested": rollback_requested,
        },
        "response_payload": {
            "status": status,
            "dataset_count": len(results),
            "routing_change_applied": bool(results) and any(result.get("routing_change_applied") for result in results),
            "applied_primary_weight_pct": _average(results, "applied_primary_weight_pct"),
        },
        "evidence": {
            "optimization_code": _first_value(results, "optimization_code"),
            "stability_snapshot_code": _first_value(results, "stability_snapshot_code"),
            "policy": {"requires_approval_before_apply": True, "writes_source_route_weight_policy_only": True},
        },
        "details": {
            "status_distribution": {name: statuses.count(name) for name in sorted(EXECUTION_STATUSES)},
            "stage_count": len(stages),
        },
        "error_message": "; ".join(blocking_issues) if status in {"blocked", "rollback_recommended", "no_primary_promotion", "review_required"} and blocking_issues else None,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": _duration_ms(started, finished),
    }


def build_route_weight_execution_required_actions(issues: list[str], status: str) -> list[str]:
    text = " ".join(issues)
    actions: list[str] = []
    if "tau5_primary_weight_not_executable" in text or status == "no_primary_promotion":
        actions.append("Wait for applied Pi-5 promotion, healthy Sigma-5 primary route and Tau-5 executable primary weight before rollout.")
    if "manual_approval_pending" in text or status == "pending_approval":
        actions.append("Collect explicit approval before applying any route-weight policy.")
    if "tau5_over_budget" in text or status == "review_required":
        actions.append("Review budget/quota risk and record approval before staged route-weight execution.")
    if "approval_rejected" in text or "approval_blocked" in text or status == "blocked":
        actions.append("Do not apply route weights until approval and guardrail blockers are resolved.")
    if "rollback_requested" in text or status in {"rollback_recommended", "rolled_back"}:
        actions.append("Keep rollback monitoring active and verify source_route_weight_policy is back to a safe backup-heavy mix.")
    if status == "approved":
        actions.append("Use dry_run or apply mode to advance the approved route-weight rollout.")
    if status == "staged":
        actions.append("Monitor Sigma-5, Rho-5 and Tau-5 before advancing to the next rollout stage.")
    if status == "applied":
        actions.append("Keep Upsilon-5 schedule active and re-check rollback guardrails before further weight increases.")
    return _dedupe(actions)


def list_vendor_route_weight_executions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("execution_code", "vrwer.execution_code"),
            ("optimization_code", "vcos.optimization_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vrwer.status"),
            ("approval_status", "vrwer.approval_status"),
            ("execution_mode", "vrwer.execution_mode"),
            ("execution_scope", "vrwer.execution_scope"),
            ("rollout_policy", "vrwer.rollout_policy"),
            ("requested_by", "vrwer.requested_by"),
            ("trigger_mode", "vrwer.trigger_mode"),
            ("environment", "vrwer.environment"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "vrwer.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "vrwer.as_of_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vrwer.execution_id, vrwer.execution_code,
            vcos.optimization_code, ss.source_code,
            ps.source_code AS primary_source_code,
            vpss.snapshot_code AS stability_snapshot_code,
            vrwer.as_of_at, vrwer.as_of_date,
            vrwer.requested_by, vrwer.trigger_mode,
            vrwer.environment, vrwer.execution_scope,
            vrwer.execution_mode, vrwer.approval_policy,
            vrwer.approval_status, vrwer.rollout_policy,
            vrwer.status, vrwer.stage_count,
            vrwer.current_stage_sequence,
            vrwer.target_primary_weight_pct,
            vrwer.target_backup_weight_pct,
            vrwer.target_free_source_weight_pct,
            vrwer.applied_primary_weight_pct,
            vrwer.applied_backup_weight_pct,
            vrwer.applied_free_source_weight_pct,
            vrwer.dataset_count,
            vrwer.pending_approval_dataset_count,
            vrwer.approved_dataset_count,
            vrwer.staged_dataset_count,
            vrwer.applied_dataset_count,
            vrwer.rollback_recommended_count,
            vrwer.rolled_back_dataset_count,
            vrwer.blocked_dataset_count,
            vrwer.no_primary_dataset_count,
            vrwer.routing_change_allowed,
            vrwer.routing_change_applied,
            vrwer.rollback_allowed,
            vrwer.rollback_applied,
            vrwer.blocking_issues,
            vrwer.required_actions,
            vrwer.error_message,
            vrwer.started_at, vrwer.finished_at,
            vrwer.duration_ms, vrwer.created_at,
            vrwer.updated_at
        FROM qmeta.vendor_route_weight_execution_run vrwer
        JOIN qmeta.source_system ss ON ss.source_id = vrwer.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vrwer.primary_source_id
        LEFT JOIN qmeta.vendor_cost_optimization_snapshot vcos ON vcos.optimization_id = vrwer.optimization_id
        LEFT JOIN qmeta.vendor_primary_stability_snapshot vpss ON vpss.snapshot_id = vrwer.stability_snapshot_id
        {where}
        ORDER BY vrwer.as_of_at DESC, vrwer.execution_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_route_weight_execution_datasets(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("execution_code", "vrwer.execution_code"),
            ("execution_dataset_code", "vrwed.execution_dataset_code"),
            ("optimization_code", "vcos.optimization_code"),
            ("plan_code", "vrwp.plan_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vrwed.status"),
            ("approval_status", "vrwed.approval_status"),
            ("rollout_policy", "vrwed.rollout_policy"),
            ("current_primary_source_code", "vrwed.current_primary_source_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vrwed.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vrwed.execution_dataset_id, vrwer.execution_code,
            vrwed.execution_dataset_code, vcos.optimization_code,
            vrwp.plan_code, ss.source_code, dc.dataset_code,
            ps.source_code AS primary_source_code,
            bs.source_code AS backup_source_code,
            vrwed.as_of_date, vrwed.status,
            vrwed.approval_status, vrwed.rollout_policy,
            vrwed.current_stage_sequence, vrwed.stage_count,
            vrwed.current_primary_source_code,
            vrwed.current_priority, vrwed.is_primary_route,
            vrwed.tau5_status, vrwed.tau5_plan_role,
            vrwed.stability_status, vrwed.stability_score,
            vrwed.contract_status, vrwed.entitlement_status,
            vrwed.target_primary_weight_pct,
            vrwed.target_backup_weight_pct,
            vrwed.target_free_source_weight_pct,
            vrwed.applied_primary_weight_pct,
            vrwed.applied_backup_weight_pct,
            vrwed.applied_free_source_weight_pct,
            vrwed.projected_budget_usage_pct,
            vrwed.projected_monthly_quota_usage_pct,
            vrwed.routing_change_allowed,
            vrwed.routing_change_applied,
            vrwed.rollback_allowed,
            vrwed.rollback_applied,
            vrwed.blocking_issues, vrwed.required_actions,
            vrwed.error_message, vrwed.created_at,
            vrwed.updated_at
        FROM qmeta.vendor_route_weight_execution_dataset vrwed
        JOIN qmeta.vendor_route_weight_execution_run vrwer ON vrwer.execution_id = vrwed.execution_id
        JOIN qmeta.source_system ss ON ss.source_id = vrwed.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrwed.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vrwed.primary_source_id
        LEFT JOIN qmeta.source_system bs ON bs.source_id = vrwed.backup_source_id
        LEFT JOIN qmeta.vendor_cost_optimization_snapshot vcos ON vcos.optimization_id = vrwed.optimization_id
        LEFT JOIN qmeta.vendor_route_weight_plan vrwp ON vrwp.plan_id = vrwed.plan_id
        {where}
        ORDER BY vrwed.created_at DESC, vrwed.execution_dataset_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_route_weight_rollout_stages(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("execution_code", "vrwer.execution_code"),
            ("execution_dataset_code", "vrwed.execution_dataset_code"),
            ("stage_code", "vrwrs.stage_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vrwrs.status"),
            ("approval_status", "vrwrs.approval_status"),
            ("gate_status", "vrwrs.gate_status"),
        ],
    )
    seq = _param(params, "stage_sequence")
    if seq:
        where, values = _append_where(where, values, "vrwrs.stage_sequence = %s", int(seq))
    where, values = _append_date_filter(where, values, params, "vrwrs.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vrwrs.stage_id, vrwer.execution_code,
            vrwed.execution_dataset_code, vrwrs.stage_code,
            ss.source_code, dc.dataset_code,
            vrwrs.as_of_date, vrwrs.stage_sequence,
            vrwrs.stage_label, vrwrs.status,
            vrwrs.approval_required, vrwrs.approval_status,
            vrwrs.gate_status,
            vrwrs.target_primary_weight_pct,
            vrwrs.target_backup_weight_pct,
            vrwrs.target_free_source_weight_pct,
            vrwrs.routing_change_allowed,
            vrwrs.routing_change_applied,
            vrwrs.blocking_issues,
            vrwrs.required_actions,
            vrwrs.error_message,
            vrwrs.created_at, vrwrs.updated_at
        FROM qmeta.vendor_route_weight_rollout_stage vrwrs
        JOIN qmeta.vendor_route_weight_execution_run vrwer ON vrwer.execution_id = vrwrs.execution_id
        LEFT JOIN qmeta.vendor_route_weight_execution_dataset vrwed ON vrwed.execution_dataset_id = vrwrs.execution_dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = vrwrs.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrwrs.dataset_id
        {where}
        ORDER BY vrwrs.created_at DESC, vrwrs.stage_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_source_route_weight_policies(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("policy_code", "srwp.policy_code"),
            ("execution_code", "vrwer.execution_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("primary_source_code", "ps.source_code"),
            ("backup_source_code", "bs.source_code"),
            ("policy_status", "srwp.policy_status"),
            ("execution_mode", "srwp.execution_mode"),
            ("created_by", "srwp.created_by"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "srwp.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            srwp.policy_id, srwp.policy_code,
            vrwer.execution_code,
            vrwed.execution_dataset_code,
            vrwrs.stage_code,
            ss.source_code, dc.dataset_code,
            ps.source_code AS primary_source_code,
            bs.source_code AS backup_source_code,
            srwp.effective_date, srwp.end_date,
            srwp.policy_status, srwp.execution_mode,
            srwp.primary_weight_pct,
            srwp.backup_weight_pct,
            srwp.free_source_weight_pct,
            srwp.previous_primary_weight_pct,
            srwp.previous_backup_weight_pct,
            srwp.previous_free_source_weight_pct,
            srwp.created_by,
            srwp.created_at, srwp.updated_at
        FROM qmeta.source_route_weight_policy srwp
        LEFT JOIN qmeta.vendor_route_weight_execution_run vrwer ON vrwer.execution_id = srwp.execution_id
        LEFT JOIN qmeta.vendor_route_weight_execution_dataset vrwed ON vrwed.execution_dataset_id = srwp.execution_dataset_id
        LEFT JOIN qmeta.vendor_route_weight_rollout_stage vrwrs ON vrwrs.stage_id = srwp.stage_id
        JOIN qmeta.source_system ss ON ss.source_id = srwp.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srwp.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = srwp.primary_source_id
        LEFT JOIN qmeta.source_system bs ON bs.source_id = srwp.backup_source_id
        {where}
        ORDER BY srwp.created_at DESC, srwp.policy_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_upsilon5_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    if isinstance(rows, dict):
        data_rows = (
            rows.get("datasets")
            if resource in {"datasets", "execution-datasets"}
            else rows.get("stages")
            if resource in {"stages", "rollout-stages"}
            else rows.get("policies")
            if resource in {"policies", "route-policies"}
            else [rows]
        )
    else:
        data_rows = rows
    data_rows = list(data_rows or [])
    lines = [f"upsilon5 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_execution_inputs(
    postgres_dsn: str,
    *,
    source_code: str,
    primary_source_code: str,
    execution_scope: str,
    dataset_codes: list[str],
) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        WITH latest_optimization AS (
            SELECT vcos.*
            FROM qmeta.vendor_cost_optimization_snapshot vcos
            JOIN qmeta.source_system ss ON ss.source_id = vcos.source_id
            LEFT JOIN qmeta.source_system ps ON ps.source_id = vcos.primary_source_id
            WHERE ss.source_code = %s
              AND vcos.optimization_scope = %s
              AND (ps.source_code = %s OR vcos.primary_source_id IS NULL)
            ORDER BY vcos.as_of_at DESC, vcos.optimization_id DESC
            LIMIT 1
        )
        SELECT
            lo.optimization_id, lo.optimization_code,
            lo.stability_snapshot_id,
            vpss.snapshot_code AS stability_snapshot_code,
            vrwp.plan_id, vrwp.plan_code,
            vrwp.source_id, ss.source_code,
            vrwp.dataset_id, dc.dataset_code,
            vrwp.primary_source_id, ps.source_code AS primary_source_code,
            vrwp.backup_source_id, bs.source_code AS backup_source_code,
            vrwp.current_priority_id,
            vrwp.current_primary_source_code,
            vrwp.current_priority,
            vrwp.is_primary_route,
            vrwp.status AS tau5_status,
            vrwp.plan_role AS tau5_plan_role,
            vrwp.stability_status,
            vrwp.stability_score,
            vrwp.contract_status,
            vrwp.entitlement_status,
            vrwp.recommended_primary_weight_pct,
            vrwp.recommended_backup_weight_pct,
            vrwp.recommended_free_source_weight_pct,
            vrwp.projected_budget_usage_pct,
            vrwp.projected_monthly_quota_usage_pct,
            vrwp.routing_change_allowed,
            vrwp.blocking_issues,
            vrwp.required_actions
        FROM latest_optimization lo
        JOIN qmeta.vendor_route_weight_plan vrwp ON vrwp.optimization_id = lo.optimization_id
        JOIN qmeta.source_system ss ON ss.source_id = vrwp.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrwp.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vrwp.primary_source_id
        LEFT JOIN qmeta.source_system bs ON bs.source_id = vrwp.backup_source_id
        LEFT JOIN qmeta.vendor_primary_stability_snapshot vpss ON vpss.snapshot_id = lo.stability_snapshot_id
        WHERE dc.dataset_code = ANY(%s::text[])
        ORDER BY ss.source_code, dc.dataset_code
        """,
        [source_code, execution_scope, primary_source_code, dataset_codes],
    )


def _fallback_dataset_rows(postgres_dsn: str, *, source_code: str, primary_source_code: str, dataset_codes: list[str]) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        WITH selected_datasets AS (
            SELECT dataset_id, dataset_code
            FROM qmeta.dataset_catalog
            WHERE dataset_code = ANY(%s::text[])
              AND is_active IS TRUE
        ),
        vendor_source AS (
            SELECT source_id, source_code
            FROM qmeta.source_system
            WHERE source_code = %s
        ),
        primary_source AS (
            SELECT source_id, source_code
            FROM qmeta.source_system
            WHERE source_code = %s
        )
        SELECT
            NULL::BIGINT AS optimization_id,
            NULL::TEXT AS optimization_code,
            NULL::BIGINT AS stability_snapshot_id,
            NULL::TEXT AS stability_snapshot_code,
            NULL::BIGINT AS plan_id,
            NULL::TEXT AS plan_code,
            vs.source_id, vs.source_code,
            sd.dataset_id, sd.dataset_code,
            ps.source_id AS primary_source_id,
            ps.source_code AS primary_source_code,
            NULL::BIGINT AS backup_source_id,
            NULL::TEXT AS backup_source_code,
            NULL::BIGINT AS current_priority_id,
            NULL::TEXT AS current_primary_source_code,
            NULL::INTEGER AS current_priority,
            FALSE AS is_primary_route,
            'blocked' AS tau5_status,
            'blocked' AS tau5_plan_role,
            'missing' AS stability_status,
            0::NUMERIC AS stability_score,
            NULL::TEXT AS contract_status,
            NULL::TEXT AS entitlement_status,
            0::NUMERIC AS recommended_primary_weight_pct,
            100::NUMERIC AS recommended_backup_weight_pct,
            0::NUMERIC AS recommended_free_source_weight_pct,
            0::NUMERIC AS projected_budget_usage_pct,
            0::NUMERIC AS projected_monthly_quota_usage_pct,
            FALSE AS routing_change_allowed,
            ARRAY['tau5_route_weight_plan_missing']::TEXT[] AS blocking_issues,
            ARRAY['Run Tau-5 cost optimization before Upsilon-5 route-weight execution.']::TEXT[] AS required_actions
        FROM selected_datasets sd
        CROSS JOIN vendor_source vs
        LEFT JOIN primary_source ps ON TRUE
        ORDER BY vs.source_code, sd.dataset_code
        """,
        [dataset_codes, source_code, primary_source_code],
    )


def _insert_execution_run(postgres_dsn: str, run: dict[str, Any]) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_route_weight_execution_run (
                    execution_code, optimization_id, source_id,
                    primary_source_id, stability_snapshot_id,
                    as_of_date, requested_by, trigger_mode,
                    environment, execution_scope, execution_mode,
                    approval_policy, approval_status,
                    rollout_policy, status, stage_count,
                    current_stage_sequence,
                    target_primary_weight_pct,
                    target_backup_weight_pct,
                    target_free_source_weight_pct,
                    applied_primary_weight_pct,
                    applied_backup_weight_pct,
                    applied_free_source_weight_pct,
                    dataset_count, pending_approval_dataset_count,
                    approved_dataset_count, staged_dataset_count,
                    applied_dataset_count,
                    rollback_recommended_count,
                    rolled_back_dataset_count,
                    blocked_dataset_count, no_primary_dataset_count,
                    routing_change_allowed, routing_change_applied,
                    rollback_allowed, rollback_applied,
                    blocking_issues, required_actions,
                    request_payload, response_payload,
                    evidence, details, error_message,
                    started_at, finished_at, duration_ms,
                    updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s,
                    %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s,
                    now()
                )
                RETURNING *
                """,
                (
                    run["execution_code"],
                    run.get("optimization_id"),
                    run["source_id"],
                    run.get("primary_source_id"),
                    run.get("stability_snapshot_id"),
                    run["as_of_date"],
                    run["requested_by"],
                    run["trigger_mode"],
                    run["environment"],
                    run["execution_scope"],
                    run["execution_mode"],
                    run["approval_policy"],
                    run["approval_status"],
                    run["rollout_policy"],
                    run["status"],
                    run["stage_count"],
                    run["current_stage_sequence"],
                    run["target_primary_weight_pct"],
                    run["target_backup_weight_pct"],
                    run["target_free_source_weight_pct"],
                    run["applied_primary_weight_pct"],
                    run["applied_backup_weight_pct"],
                    run["applied_free_source_weight_pct"],
                    run["dataset_count"],
                    run["pending_approval_dataset_count"],
                    run["approved_dataset_count"],
                    run["staged_dataset_count"],
                    run["applied_dataset_count"],
                    run["rollback_recommended_count"],
                    run["rolled_back_dataset_count"],
                    run["blocked_dataset_count"],
                    run["no_primary_dataset_count"],
                    run["routing_change_allowed"],
                    run["routing_change_applied"],
                    run["rollback_allowed"],
                    run["rollback_applied"],
                    run["blocking_issues"],
                    run["required_actions"],
                    _json(run["request_payload"]),
                    _json(run["response_payload"]),
                    _json(run["evidence"]),
                    _json(run["details"]),
                    run.get("error_message"),
                    run["started_at"],
                    run["finished_at"],
                    run["duration_ms"],
                ),
            )
            row = normalize_rows([dict(cursor.fetchone())])[0]
            row["source_code"] = run.get("source_code")
            row["primary_source_code"] = run.get("primary_source_code")
            row["optimization_code"] = run.get("optimization_code")
            row["stability_snapshot_code"] = run.get("stability_snapshot_code")
            return row


def _insert_execution_datasets(postgres_dsn: str, run: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for result in results:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_route_weight_execution_dataset (
                        execution_dataset_code, execution_id,
                        optimization_id, plan_id, source_id,
                        dataset_id, primary_source_id, backup_source_id,
                        current_priority_id, as_of_date, status,
                        approval_status, rollout_policy,
                        current_stage_sequence, stage_count,
                        current_primary_source_code, current_priority,
                        is_primary_route, tau5_status, tau5_plan_role,
                        stability_status, stability_score,
                        contract_status, entitlement_status,
                        target_primary_weight_pct,
                        target_backup_weight_pct,
                        target_free_source_weight_pct,
                        applied_primary_weight_pct,
                        applied_backup_weight_pct,
                        applied_free_source_weight_pct,
                        projected_budget_usage_pct,
                        projected_monthly_quota_usage_pct,
                        routing_change_allowed,
                        routing_change_applied,
                        rollback_allowed, rollback_applied,
                        blocking_issues, required_actions,
                        evidence, error_message, updated_at
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
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
                        %s,
                        %s,
                        %s, %s,
                        %s, %s,
                        %s::jsonb, %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        result["execution_dataset_code"],
                        run["execution_id"],
                        result.get("optimization_id"),
                        result.get("plan_id"),
                        result["source_id"],
                        result["dataset_id"],
                        result.get("primary_source_id"),
                        result.get("backup_source_id"),
                        result.get("current_priority_id"),
                        result["as_of_date"],
                        result["status"],
                        result["approval_status"],
                        result["rollout_policy"],
                        result["current_stage_sequence"],
                        result["stage_count"],
                        result.get("current_primary_source_code"),
                        result.get("current_priority"),
                        result["is_primary_route"],
                        result.get("tau5_status"),
                        result.get("tau5_plan_role"),
                        result.get("stability_status"),
                        result["stability_score"],
                        result.get("contract_status"),
                        result.get("entitlement_status"),
                        result["target_primary_weight_pct"],
                        result["target_backup_weight_pct"],
                        result["target_free_source_weight_pct"],
                        result["applied_primary_weight_pct"],
                        result["applied_backup_weight_pct"],
                        result["applied_free_source_weight_pct"],
                        result["projected_budget_usage_pct"],
                        result["projected_monthly_quota_usage_pct"],
                        result["routing_change_allowed"],
                        result["routing_change_applied"],
                        result["rollback_allowed"],
                        result["rollback_applied"],
                        result["blocking_issues"],
                        result["required_actions"],
                        _json(result["evidence"]),
                        result.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row.update(
                    {
                        "execution_code": run.get("execution_code"),
                        "optimization_code": result.get("optimization_code"),
                        "plan_code": result.get("plan_code"),
                        "source_code": result.get("source_code"),
                        "dataset_code": result.get("dataset_code"),
                        "primary_source_code": result.get("primary_source_code"),
                        "backup_source_code": result.get("backup_source_code"),
                    }
                )
                inserted.append(row)
    return inserted


def _insert_rollout_stages(
    postgres_dsn: str,
    run: dict[str, Any],
    datasets: list[dict[str, Any]],
    stages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dataset_by_code = {row.get("execution_dataset_code"): row for row in datasets}
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for stage in stages:
                dataset_row = dataset_by_code.get(stage.get("execution_dataset_code"))
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_route_weight_rollout_stage (
                        stage_code, execution_id, execution_dataset_id,
                        source_id, dataset_id, as_of_date,
                        stage_sequence, stage_label, status,
                        approval_required, approval_status, gate_status,
                        target_primary_weight_pct,
                        target_backup_weight_pct,
                        target_free_source_weight_pct,
                        routing_change_allowed,
                        routing_change_applied,
                        blocking_issues, required_actions,
                        evidence, error_message, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s, %s,
                        %s::jsonb, %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        stage["stage_code"],
                        run["execution_id"],
                        dataset_row.get("execution_dataset_id") if dataset_row else None,
                        stage["source_id"],
                        stage["dataset_id"],
                        stage["as_of_date"],
                        stage["stage_sequence"],
                        stage["stage_label"],
                        stage["status"],
                        stage["approval_required"],
                        stage["approval_status"],
                        stage["gate_status"],
                        stage["target_primary_weight_pct"],
                        stage["target_backup_weight_pct"],
                        stage["target_free_source_weight_pct"],
                        stage["routing_change_allowed"],
                        stage["routing_change_applied"],
                        stage["blocking_issues"],
                        stage["required_actions"],
                        _json(stage["evidence"]),
                        stage.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row.update(
                    {
                        "execution_code": run.get("execution_code"),
                        "execution_dataset_code": stage.get("execution_dataset_code"),
                        "source_code": stage.get("source_code"),
                        "dataset_code": stage.get("dataset_code"),
                    }
                )
                inserted.append(row)
    return inserted


def _insert_source_route_weight_policies(
    postgres_dsn: str,
    run: dict[str, Any],
    datasets: list[dict[str, Any]],
    stages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    applied_stage_by_dataset = {
        stage.get("execution_dataset_code"): stage for stage in stages if stage.get("status") in {"applied", "rolled_back"}
    }
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for dataset in datasets:
                if not dataset.get("routing_change_applied") and not dataset.get("rollback_applied"):
                    continue
                stage = applied_stage_by_dataset.get(dataset.get("execution_dataset_code"))
                policy_status = "rolled_back" if dataset.get("rollback_applied") else "active"
                policy_code = _policy_code(str(dataset.get("source_code") or "unknown"), str(dataset.get("dataset_code") or "unknown"), policy_status)
                cursor.execute(
                    """
                    UPDATE qmeta.source_route_weight_policy
                    SET policy_status = 'superseded',
                        end_date = %s,
                        updated_at = now()
                    WHERE dataset_id = %s
                      AND source_id = %s
                      AND policy_status = 'active'
                      AND effective_date <= %s
                      AND (end_date IS NULL OR end_date >= %s)
                    """,
                    (run["as_of_date"], dataset["dataset_id"], dataset["source_id"], run["as_of_date"], run["as_of_date"]),
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.source_route_weight_policy (
                        policy_code, execution_id,
                        execution_dataset_id, stage_id, source_id,
                        dataset_id, primary_source_id, backup_source_id,
                        effective_date, policy_status, execution_mode,
                        primary_weight_pct, backup_weight_pct,
                        free_source_weight_pct, created_by,
                        evidence, updated_at
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s::jsonb, now()
                    )
                    RETURNING *
                    """,
                    (
                        policy_code,
                        run["execution_id"],
                        dataset["execution_dataset_id"],
                        stage.get("stage_id") if stage else None,
                        dataset["source_id"],
                        dataset["dataset_id"],
                        dataset.get("primary_source_id"),
                        dataset.get("backup_source_id"),
                        run["as_of_date"],
                        policy_status,
                        run["execution_mode"],
                        dataset["applied_primary_weight_pct"],
                        dataset["applied_backup_weight_pct"],
                        dataset["applied_free_source_weight_pct"],
                        run.get("requested_by") or "upsilon5",
                        _json(
                            {
                                "execution_code": run.get("execution_code"),
                                "execution_dataset_code": dataset.get("execution_dataset_code"),
                                "stage_code": stage.get("stage_code") if stage else None,
                            }
                        ),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row.update(
                    {
                        "execution_code": run.get("execution_code"),
                        "execution_dataset_code": dataset.get("execution_dataset_code"),
                        "stage_code": stage.get("stage_code") if stage else None,
                        "source_code": dataset.get("source_code"),
                        "dataset_code": dataset.get("dataset_code"),
                        "primary_source_code": dataset.get("primary_source_code"),
                        "backup_source_code": dataset.get("backup_source_code"),
                    }
                )
                inserted.append(row)
    return inserted


def _execution_eval(
    status: str,
    approval_status: str,
    target_primary: float,
    target_backup: float,
    target_free: float,
    applied_primary: float,
    applied_backup: float,
    applied_free: float,
    *,
    current_stage_sequence: int,
    stage_count: int,
    routing_allowed: bool,
    routing_applied: bool,
    rollback_allowed: bool,
    rollback_applied: bool,
    issues: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "approval_status": approval_status,
        "target_primary_weight_pct": round(target_primary, 4),
        "target_backup_weight_pct": round(target_backup, 4),
        "target_free_source_weight_pct": round(target_free, 4),
        "applied_primary_weight_pct": round(applied_primary, 4),
        "applied_backup_weight_pct": round(applied_backup, 4),
        "applied_free_source_weight_pct": round(applied_free, 4),
        "current_stage_sequence": current_stage_sequence,
        "stage_count": stage_count,
        "routing_change_allowed": routing_allowed,
        "routing_change_applied": routing_applied,
        "rollback_allowed": rollback_allowed,
        "rollback_applied": rollback_applied,
        "blocking_issues": _dedupe(issues),
    }


def _target_stages(target_primary: float, rollout_stages: Iterable[float], rollout_policy: str) -> list[float]:
    if target_primary <= 0:
        return []
    if rollout_policy == "review_only":
        return [target_primary]
    if rollout_policy == "full":
        return [target_primary]
    values = [value for value in _normalize_rollout_stages(rollout_stages) if value < target_primary]
    values.append(target_primary)
    return _dedupe_float(values)


def _stage_primary_weight(
    target_primary: float,
    target_stage_values: list[float],
    current_stage_sequence: int,
    max_initial_primary_weight_pct: float,
    rollout_policy: str,
) -> float:
    if not target_stage_values:
        return 0.0
    value = target_stage_values[min(max(current_stage_sequence, 1), len(target_stage_values)) - 1]
    if rollout_policy in {"canary", "gradual"} and current_stage_sequence == 1:
        value = min(value, max_initial_primary_weight_pct)
    return round(min(value, target_primary), 4)


def _stage_status(result: dict[str, Any], sequence: int, current_stage_sequence: int, execution_mode: str) -> str:
    result_status = str(result.get("status") or "blocked")
    if result_status in {"blocked", "no_primary_promotion", "review_required"}:
        return "blocked"
    if result_status == "rollback_recommended":
        return "rollback_recommended"
    if result_status == "rolled_back":
        return "rolled_back"
    if result_status == "pending_approval":
        return "pending"
    if sequence < current_stage_sequence and execution_mode == "apply":
        return "applied"
    if sequence == current_stage_sequence:
        return "applied" if result.get("routing_change_applied") else "ready"
    return "pending"


def _aggregate_status(statuses: list[str]) -> str:
    unique = set(statuses)
    if unique and unique <= {"no_primary_promotion"}:
        return "no_primary_promotion"
    if unique and unique <= {"applied"}:
        return "applied"
    for status in ("blocked", "rollback_recommended", "review_required", "pending_approval", "staged", "approved", "rolled_back", "no_primary_promotion"):
        if status in unique:
            return status
    return "review_required" if unique else "blocked"


def _aggregate_approval_status(results: list[dict[str, Any]], default: str) -> str:
    statuses = {str(result.get("approval_status") or default) for result in results}
    if "blocked" in statuses:
        return "blocked"
    if "rejected" in statuses:
        return "rejected"
    if "pending" in statuses:
        return "pending"
    if "approved" in statuses:
        return "approved"
    if "not_required" in statuses:
        return "not_required"
    return default


def _dataset_evidence(row: dict[str, Any], evaluation: dict[str, Any], stages: list[float]) -> dict[str, Any]:
    return {
        "tau5": {
            "optimization_code": row.get("optimization_code"),
            "plan_code": row.get("plan_code"),
            "status": row.get("tau5_status") or row.get("status"),
            "recommended_primary_weight_pct": row.get("recommended_primary_weight_pct"),
        },
        "routing": {
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": row.get("current_priority"),
            "is_primary_route": bool(row.get("is_primary_route")),
        },
        "execution": {
            "status": evaluation.get("status"),
            "approval_status": evaluation.get("approval_status"),
            "rollout_stages": stages,
        },
    }


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    execution_scope: str,
    execution_mode: str,
    approval_policy: str,
    approval_status: str,
    rollout_policy: str,
    rollout_stages: list[float],
    current_stage_sequence: int,
    max_initial_primary_weight_pct: float,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, once, smoke, api")
    if execution_scope not in EXECUTION_SCOPES:
        raise QDataValidationError("execution_scope must be one of: primary_source, all_datasets, full_market")
    if execution_mode not in EXECUTION_MODES:
        raise QDataValidationError("execution_mode must be one of: review_only, dry_run, apply")
    if approval_policy not in APPROVAL_POLICIES:
        raise QDataValidationError("approval_policy must be one of: manual_required, auto_if_optimized")
    if approval_status not in APPROVAL_STATUSES:
        raise QDataValidationError("approval_status must be one of: not_required, pending, approved, rejected, blocked")
    if rollout_policy not in ROLLOUT_POLICIES:
        raise QDataValidationError("rollout_policy must be one of: review_only, canary, gradual, full")
    if not rollout_stages:
        raise QDataValidationError("rollout_stages must not be empty")
    if current_stage_sequence < 1:
        raise QDataValidationError("current_stage_sequence must be greater than 0")
    if max_initial_primary_weight_pct < 0 or max_initial_primary_weight_pct > 100:
        raise QDataValidationError("max_initial_primary_weight_pct must be between 0 and 100")


def _normalize_rollout_stages(values: Iterable[float] | None) -> list[float]:
    raw = list(values or DEFAULT_ROLLOUT_STAGES)
    stages: list[float] = []
    for value in raw:
        stage = float(value)
        if stage <= 0 or stage > 100:
            raise QDataValidationError("rollout stage weights must be greater than 0 and less than or equal to 100")
        stages.append(round(stage, 4))
    return _dedupe_float(sorted(stages))


def _dedupe_float(values: Iterable[float]) -> list[float]:
    result: list[float] = []
    seen: set[float] = set()
    for value in values:
        rounded = round(float(value), 4)
        if rounded in seen:
            continue
        seen.add(rounded)
        result.append(rounded)
    return result


def _append_where(where: str, values: list[Any], clause: str, value: Any) -> tuple[str, list[Any]]:
    prefix = " AND " if where else "WHERE "
    return where + prefix + clause, values + [value]


def _first_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _execution_code(source_code: str, execution_scope: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{execution_scope}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"upsilon5-route-execution-{source_code}-{execution_scope}-{status}-{digest}"[:180]


def _dataset_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"upsilon5-route-dataset-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _stage_code(source_code: str, dataset_code: str, sequence: int, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{sequence}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"upsilon5-route-stage-{source_code}-{dataset_code}-{sequence}-{status}-{digest}"[:180]


def _policy_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"upsilon5-route-policy-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _report_keys(row: dict[str, Any]) -> list[str]:
    preferred = [
        "execution_code",
        "execution_dataset_code",
        "stage_code",
        "policy_code",
        "optimization_code",
        "plan_code",
        "source_code",
        "dataset_code",
        "primary_source_code",
        "backup_source_code",
        "status",
        "approval_status",
        "execution_mode",
        "rollout_policy",
        "stage_sequence",
        "current_stage_sequence",
        "dataset_count",
        "pending_approval_dataset_count",
        "approved_dataset_count",
        "staged_dataset_count",
        "applied_dataset_count",
        "blocked_dataset_count",
        "no_primary_dataset_count",
        "target_primary_weight_pct",
        "applied_primary_weight_pct",
        "primary_weight_pct",
        "backup_weight_pct",
        "free_source_weight_pct",
        "routing_change_allowed",
        "routing_change_applied",
        "rollback_allowed",
        "rollback_applied",
        "blocking_issues",
        "required_actions",
    ]
    return [key for key in preferred if key in row] + [key for key in row.keys() if key not in preferred]
