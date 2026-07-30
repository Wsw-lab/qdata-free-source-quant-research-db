from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omicron5_vendor_contract import DEFAULT_VENDOR_DATASETS, DEFAULT_VENDOR_SOURCE_CODES


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
PROMOTION_SCOPES = {"canary", "full_market"}
PROMOTION_STATUSES = {"blocked", "canary_required", "full_market_required", "pending_signoff", "approved_for_primary", "applied"}
APPLY_MODES = {"review_only", "dry_run", "apply"}


def run_vendor_primary_promotion_review(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    source_code: str = DEFAULT_VENDOR_SOURCE_CODES[0],
    primary_source_code: str = "csv",
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "pi5",
    trigger_mode: str = "manual",
    environment: str = "local",
    promotion_scope: str = "full_market",
    required_windows: Iterable[int] = (5, 20, 60),
    require_full_market: bool = True,
    require_signoff: bool = True,
    apply_routing: bool = False,
    target_priority: int = 0,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        promotion_scope=promotion_scope,
        required_windows=required_windows,
        target_priority=target_priority,
    )
    snapshot_date = _as_of_date(as_of_date)
    windows = _normalize_windows(required_windows)
    datasets = _normalize_optional_codes(dataset_codes) or list(DEFAULT_VENDOR_DATASETS)
    rows = _load_promotion_inputs(
        _require_dsn(postgres_dsn),
        as_of_date=snapshot_date,
        source_code=source_code,
        primary_source_code=primary_source_code,
        dataset_codes=datasets,
    )
    results = build_vendor_primary_promotion_results(
        rows,
        as_of_date=snapshot_date,
        promotion_scope=promotion_scope,
        required_windows=windows,
        require_full_market=require_full_market,
        require_signoff=require_signoff,
        target_priority=target_priority,
    )
    can_apply = apply_routing and results and all(row["routing_change_allowed"] or row["status"] == "applied" for row in results)
    if can_apply:
        _mark_applied_results(results)
    run = build_vendor_primary_promotion_run(
        results,
        source_code=source_code,
        primary_source_code=primary_source_code,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        promotion_scope=promotion_scope,
        required_windows=windows,
        require_full_market=require_full_market,
        require_signoff=require_signoff,
        apply_mode="apply" if apply_routing else "review_only",
        target_priority=target_priority,
    )
    if apply_routing and not can_apply:
        run["blocking_issues"] = _dedupe(list(run["blocking_issues"]) + ["apply_routing_blocked_until_all_datasets_approved"])
        run["required_actions"] = _dedupe(list(run["required_actions"]) + ["Keep apply_routing disabled until every dataset is approved_for_primary or already applied."])
        run["error_message"] = "; ".join(run["blocking_issues"])
    if not write_db:
        run["results"] = normalize_rows(results)
        return normalize_rows([run])[0]
    if can_apply:
        _apply_source_priority(
            _require_dsn(postgres_dsn),
            results,
            source_code=source_code,
            effective_date=snapshot_date,
            target_priority=target_priority,
        )
    stored = _insert_promotion_run(_require_dsn(postgres_dsn), run, results)
    stored["results"] = _insert_promotion_results(_require_dsn(postgres_dsn), stored, results)
    return stored


