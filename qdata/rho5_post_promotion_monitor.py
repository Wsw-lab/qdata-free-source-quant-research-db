from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omicron5_vendor_contract import DEFAULT_VENDOR_DATASETS, DEFAULT_VENDOR_SOURCE_CODES


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
MONITOR_SCOPES = {"shadow", "post_promotion", "rollback_drill"}
MONITOR_STATUSES = {"healthy", "warning", "rollback_recommended", "rolled_back", "blocked", "no_applied_promotion"}
ROLLBACK_MODES = {"review_only", "dry_run", "apply"}


def run_post_promotion_monitor(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    source_code: str = DEFAULT_VENDOR_SOURCE_CODES[0],
    primary_source_code: str = "csv",
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "rho5",
    trigger_mode: str = "manual",
    environment: str = "local",
    promotion_scope: str = "full_market",
    monitor_scope: str = "post_promotion",
    require_applied_promotion: bool = True,
    apply_rollback: bool = False,
    rollback_dry_run: bool = False,
    shadow_window_hours: int = 24,
    max_conflict_rate_bps: float = 5.0,
    max_failure_rate: float = 0.01,
    max_stale_minutes: int = 90,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        monitor_scope=monitor_scope,
        shadow_window_hours=shadow_window_hours,
        max_conflict_rate_bps=max_conflict_rate_bps,
        max_failure_rate=max_failure_rate,
        max_stale_minutes=max_stale_minutes,
    )
    snapshot_date = _as_of_date(as_of_date)
    datasets = _normalize_optional_codes(dataset_codes) or list(DEFAULT_VENDOR_DATASETS)
    rollback_mode = "apply" if apply_rollback else "dry_run" if rollback_dry_run else "review_only"
    rows = _load_monitor_inputs(
        _require_dsn(postgres_dsn),
        as_of_date=snapshot_date,
        source_code=source_code,
        primary_source_code=primary_source_code,
        promotion_scope=promotion_scope,
        dataset_codes=datasets,
    )
    results = build_post_promotion_dataset_results(
        rows,
        as_of_date=snapshot_date,
        monitor_scope=monitor_scope,
        rollback_mode=rollback_mode,
        require_applied_promotion=require_applied_promotion,
        shadow_window_hours=shadow_window_hours,
        max_conflict_rate_bps=max_conflict_rate_bps,
        max_failure_rate=max_failure_rate,
        max_stale_minutes=max_stale_minutes,
    )
    if apply_rollback:
        mark_rolled_back_results(results)
    run = build_post_promotion_run(
        results,
        source_code=source_code,
        primary_source_code=primary_source_code,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        monitor_scope=monitor_scope,
        rollback_mode=rollback_mode,
        require_applied_promotion=require_applied_promotion,
        shadow_window_hours=shadow_window_hours,
        max_conflict_rate_bps=max_conflict_rate_bps,
        max_failure_rate=max_failure_rate,
        max_stale_minutes=max_stale_minutes,
        promotion_id=_first_value(results, "promotion_id"),
        promotion_code=_first_value(results, "promotion_code"),
    )
    if not write_db:
        run["results"] = normalize_rows(results)
        return normalize_rows([run])[0]
    if apply_rollback:
        _apply_source_priority_rollback(_require_dsn(postgres_dsn), results, effective_date=snapshot_date)
    stored = _insert_monitor_run(_require_dsn(postgres_dsn), run)
    stored["results"] = _insert_monitor_results(_require_dsn(postgres_dsn), stored, results)
    return stored


