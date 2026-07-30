from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows
from qdata.exceptions import QDataValidationError
from qdata.omicron5_vendor_contract import DEFAULT_VENDOR_DATASETS, DEFAULT_VENDOR_SOURCE_CODES
from qdata.tau5_vendor_cost_optimization import (
    _append_date_filter,
    _as_of_date,
    _connect_required,
    _dedupe,
    _duration_ms,
    _fetch_rows,
    _float_or_zero,
    _json,
    _normalize_optional_codes,
    _param,
    _require_dsn,
    _where_equal,
)
from qdata.theta import load_vendor_runtime_config, redacted_vendor_config


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api", "worker"}
ENVIRONMENTS = {"local", "staging", "production"}
CLOSURE_SCOPES = {"production_primary", "canary", "full_market"}
CLOSURE_MODES = {"review_only", "dry_run", "apply"}
PRODUCTION_STATUSES = {
    "blocked",
    "review_required",
    "ready_for_pilot",
    "ready_for_primary",
    "ready_for_rollout",
    "production_ready",
    "applied",
    "monitoring",
    "rollback_required",
    "failed",
}
PRODUCTION_ROLES = {"blocked", "research_only", "validator", "backup", "primary_candidate", "primary"}
DECISION_TYPES = (
    "profile_env",
    "contract_entitlement",
    "live_pilot",
    "primary_promotion",
    "stability",
    "cost_quota",
    "route_execution",
    "rollback_guard",
    "final_decision",
)


def run_vendor_production_source_closure(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    source_code: str = DEFAULT_VENDOR_SOURCE_CODES[0],
    primary_source_code: str = "csv",
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "eta6",
    trigger_mode: str = "manual",
    environment: str = "local",
    closure_scope: str = "production_primary",
    closure_mode: str = "review_only",
    require_real_vendor_env: bool = True,
    external_probe_allowed: bool = False,
    min_stability_score: float = 70.0,
    allow_cost_watch: bool = False,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        closure_scope=closure_scope,
        closure_mode=closure_mode,
        min_stability_score=min_stability_score,
    )
    snapshot_date = _as_of_date(as_of_date)
    datasets = _normalize_optional_codes(dataset_codes) or list(DEFAULT_VENDOR_DATASETS)
    dsn = _require_dsn(postgres_dsn)
    runtime = load_vendor_runtime(source_code)
    started_at = datetime.now(timezone.utc)
    rows = _load_production_inputs(
        dsn,
        source_code=source_code,
        primary_source_code=primary_source_code,
        dataset_codes=datasets,
    )
    if not rows:
        rows = _fallback_dataset_rows(dsn, source_code=source_code, primary_source_code=primary_source_code, dataset_codes=datasets)
    checks = build_production_dataset_checks(
        rows,
        as_of_date=snapshot_date,
        runtime=runtime,
        require_real_vendor_env=require_real_vendor_env,
        min_stability_score=min_stability_score,
        allow_cost_watch=allow_cost_watch,
    )
    decisions = build_production_decisions(checks, runtime=runtime)
    finished_at = datetime.now(timezone.utc)
    run = build_production_source_run(
        checks,
        decisions,
        runtime=runtime,
        source_code=source_code,
        primary_source_code=primary_source_code,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        closure_scope=closure_scope,
        closure_mode=closure_mode,
        require_real_vendor_env=require_real_vendor_env,
        external_probe_allowed=external_probe_allowed,
        min_stability_score=min_stability_score,
        allow_cost_watch=allow_cost_watch,
        started_at=started_at,
        finished_at=finished_at,
    )
    if not write_db:
        run["dataset_checks"] = normalize_rows(checks)
        run["decisions"] = normalize_rows(decisions)
        return normalize_rows([run])[0]
    stored = _insert_production_run(dsn, run)
    stored_checks = _insert_dataset_checks(dsn, stored, checks)
    stored_decisions = _insert_decisions(dsn, stored, stored_checks, decisions)
    stored["dataset_checks"] = stored_checks
    stored["decisions"] = stored_decisions
    return stored


def load_vendor_runtime(source_code: str = DEFAULT_VENDOR_SOURCE_CODES[0]) -> dict[str, Any]:
    config = load_vendor_runtime_config(source_code)
    token_present = _token_present(config)
    token_material = ""
    if config.auth_mode == "basic":
        token_material = f"{config.username or ''}:{config.password or ''}"
    else:
        token_material = config.token or ""
    token_digest = hashlib.sha256(token_material.encode("utf-8")).hexdigest() if token_material else None
    return {
        "source_code": config.source_code or source_code,
        "provider_name": config.provider_name,
        "auth_mode": config.auth_mode,
        "live_base_url_present": bool(config.base_url),
        "live_token_present": token_present,
        "token_digest": token_digest,
        "token_digest_tail": token_digest[-12:] if token_digest else None,
        "daily_path": config.daily_path,
        "rate_limit_per_min": config.rate_limit_per_min,
        "timeout": config.timeout,
        "redacted_config": redacted_vendor_config(config),
    }