def build_vendor_primary_promotion_results(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    promotion_scope: str = "full_market",
    required_windows: Iterable[int] = (5, 20, 60),
    require_full_market: bool = True,
    require_signoff: bool = True,
    target_priority: int = 0,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    windows = _normalize_windows(required_windows)
    results: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        evaluation = evaluate_vendor_primary_promotion(
            row,
            required_windows=windows,
            require_full_market=require_full_market,
            require_signoff=require_signoff,
            target_priority=target_priority,
        )
        result = {
            "result_code": _result_code(str(row.get("source_code") or "unknown"), str(row.get("dataset_code") or "unknown"), evaluation["status"]),
            "source_id": row["source_id"],
            "dataset_id": row["dataset_id"],
            "primary_source_id": row.get("primary_source_id"),
            "source_code": row.get("source_code"),
            "dataset_code": row.get("dataset_code"),
            "primary_source_code": row.get("primary_source_code"),
            "procurement_snapshot_id": row.get("procurement_snapshot_id"),
            "procurement_snapshot_code": row.get("procurement_snapshot_code"),
            "readiness_review_id": row.get("readiness_review_id"),
            "readiness_review_code": row.get("readiness_review_code"),
            "canary_pilot_id": row.get("canary_pilot_id"),
            "canary_pilot_code": row.get("canary_pilot_code"),
            "full_market_pilot_id": row.get("full_market_pilot_id"),
            "full_market_pilot_code": row.get("full_market_pilot_code"),
            "current_priority_id": row.get("current_priority_id"),
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": row.get("current_priority"),
            "target_priority": target_priority,
            "as_of_date": snapshot_date.isoformat(),
            "promotion_scope": promotion_scope,
            "status": evaluation["status"],
            "promotion_role": evaluation["promotion_role"],
            "routing_change_allowed": evaluation["routing_change_allowed"],
            "routing_change_applied": False,
            "procurement_status": row.get("procurement_status"),
            "procurement_role": row.get("procurement_role"),
            "readiness_status": row.get("readiness_status"),
            "readiness_recommendation": row.get("readiness_recommendation"),
            "readiness_recommended_role": row.get("readiness_recommended_role"),
            "canary_status": row.get("canary_status"),
            "canary_signoff_status": row.get("canary_signoff_status"),
            "canary_recommendation": row.get("canary_recommendation"),
            "canary_risk_level": row.get("canary_risk_level"),
            "full_market_status": row.get("full_market_status"),
            "full_market_signoff_status": row.get("full_market_signoff_status"),
            "full_market_recommendation": row.get("full_market_recommendation"),
            "full_market_risk_level": row.get("full_market_risk_level"),
            "promotion_score": evaluation["promotion_score"],
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": evaluation["required_actions"],
            "evidence": _result_evidence(row, windows, require_full_market, require_signoff, target_priority),
            "error_message": "; ".join(evaluation["blocking_issues"]) if evaluation["status"] in {"blocked", "canary_required", "full_market_required", "pending_signoff"} and evaluation["blocking_issues"] else None,
        }
        results.append(result)
    return results


def evaluate_vendor_primary_promotion(
    row: dict[str, Any],
    *,
    required_windows: Iterable[int] = (5, 20, 60),
    require_full_market: bool = True,
    require_signoff: bool = True,
    target_priority: int = 0,
) -> dict[str, Any]:
    windows = _normalize_windows(required_windows)
    issues: list[str] = []

    procurement_ready = row.get("procurement_status") == "ready" and row.get("procurement_role") == "primary_candidate"
    if not row.get("procurement_snapshot_id"):
        issues.append("omicron5_procurement_readiness_missing")
    elif not procurement_ready:
        issues.append(f"omicron5_procurement_not_primary_candidate:{row.get('procurement_status') or 'missing'}/{row.get('procurement_role') or 'missing'}")

    readiness_ready = (
        row.get("readiness_status") == "ready"
        and row.get("readiness_recommendation") == "approve_primary"
        and row.get("readiness_recommended_role") == "primary"
        and _covers_windows(row.get("readiness_required_windows"), windows)
        and int(row.get("readiness_missing_window_count") or 0) == 0
        and int(row.get("readiness_failed_window_count") or 0) == 0
    )
    if not row.get("readiness_review_id"):
        issues.append("pi_readiness_review_missing")
    elif not readiness_ready:
        issues.append(f"pi_readiness_not_approve_primary:{row.get('readiness_status') or 'missing'}/{row.get('readiness_recommendation') or 'missing'}/{row.get('readiness_recommended_role') or 'missing'}")

    canary_ready = _pilot_ready(row, "canary")
    if not row.get("canary_pilot_id"):
        issues.append("theta3_canary_pilot_missing")
    elif not canary_ready:
        issues.append(f"theta3_canary_pilot_not_ready:{row.get('canary_status') or 'missing'}/{row.get('canary_recommendation') or 'missing'}/{row.get('canary_signoff_status') or 'missing'}")

    full_market_ready = _pilot_ready(row, "full_market")
    if require_full_market:
        if not row.get("full_market_pilot_id"):
            issues.append("theta3_full_market_pilot_missing")
        elif not full_market_ready:
            issues.append(f"theta3_full_market_pilot_not_ready:{row.get('full_market_status') or 'missing'}/{row.get('full_market_recommendation') or 'missing'}/{row.get('full_market_signoff_status') or 'missing'}")

    signoff_ready = _signoff_ready(row, require_full_market)
    if require_signoff and not signoff_ready:
        issues.append("promotion_signoff_not_approved")

    if not row.get("primary_source_id"):
        issues.append("primary_source_not_found")

    current_primary_source_code = row.get("current_primary_source_code")
    target_source_code = row.get("source_code")
    already_primary = bool(current_primary_source_code and current_primary_source_code == target_source_code and _int_or_none(row.get("current_priority")) == target_priority)

    non_signoff_issues = [issue for issue in issues if issue != "promotion_signoff_not_approved"]
    if not procurement_ready or not row.get("procurement_snapshot_id"):
        status = "blocked"
        role = "blocked"
    elif not readiness_ready or not row.get("readiness_review_id"):
        status = "blocked"
        role = "blocked"
    elif not canary_ready or not row.get("canary_pilot_id"):
        status = "canary_required"
        role = "validator"
    elif require_full_market and (not full_market_ready or not row.get("full_market_pilot_id")):
        status = "full_market_required"
        role = "backup"
    elif require_signoff and not signoff_ready and not non_signoff_issues:
        status = "pending_signoff"
        role = "backup"
    elif issues:
        status = "blocked"
        role = "blocked"
    elif already_primary:
        status = "applied"
        role = "primary"
    else:
        status = "approved_for_primary"
        role = "primary"

    return {
        "status": status,
        "promotion_role": role,
        "routing_change_allowed": status == "approved_for_primary",
        "promotion_score": _promotion_score(procurement_ready, readiness_ready, canary_ready, full_market_ready, signoff_ready, require_full_market, require_signoff),
        "blocking_issues": _dedupe(issues),
        "required_actions": build_vendor_primary_promotion_required_actions(_dedupe(issues), status),
    }


def build_vendor_primary_promotion_run(
    results: list[dict[str, Any]],
    *,
    source_code: str,
    primary_source_code: str,
    as_of_date: str | date | None = None,
    requested_by: str = "pi5",
    trigger_mode: str = "manual",
    environment: str = "local",
    promotion_scope: str = "full_market",
    required_windows: Iterable[int] = (5, 20, 60),
    require_full_market: bool = True,
    require_signoff: bool = True,
    apply_mode: str = "review_only",
    target_priority: int = 0,
) -> dict[str, Any]:
    snapshot_date = _as_of_date(as_of_date)
    windows = _normalize_windows(required_windows)
    statuses = [str(result.get("status")) for result in results]
    status = _aggregate_status(statuses)
    blocking_issues = _dedupe(issue for result in results for issue in result.get("blocking_issues") or [])
    required_actions = _dedupe(action for result in results for action in result.get("required_actions") or [])
    current_primaries = _dedupe(str(result.get("current_primary_source_code")) for result in results if result.get("current_primary_source_code"))
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)
    return {
        "promotion_code": _promotion_code(source_code, promotion_scope, status),
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "as_of_date": snapshot_date.isoformat(),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "promotion_scope": promotion_scope,
        "status": status,
        "apply_mode": apply_mode,
        "routing_change_allowed": bool(results) and all(result.get("routing_change_allowed") or result.get("status") == "applied" for result in results),
        "routing_change_applied": bool(results) and all(result.get("routing_change_applied") or result.get("status") == "applied" for result in results),
        "dataset_count": len(results),
        "approved_dataset_count": sum(1 for result in results if result.get("status") == "approved_for_primary"),
        "pending_dataset_count": sum(1 for result in results if result.get("status") in {"canary_required", "full_market_required", "pending_signoff"}),
        "blocked_dataset_count": sum(1 for result in results if result.get("status") == "blocked"),
        "applied_dataset_count": sum(1 for result in results if result.get("status") == "applied" or result.get("routing_change_applied")),
        "canary_ready_count": sum(1 for result in results if result.get("canary_status") == "success" and result.get("canary_recommendation") == "primary_candidate"),
        "full_market_ready_count": sum(1 for result in results if result.get("full_market_status") == "success" and result.get("full_market_recommendation") == "primary_candidate"),
        "signoff_ready_count": sum(1 for result in results if _result_signoff_ready(result, require_full_market)),
        "required_windows": windows,
        "require_full_market": require_full_market,
        "require_signoff": require_signoff,
        "target_priority": target_priority,
        "current_primary_source_codes": current_primaries,
        "promotion_score": _average_score(results),
        "blocking_issues": blocking_issues,
        "required_actions": required_actions or build_vendor_primary_promotion_required_actions(blocking_issues, status),
        "request_payload": {
            "source_code": source_code,
            "primary_source_code": primary_source_code,
            "dataset_codes": [result.get("dataset_code") for result in results],
            "required_windows": windows,
            "promotion_scope": promotion_scope,
            "require_full_market": require_full_market,
            "require_signoff": require_signoff,
            "apply_mode": apply_mode,
            "target_priority": target_priority,
        },
        "response_payload": {
            "status": status,
            "dataset_count": len(results),
            "approved_dataset_count": sum(1 for result in results if result.get("status") == "approved_for_primary"),
            "blocked_dataset_count": sum(1 for result in results if result.get("status") == "blocked"),
        },
        "evidence": {
            "policy": {
                "requires_omicron5_primary_candidate": True,
                "requires_pi_5_20_60_approve_primary": True,
                "requires_theta3_canary": True,
                "requires_theta3_full_market": require_full_market,
                "requires_business_signoff": require_signoff,
            }
        },
        "error_message": "; ".join(blocking_issues) if status in {"blocked", "canary_required", "full_market_required", "pending_signoff"} and blocking_issues else None,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
    }