def build_post_promotion_dataset_results(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    monitor_scope: str = "post_promotion",
    rollback_mode: str = "review_only",
    require_applied_promotion: bool = True,
    shadow_window_hours: int = 24,
    max_conflict_rate_bps: float = 5.0,
    max_failure_rate: float = 0.01,
    max_stale_minutes: int = 90,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    if monitor_scope not in MONITOR_SCOPES:
        raise QDataValidationError("monitor_scope must be one of: shadow, post_promotion, rollback_drill")
    if rollback_mode not in ROLLBACK_MODES:
        raise QDataValidationError("rollback_mode must be one of: review_only, dry_run, apply")
    results: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        evaluation = evaluate_post_promotion_dataset(
            row,
            require_applied_promotion=require_applied_promotion,
            max_conflict_rate_bps=max_conflict_rate_bps,
            max_failure_rate=max_failure_rate,
            max_stale_minutes=max_stale_minutes,
        )
        result = {
            "result_code": _result_code(str(row.get("source_code") or "unknown"), str(row.get("dataset_code") or "unknown"), evaluation["status"]),
            "promotion_id": row.get("promotion_id"),
            "promotion_code": row.get("promotion_code"),
            "promotion_result_id": row.get("promotion_result_id"),
            "promotion_result_code": row.get("promotion_result_code"),
            "source_id": row["source_id"],
            "source_code": row.get("source_code"),
            "dataset_id": row["dataset_id"],
            "dataset_code": row.get("dataset_code"),
            "primary_source_id": row.get("primary_source_id"),
            "primary_source_code": row.get("primary_source_code"),
            "previous_primary_source_id": row.get("previous_primary_source_id") or row.get("primary_source_id"),
            "previous_primary_source_code": row.get("previous_primary_source_code") or row.get("primary_source_code"),
            "current_priority_id": row.get("current_priority_id"),
            "previous_priority_id": row.get("previous_priority_id"),
            "as_of_date": snapshot_date.isoformat(),
            "monitor_scope": monitor_scope,
            "status": evaluation["status"],
            "rollback_mode": rollback_mode,
            "rollback_allowed": evaluation["rollback_allowed"],
            "rollback_applied": False,
            "promotion_status": row.get("promotion_status"),
            "promotion_role": row.get("promotion_role"),
            "routing_change_applied": bool(row.get("promotion_routing_change_applied") or row.get("result_routing_change_applied")),
            "current_primary_source_code": row.get("current_primary_source_code"),
            "current_priority": _int_or_none(row.get("current_priority")),
            "previous_priority": _int_or_none(row.get("previous_priority")),
            "target_priority": _int_or_none(row.get("target_priority")) or 0,
            "shadow_status": str(row.get("shadow_status") or "not_available"),
            "shadow_conflict_rate_bps": _float_or_zero(row.get("shadow_conflict_rate_bps")),
            "shadow_failure_rate": _float_or_zero(row.get("shadow_failure_rate")),
            "shadow_latency_p95_ms": _float_or_none(row.get("shadow_latency_p95_ms")),
            "stale_minutes": _int_or_none(row.get("stale_minutes")) or 0,
            "shadow_window_hours": shadow_window_hours,
            "monitor_score": evaluation["monitor_score"],
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": evaluation["required_actions"],
            "evidence": _result_evidence(row, shadow_window_hours, max_conflict_rate_bps, max_failure_rate, max_stale_minutes),
            "error_message": "; ".join(evaluation["blocking_issues"]) if evaluation["status"] in {"blocked", "rollback_recommended", "no_applied_promotion"} and evaluation["blocking_issues"] else None,
        }
        results.append(result)
    return results


def evaluate_post_promotion_dataset(
    row: dict[str, Any],
    *,
    require_applied_promotion: bool = True,
    max_conflict_rate_bps: float = 5.0,
    max_failure_rate: float = 0.01,
    max_stale_minutes: int = 90,
) -> dict[str, Any]:
    issues: list[str] = []
    promotion_status = row.get("promotion_status")
    result_status = row.get("promotion_result_status") or row.get("result_status")
    promotion_applied = (
        promotion_status == "applied"
        and bool(row.get("promotion_routing_change_applied"))
        and (result_status == "applied" or bool(row.get("result_routing_change_applied")))
    )
    if require_applied_promotion and not promotion_applied:
        issues.append(f"pi5_promotion_not_applied:{promotion_status or 'missing'}")
        status = "no_applied_promotion"
        return {
            "status": status,
            "rollback_allowed": False,
            "monitor_score": 0.0,
            "blocking_issues": _dedupe(issues),
            "required_actions": build_post_promotion_required_actions(_dedupe(issues), status),
        }

    target_source_code = row.get("source_code")
    current_primary_source_code = row.get("current_primary_source_code")
    current_priority = _int_or_none(row.get("current_priority"))
    target_priority = _int_or_none(row.get("target_priority")) or 0
    if current_primary_source_code != target_source_code or current_priority != target_priority:
        issues.append(f"routing_not_current:{current_primary_source_code or 'missing'}/{current_priority if current_priority is not None else 'missing'}")

    shadow_status = str(row.get("shadow_status") or "not_available")
    conflict_rate = _float_or_zero(row.get("shadow_conflict_rate_bps"))
    failure_rate = _float_or_zero(row.get("shadow_failure_rate"))
    stale_minutes = _int_or_none(row.get("stale_minutes")) or 0

    rollback_issues: list[str] = []
    warning_issues: list[str] = []
    if shadow_status in {"failed", "critical", "rejected"}:
        rollback_issues.append(f"shadow_status_{shadow_status}")
    elif shadow_status in {"warning", "degraded", "not_available"}:
        warning_issues.append(f"shadow_status_{shadow_status}")
    if conflict_rate > max_conflict_rate_bps:
        rollback_issues.append(f"shadow_conflict_rate_high:{conflict_rate}")
    if failure_rate > max_failure_rate:
        rollback_issues.append(f"shadow_failure_rate_high:{failure_rate}")
    if stale_minutes > max_stale_minutes:
        rollback_issues.append(f"shadow_stale_minutes_high:{stale_minutes}")

    if issues:
        status = "blocked"
        all_issues = _dedupe(issues + rollback_issues + warning_issues)
        rollback_allowed = False
    elif rollback_issues:
        status = "rollback_recommended"
        all_issues = _dedupe(rollback_issues + warning_issues)
        rollback_allowed = bool(row.get("previous_primary_source_code") or row.get("primary_source_code"))
    elif warning_issues:
        status = "warning"
        all_issues = _dedupe(warning_issues)
        rollback_allowed = False
    else:
        status = "healthy"
        all_issues = []
        rollback_allowed = False
    return {
        "status": status,
        "rollback_allowed": rollback_allowed,
        "monitor_score": _monitor_score(status),
        "blocking_issues": all_issues,
        "required_actions": build_post_promotion_required_actions(all_issues, status),
    }


def mark_rolled_back_results(results: list[dict[str, Any]]) -> None:
    for result in results:
        if result.get("status") != "rollback_recommended" or not result.get("rollback_allowed"):
            continue
        result["status"] = "rolled_back"
        result["rollback_applied"] = True
        result["monitor_score"] = _monitor_score("rolled_back")
        result["blocking_issues"] = _dedupe(list(result.get("blocking_issues") or []) + ["rollback_applied"])
        result["required_actions"] = build_post_promotion_required_actions(result["blocking_issues"], "rolled_back")
        result["error_message"] = None


def build_post_promotion_run(
    results: list[dict[str, Any]],
    *,
    source_code: str,
    primary_source_code: str,
    as_of_date: str | date | None = None,
    requested_by: str = "rho5",
    trigger_mode: str = "manual",
    environment: str = "local",
    monitor_scope: str = "post_promotion",
    rollback_mode: str = "review_only",
    require_applied_promotion: bool = True,
    shadow_window_hours: int = 24,
    max_conflict_rate_bps: float = 5.0,
    max_failure_rate: float = 0.01,
    max_stale_minutes: int = 90,
    promotion_id: int | None = None,
    promotion_code: str | None = None,
) -> dict[str, Any]:
    snapshot_date = _as_of_date(as_of_date)
    statuses = [str(result.get("status")) for result in results]
    status = _aggregate_status(statuses, require_applied_promotion)
    blocking_issues = _dedupe(issue for result in results for issue in result.get("blocking_issues") or [])
    required_actions = _dedupe(action for result in results for action in result.get("required_actions") or [])
    current_primaries = _dedupe(str(result.get("current_primary_source_code")) for result in results if result.get("current_primary_source_code"))
    previous_primaries = _dedupe(str(result.get("previous_primary_source_code")) for result in results if result.get("previous_primary_source_code"))
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)
    return {
        "monitor_code": _monitor_code(source_code, monitor_scope, status),
        "promotion_id": promotion_id,
        "promotion_code": promotion_code,
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "as_of_date": snapshot_date.isoformat(),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "monitor_scope": monitor_scope,
        "status": status,
        "rollback_mode": rollback_mode,
        "require_applied_promotion": require_applied_promotion,
        "rollback_allowed": bool(results) and any(result.get("rollback_allowed") for result in results),
        "rollback_applied": bool(results) and any(result.get("rollback_applied") for result in results),
        "dataset_count": len(results),
        "healthy_dataset_count": sum(1 for result in results if result.get("status") == "healthy"),
        "warning_dataset_count": sum(1 for result in results if result.get("status") == "warning"),
        "rollback_recommended_count": sum(1 for result in results if result.get("status") == "rollback_recommended"),
        "rolled_back_dataset_count": sum(1 for result in results if result.get("status") == "rolled_back"),
        "blocked_dataset_count": sum(1 for result in results if result.get("status") == "blocked"),
        "no_applied_dataset_count": sum(1 for result in results if result.get("status") == "no_applied_promotion"),
        "shadow_window_hours": shadow_window_hours,
        "max_conflict_rate_bps": max_conflict_rate_bps,
        "max_failure_rate": max_failure_rate,
        "max_stale_minutes": max_stale_minutes,
        "current_primary_source_codes": current_primaries,
        "previous_primary_source_codes": previous_primaries,
        "monitor_score": _average_score(results),
        "blocking_issues": blocking_issues,
        "required_actions": required_actions or build_post_promotion_required_actions(blocking_issues, status),
        "request_payload": {
            "source_code": source_code,
            "primary_source_code": primary_source_code,
            "dataset_codes": [result.get("dataset_code") for result in results],
            "monitor_scope": monitor_scope,
            "rollback_mode": rollback_mode,
            "require_applied_promotion": require_applied_promotion,
            "shadow_window_hours": shadow_window_hours,
            "max_conflict_rate_bps": max_conflict_rate_bps,
            "max_failure_rate": max_failure_rate,
            "max_stale_minutes": max_stale_minutes,
        },
        "response_payload": {
            "status": status,
            "dataset_count": len(results),
            "healthy_dataset_count": sum(1 for result in results if result.get("status") == "healthy"),
            "rollback_recommended_count": sum(1 for result in results if result.get("status") == "rollback_recommended"),
            "rolled_back_dataset_count": sum(1 for result in results if result.get("status") == "rolled_back"),
            "no_applied_dataset_count": sum(1 for result in results if result.get("status") == "no_applied_promotion"),
        },
        "evidence": {
            "promotion_code": promotion_code,
            "policy": {
                "requires_pi5_applied_promotion": require_applied_promotion,
                "requires_current_route_to_promoted_source": True,
                "requires_shadow_conflict_rate_bps_lte": max_conflict_rate_bps,
                "requires_shadow_failure_rate_lte": max_failure_rate,
                "requires_stale_minutes_lte": max_stale_minutes,
            },
        },
        "error_message": "; ".join(blocking_issues) if status in {"blocked", "rollback_recommended", "no_applied_promotion"} and blocking_issues else None,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
    }