def build_production_dataset_checks(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    runtime: dict[str, Any] | None = None,
    require_real_vendor_env: bool = True,
    min_stability_score: float = 70.0,
    allow_cost_watch: bool = False,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    runtime = runtime or load_vendor_runtime()
    checks: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        evaluation = evaluate_production_dataset(
            row,
            runtime=runtime,
            require_real_vendor_env=require_real_vendor_env,
            min_stability_score=min_stability_score,
            allow_cost_watch=allow_cost_watch,
        )
        status = evaluation["status"]
        check = {
            "dataset_check_code": _code("eta6-dataset", str(row.get("source_code") or "unknown"), str(row.get("dataset_code") or "unknown"), status),
            "source_id": row["source_id"],
            "source_code": row.get("source_code"),
            "dataset_id": row["dataset_id"],
            "dataset_code": row.get("dataset_code"),
            "primary_source_id": row.get("primary_source_id"),
            "primary_source_code": row.get("primary_source_code"),
            "contract_id": row.get("contract_id"),
            "contract_code": row.get("contract_code"),
            "entitlement_id": row.get("entitlement_id"),
            "entitlement_code": row.get("entitlement_code"),
            "procurement_snapshot_id": row.get("procurement_snapshot_id"),
            "procurement_snapshot_code": row.get("procurement_snapshot_code"),
            "canary_pilot_id": row.get("canary_pilot_id"),
            "canary_pilot_code": row.get("canary_pilot_code"),
            "full_market_pilot_id": row.get("full_market_pilot_id"),
            "full_market_pilot_code": row.get("full_market_pilot_code"),
            "promotion_id": row.get("promotion_id"),
            "promotion_code": row.get("promotion_code"),
            "promotion_result_id": row.get("promotion_result_id"),
            "promotion_result_code": row.get("promotion_result_code"),
            "stability_snapshot_id": row.get("stability_snapshot_id"),
            "stability_snapshot_code": row.get("stability_snapshot_code"),
            "stability_dataset_snapshot_id": row.get("stability_dataset_snapshot_id"),
            "stability_dataset_snapshot_code": row.get("stability_dataset_snapshot_code"),
            "optimization_id": row.get("optimization_id"),
            "optimization_code": row.get("optimization_code"),
            "route_plan_id": row.get("route_plan_id"),
            "route_plan_code": row.get("route_plan_code"),
            "route_execution_id": row.get("route_execution_id"),
            "route_execution_code": row.get("route_execution_code"),
            "route_execution_dataset_id": row.get("route_execution_dataset_id"),
            "route_execution_dataset_code": row.get("route_execution_dataset_code"),
            "as_of_date": snapshot_date.isoformat(),
            "status": status,
            "production_role": evaluation["production_role"],
            "contract_status": row.get("contract_status"),
            "entitlement_status": row.get("entitlement_status"),
            "allowed_role": row.get("allowed_role"),
            "procurement_status": row.get("procurement_status"),
            "procurement_role": row.get("procurement_role"),
            "canary_status": row.get("canary_status"),
            "canary_signoff_status": row.get("canary_signoff_status"),
            "full_market_status": row.get("full_market_status"),
            "full_market_signoff_status": row.get("full_market_signoff_status"),
            "promotion_status": row.get("promotion_status"),
            "promotion_result_status": row.get("promotion_result_status"),
            "stability_status": row.get("stability_status"),
            "stability_score": _float_or_zero(row.get("stability_score")),
            "optimization_status": row.get("optimization_status"),
            "route_plan_status": row.get("route_plan_status"),
            "route_execution_status": row.get("route_execution_status"),
            "route_policy_status": row.get("route_policy_status"),
            "current_primary_source_code": row.get("current_primary_source_code"),
            "is_primary_route": bool(row.get("is_primary_route")),
            "recommended_primary_weight_pct": _float_or_zero(row.get("recommended_primary_weight_pct")),
            "applied_primary_weight_pct": _float_or_zero(row.get("applied_primary_weight_pct")),
            "production_score": evaluation["production_score"],
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": evaluation["required_actions"],
            "evidence": _dataset_evidence(row, runtime, evaluation),
            "error_message": "; ".join(evaluation["blocking_issues"]) if evaluation["blocking_issues"] else None,
        }
        checks.append(check)
    return checks


def evaluate_production_dataset(
    row: dict[str, Any],
    *,
    runtime: dict[str, Any],
    require_real_vendor_env: bool = True,
    min_stability_score: float = 70.0,
    allow_cost_watch: bool = False,
) -> dict[str, Any]:
    gates: dict[str, bool] = {}
    issues: list[str] = []

    profile_ok = row.get("vendor_profile_status") == "active"
    env_ok = bool(runtime.get("live_base_url_present")) and bool(runtime.get("live_token_present"))
    gates["profile_env"] = profile_ok and (env_ok or not require_real_vendor_env)
    if not profile_ok:
        issues.append(f"vendor_profile_not_active:{row.get('vendor_profile_status') or 'missing'}")
    if require_real_vendor_env and not runtime.get("live_base_url_present"):
        issues.append("missing_env:QDATA_VENDOR_BASE_URL")
    if require_real_vendor_env and not runtime.get("live_token_present"):
        issues.append("missing_env:QDATA_VENDOR_TOKEN")

    contract_ok = (
        row.get("procurement_contract_status") == "active"
        and row.get("contract_status") == "active"
        and row.get("commercial_clearance") == "clear"
        and bool(row.get("contract_production_use_allowed"))
    )
    entitlement_ok = (
        row.get("entitlement_status") == "active"
        and row.get("allowed_role") == "primary_candidate"
        and bool(row.get("entitlement_commercial_use_allowed"))
        and bool(row.get("entitlement_production_use_allowed"))
        and row.get("entitlement_redistribution_allowed") == "yes"
        and row.get("schema_status") in {"mapped", "validated"}
        and row.get("field_mapping_status") in {"mapped", "validated"}
    )
    procurement_ok = row.get("procurement_status") == "ready" and row.get("procurement_role") == "primary_candidate"
    gates["contract_entitlement"] = contract_ok and entitlement_ok and procurement_ok
    if not row.get("contract_id"):
        issues.append("contract_profile_missing")
    elif not contract_ok:
        issues.append(f"contract_not_production_active:{row.get('procurement_contract_status') or 'missing'}/{row.get('contract_status') or 'missing'}/{row.get('commercial_clearance') or 'missing'}")
    if not row.get("entitlement_id"):
        issues.append("dataset_entitlement_missing")
    elif not entitlement_ok:
        issues.append(f"entitlement_not_primary_candidate:{row.get('entitlement_status') or 'missing'}/{row.get('allowed_role') or 'missing'}")
    if not row.get("procurement_snapshot_id"):
        issues.append("omicron5_procurement_readiness_missing")
    elif not procurement_ok:
        issues.append(f"omicron5_procurement_not_ready:{row.get('procurement_status') or 'missing'}/{row.get('procurement_role') or 'missing'}")

    canary_ok = _pilot_ok(row, "canary")
    full_market_ok = _pilot_ok(row, "full_market")
    gates["live_pilot"] = canary_ok and full_market_ok
    if not row.get("canary_pilot_id"):
        issues.append("theta3_canary_pilot_missing")
    elif not canary_ok:
        issues.append(f"theta3_canary_not_primary_candidate:{row.get('canary_status') or 'missing'}/{row.get('canary_signoff_status') or 'missing'}")
    if not row.get("full_market_pilot_id"):
        issues.append("theta3_full_market_pilot_missing")
    elif not full_market_ok:
        issues.append(f"theta3_full_market_not_primary_candidate:{row.get('full_market_status') or 'missing'}/{row.get('full_market_signoff_status') or 'missing'}")

    promotion_ok = row.get("promotion_result_status") in {"approved_for_primary", "applied"} or row.get("promotion_status") in {"approved_for_primary", "applied"}
    gates["primary_promotion"] = promotion_ok
    if not row.get("promotion_result_id") and not row.get("promotion_id"):
        issues.append("pi5_primary_promotion_missing")
    elif not promotion_ok:
        issues.append(f"pi5_primary_promotion_not_ready:{row.get('promotion_status') or 'missing'}/{row.get('promotion_result_status') or 'missing'}")

    stability_score = _float_or_zero(row.get("stability_score"))
    stability_ok = row.get("stability_status") == "healthy" and stability_score >= min_stability_score
    gates["stability"] = stability_ok
    if not row.get("stability_snapshot_id"):
        issues.append("sigma5_stability_snapshot_missing")
    elif not stability_ok:
        issues.append(f"sigma5_stability_not_healthy:{row.get('stability_status') or 'missing'}/{stability_score:g}")

    optimization_status = row.get("optimization_status")
    cost_ok = optimization_status == "optimized" or (allow_cost_watch and optimization_status == "watch")
    gates["cost_quota"] = cost_ok
    if not row.get("optimization_id"):
        issues.append("tau5_cost_optimization_missing")
    elif not cost_ok:
        issues.append(f"tau5_cost_not_optimized:{optimization_status or 'missing'}")

    route_status = row.get("route_execution_status")
    policy_status = row.get("route_policy_status")
    route_ready = route_status in {"approved", "staged", "applied"} or policy_status == "active"
    route_applied = route_status == "applied" or policy_status == "active" or bool(row.get("is_primary_route"))
    gates["route_execution"] = route_ready
    if not row.get("route_execution_id") and not row.get("route_policy_status"):
        issues.append("upsilon5_route_execution_missing")
    elif not route_ready:
        issues.append(f"upsilon5_route_not_ready:{route_status or policy_status or 'missing'}")

    rollback_clear = row.get("post_promotion_status") not in {"rollback_recommended", "rolled_back"} and row.get("source_route_health_status") not in {"degraded", "circuit_open"}
    gates["rollback_guard"] = rollback_clear
    if not rollback_clear:
        issues.append(f"rollback_guard_active:{row.get('post_promotion_status') or row.get('source_route_health_status') or 'unknown'}")

    score = round(sum(1 for ok in gates.values() if ok) * 100.0 / len(gates), 4)
    if not gates["profile_env"] or not gates["contract_entitlement"]:
        status = "blocked"
        role = "blocked"
    elif not gates["live_pilot"]:
        status = "ready_for_pilot"
        role = "validator"
    elif not gates["primary_promotion"]:
        status = "ready_for_primary"
        role = "backup"
    elif not gates["stability"] or not gates["cost_quota"]:
        status = "review_required"
        role = "primary_candidate"
    elif not gates["route_execution"]:
        status = "ready_for_rollout"
        role = "primary_candidate"
    elif not gates["rollback_guard"]:
        status = "rollback_required"
        role = "blocked"
    elif route_applied:
        status = "monitoring"
        role = "primary"
    else:
        status = "production_ready"
        role = "primary_candidate"

    return {
        "status": status,
        "production_role": role,
        "production_score": score,
        "gates": gates,
        "blocking_issues": _dedupe(issues),
        "required_actions": _required_actions(issues, status),
    }


def build_production_decisions(checks: list[dict[str, Any]], *, runtime: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for check in checks:
        gate_statuses = dict((check.get("evidence") or {}).get("gates") or {})
        for decision_type in DECISION_TYPES:
            if decision_type == "final_decision":
                passed = check["status"] in {"production_ready", "applied", "monitoring"}
                status = "passed" if passed else "blocked" if check["status"] == "blocked" else "warning"
            else:
                gate = gate_statuses.get(decision_type)
                status = "passed" if gate is True else "blocked" if decision_type in {"profile_env", "contract_entitlement"} and gate is False else "warning" if gate is False else "skipped"
            severity = "critical" if status in {"blocked", "failed"} else "warning" if status == "warning" else "info"
            decisions.append(
                {
                    "decision_code": _code("eta6-decision", str(check.get("source_code") or "unknown"), str(check.get("dataset_code") or "unknown"), decision_type, status),
                    "source_id": check["source_id"],
                    "source_code": check.get("source_code"),
                    "dataset_id": check["dataset_id"],
                    "dataset_code": check.get("dataset_code"),
                    "dataset_check_code": check["dataset_check_code"],
                    "decision_type": decision_type,
                    "status": status,
                    "severity": severity,
                    "decision_summary": _decision_summary(decision_type, status, check),
                    "blocking_issues": check["blocking_issues"] if status in {"blocked", "failed"} else [],
                    "required_actions": check["required_actions"] if status in {"blocked", "warning", "failed"} else [],
                    "evidence": {
                        "dataset_check_code": check["dataset_check_code"],
                        "dataset_status": check["status"],
                        "production_score": check["production_score"],
                        "token_material_persisted": False,
                    },
                    "error_message": check.get("error_message") if status in {"blocked", "failed"} else None,
                }
            )
    return decisions


def build_production_source_run(
    checks: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    runtime: dict[str, Any],
    source_code: str,
    primary_source_code: str,
    as_of_date: str | date | None = None,
    requested_by: str = "eta6",
    trigger_mode: str = "manual",
    environment: str = "local",
    closure_scope: str = "production_primary",
    closure_mode: str = "review_only",
    require_real_vendor_env: bool = True,
    external_probe_allowed: bool = False,
    min_stability_score: float = 70.0,
    allow_cost_watch: bool = False,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot_date = _as_of_date(as_of_date)
    started_at = started_at or datetime.now(timezone.utc)
    finished_at = finished_at or datetime.now(timezone.utc)
    dataset_count = len(checks)
    blocked_count = sum(1 for row in checks if row["status"] in {"blocked", "failed", "rollback_required"})
    production_ready_count = sum(1 for row in checks if row["status"] in {"production_ready", "applied", "monitoring"})
    applied_count = sum(1 for row in checks if row["status"] in {"applied", "monitoring"} or row.get("is_primary_route"))
    if not checks:
        status = "failed"
        role = "blocked"
    elif blocked_count:
        status = "blocked"
        role = "blocked"
    elif production_ready_count == dataset_count and applied_count == dataset_count:
        status = "monitoring"
        role = "primary"
    elif production_ready_count == dataset_count:
        status = "production_ready"
        role = "primary_candidate"
    elif any(row["status"] == "ready_for_rollout" for row in checks):
        status = "ready_for_rollout"
        role = "primary_candidate"
    elif any(row["status"] == "ready_for_primary" for row in checks):
        status = "ready_for_primary"
        role = "backup"
    elif any(row["status"] == "ready_for_pilot" for row in checks):
        status = "ready_for_pilot"
        role = "validator"
    else:
        status = "review_required"
        role = "primary_candidate"
    score = round(sum(_float_or_zero(row.get("production_score")) for row in checks) / dataset_count, 4) if dataset_count else 0.0
    issues = _dedupe([issue for row in checks for issue in row.get("blocking_issues", [])])
    actions = _dedupe([action for row in checks for action in row.get("required_actions", [])])
    routing_allowed = status in {"production_ready", "monitoring"} and closure_mode in {"dry_run", "apply"}
    routing_applied = False
    first = checks[0] if checks else {}
    return {
        "production_code": _code("eta6-production", source_code, primary_source_code, status),
        "source_id": first.get("source_id"),
        "source_code": source_code,
        "primary_source_id": first.get("primary_source_id"),
        "primary_source_code": primary_source_code,
        "as_of_date": snapshot_date.isoformat(),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "closure_scope": closure_scope,
        "closure_mode": closure_mode,
        "status": status,
        "production_role": role,
        "dataset_count": dataset_count,
        "authorized_dataset_count": sum(1 for row in checks if (row.get("evidence") or {}).get("gates", {}).get("contract_entitlement")),
        "live_ready_dataset_count": sum(1 for row in checks if (row.get("evidence") or {}).get("gates", {}).get("profile_env")),
        "pilot_ready_dataset_count": sum(1 for row in checks if (row.get("evidence") or {}).get("gates", {}).get("live_pilot")),
        "promoted_dataset_count": sum(1 for row in checks if (row.get("evidence") or {}).get("gates", {}).get("primary_promotion")),
        "stable_dataset_count": sum(1 for row in checks if (row.get("evidence") or {}).get("gates", {}).get("stability")),
        "optimized_dataset_count": sum(1 for row in checks if (row.get("evidence") or {}).get("gates", {}).get("cost_quota")),
        "route_ready_dataset_count": sum(1 for row in checks if (row.get("evidence") or {}).get("gates", {}).get("route_execution")),
        "production_ready_dataset_count": production_ready_count,
        "applied_dataset_count": applied_count,
        "blocked_dataset_count": blocked_count,
        "require_real_vendor_env": require_real_vendor_env,
        "live_base_url_present": bool(runtime.get("live_base_url_present")),
        "live_token_present": bool(runtime.get("live_token_present")),
        "token_digest": runtime.get("token_digest"),
        "external_probe_allowed": external_probe_allowed,
        "routing_change_allowed": routing_allowed,
        "routing_change_applied": routing_applied,
        "rollback_guard_armed": any(row["status"] == "rollback_required" for row in checks),
        "production_score": score,
        "blocking_issues": issues,
        "required_actions": actions,
        "request_payload": {
            "source_code": source_code,
            "primary_source_code": primary_source_code,
            "dataset_codes": [row.get("dataset_code") for row in checks],
            "closure_mode": closure_mode,
            "require_real_vendor_env": require_real_vendor_env,
            "external_probe_allowed": external_probe_allowed,
            "min_stability_score": min_stability_score,
            "allow_cost_watch": allow_cost_watch,
        },
        "response_payload": {
            "dataset_status_counts": _status_counts(checks),
            "decision_status_counts": _status_counts(decisions),
        },
        "evidence": {
            "runtime_config": runtime.get("redacted_config") or {},
            "token_digest_tail": runtime.get("token_digest_tail"),
            "token_material_persisted": False,
            "decision_count": len(decisions),
        },
        "error_message": "; ".join(issues) if status in {"blocked", "failed", "rollback_required"} and issues else None,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
    }


def list_vendor_production_source_runs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("production_code", "vpsr.production_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vpsr.status"),
            ("production_role", "vpsr.production_role"),
            ("environment", "vpsr.environment"),
            ("closure_scope", "vpsr.closure_scope"),
            ("closure_mode", "vpsr.closure_mode"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vpsr.as_of_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vpsr.production_id, vpsr.production_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vpsr.as_of_at, vpsr.as_of_date,
            vpsr.requested_by, vpsr.trigger_mode,
            vpsr.environment, vpsr.closure_scope,
            vpsr.closure_mode, vpsr.status,
            vpsr.production_role, vpsr.dataset_count,
            vpsr.authorized_dataset_count,
            vpsr.live_ready_dataset_count,
            vpsr.pilot_ready_dataset_count,
            vpsr.promoted_dataset_count,
            vpsr.stable_dataset_count,
            vpsr.optimized_dataset_count,
            vpsr.route_ready_dataset_count,
            vpsr.production_ready_dataset_count,
            vpsr.applied_dataset_count,
            vpsr.blocked_dataset_count,
            vpsr.require_real_vendor_env,
            vpsr.live_base_url_present,
            vpsr.live_token_present,
            vpsr.external_probe_allowed,
            vpsr.routing_change_allowed,
            vpsr.routing_change_applied,
            vpsr.rollback_guard_armed,
            vpsr.production_score,
            vpsr.blocking_issues,
            vpsr.required_actions,
            vpsr.error_message,
            vpsr.started_at, vpsr.finished_at,
            vpsr.duration_ms, vpsr.created_at,
            vpsr.updated_at
        FROM qmeta.vendor_production_source_run vpsr
        JOIN qmeta.source_system ss ON ss.source_id = vpsr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vpsr.primary_source_id
        {where}
        ORDER BY vpsr.as_of_at DESC, vpsr.production_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_production_source_dataset_checks(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("production_code", "vpsr.production_code"),
            ("dataset_check_code", "vpsdc.dataset_check_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vpsdc.status"),
            ("production_role", "vpsdc.production_role"),
            ("route_policy_status", "vpsdc.route_policy_status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vpsdc.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vpsdc.dataset_check_id,
            vpsr.production_code,
            vpsdc.dataset_check_code,
            ss.source_code, dc.dataset_code,
            ps.source_code AS primary_source_code,
            vpsdc.as_of_date, vpsdc.status,
            vpsdc.production_role,
            vpsdc.contract_status,
            vpsdc.entitlement_status,
            vpsdc.allowed_role,
            vpsdc.procurement_status,
            vpsdc.procurement_role,
            vpsdc.canary_status,
            vpsdc.canary_signoff_status,
            vpsdc.full_market_status,
            vpsdc.full_market_signoff_status,
            vpsdc.promotion_status,
            vpsdc.promotion_result_status,
            vpsdc.stability_status,
            vpsdc.stability_score,
            vpsdc.optimization_status,
            vpsdc.route_plan_status,
            vpsdc.route_execution_status,
            vpsdc.route_policy_status,
            vpsdc.current_primary_source_code,
            vpsdc.is_primary_route,
            vpsdc.recommended_primary_weight_pct,
            vpsdc.applied_primary_weight_pct,
            vpsdc.production_score,
            vpsdc.blocking_issues,
            vpsdc.required_actions,
            vpsdc.error_message,
            vpsdc.created_at,
            vpsdc.updated_at
        FROM qmeta.vendor_production_source_dataset_check vpsdc
        JOIN qmeta.vendor_production_source_run vpsr ON vpsr.production_id = vpsdc.production_id
        JOIN qmeta.source_system ss ON ss.source_id = vpsdc.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vpsdc.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vpsdc.primary_source_id
        {where}
        ORDER BY vpsdc.created_at DESC, vpsdc.dataset_check_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_production_source_decisions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("production_code", "vpsr.production_code"),
            ("dataset_check_code", "vpsdc.dataset_check_code"),
            ("decision_code", "vpsd.decision_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("decision_type", "vpsd.decision_type"),
            ("status", "vpsd.status"),
            ("severity", "vpsd.severity"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vpsd.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vpsd.decision_id,
            vpsr.production_code,
            vpsdc.dataset_check_code,
            vpsd.decision_code,
            ss.source_code,
            dc.dataset_code,
            vpsd.decision_type,
            vpsd.status,
            vpsd.severity,
            vpsd.decision_summary,
            vpsd.blocking_issues,
            vpsd.required_actions,
            vpsd.error_message,
            vpsd.created_at,
            vpsd.updated_at
        FROM qmeta.vendor_production_source_decision vpsd
        JOIN qmeta.vendor_production_source_run vpsr ON vpsr.production_id = vpsd.production_id
        LEFT JOIN qmeta.vendor_production_source_dataset_check vpsdc ON vpsdc.dataset_check_id = vpsd.dataset_check_id
        JOIN qmeta.source_system ss ON ss.source_id = vpsd.source_id
        LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vpsd.dataset_id
        {where}
        ORDER BY vpsd.created_at DESC, vpsd.decision_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_eta6_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    if isinstance(rows, dict):
        data_rows = (
            rows.get("dataset_checks")
            if resource in {"dataset-checks", "checks"}
            else rows.get("decisions")
            if resource == "decisions"
            else [rows]
        )
    else:
        data_rows = rows
    data_rows = list(data_rows or [])
    lines = [f"eta6 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_production_inputs(
    postgres_dsn: str,
    *,
    source_code: str,
    primary_source_code: str,
    dataset_codes: list[str],
) -> list[dict[str, Any]]:
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
            SELECT ss.source_id, ss.source_code, vip.profile_id,
                   vip.status AS vendor_profile_status,
                   vip.auth_mode AS profile_auth_mode,
                   vip.enabled_datasets,
                   vip.rate_limit_per_min AS profile_rate_limit_per_min
            FROM qmeta.source_system ss
            LEFT JOIN qmeta.vendor_integration_profile vip ON vip.source_id = ss.source_id
            WHERE ss.source_code = %s
            ORDER BY vip.updated_at DESC NULLS LAST, vip.profile_id DESC NULLS LAST
            LIMIT 1
        ),
        primary_source AS (
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
        latest_entitlement AS (
            SELECT DISTINCT ON (vcde.dataset_id) vcde.*
            FROM qmeta.vendor_contract_dataset_entitlement vcde
            JOIN latest_contract lc ON lc.contract_id = vcde.contract_id
            JOIN selected_datasets sd ON sd.dataset_id = vcde.dataset_id
            ORDER BY vcde.dataset_id,
                CASE WHEN vcde.entitlement_status = 'active' AND vcde.allowed_role = 'primary_candidate' AND vcde.production_use_allowed IS TRUE THEN 0 ELSE 1 END,
                vcde.updated_at DESC,
                vcde.entitlement_id DESC
        ),
        latest_procurement AS (
            SELECT DISTINCT ON (vprs.dataset_id) vprs.*
            FROM qmeta.vendor_procurement_readiness_snapshot vprs
            JOIN vendor_source vs ON vs.source_id = vprs.source_id
            JOIN selected_datasets sd ON sd.dataset_id = vprs.dataset_id
            ORDER BY vprs.dataset_id, vprs.created_at DESC, vprs.snapshot_id DESC
        ),
        latest_canary AS (
            SELECT DISTINCT ON (vlpdr.dataset_id)
                vlpdr.*, vlpr.pilot_code, vlpr.signoff_status, vlpr.pilot_scope
            FROM qmeta.vendor_live_pilot_dataset_result vlpdr
            JOIN qmeta.vendor_live_pilot_run vlpr ON vlpr.pilot_id = vlpdr.pilot_id
            JOIN vendor_source vs ON vs.source_id = vlpdr.source_id
            WHERE vlpr.pilot_scope = 'canary'
            ORDER BY vlpdr.dataset_id, vlpdr.created_at DESC, vlpdr.result_id DESC
        ),
        latest_full_market AS (
            SELECT DISTINCT ON (vlpdr.dataset_id)
                vlpdr.*, vlpr.pilot_code, vlpr.signoff_status, vlpr.pilot_scope
            FROM qmeta.vendor_live_pilot_dataset_result vlpdr
            JOIN qmeta.vendor_live_pilot_run vlpr ON vlpr.pilot_id = vlpdr.pilot_id
            JOIN vendor_source vs ON vs.source_id = vlpdr.source_id
            WHERE vlpr.pilot_scope = 'full_market'
            ORDER BY vlpdr.dataset_id, vlpdr.created_at DESC, vlpdr.result_id DESC
        ),
        latest_promotion AS (
            SELECT DISTINCT ON (vppr.dataset_id)
                vppr.result_id AS promotion_result_id,
                vppr.result_code AS promotion_result_code,
                vppr.promotion_id AS promotion_run_id,
                vppr.source_id,
                vppr.dataset_id,
                vppr.primary_source_id AS promotion_primary_source_id,
                vppr.current_priority_id AS promotion_current_priority_id,
                vppr.current_primary_source_code AS promotion_current_primary_source_code,
                vppr.current_priority AS promotion_current_priority,
                vppr.evidence AS promotion_result_evidence,
                vppr.source_id AS promotion_source_id,
                vppr.dataset_id AS promotion_dataset_id,
                vppr.procurement_status AS promotion_procurement_status,
                vppr.procurement_role AS promotion_procurement_role,
                vppr.readiness_status AS promotion_readiness_status,
                vppr.canary_status AS promotion_canary_status,
                vppr.full_market_status AS promotion_full_market_status,
                vppr.promotion_role,
                vppr.status AS promotion_result_status,
                vppr.target_priority,
                vppr.routing_change_allowed AS promotion_routing_change_allowed,
                vppr.routing_change_applied AS promotion_routing_change_applied,
                vppr.promotion_score AS promotion_result_score,
                vppr.blocking_issues AS promotion_result_blocking_issues,
                vppr.required_actions AS promotion_result_required_actions,
                vppr.error_message AS promotion_result_error_message,
                vppr.created_at AS promotion_result_created_at,
                vppr.updated_at AS promotion_result_updated_at,
                vppr2.promotion_code,
                vppr2.status AS promotion_status,
                vppr2.apply_mode AS promotion_apply_mode
            FROM qmeta.vendor_primary_promotion_dataset_result vppr
            JOIN qmeta.vendor_primary_promotion_run vppr2 ON vppr2.promotion_id = vppr.promotion_id
            JOIN vendor_source vs ON vs.source_id = vppr.source_id
            ORDER BY vppr.dataset_id, vppr.created_at DESC, vppr.result_id DESC
        ),
        latest_stability AS (
            SELECT vpss.*
            FROM qmeta.vendor_primary_stability_snapshot vpss
            JOIN vendor_source vs ON vs.source_id = vpss.source_id
            ORDER BY vpss.as_of_at DESC, vpss.snapshot_id DESC
            LIMIT 1
        ),
        latest_stability_dataset AS (
            SELECT DISTINCT ON (vpsds.dataset_id) vpsds.*
            FROM qmeta.vendor_primary_stability_dataset_snapshot vpsds
            JOIN vendor_source vs ON vs.source_id = vpsds.source_id
            ORDER BY vpsds.dataset_id, vpsds.created_at DESC, vpsds.dataset_snapshot_id DESC
        ),
        latest_optimization AS (
            SELECT vcos.*
            FROM qmeta.vendor_cost_optimization_snapshot vcos
            JOIN vendor_source vs ON vs.source_id = vcos.source_id
            ORDER BY vcos.as_of_at DESC, vcos.optimization_id DESC
            LIMIT 1
        ),
        latest_route_plan AS (
            SELECT DISTINCT ON (vrwp.dataset_id) vrwp.*
            FROM qmeta.vendor_route_weight_plan vrwp
            JOIN latest_optimization lo ON lo.optimization_id = vrwp.optimization_id
            ORDER BY vrwp.dataset_id, vrwp.created_at DESC, vrwp.plan_id DESC
        ),
        latest_route_execution AS (
            SELECT vrwer.*
            FROM qmeta.vendor_route_weight_execution_run vrwer
            JOIN vendor_source vs ON vs.source_id = vrwer.source_id
            ORDER BY vrwer.as_of_at DESC, vrwer.execution_id DESC
            LIMIT 1
        ),
        latest_route_execution_dataset AS (
            SELECT DISTINCT ON (vrwed.dataset_id) vrwed.*
            FROM qmeta.vendor_route_weight_execution_dataset vrwed
            JOIN qmeta.vendor_route_weight_execution_run vrwer ON vrwer.execution_id = vrwed.execution_id
            JOIN vendor_source vs ON vs.source_id = vrwed.source_id
            ORDER BY vrwed.dataset_id, vrwed.created_at DESC, vrwed.execution_dataset_id DESC
        ),
        latest_policy AS (
            SELECT DISTINCT ON (srwp.dataset_id) srwp.*
            FROM qmeta.source_route_weight_policy srwp
            JOIN vendor_source vs ON vs.source_id = srwp.source_id
            WHERE srwp.policy_status = 'active'
              AND srwp.effective_date <= CURRENT_DATE
              AND (srwp.end_date IS NULL OR srwp.end_date >= CURRENT_DATE)
            ORDER BY srwp.dataset_id, srwp.created_at DESC, srwp.policy_id DESC
        ),
        latest_post_monitor AS (
            SELECT DISTINCT ON (vppdm.dataset_id) vppdm.*
            FROM qmeta.vendor_post_promotion_dataset_monitor vppdm
            JOIN vendor_source vs ON vs.source_id = vppdm.source_id
            ORDER BY vppdm.dataset_id, vppdm.created_at DESC, vppdm.result_id DESC
        ),
        latest_route_health AS (
            SELECT DISTINCT ON (srhs.dataset_id) srhs.*
            FROM qmeta.source_route_health_snapshot srhs
            JOIN vendor_source vs ON vs.source_id = srhs.source_id
            ORDER BY srhs.dataset_id, srhs.as_of_at DESC, srhs.snapshot_id DESC
        ),
        current_priority AS (
            SELECT DISTINCT ON (sp.dataset_id)
                sp.priority_id, sp.dataset_id, ss.source_code, sp.priority
            FROM qmeta.source_priority sp
            JOIN qmeta.source_system ss ON ss.source_id = sp.source_id
            WHERE sp.effective_date <= CURRENT_DATE
              AND (sp.end_date IS NULL OR sp.end_date >= CURRENT_DATE)
            ORDER BY sp.dataset_id, sp.priority ASC, sp.effective_date DESC, sp.priority_id DESC
        )
        SELECT
            vs.source_id, vs.source_code,
            vs.profile_id, vs.vendor_profile_status,
            vs.profile_auth_mode, vs.enabled_datasets,
            vs.profile_rate_limit_per_min,
            ps.source_id AS primary_source_id,
            ps.source_code AS primary_source_code,
            sd.dataset_id, sd.dataset_code,
            lc.contract_id, lc.contract_code,
            lc.procurement_status AS procurement_contract_status,
            lc.contract_status,
            lc.commercial_clearance,
            lc.redistribution_allowed AS contract_redistribution_allowed,
            lc.production_use_allowed AS contract_production_use_allowed,
            lc.contract_ref,
            lc.contract_end_date,
            lc.sla_uptime_pct AS contract_sla_uptime_pct,
            lc.rate_limit_per_min AS contract_rate_limit_per_min,
            lc.daily_quota AS contract_daily_quota,
            vcde.entitlement_id, vcde.entitlement_code,
            vcde.entitlement_status, vcde.allowed_role,
            vcde.commercial_use_allowed AS entitlement_commercial_use_allowed,
            vcde.redistribution_allowed AS entitlement_redistribution_allowed,
            vcde.production_use_allowed AS entitlement_production_use_allowed,
            vcde.schema_status,
            vcde.field_mapping_status,
            vcde.rate_limit_per_min AS entitlement_rate_limit_per_min,
            vcde.daily_quota AS entitlement_daily_quota,
            vprs.snapshot_id AS procurement_snapshot_id,
            vprs.snapshot_code AS procurement_snapshot_code,
            vprs.status AS procurement_status,
            vprs.procurement_role,
            vprs.readiness_score AS procurement_readiness_score,
            lcny.pilot_id AS canary_pilot_id,
            lcny.pilot_code AS canary_pilot_code,
            lcny.status AS canary_status,
            lcny.signoff_status AS canary_signoff_status,
            lcny.recommendation AS canary_recommendation,
            lcny.recommended_role AS canary_recommended_role,
            lfm.pilot_id AS full_market_pilot_id,
            lfm.pilot_code AS full_market_pilot_code,
            lfm.status AS full_market_status,
            lfm.signoff_status AS full_market_signoff_status,
            lfm.recommendation AS full_market_recommendation,
            lfm.recommended_role AS full_market_recommended_role,
            lp.promotion_run_id AS promotion_id,
            lp.promotion_code,
            lp.promotion_result_id,
            lp.promotion_result_code,
            lp.promotion_status,
            lp.promotion_result_status,
            lsd.snapshot_id AS stability_snapshot_id,
            lsd.snapshot_code AS stability_snapshot_code,
            lsdd.dataset_snapshot_id AS stability_dataset_snapshot_id,
            lsdd.dataset_snapshot_code AS stability_dataset_snapshot_code,
            COALESCE(lsdd.status, lsd.status) AS stability_status,
            COALESCE(lsdd.stability_score, lsd.stability_score, 0) AS stability_score,
            lo.optimization_id,
            lo.optimization_code,
            lo.status AS optimization_status,
            lrp.plan_id AS route_plan_id,
            lrp.plan_code AS route_plan_code,
            lrp.status AS route_plan_status,
            lrp.recommended_primary_weight_pct,
            lre.execution_id AS route_execution_id,
            lre.execution_code AS route_execution_code,
            lre.status AS route_execution_status,
            lred.execution_dataset_id AS route_execution_dataset_id,
            lred.execution_dataset_code AS route_execution_dataset_code,
            lred.status AS route_execution_dataset_status,
            COALESCE(lred.applied_primary_weight_pct, lre.applied_primary_weight_pct, 0) AS applied_primary_weight_pct,
            lpol.policy_status AS route_policy_status,
            cp.source_code AS current_primary_source_code,
            cp.priority AS current_priority,
            COALESCE(lp.promotion_current_primary_source_code = vs.source_code, lsdd.is_primary_route, lred.is_primary_route, cp.source_code = vs.source_code, FALSE) AS is_primary_route,
            lpm.status AS post_promotion_status,
            lrh.status AS source_route_health_status
        FROM selected_datasets sd
        CROSS JOIN vendor_source vs
        LEFT JOIN primary_source ps ON TRUE
        LEFT JOIN latest_contract lc ON TRUE
        LEFT JOIN latest_entitlement vcde ON vcde.dataset_id = sd.dataset_id
        LEFT JOIN latest_procurement vprs ON vprs.dataset_id = sd.dataset_id
        LEFT JOIN latest_canary lcny ON lcny.dataset_id = sd.dataset_id
        LEFT JOIN latest_full_market lfm ON lfm.dataset_id = sd.dataset_id
        LEFT JOIN latest_promotion lp ON lp.dataset_id = sd.dataset_id
        LEFT JOIN latest_stability lsd ON TRUE
        LEFT JOIN latest_stability_dataset lsdd ON lsdd.dataset_id = sd.dataset_id
        LEFT JOIN latest_optimization lo ON TRUE
        LEFT JOIN latest_route_plan lrp ON lrp.dataset_id = sd.dataset_id
        LEFT JOIN latest_route_execution lre ON TRUE
        LEFT JOIN latest_route_execution_dataset lred ON lred.dataset_id = sd.dataset_id
        LEFT JOIN latest_policy lpol ON lpol.dataset_id = sd.dataset_id
        LEFT JOIN current_priority cp ON cp.dataset_id = sd.dataset_id
        LEFT JOIN latest_post_monitor lpm ON lpm.dataset_id = sd.dataset_id
        LEFT JOIN latest_route_health lrh ON lrh.dataset_id = sd.dataset_id
        ORDER BY vs.source_code, sd.dataset_code
        """,
        [dataset_codes, source_code, primary_source_code],
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
            vs.source_id, vs.source_code,
            NULL::BIGINT AS profile_id,
            NULL::TEXT AS vendor_profile_status,
            ps.source_id AS primary_source_id,
            ps.source_code AS primary_source_code,
            sd.dataset_id, sd.dataset_code
        FROM selected_datasets sd
        CROSS JOIN vendor_source vs
        LEFT JOIN primary_source ps ON TRUE
        ORDER BY vs.source_code, sd.dataset_code
        """,
        [dataset_codes, source_code, primary_source_code],
    )


def _insert_production_run(postgres_dsn: str, run: dict[str, Any]) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_production_source_run (
                    production_code, source_id, primary_source_id,
                    as_of_date, requested_by, trigger_mode,
                    environment, closure_scope, closure_mode,
                    status, production_role, dataset_count,
                    authorized_dataset_count, live_ready_dataset_count,
                    pilot_ready_dataset_count, promoted_dataset_count,
                    stable_dataset_count, optimized_dataset_count,
                    route_ready_dataset_count,
                    production_ready_dataset_count,
                    applied_dataset_count, blocked_dataset_count,
                    require_real_vendor_env,
                    live_base_url_present, live_token_present,
                    token_digest, external_probe_allowed,
                    routing_change_allowed, routing_change_applied,
                    rollback_guard_armed, production_score,
                    blocking_issues, required_actions,
                    request_payload, response_payload,
                    evidence, error_message,
                    started_at, finished_at, duration_ms,
                    updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s,
                    %s,
                    %s, %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s::jsonb, %s::jsonb,
                    %s::jsonb, %s,
                    %s, %s, %s,
                    now()
                )
                RETURNING *
                """,
                (
                    run["production_code"],
                    run["source_id"],
                    run.get("primary_source_id"),
                    run["as_of_date"],
                    run["requested_by"],
                    run["trigger_mode"],
                    run["environment"],
                    run["closure_scope"],
                    run["closure_mode"],
                    run["status"],
                    run["production_role"],
                    run["dataset_count"],
                    run["authorized_dataset_count"],
                    run["live_ready_dataset_count"],
                    run["pilot_ready_dataset_count"],
                    run["promoted_dataset_count"],
                    run["stable_dataset_count"],
                    run["optimized_dataset_count"],
                    run["route_ready_dataset_count"],
                    run["production_ready_dataset_count"],
                    run["applied_dataset_count"],
                    run["blocked_dataset_count"],
                    run["require_real_vendor_env"],
                    run["live_base_url_present"],
                    run["live_token_present"],
                    run.get("token_digest"),
                    run["external_probe_allowed"],
                    run["routing_change_allowed"],
                    run["routing_change_applied"],
                    run["rollback_guard_armed"],
                    run["production_score"],
                    run["blocking_issues"],
                    run["required_actions"],
                    _json(run["request_payload"]),
                    _json(run["response_payload"]),
                    _json(run["evidence"]),
                    run.get("error_message"),
                    run["started_at"],
                    run["finished_at"],
                    run["duration_ms"],
                ),
            )
            stored = normalize_rows([dict(cursor.fetchone())])[0]
            stored["source_code"] = run.get("source_code")
            stored["primary_source_code"] = run.get("primary_source_code")
            return stored


def _insert_dataset_checks(postgres_dsn: str, run: dict[str, Any], checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for check in checks:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_production_source_dataset_check (
                        dataset_check_code, production_id,
                        source_id, dataset_id, primary_source_id,
                        contract_id, entitlement_id,
                        procurement_snapshot_id,
                        canary_pilot_id, full_market_pilot_id,
                        promotion_id, promotion_result_id,
                        stability_snapshot_id,
                        stability_dataset_snapshot_id,
                        optimization_id, route_plan_id,
                        route_execution_id,
                        route_execution_dataset_id,
                        as_of_date, status, production_role,
                        contract_status, entitlement_status,
                        allowed_role, procurement_status,
                        procurement_role, canary_status,
                        canary_signoff_status, full_market_status,
                        full_market_signoff_status,
                        promotion_status,
                        promotion_result_status,
                        stability_status, stability_score,
                        optimization_status, route_plan_status,
                        route_execution_status,
                        route_policy_status,
                        current_primary_source_code,
                        is_primary_route,
                        recommended_primary_weight_pct,
                        applied_primary_weight_pct,
                        production_score,
                        blocking_issues, required_actions,
                        evidence, error_message, updated_at
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        %s,
                        %s, %s,
                        %s,
                        %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        %s,
                        %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        %s,
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
                        check["dataset_check_code"],
                        run["production_id"],
                        check["source_id"],
                        check["dataset_id"],
                        check.get("primary_source_id"),
                        check.get("contract_id"),
                        check.get("entitlement_id"),
                        check.get("procurement_snapshot_id"),
                        check.get("canary_pilot_id"),
                        check.get("full_market_pilot_id"),
                        check.get("promotion_id"),
                        check.get("promotion_result_id"),
                        check.get("stability_snapshot_id"),
                        check.get("stability_dataset_snapshot_id"),
                        check.get("optimization_id"),
                        check.get("route_plan_id"),
                        check.get("route_execution_id"),
                        check.get("route_execution_dataset_id"),
                        check["as_of_date"],
                        check["status"],
                        check["production_role"],
                        check.get("contract_status"),
                        check.get("entitlement_status"),
                        check.get("allowed_role"),
                        check.get("procurement_status"),
                        check.get("procurement_role"),
                        check.get("canary_status"),
                        check.get("canary_signoff_status"),
                        check.get("full_market_status"),
                        check.get("full_market_signoff_status"),
                        check.get("promotion_status"),
                        check.get("promotion_result_status"),
                        check.get("stability_status"),
                        check["stability_score"],
                        check.get("optimization_status"),
                        check.get("route_plan_status"),
                        check.get("route_execution_status"),
                        check.get("route_policy_status"),
                        check.get("current_primary_source_code"),
                        check["is_primary_route"],
                        check["recommended_primary_weight_pct"],
                        check["applied_primary_weight_pct"],
                        check["production_score"],
                        check["blocking_issues"],
                        check["required_actions"],
                        _json(check["evidence"]),
                        check.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row.update(
                    {
                        "production_code": run.get("production_code"),
                        "source_code": check.get("source_code"),
                        "dataset_code": check.get("dataset_code"),
                        "primary_source_code": check.get("primary_source_code"),
                    }
                )
                inserted.append(row)
    return inserted


def _insert_decisions(postgres_dsn: str, run: dict[str, Any], checks: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    check_by_code = {row["dataset_check_code"]: row for row in checks}
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for decision in decisions:
                check = check_by_code.get(str(decision.get("dataset_check_code") or ""))
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_production_source_decision (
                        decision_code, production_id,
                        dataset_check_id, source_id, dataset_id,
                        decision_type, status, severity,
                        decision_summary, blocking_issues,
                        required_actions, evidence,
                        error_message, updated_at
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s::jsonb,
                        %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        decision["decision_code"],
                        run["production_id"],
                        check.get("dataset_check_id") if check else None,
                        decision["source_id"],
                        decision.get("dataset_id"),
                        decision["decision_type"],
                        decision["status"],
                        decision["severity"],
                        decision.get("decision_summary"),
                        decision["blocking_issues"],
                        decision["required_actions"],
                        _json(decision["evidence"]),
                        decision.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row.update(
                    {
                        "production_code": run.get("production_code"),
                        "dataset_check_code": decision.get("dataset_check_code"),
                        "source_code": decision.get("source_code"),
                        "dataset_code": decision.get("dataset_code"),
                    }
                )
                inserted.append(row)
    return inserted


def _validate_inputs(**kwargs: Any) -> None:
    if not kwargs.get("requested_by"):
        raise QDataValidationError("requested_by is required")
    if kwargs.get("trigger_mode") not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: " + ", ".join(sorted(TRIGGER_MODES)))
    if kwargs.get("environment") not in ENVIRONMENTS:
        raise QDataValidationError("environment must be one of: " + ", ".join(sorted(ENVIRONMENTS)))
    if kwargs.get("closure_scope") not in CLOSURE_SCOPES:
        raise QDataValidationError("closure_scope must be one of: " + ", ".join(sorted(CLOSURE_SCOPES)))
    if kwargs.get("closure_mode") not in CLOSURE_MODES:
        raise QDataValidationError("closure_mode must be one of: " + ", ".join(sorted(CLOSURE_MODES)))
    if float(kwargs.get("min_stability_score") or 0) < 0:
        raise QDataValidationError("min_stability_score must be non-negative")


def _pilot_ok(row: dict[str, Any], prefix: str) -> bool:
    return (
        row.get(f"{prefix}_status") in {"success", "warning"}
        and row.get(f"{prefix}_signoff_status") == "approved"
        and row.get(f"{prefix}_recommendation") == "primary_candidate"
        and row.get(f"{prefix}_recommended_role") == "primary_candidate"
    )


def _token_present(config: Any) -> bool:
    if config.auth_mode == "none":
        return True
    if config.auth_mode == "basic":
        return bool(config.username and config.password)
    return bool(config.token)


def _dataset_evidence(row: dict[str, Any], runtime: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "gates": evaluation["gates"],
        "contract_code": row.get("contract_code"),
        "entitlement_code": row.get("entitlement_code"),
        "procurement_snapshot_code": row.get("procurement_snapshot_code"),
        "canary_pilot_code": row.get("canary_pilot_code"),
        "full_market_pilot_code": row.get("full_market_pilot_code"),
        "promotion_code": row.get("promotion_code"),
        "stability_snapshot_code": row.get("stability_snapshot_code"),
        "optimization_code": row.get("optimization_code"),
        "route_execution_code": row.get("route_execution_code"),
        "route_policy_status": row.get("route_policy_status"),
        "token_digest_tail": runtime.get("token_digest_tail"),
        "token_material_persisted": False,
    }


def _required_actions(issues: Iterable[str], status: str) -> list[str]:
    issue_text = " ".join(issues)
    actions: list[str] = []
    if "missing_env" in issue_text or "vendor_profile" in issue_text:
        actions.append("Configure real QDATA_VENDOR_BASE_URL/QDATA_VENDOR_TOKEN and activate the vendor profile.")
    if "contract" in issue_text or "entitlement" in issue_text or "procurement" in issue_text:
        actions.append("Move contract and dataset entitlement to active production-use status, then rerun Omicron-5 readiness.")
    if "theta3" in issue_text:
        actions.append("Run Theta-3 canary and full-market live pilot with approved signoff.")
    if "pi5" in issue_text:
        actions.append("Run Pi-5 primary promotion after procurement and pilot evidence are ready.")
    if "sigma5" in issue_text:
        actions.append("Run Sigma-5 primary stability until the production source is healthy.")
    if "tau5" in issue_text:
        actions.append("Run Tau-5 cost optimization and quota stress before rollout.")
    if "upsilon5" in issue_text:
        actions.append("Run Upsilon-5 route execution or create an active route weight policy.")
    if "rollback_guard" in issue_text:
        actions.append("Resolve rollback guardrails before increasing primary traffic.")
    if not actions and status in {"production_ready", "monitoring"}:
        actions.append("Keep Kappa/Upsilon monitoring active and retain rollback guardrails.")
    elif not actions:
        actions.append("Review Eta-6 dataset blockers before production rollout.")
    return _dedupe(actions)


def _decision_summary(decision_type: str, status: str, check: dict[str, Any]) -> str:
    return f"{decision_type} {status} for {check.get('source_code')}/{check.get('dataset_code')} status={check.get('status')}"


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "runs": ["as_of_at", "production_code", "source_code", "primary_source_code", "status", "production_role", "closure_mode", "dataset_count", "production_ready_dataset_count", "applied_dataset_count", "blocked_dataset_count", "live_base_url_present", "live_token_present", "routing_change_allowed", "production_score", "error_message"],
        "run": ["production_code", "source_code", "primary_source_code", "status", "production_role", "dataset_count", "production_ready_dataset_count", "blocked_dataset_count", "live_base_url_present", "live_token_present", "production_score", "error_message"],
        "dataset-checks": ["created_at", "production_code", "dataset_check_code", "source_code", "dataset_code", "status", "production_role", "contract_status", "entitlement_status", "procurement_status", "canary_status", "full_market_status", "promotion_result_status", "stability_status", "optimization_status", "route_execution_status", "route_policy_status", "production_score", "error_message"],
        "checks": ["created_at", "production_code", "dataset_check_code", "source_code", "dataset_code", "status", "production_role", "production_score", "error_message"],
        "decisions": ["created_at", "production_code", "dataset_check_code", "decision_code", "source_code", "dataset_code", "decision_type", "status", "severity", "decision_summary", "error_message"],
    }
    preferred = preferred_by_resource.get(resource, [])
    if preferred:
        return [key for key in preferred if key in row]
    return [key for key in row]


def _code(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}-{timestamp}-{digest}"