def build_vendor_primary_promotion_required_actions(issues: list[str], status: str) -> list[str]:
    issue_text = " ".join(issues)
    actions: list[str] = []
    if "omicron5_procurement" in issue_text:
        actions.append("Complete Omicron-5 contract, entitlement, redistribution, production-use, SLA and quota readiness before routing promotion.")
    if "pi_readiness" in issue_text:
        actions.append("Complete Pi 5/20/60 benchmark readiness with approve_primary and primary role.")
    if "theta3_canary" in issue_text:
        actions.append("Run Theta-3 canary live pilot successfully before any full-market promotion.")
    if "theta3_full_market" in issue_text:
        actions.append("Run Theta-3 full-market pilot successfully after canary passes.")
    if "promotion_signoff" in issue_text:
        actions.append("Collect legal, data owner and quant platform signoff before routing change.")
    if "primary_source_not_found" in issue_text:
        actions.append("Register the current primary source before computing a promotion diff.")
    if status == "approved_for_primary":
        actions.append("Promotion is approved for controlled source_priority application with rollback monitoring.")
    elif status == "applied":
        actions.append("Keep post-promotion monitoring active and retain previous source as fallback.")
    else:
        actions.append("Do not modify source_priority until Pi-5 blockers are closed.")
    return _dedupe(actions)