def build_post_promotion_required_actions(issues: list[str], status: str) -> list[str]:
    issue_text = " ".join(issues)
    actions: list[str] = []
    if "pi5_promotion_not_applied" in issue_text:
        actions.append("Run Pi-5 with explicit apply routing after all legal, data-owner and quant platform gates are approved.")
    if "routing_not_current" in issue_text:
        actions.append("Verify source_priority before any rollback action; the promoted vendor is not the active primary route.")
    if "shadow_conflict_rate_high" in issue_text or "shadow_failure_rate_high" in issue_text or "shadow_status_failed" in issue_text or "shadow_status_critical" in issue_text:
        actions.append("Prepare immediate rollback to the previous primary source and keep the promoted vendor in validator mode.")
    if "shadow_stale_minutes_high" in issue_text or "shadow_status_degraded" in issue_text or "shadow_status_warning" in issue_text or "shadow_status_not_available" in issue_text:
        actions.append("Keep shadow reconciliation running and review freshness, latency and dataset coverage before expanding traffic.")
    if "rollback_applied" in issue_text:
        actions.append("Confirm the previous primary route is serving traffic and keep post-rollback monitoring active.")
    if status == "healthy":
        actions.append("Keep Rho-5 post-promotion monitoring active and retain previous primary as fallback.")
    elif status == "rolled_back":
        actions.append("Open a post-rollback review before reattempting Pi-5 promotion.")
    elif status == "rollback_recommended":
        actions.append("Do not expand promoted-source traffic until rollback decision is reviewed.")
    elif status == "no_applied_promotion":
        actions.append("Rho-5 is waiting for an applied Pi-5 promotion before production rollback can be armed.")
    elif status == "blocked":
        actions.append("Resolve route or evidence blockers before running a rollback drill.")
    return _dedupe(actions)