def list_vendor_primary_promotions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("promotion_code", "vppr.promotion_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vppr.status"),
            ("promotion_status", "vppr.status"),
            ("promotion_scope", "vppr.promotion_scope"),
            ("apply_mode", "vppr.apply_mode"),
            ("requested_by", "vppr.requested_by"),
            ("trigger_mode", "vppr.trigger_mode"),
            ("environment", "vppr.environment"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "vppr.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "vppr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vppr.promotion_id, vppr.promotion_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vppr.as_of_date, vppr.requested_by, vppr.trigger_mode,
            vppr.environment, vppr.promotion_scope, vppr.status,
            vppr.apply_mode, vppr.routing_change_allowed,
            vppr.routing_change_applied, vppr.dataset_count,
            vppr.approved_dataset_count, vppr.pending_dataset_count,
            vppr.blocked_dataset_count, vppr.applied_dataset_count,
            vppr.canary_ready_count, vppr.full_market_ready_count,
            vppr.signoff_ready_count, vppr.required_windows,
            vppr.require_full_market, vppr.require_signoff,
            vppr.target_priority, vppr.current_primary_source_codes,
            vppr.promotion_score, vppr.blocking_issues,
            vppr.required_actions, vppr.error_message,
            vppr.started_at, vppr.finished_at, vppr.duration_ms,
            vppr.created_at, vppr.updated_at
        FROM qmeta.vendor_primary_promotion_run vppr
        JOIN qmeta.source_system ss ON ss.source_id = vppr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vppr.primary_source_id
        {where}
        ORDER BY vppr.started_at DESC, vppr.promotion_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_primary_promotion_results(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("promotion_code", "vppr.promotion_code"),
            ("result_code", "vppdr.result_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vppdr.status"),
            ("promotion_status", "vppdr.status"),
            ("promotion_scope", "vppr.promotion_scope"),
            ("apply_mode", "vppr.apply_mode"),
            ("promotion_role", "vppdr.promotion_role"),
            ("procurement_status", "vppdr.procurement_status"),
            ("procurement_role", "vppdr.procurement_role"),
            ("readiness_status", "vppdr.readiness_status"),
            ("canary_status", "vppdr.canary_status"),
            ("full_market_status", "vppdr.full_market_status"),
            ("canary_signoff_status", "vppdr.canary_signoff_status"),
            ("full_market_signoff_status", "vppdr.full_market_signoff_status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vppdr.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vppdr.result_id, vppr.promotion_code,
            vppdr.result_code, ss.source_code,
            ps.source_code AS primary_source_code,
            dc.dataset_code, vppdr.current_primary_source_code,
            vppdr.current_priority, vppdr.target_priority,
            vppdr.status, vppdr.promotion_role,
            vppdr.routing_change_allowed,
            vppdr.routing_change_applied,
            vppdr.procurement_snapshot_code,
            vppdr.procurement_status, vppdr.procurement_role,
            vppdr.readiness_review_code,
            vppdr.readiness_status, vppdr.readiness_recommendation,
            vppdr.readiness_recommended_role,
            vppdr.canary_pilot_code, vppdr.canary_status,
            vppdr.canary_signoff_status,
            vppdr.canary_recommendation,
            vppdr.canary_risk_level,
            vppdr.full_market_pilot_code,
            vppdr.full_market_status,
            vppdr.full_market_signoff_status,
            vppdr.full_market_recommendation,
            vppdr.full_market_risk_level,
            vppdr.promotion_score, vppdr.blocking_issues,
            vppdr.required_actions, vppdr.error_message,
            vppdr.created_at, vppdr.updated_at
        FROM qmeta.vendor_primary_promotion_dataset_result vppdr
        JOIN qmeta.vendor_primary_promotion_run vppr ON vppr.promotion_id = vppdr.promotion_id
        JOIN qmeta.source_system ss ON ss.source_id = vppdr.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vppdr.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vppdr.primary_source_id
        {where}
        ORDER BY vppdr.created_at DESC, vppdr.result_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_pi5_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    if isinstance(rows, dict):
        data_rows = rows.get("results") if resource == "results" else [rows]
    else:
        data_rows = rows
    data_rows = list(data_rows or [])
    lines = [f"pi5 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_promotion_inputs(
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
        SELECT
            ss.source_id, ss.source_code,
            ps.source_id AS primary_source_id,
            ps.source_code AS primary_source_code,
            dc.dataset_id, dc.dataset_code,
            vcp.contract_id, vcp.contract_code,
            vcde.entitlement_id, vcde.entitlement_code,
            latest_proc.snapshot_id AS procurement_snapshot_id,
            latest_proc.snapshot_code AS procurement_snapshot_code,
            latest_proc.status AS procurement_status,
            latest_proc.procurement_role,
            latest_proc.readiness_score AS procurement_readiness_score,
            latest_pi.review_id AS readiness_review_id,
            latest_pi.review_code AS readiness_review_code,
            latest_pi.status AS readiness_status,
            latest_pi.recommendation AS readiness_recommendation,
            latest_pi.recommended_role AS readiness_recommended_role,
            latest_pi.required_windows AS readiness_required_windows,
            latest_pi.suite_count AS readiness_suite_count,
            latest_pi.failed_window_count AS readiness_failed_window_count,
            latest_pi.missing_window_count AS readiness_missing_window_count,
            latest_canary.pilot_id AS canary_pilot_id,
            latest_canary.pilot_code AS canary_pilot_code,
            latest_canary.status AS canary_status,
            latest_canary.signoff_status AS canary_signoff_status,
            latest_canary.recommendation AS canary_recommendation,
            latest_canary.recommended_role AS canary_recommended_role,
            latest_canary.risk_level AS canary_risk_level,
            latest_full.pilot_id AS full_market_pilot_id,
            latest_full.pilot_code AS full_market_pilot_code,
            latest_full.status AS full_market_status,
            latest_full.signoff_status AS full_market_signoff_status,
            latest_full.recommendation AS full_market_recommendation,
            latest_full.recommended_role AS full_market_recommended_role,
            latest_full.risk_level AS full_market_risk_level,
            current_priority.priority_id AS current_priority_id,
            current_priority.source_code AS current_primary_source_code,
            current_priority.priority AS current_priority
        FROM qmeta.vendor_contract_dataset_entitlement vcde
        JOIN qmeta.vendor_contract_profile vcp ON vcp.contract_id = vcde.contract_id
        JOIN qmeta.source_system ss ON ss.source_id = vcde.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vcde.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_code = %s
        LEFT JOIN LATERAL (
            SELECT snapshot_id, snapshot_code, status, procurement_role, readiness_score, created_at
            FROM qmeta.vendor_procurement_readiness_snapshot vprs
            WHERE vprs.source_id = vcde.source_id
              AND vprs.dataset_id = vcde.dataset_id
            ORDER BY vprs.as_of_date DESC, vprs.created_at DESC, vprs.snapshot_id DESC
            LIMIT 1
        ) latest_proc ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                review_id, review_code, status, recommendation,
                recommended_role, required_windows, suite_count,
                failed_window_count, missing_window_count, updated_at
            FROM qmeta.vendor_readiness_review vrr
            WHERE vrr.source_id = vcde.source_id
              AND vrr.dataset_id = vcde.dataset_id
              AND (ps.source_id IS NULL OR vrr.primary_source_id = ps.source_id)
            ORDER BY vrr.review_date DESC, vrr.updated_at DESC, vrr.review_id DESC
            LIMIT 1
        ) latest_pi ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                vlpr.pilot_id, vlpr.pilot_code, vlpr.status,
                vlpr.signoff_status, vlpr.recommendation,
                vlpr.recommended_role, vlpr.risk_level, vlpr.started_at
            FROM qmeta.vendor_live_pilot_dataset_result vlpdr
            JOIN qmeta.vendor_live_pilot_run vlpr ON vlpr.pilot_id = vlpdr.pilot_id
            WHERE vlpdr.source_id = vcde.source_id
              AND vlpdr.dataset_id = vcde.dataset_id
              AND vlpr.pilot_scope = 'canary'
            ORDER BY vlpdr.started_at DESC, vlpdr.result_id DESC
            LIMIT 1
        ) latest_canary ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                vlpr.pilot_id, vlpr.pilot_code, vlpr.status,
                vlpr.signoff_status, vlpr.recommendation,
                vlpr.recommended_role, vlpr.risk_level, vlpr.started_at
            FROM qmeta.vendor_live_pilot_dataset_result vlpdr
            JOIN qmeta.vendor_live_pilot_run vlpr ON vlpr.pilot_id = vlpdr.pilot_id
            WHERE vlpdr.source_id = vcde.source_id
              AND vlpdr.dataset_id = vcde.dataset_id
              AND (vlpr.pilot_scope = 'full_market' OR vlpr.full_market IS TRUE)
            ORDER BY vlpdr.started_at DESC, vlpdr.result_id DESC
            LIMIT 1
        ) latest_full ON TRUE
        LEFT JOIN LATERAL (
            SELECT sp.priority_id, ssp.source_code, sp.priority
            FROM qmeta.source_priority sp
            JOIN qmeta.source_system ssp ON ssp.source_id = sp.source_id
            WHERE sp.dataset_id = vcde.dataset_id
              AND sp.effective_date <= %s
              AND (sp.end_date IS NULL OR sp.end_date >= %s)
            ORDER BY sp.priority ASC, sp.effective_date DESC, sp.priority_id DESC
            LIMIT 1
        ) current_priority ON TRUE
        WHERE ss.source_code = %s
          AND dc.dataset_code = ANY(%s::text[])
          AND vcp.status = 'active'
          AND vcde.status = 'active'
        ORDER BY ss.source_code, dc.dataset_code
        """,
        [primary_source_code, as_of_date, as_of_date, source_code, dataset_codes],
    )


def _insert_promotion_run(postgres_dsn: str, run: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, str(run["source_code"]))
            primary_source_id = _lookup_source_id(cursor, str(run["primary_source_code"])) if run.get("primary_source_code") else None
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_primary_promotion_run (
                    promotion_code, source_id, primary_source_id, as_of_date,
                    requested_by, trigger_mode, environment, promotion_scope,
                    status, apply_mode, routing_change_allowed,
                    routing_change_applied, dataset_count,
                    approved_dataset_count, pending_dataset_count,
                    blocked_dataset_count, applied_dataset_count,
                    canary_ready_count, full_market_ready_count,
                    signoff_ready_count, required_windows,
                    require_full_market, require_signoff,
                    target_priority, current_primary_source_codes,
                    promotion_score, blocking_issues, required_actions,
                    request_payload, response_payload, evidence,
                    error_message, started_at, finished_at,
                    duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    run["promotion_code"],
                    source_id,
                    primary_source_id,
                    run["as_of_date"],
                    run["requested_by"],
                    run["trigger_mode"],
                    run["environment"],
                    run["promotion_scope"],
                    run["status"],
                    run["apply_mode"],
                    run["routing_change_allowed"],
                    run["routing_change_applied"],
                    run["dataset_count"],
                    run["approved_dataset_count"],
                    run["pending_dataset_count"],
                    run["blocked_dataset_count"],
                    run["applied_dataset_count"],
                    run["canary_ready_count"],
                    run["full_market_ready_count"],
                    run["signoff_ready_count"],
                    run["required_windows"],
                    run["require_full_market"],
                    run["require_signoff"],
                    run["target_priority"],
                    run["current_primary_source_codes"],
                    run["promotion_score"],
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
            stored["source_code"] = run["source_code"]
            stored["primary_source_code"] = run.get("primary_source_code")
            return stored


def _insert_promotion_results(postgres_dsn: str, run: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for result in results:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_primary_promotion_dataset_result (
                        result_code, promotion_id, source_id, dataset_id,
                        primary_source_id, procurement_snapshot_id,
                        procurement_snapshot_code, readiness_review_id,
                        readiness_review_code, canary_pilot_id,
                        canary_pilot_code, full_market_pilot_id,
                        full_market_pilot_code, current_priority_id,
                        current_primary_source_code, current_priority,
                        target_priority, status, promotion_role,
                        routing_change_allowed, routing_change_applied,
                        procurement_status, procurement_role,
                        readiness_status, readiness_recommendation,
                        readiness_recommended_role, canary_status,
                        canary_signoff_status, canary_recommendation,
                        canary_risk_level, full_market_status,
                        full_market_signoff_status, full_market_recommendation,
                        full_market_risk_level, promotion_score,
                        blocking_issues, required_actions, evidence,
                        error_message, updated_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
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
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s::jsonb,
                        %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        result["result_code"],
                        run["promotion_id"],
                        result["source_id"],
                        result["dataset_id"],
                        result.get("primary_source_id"),
                        result.get("procurement_snapshot_id"),
                        result.get("procurement_snapshot_code"),
                        result.get("readiness_review_id"),
                        result.get("readiness_review_code"),
                        result.get("canary_pilot_id"),
                        result.get("canary_pilot_code"),
                        result.get("full_market_pilot_id"),
                        result.get("full_market_pilot_code"),
                        result.get("current_priority_id"),
                        result.get("current_primary_source_code"),
                        result.get("current_priority"),
                        result["target_priority"],
                        result["status"],
                        result["promotion_role"],
                        result["routing_change_allowed"],
                        result["routing_change_applied"],
                        result.get("procurement_status"),
                        result.get("procurement_role"),
                        result.get("readiness_status"),
                        result.get("readiness_recommendation"),
                        result.get("readiness_recommended_role"),
                        result.get("canary_status"),
                        result.get("canary_signoff_status"),
                        result.get("canary_recommendation"),
                        result.get("canary_risk_level"),
                        result.get("full_market_status"),
                        result.get("full_market_signoff_status"),
                        result.get("full_market_recommendation"),
                        result.get("full_market_risk_level"),
                        result["promotion_score"],
                        result["blocking_issues"],
                        result["required_actions"],
                        _json(result["evidence"]),
                        result.get("error_message"),
                    ),
                )
                row = normalize_rows([dict(cursor.fetchone())])[0]
                row["source_code"] = result.get("source_code")
                row["dataset_code"] = result.get("dataset_code")
                row["primary_source_code"] = result.get("primary_source_code")
                inserted.append(row)
    return inserted


def _apply_source_priority(postgres_dsn: str, results: list[dict[str, Any]], *, source_code: str, effective_date: date, target_priority: int) -> None:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, source_code)
            previous_end_date = effective_date - timedelta(days=1)
            for result in results:
                if result.get("status") not in {"applied", "approved_for_primary"}:
                    continue
                dataset_id = int(result["dataset_id"])
                cursor.execute(
                    """
                    UPDATE qmeta.source_priority
                    SET end_date = %s, updated_at = now()
                    WHERE dataset_id = %s
                      AND source_id <> %s
                      AND priority = %s
                      AND effective_date <= %s
                      AND (end_date IS NULL OR end_date >= %s)
                    """,
                    (previous_end_date, dataset_id, source_id, target_priority, effective_date, effective_date),
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.source_priority (
                        dataset_id, source_id, priority, is_fallback, effective_date, end_date, updated_at
                    ) VALUES (%s, %s, %s, FALSE, %s, NULL, now())
                    ON CONFLICT (dataset_id, source_id, effective_date) DO UPDATE SET
                        priority = EXCLUDED.priority,
                        is_fallback = FALSE,
                        end_date = NULL,
                        updated_at = now()
                    """,
                    (dataset_id, source_id, target_priority, effective_date),
                )


def _mark_applied_results(results: list[dict[str, Any]]) -> None:
    for result in results:
        if result["status"] == "approved_for_primary":
            result["status"] = "applied"
            result["routing_change_allowed"] = True
            result["routing_change_applied"] = True
            result["promotion_role"] = "primary"
            result["required_actions"] = build_vendor_primary_promotion_required_actions(result["blocking_issues"], "applied")
            result["error_message"] = None


def _result_evidence(row: dict[str, Any], windows: list[int], require_full_market: bool, require_signoff: bool, target_priority: int) -> dict[str, Any]:
    return {
        "policy": {
            "required_windows": windows,
            "require_full_market": require_full_market,
            "require_signoff": require_signoff,
            "requires_omicron5_primary_candidate": True,
            "requires_pi_approve_primary": True,
            "requires_theta3_primary_candidate_pilot": True,
        },
        "omicron5": {
            "snapshot_code": row.get("procurement_snapshot_code"),
            "status": row.get("procurement_status"),
            "role": row.get("procurement_role"),
        },
        "pi": {
            "review_code": row.get("readiness_review_code"),
            "status": row.get("readiness_status"),
            "recommendation": row.get("readiness_recommendation"),
            "role": row.get("readiness_recommended_role"),
        },
        "theta3": {
            "canary_pilot_code": row.get("canary_pilot_code"),
            "canary_status": row.get("canary_status"),
            "full_market_pilot_code": row.get("full_market_pilot_code"),
            "full_market_status": row.get("full_market_status"),
        },
        "routing": {
            "current_primary_source_code": row.get("current_primary_source_code"),
            "target_source_code": row.get("source_code"),
            "target_priority": target_priority,
        },
    }