def list_vendor_post_promotion_monitors(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("monitor_code", "vppmr.monitor_code"),
            ("promotion_code", "vppr.promotion_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vppmr.status"),
            ("monitor_scope", "vppmr.monitor_scope"),
            ("rollback_mode", "vppmr.rollback_mode"),
            ("requested_by", "vppmr.requested_by"),
            ("trigger_mode", "vppmr.trigger_mode"),
            ("environment", "vppmr.environment"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "vppmr.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "vppmr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vppmr.monitor_id, vppmr.monitor_code,
            vppr.promotion_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vppmr.as_of_date, vppmr.requested_by,
            vppmr.trigger_mode, vppmr.environment,
            vppmr.monitor_scope, vppmr.status,
            vppmr.rollback_mode, vppmr.require_applied_promotion,
            vppmr.rollback_allowed, vppmr.rollback_applied,
            vppmr.dataset_count, vppmr.healthy_dataset_count,
            vppmr.warning_dataset_count,
            vppmr.rollback_recommended_count,
            vppmr.rolled_back_dataset_count,
            vppmr.blocked_dataset_count,
            vppmr.no_applied_dataset_count,
            vppmr.shadow_window_hours,
            vppmr.max_conflict_rate_bps,
            vppmr.max_failure_rate,
            vppmr.max_stale_minutes,
            vppmr.current_primary_source_codes,
            vppmr.previous_primary_source_codes,
            vppmr.monitor_score, vppmr.blocking_issues,
            vppmr.required_actions, vppmr.error_message,
            vppmr.started_at, vppmr.finished_at,
            vppmr.duration_ms, vppmr.created_at,
            vppmr.updated_at
        FROM qmeta.vendor_post_promotion_monitor_run vppmr
        JOIN qmeta.source_system ss ON ss.source_id = vppmr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vppmr.primary_source_id
        LEFT JOIN qmeta.vendor_primary_promotion_run vppr ON vppr.promotion_id = vppmr.promotion_id
        {where}
        ORDER BY vppmr.started_at DESC, vppmr.monitor_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_post_promotion_results(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("monitor_code", "vppmr.monitor_code"),
            ("result_code", "vppdm.result_code"),
            ("promotion_code", "vppr.promotion_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vppdm.status"),
            ("monitor_scope", "vppdm.monitor_scope"),
            ("rollback_mode", "vppdm.rollback_mode"),
            ("promotion_status", "vppdm.promotion_status"),
            ("promotion_role", "vppdm.promotion_role"),
            ("shadow_status", "vppdm.shadow_status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vppdm.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vppdm.result_id, vppmr.monitor_code,
            vppdm.result_code, vppr.promotion_code,
            vppdr.result_code AS promotion_result_code,
            ss.source_code, ps.source_code AS primary_source_code,
            dc.dataset_code, vppdm.status,
            vppdm.monitor_scope, vppdm.rollback_mode,
            vppdm.rollback_allowed, vppdm.rollback_applied,
            vppdm.promotion_status, vppdm.promotion_role,
            vppdm.routing_change_applied,
            vppdm.current_primary_source_code,
            vppdm.current_priority,
            COALESCE(prev.source_code, vppdm.previous_primary_source_code) AS previous_primary_source_code,
            vppdm.previous_priority,
            vppdm.target_priority,
            vppdm.shadow_status,
            vppdm.shadow_conflict_rate_bps,
            vppdm.shadow_failure_rate,
            vppdm.shadow_latency_p95_ms,
            vppdm.stale_minutes,
            vppdm.monitor_score, vppdm.blocking_issues,
            vppdm.required_actions, vppdm.error_message,
            vppdm.created_at, vppdm.updated_at
        FROM qmeta.vendor_post_promotion_dataset_monitor vppdm
        JOIN qmeta.vendor_post_promotion_monitor_run vppmr ON vppmr.monitor_id = vppdm.monitor_id
        LEFT JOIN qmeta.vendor_primary_promotion_run vppr ON vppr.promotion_id = vppdm.promotion_id
        LEFT JOIN qmeta.vendor_primary_promotion_dataset_result vppdr ON vppdr.result_id = vppdm.promotion_result_id
        JOIN qmeta.source_system ss ON ss.source_id = vppdm.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vppdm.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vppdm.primary_source_id
        LEFT JOIN qmeta.source_system prev ON prev.source_id = vppdm.previous_primary_source_id
        {where}
        ORDER BY vppdm.created_at DESC, vppdm.result_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_rho5_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    if isinstance(rows, dict):
        data_rows = rows.get("results") if resource == "results" else [rows]
    else:
        data_rows = rows
    data_rows = list(data_rows or [])
    lines = [f"rho5 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_monitor_inputs(
    postgres_dsn: str,
    *,
    as_of_date: date,
    source_code: str,
    primary_source_code: str,
    promotion_scope: str,
    dataset_codes: list[str],
) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        WITH latest_promotion AS (
            SELECT vppr.*
            FROM qmeta.vendor_primary_promotion_run vppr
            JOIN qmeta.source_system ss ON ss.source_id = vppr.source_id
            LEFT JOIN qmeta.source_system ps ON ps.source_id = vppr.primary_source_id
            WHERE ss.source_code = %s
              AND (ps.source_code = %s OR vppr.primary_source_id IS NULL)
              AND vppr.promotion_scope = %s
            ORDER BY
                CASE WHEN vppr.status = 'applied' AND vppr.routing_change_applied IS TRUE THEN 0 ELSE 1 END,
                vppr.started_at DESC,
                vppr.promotion_id DESC
            LIMIT 1
        )
        SELECT
            lp.promotion_id, lp.promotion_code,
            lp.status AS promotion_status,
            lp.routing_change_applied AS promotion_routing_change_applied,
            lp.promotion_scope, lp.apply_mode AS promotion_apply_mode,
            vppdr.result_id AS promotion_result_id,
            vppdr.result_code AS promotion_result_code,
            vppdr.status AS promotion_result_status,
            vppdr.promotion_role,
            vppdr.routing_change_applied AS result_routing_change_applied,
            ss.source_id, ss.source_code,
            COALESCE(vppdr.primary_source_id, lp.primary_source_id) AS primary_source_id,
            ps.source_code AS primary_source_code,
            COALESCE(vppdr.primary_source_id, lp.primary_source_id) AS previous_primary_source_id,
            COALESCE(vppdr.current_primary_source_code, ps.source_code) AS previous_primary_source_code,
            vppdr.current_priority_id AS previous_priority_id,
            vppdr.current_priority AS previous_priority,
            dc.dataset_id, dc.dataset_code,
            current_priority.priority_id AS current_priority_id,
            current_priority.source_code AS current_primary_source_code,
            current_priority.priority AS current_priority,
            vppdr.target_priority,
            'not_available'::text AS shadow_status,
            0::numeric AS shadow_conflict_rate_bps,
            0::numeric AS shadow_failure_rate,
            NULL::numeric AS shadow_latency_p95_ms,
            0::integer AS stale_minutes
        FROM latest_promotion lp
        JOIN qmeta.vendor_primary_promotion_dataset_result vppdr ON vppdr.promotion_id = lp.promotion_id
        JOIN qmeta.source_system ss ON ss.source_id = vppdr.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vppdr.dataset_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = COALESCE(vppdr.primary_source_id, lp.primary_source_id)
        LEFT JOIN LATERAL (
            SELECT sp.priority_id, ssp.source_code, sp.priority
            FROM qmeta.source_priority sp
            JOIN qmeta.source_system ssp ON ssp.source_id = sp.source_id
            WHERE sp.dataset_id = vppdr.dataset_id
              AND sp.effective_date <= %s
              AND (sp.end_date IS NULL OR sp.end_date >= %s)
            ORDER BY sp.priority ASC, sp.effective_date DESC, sp.priority_id DESC
            LIMIT 1
        ) current_priority ON TRUE
        WHERE dc.dataset_code = ANY(%s::text[])
        ORDER BY ss.source_code, dc.dataset_code
        """,
        [source_code, primary_source_code, promotion_scope, as_of_date, as_of_date, dataset_codes],
    )


def _insert_monitor_run(postgres_dsn: str, run: dict[str, Any]) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, str(run["source_code"]))
            primary_source_id = _lookup_source_id(cursor, str(run["primary_source_code"])) if run.get("primary_source_code") else None
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_post_promotion_monitor_run (
                    monitor_code, promotion_id, source_id, primary_source_id,
                    as_of_date, requested_by, trigger_mode, environment,
                    monitor_scope, status, rollback_mode,
                    require_applied_promotion, rollback_allowed,
                    rollback_applied, dataset_count,
                    healthy_dataset_count, warning_dataset_count,
                    rollback_recommended_count, rolled_back_dataset_count,
                    blocked_dataset_count, no_applied_dataset_count,
                    shadow_window_hours, max_conflict_rate_bps,
                    max_failure_rate, max_stale_minutes,
                    current_primary_source_codes, previous_primary_source_codes,
                    monitor_score, blocking_issues, required_actions,
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
                    %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    run["monitor_code"],
                    run.get("promotion_id"),
                    source_id,
                    primary_source_id,
                    run["as_of_date"],
                    run["requested_by"],
                    run["trigger_mode"],
                    run["environment"],
                    run["monitor_scope"],
                    run["status"],
                    run["rollback_mode"],
                    run["require_applied_promotion"],
                    run["rollback_allowed"],
                    run["rollback_applied"],
                    run["dataset_count"],
                    run["healthy_dataset_count"],
                    run["warning_dataset_count"],
                    run["rollback_recommended_count"],
                    run["rolled_back_dataset_count"],
                    run["blocked_dataset_count"],
                    run["no_applied_dataset_count"],
                    run["shadow_window_hours"],
                    run["max_conflict_rate_bps"],
                    run["max_failure_rate"],
                    run["max_stale_minutes"],
                    run["current_primary_source_codes"],
                    run["previous_primary_source_codes"],
                    run["monitor_score"],
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
            stored["promotion_code"] = run.get("promotion_code")
            return stored


def _insert_monitor_results(postgres_dsn: str, run: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for result in results:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_post_promotion_dataset_monitor (
                        result_code, monitor_id, promotion_id,
                        promotion_result_id, source_id, dataset_id,
                        primary_source_id, previous_primary_source_id,
                        current_priority_id, previous_priority_id,
                        as_of_date, monitor_scope, status,
                        rollback_mode, rollback_allowed, rollback_applied,
                        promotion_status, promotion_role,
                        routing_change_applied, current_primary_source_code,
                        current_priority, previous_primary_source_code,
                        previous_priority, target_priority,
                        shadow_status, shadow_conflict_rate_bps,
                        shadow_failure_rate, shadow_latency_p95_ms,
                        stale_minutes, monitor_score,
                        blocking_issues, required_actions, evidence,
                        error_message, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
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
                        run["monitor_id"],
                        result.get("promotion_id"),
                        result.get("promotion_result_id"),
                        result["source_id"],
                        result["dataset_id"],
                        result.get("primary_source_id"),
                        result.get("previous_primary_source_id"),
                        result.get("current_priority_id"),
                        result.get("previous_priority_id"),
                        result["as_of_date"],
                        result["monitor_scope"],
                        result["status"],
                        result["rollback_mode"],
                        result["rollback_allowed"],
                        result["rollback_applied"],
                        result.get("promotion_status"),
                        result.get("promotion_role"),
                        result["routing_change_applied"],
                        result.get("current_primary_source_code"),
                        result.get("current_priority"),
                        result.get("previous_primary_source_code"),
                        result.get("previous_priority"),
                        result["target_priority"],
                        result["shadow_status"],
                        result["shadow_conflict_rate_bps"],
                        result["shadow_failure_rate"],
                        result.get("shadow_latency_p95_ms"),
                        result["stale_minutes"],
                        result["monitor_score"],
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
                row["promotion_code"] = result.get("promotion_code")
                row["promotion_result_code"] = result.get("promotion_result_code")
                inserted.append(row)
    return inserted


def _apply_source_priority_rollback(postgres_dsn: str, results: list[dict[str, Any]], *, effective_date: date) -> None:
    rollback_rows = [result for result in results if result.get("status") == "rolled_back" and result.get("rollback_applied")]
    if not rollback_rows:
        return
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            previous_end_date = effective_date - timedelta(days=1)
            for result in rollback_rows:
                previous_source_code = result.get("previous_primary_source_code") or result.get("primary_source_code")
                if not previous_source_code:
                    continue
                dataset_id = int(result["dataset_id"])
                promoted_source_id = int(result["source_id"])
                previous_source_id = _lookup_source_id(cursor, str(previous_source_code))
                target_priority = int(result.get("target_priority") or 0)
                cursor.execute(
                    """
                    UPDATE qmeta.source_priority
                    SET end_date = %s, updated_at = now()
                    WHERE dataset_id = %s
                      AND source_id = %s
                      AND priority = %s
                      AND effective_date <= %s
                      AND (end_date IS NULL OR end_date >= %s)
                    """,
                    (previous_end_date, dataset_id, promoted_source_id, target_priority, effective_date, effective_date),
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
                    (dataset_id, previous_source_id, target_priority, effective_date),
                )


def _result_evidence(row: dict[str, Any], shadow_window_hours: int, max_conflict_rate_bps: float, max_failure_rate: float, max_stale_minutes: int) -> dict[str, Any]:
    return {
        "promotion": {
            "promotion_code": row.get("promotion_code"),
            "promotion_result_code": row.get("promotion_result_code"),
            "promotion_status": row.get("promotion_status"),
            "result_status": row.get("promotion_result_status") or row.get("result_status"),
        },
        "routing": {
            "current_primary_source_code": row.get("current_primary_source_code"),
            "promoted_source_code": row.get("source_code"),
            "previous_primary_source_code": row.get("previous_primary_source_code") or row.get("primary_source_code"),
            "target_priority": row.get("target_priority"),
        },
        "shadow_policy": {
            "window_hours": shadow_window_hours,
            "max_conflict_rate_bps": max_conflict_rate_bps,
            "max_failure_rate": max_failure_rate,
            "max_stale_minutes": max_stale_minutes,
        },
        "shadow_observed": {
            "status": row.get("shadow_status") or "not_available",
            "conflict_rate_bps": _float_or_zero(row.get("shadow_conflict_rate_bps")),
            "failure_rate": _float_or_zero(row.get("shadow_failure_rate")),
            "latency_p95_ms": _float_or_none(row.get("shadow_latency_p95_ms")),
            "stale_minutes": _int_or_none(row.get("stale_minutes")) or 0,
        },
    }


def _aggregate_status(statuses: list[str], require_applied_promotion: bool) -> str:
    if not statuses:
        return "no_applied_promotion" if require_applied_promotion else "blocked"
    unique = set(statuses)
    if "blocked" in unique:
        return "blocked"
    if "rollback_recommended" in unique:
        return "rollback_recommended"
    if "rolled_back" in unique:
        return "rolled_back"
    if "warning" in unique:
        return "warning"
    if unique <= {"healthy"}:
        return "healthy"
    if "no_applied_promotion" in unique:
        return "no_applied_promotion"
    return "blocked"


def _monitor_score(status: str) -> float:
    return {
        "healthy": 100.0,
        "warning": 70.0,
        "rolled_back": 60.0,
        "rollback_recommended": 35.0,
        "blocked": 0.0,
        "no_applied_promotion": 0.0,
    }.get(status, 0.0)


def _average_score(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return round(sum(float(result.get("monitor_score") or 0) for result in results) / len(results), 4)


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
        "monitor_code",
        "result_code",
        "promotion_code",
        "promotion_result_code",
        "source_code",
        "dataset_code",
        "primary_source_code",
        "status",
        "monitor_scope",
        "rollback_mode",
        "rollback_allowed",
        "rollback_applied",
        "dataset_count",
        "healthy_dataset_count",
        "warning_dataset_count",
        "rollback_recommended_count",
        "rolled_back_dataset_count",
        "blocked_dataset_count",
        "no_applied_dataset_count",
        "promotion_status",
        "promotion_role",
        "routing_change_applied",
        "current_primary_source_code",
        "previous_primary_source_code",
        "shadow_status",
        "shadow_conflict_rate_bps",
        "shadow_failure_rate",
        "stale_minutes",
        "monitor_score",
    ]
    return [key for key in preferred if key in row] + [key for key in row.keys() if key not in preferred]


def _monitor_code(source_code: str, monitor_scope: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{monitor_scope}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"rho5-post-promotion-{source_code}-{monitor_scope}-{status}-{digest}"[:180]


def _result_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"rho5-post-promotion-result-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    monitor_scope: str,
    shadow_window_hours: int,
    max_conflict_rate_bps: float,
    max_failure_rate: float,
    max_stale_minutes: int,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, once, smoke, api")
    if monitor_scope not in MONITOR_SCOPES:
        raise QDataValidationError("monitor_scope must be one of: shadow, post_promotion, rollback_drill")
    if shadow_window_hours <= 0:
        raise QDataValidationError("shadow_window_hours must be greater than 0")
    if max_conflict_rate_bps < 0:
        raise QDataValidationError("max_conflict_rate_bps must be greater than or equal to 0")
    if max_failure_rate < 0:
        raise QDataValidationError("max_failure_rate must be greater than or equal to 0")
    if max_stale_minutes < 0:
        raise QDataValidationError("max_stale_minutes must be greater than or equal to 0")


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


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return 0.0 if parsed is None else parsed


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
        raise QDataValidationError("psycopg is required for Rho-5 post-promotion monitor") from exc
    return psycopg.connect(_require_dsn(postgres_dsn), row_factory=dict_row)