def _pilot_ready(row: dict[str, Any], prefix: str) -> bool:
    return (
        row.get(f"{prefix}_status") == "success"
        and row.get(f"{prefix}_recommendation") == "primary_candidate"
        and row.get(f"{prefix}_risk_level") in {"low", "medium"}
    )


def _signoff_ready(row: dict[str, Any], require_full_market: bool) -> bool:
    canary = row.get("canary_signoff_status") == "approved"
    if not require_full_market:
        return canary
    return canary and row.get("full_market_signoff_status") == "approved"


def _result_signoff_ready(result: dict[str, Any], require_full_market: bool) -> bool:
    canary = result.get("canary_signoff_status") == "approved"
    if not require_full_market:
        return canary
    return canary and result.get("full_market_signoff_status") == "approved"


def _covers_windows(observed: Any, required: list[int]) -> bool:
    if not observed:
        return False
    observed_set = {int(item) for item in observed}
    return set(required).issubset(observed_set)


def _promotion_score(
    procurement_ready: bool,
    readiness_ready: bool,
    canary_ready: bool,
    full_market_ready: bool,
    signoff_ready: bool,
    require_full_market: bool,
    require_signoff: bool,
) -> float:
    checks = [procurement_ready, readiness_ready, canary_ready]
    if require_full_market:
        checks.append(full_market_ready)
    if require_signoff:
        checks.append(signoff_ready)
    return round(sum(1 for item in checks if item) / len(checks) * 100, 4)


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "blocked"
    unique = set(statuses)
    if unique <= {"applied"}:
        return "applied"
    if unique <= {"approved_for_primary", "applied"}:
        return "approved_for_primary"
    if "blocked" in unique:
        return "blocked"
    if "canary_required" in unique:
        return "canary_required"
    if "full_market_required" in unique:
        return "full_market_required"
    if "pending_signoff" in unique:
        return "pending_signoff"
    return "blocked"


def _average_score(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return round(sum(float(result.get("promotion_score") or 0) for result in results) / len(results), 4)


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
        "promotion_code",
        "result_code",
        "source_code",
        "dataset_code",
        "primary_source_code",
        "status",
        "promotion_role",
        "promotion_scope",
        "apply_mode",
        "routing_change_allowed",
        "routing_change_applied",
        "dataset_count",
        "approved_dataset_count",
        "blocked_dataset_count",
        "promotion_score",
        "procurement_status",
        "procurement_role",
        "readiness_status",
        "readiness_recommendation",
        "canary_status",
        "full_market_status",
        "canary_signoff_status",
        "full_market_signoff_status",
        "current_primary_source_code",
        "target_priority",
    ]
    return [key for key in preferred if key in row] + [key for key in row.keys() if key not in preferred]


def _promotion_code(source_code: str, promotion_scope: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{promotion_scope}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"pi5-primary-promotion-{source_code}-{promotion_scope}-{status}-{digest}"[:180]


def _result_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"pi5-primary-promotion-result-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    promotion_scope: str,
    required_windows: Iterable[int],
    target_priority: int,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, once, smoke, api")
    if promotion_scope not in PROMOTION_SCOPES:
        raise QDataValidationError("promotion_scope must be one of: canary, full_market")
    _normalize_windows(required_windows)
    if target_priority < 0:
        raise QDataValidationError("target_priority must be greater than or equal to 0")


def _normalize_windows(windows: Iterable[int]) -> list[int]:
    result = sorted({int(window) for window in windows})
    if not result or any(window <= 0 for window in result):
        raise QDataValidationError("required_windows must contain positive integers")
    return result


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


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _lookup_source_id(cursor, source_code: str) -> int:
    cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = %s", (source_code,))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"source not found: {source_code}")
    return int(row["source_id"])


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required")
    return postgres_dsn


def _connect_required(postgres_dsn: str | None):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Pi-5 vendor primary promotion") from exc
    return psycopg.connect(_require_dsn(postgres_dsn), row_factory=dict_row)
