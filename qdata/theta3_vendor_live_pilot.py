from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.epsilon3_vendor_gate import DEFAULT_PRIMARY_SOURCE_CODE, DEFAULT_SOURCE_CODE
from qdata.eta3_vendor_live_closure import (
    list_vendor_live_probes,
    run_vendor_live_closure,
)
from qdata.exceptions import QDataValidationError
from qdata.zeta3_vendor_onboarding import DEFAULT_CANARY_SYMBOLS, DEFAULT_DATASETS, DEFAULT_WINDOWS


STATUSES = {"planned", "success", "warning", "failed", "blocked", "skipped"}
TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
PILOT_SCOPES = {"canary", "full_market"}
RECOMMENDATIONS = {"reject", "research_only", "backup", "primary_candidate"}
SIGNOFF_STATUSES = {"not_ready", "pending_review", "approved", "rejected", "skipped"}
RISK_LEVELS = {"unknown", "low", "medium", "high", "critical"}


def run_vendor_live_pilot(
    postgres_dsn: str,
    *,
    source_code: str = DEFAULT_SOURCE_CODE,
    primary_source_code: str = DEFAULT_PRIMARY_SOURCE_CODE,
    dataset_codes: Iterable[str] = DEFAULT_DATASETS,
    start_date: str,
    end_date: str,
    windows: Iterable[int] = DEFAULT_WINDOWS,
    canary_symbols: list[str] | None = None,
    shard_size: int = 500,
    max_symbols: int | None = 10,
    requested_by: str = "theta3",
    trigger_mode: str = "manual",
    environment: str = "local",
    pilot_scope: str = "canary",
    allow_live: bool = False,
    require_live: bool = False,
    allow_profile_write: bool = False,
    activate_profile: bool = False,
    enable_profile_datasets: bool = False,
    commercial_contract_ref: str | None = None,
    redistribution_allowed: bool | None = None,
    rate_limit_per_min: int | None = None,
    require_active_profile: bool = True,
    require_contract: bool = True,
    run_endpoint_probes: bool = True,
    run_onboarding: bool = True,
    run_benchmarks: bool = False,
    full_market: bool = False,
) -> dict[str, Any]:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    if pilot_scope not in PILOT_SCOPES:
        raise QDataValidationError("pilot_scope must be one of: canary, full_market")
    if shard_size <= 0:
        raise QDataValidationError("shard_size must be greater than 0")
    if max_symbols is not None and max_symbols <= 0:
        raise QDataValidationError("max_symbols must be greater than 0")
    start, end = date_range(start_date, end_date)
    normalized_datasets = _normalize_codes(dataset_codes, "dataset_codes")
    normalized_windows = _normalize_windows(windows)
    symbols = _normalize_symbols(canary_symbols or list(DEFAULT_CANARY_SYMBOLS))
    effective_full_market = full_market or pilot_scope == "full_market"
    started_at = datetime.now(timezone.utc)

    closure = run_vendor_live_closure(
        postgres_dsn,
        source_code=source_code,
        primary_source_code=primary_source_code,
        dataset_codes=normalized_datasets,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        windows=normalized_windows,
        canary_symbols=symbols,
        shard_size=shard_size,
        max_symbols=max_symbols,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        allow_live=allow_live,
        require_live=False,
        allow_profile_write=allow_profile_write,
        activate_profile=activate_profile,
        enable_profile_datasets=enable_profile_datasets,
        commercial_contract_ref=commercial_contract_ref,
        redistribution_allowed=redistribution_allowed,
        rate_limit_per_min=rate_limit_per_min,
        require_active_profile=require_active_profile,
        require_contract=require_contract,
        run_endpoint_probes=run_endpoint_probes,
        run_onboarding=run_onboarding,
        run_benchmarks=run_benchmarks,
        full_market=effective_full_market,
    )
    probes = list_vendor_live_probes(postgres_dsn, {"closure_code": [str(closure["closure_code"])]}, max(100, len(normalized_datasets) + 5), 0)
    dataset_results = _build_dataset_results(
        closure=closure,
        probes=probes,
        dataset_codes=normalized_datasets,
        run_benchmarks=run_benchmarks,
    )
    status = _pilot_status(str(closure.get("status") or "planned"), [str(row["status"]) for row in dataset_results])
    recommendation, recommended_role = _pilot_recommendation(status, closure)
    risk_level = _risk_level(status, dataset_results)
    benchmark_status = _benchmark_status(run_benchmarks, str(closure.get("onboarding_status") or "planned"), status)
    signoff_status = _signoff_status(status, recommendation)
    finished_at = datetime.now(timezone.utc)
    blocking_issues = _dedupe(_global_closure_issues(closure) + _dataset_issues(dataset_results))
    if str(closure.get("status")) in {"blocked", "failed"}:
        blocking_issues = _dedupe(["eta3_live_closure_not_ready"] + blocking_issues)
    next_actions = _next_actions(status, recommendation, blocking_issues, dataset_results)
    run_row = _insert_pilot_run(
        postgres_dsn,
        source_code=source_code,
        primary_source_code=primary_source_code,
        closure=closure,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        pilot_scope=pilot_scope,
        status=status,
        benchmark_status=benchmark_status,
        signoff_status=signoff_status,
        recommendation=recommendation,
        recommended_role=recommended_role,
        risk_level=risk_level,
        dataset_codes=normalized_datasets,
        canary_symbols=symbols,
        windows=normalized_windows,
        shard_size=shard_size,
        max_symbols=max_symbols,
        allow_live=allow_live,
        require_live=require_live,
        run_endpoint_probes=run_endpoint_probes,
        run_onboarding=run_onboarding,
        run_benchmarks=run_benchmarks,
        full_market=effective_full_market,
        dataset_results=dataset_results,
        blocking_issues=blocking_issues,
        next_actions=next_actions,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        started_at=started_at,
        finished_at=finished_at,
    )
    _insert_dataset_results(postgres_dsn, run_row, closure, dataset_results)
    if require_live and status in {"blocked", "failed"}:
        raise QDataValidationError(run_row.get("error_message") or "vendor live pilot blocked")
    return run_row


def list_vendor_live_pilots(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("pilot_code", "vlpr.pilot_code"),
            ("run_code", "vlpr.pilot_code"),
            ("closure_code", "vlpr.closure_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vlpr.status"),
            ("closure_status", "vlpr.closure_status"),
            ("endpoint_status", "vlpr.endpoint_status"),
            ("onboarding_status", "vlpr.onboarding_status"),
            ("benchmark_status", "vlpr.benchmark_status"),
            ("signoff_status", "vlpr.signoff_status"),
            ("recommendation", "vlpr.recommendation"),
            ("recommended_role", "vlpr.recommended_role"),
            ("risk_level", "vlpr.risk_level"),
            ("pilot_scope", "vlpr.pilot_scope"),
            ("requested_by", "vlpr.requested_by"),
            ("trigger_mode", "vlpr.trigger_mode"),
            ("environment", "vlpr.environment"),
        ],
    )
    dataset_code = _param(params, "dataset_code")
    if dataset_code:
        where, values = _append_where(where, values, "%s = ANY(vlpr.dataset_codes)", dataset_code)
    where, values = _append_date_filter(where, values, params, "vlpr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vlpr.pilot_id, vlpr.pilot_code, ss.source_code,
            ps.source_code AS primary_source_code, vlpr.closure_code,
            vlpr.requested_by, vlpr.trigger_mode, vlpr.environment,
            vlpr.pilot_scope, vlpr.status, vlpr.closure_status,
            vlpr.endpoint_status, vlpr.onboarding_status,
            vlpr.benchmark_status, vlpr.signoff_status,
            vlpr.recommendation, vlpr.recommended_role, vlpr.risk_level,
            vlpr.dataset_codes, vlpr.canary_symbols, vlpr.required_windows,
            vlpr.shard_size, vlpr.max_symbols, vlpr.allow_live,
            vlpr.require_live, vlpr.run_endpoint_probes,
            vlpr.run_onboarding, vlpr.run_benchmarks, vlpr.full_market,
            vlpr.live_base_url_present, vlpr.live_token_present,
            vlpr.dataset_result_count, vlpr.dataset_success_count,
            vlpr.dataset_warning_count, vlpr.dataset_blocked_count,
            vlpr.dataset_failed_count, vlpr.blocking_issues,
            vlpr.next_actions, vlpr.error_message,
            vlpr.started_at, vlpr.finished_at, vlpr.duration_ms,
            vlpr.created_at, vlpr.updated_at
        FROM qmeta.vendor_live_pilot_run vlpr
        JOIN qmeta.source_system ss ON ss.source_id = vlpr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vlpr.primary_source_id
        {where}
        ORDER BY vlpr.started_at DESC, vlpr.pilot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_live_pilot_results(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("pilot_code", "vlpr.pilot_code"),
            ("run_code", "vlpr.pilot_code"),
            ("result_code", "vlpdr.result_code"),
            ("closure_code", "vlpr.closure_code"),
            ("probe_code", "vlpdr.probe_code"),
            ("gate_code", "vlpdr.gate_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("status", "vlpdr.status"),
            ("closure_status", "vlpdr.closure_status"),
            ("endpoint_status", "vlpdr.endpoint_status"),
            ("schema_status", "vlpdr.schema_status"),
            ("onboarding_status", "vlpdr.onboarding_status"),
            ("gate_status", "vlpdr.gate_status"),
            ("benchmark_status", "vlpdr.benchmark_status"),
            ("recommendation", "vlpdr.recommendation"),
            ("recommended_role", "vlpdr.recommended_role"),
            ("risk_level", "vlpdr.risk_level"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vlpdr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vlpdr.result_id, vlpr.pilot_code, vlpr.closure_code,
            vlpdr.result_code, dc.dataset_code, ss.source_code,
            vlpdr.probe_code, vlpdr.gate_code, vlpdr.status,
            vlpdr.closure_status, vlpdr.endpoint_status,
            vlpdr.schema_status, vlpdr.onboarding_status,
            vlpdr.gate_status, vlpdr.benchmark_status,
            vlpdr.recommendation, vlpdr.recommended_role,
            vlpdr.risk_level, vlpdr.live_requested,
            vlpdr.live_executed, vlpdr.row_count,
            vlpdr.missing_fields, vlpdr.blocking_issues,
            vlpdr.next_actions, vlpdr.error_message,
            vlpdr.started_at, vlpdr.finished_at, vlpdr.duration_ms,
            vlpdr.created_at, vlpdr.updated_at
        FROM qmeta.vendor_live_pilot_dataset_result vlpdr
        JOIN qmeta.vendor_live_pilot_run vlpr ON vlpr.pilot_id = vlpdr.pilot_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vlpdr.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = vlpdr.source_id
        {where}
        ORDER BY vlpdr.started_at DESC, vlpdr.result_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_theta3_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"theta3 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _build_dataset_results(
    *,
    closure: dict[str, Any],
    probes: list[dict[str, Any]],
    dataset_codes: list[str],
    run_benchmarks: bool,
) -> list[dict[str, Any]]:
    probes_by_dataset = {str(probe.get("dataset_code")): probe for probe in probes}
    results: list[dict[str, Any]] = []
    for dataset_code in dataset_codes:
        probe = probes_by_dataset.get(dataset_code, {})
        gate_code = _gate_code_for_dataset(list(closure.get("gate_codes") or []), dataset_code)
        status = _dataset_status(
            closure_status=str(closure.get("status") or "planned"),
            probe_status=str(probe.get("status") or ("skipped" if not probe else "planned")),
            schema_status=str(probe.get("schema_status") or "skipped"),
            onboarding_status=str(closure.get("onboarding_status") or "planned"),
        )
        blocking_issues = _dataset_blocking_issues(dataset_code, closure, probe, status)
        result = {
            "dataset_code": dataset_code,
            "result_code": _result_code(str(closure.get("source_code") or DEFAULT_SOURCE_CODE), dataset_code, status),
            "probe_code": probe.get("probe_code"),
            "gate_code": gate_code,
            "status": status,
            "closure_status": str(closure.get("status") or "planned"),
            "endpoint_status": str(probe.get("status") or closure.get("endpoint_status") or "planned"),
            "schema_status": str(probe.get("schema_status") or "skipped"),
            "onboarding_status": str(closure.get("onboarding_status") or "planned"),
            "gate_status": _gate_status(gate_code, str(closure.get("onboarding_status") or "planned"), status),
            "benchmark_status": _benchmark_status(run_benchmarks, str(closure.get("onboarding_status") or "planned"), status),
            "recommendation": _dataset_recommendation(status, closure),
            "recommended_role": _dataset_recommendation(status, closure),
            "risk_level": _risk_level(status, []),
            "live_requested": bool(probe.get("live_requested")),
            "live_executed": bool(probe.get("live_executed")),
            "row_count": probe.get("row_count"),
            "missing_fields": list(probe.get("missing_fields") or []),
            "blocking_issues": blocking_issues,
            "next_actions": _dataset_next_actions(status, blocking_issues, probe),
            "evidence": {
                "closure_code": closure.get("closure_code"),
                "probe_code": probe.get("probe_code"),
                "gate_code": gate_code,
                "token_storage": "env_var_only",
            },
            "error_message": "; ".join(blocking_issues) if status in {"blocked", "failed"} and blocking_issues else probe.get("error_message"),
        }
        results.append(result)
    return results


def _dataset_status(*, closure_status: str, probe_status: str, schema_status: str, onboarding_status: str) -> str:
    statuses = {closure_status, probe_status, schema_status, onboarding_status}
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if statuses <= {"success", "skipped"}:
        return "success"
    return "planned"


def _pilot_status(closure_status: str, dataset_statuses: list[str]) -> str:
    statuses = {closure_status, *dataset_statuses}
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if statuses <= {"success", "skipped"}:
        return "success"
    return "planned"


def _pilot_recommendation(status: str, closure: dict[str, Any]) -> tuple[str, str]:
    if status == "failed":
        return "reject", "reject"
    if status == "blocked":
        return "research_only", "research_only"
    closure_recommendation = str(closure.get("recommendation") or "research_only")
    if status == "success" and closure_recommendation == "primary_candidate":
        return "primary_candidate", "primary_candidate"
    if status in {"success", "warning"}:
        return "backup", "backup"
    return "research_only", "research_only"


def _dataset_recommendation(status: str, closure: dict[str, Any]) -> str:
    if status == "failed":
        return "reject"
    if status == "blocked":
        return "research_only"
    closure_recommendation = str(closure.get("recommendation") or "research_only")
    if status == "success" and closure_recommendation == "primary_candidate":
        return "primary_candidate"
    if status in {"success", "warning"}:
        return "backup"
    return "research_only"


def _benchmark_status(run_benchmarks: bool, onboarding_status: str, status: str) -> str:
    if not run_benchmarks:
        return "skipped"
    if status in {"blocked", "failed"}:
        return status
    return onboarding_status if onboarding_status in STATUSES else "planned"


def _signoff_status(status: str, recommendation: str) -> str:
    if status in {"blocked", "failed"}:
        return "not_ready"
    if recommendation == "primary_candidate":
        return "pending_review"
    if recommendation == "backup":
        return "pending_review"
    if recommendation == "reject":
        return "rejected"
    return "not_ready"


def _risk_level(status: str, dataset_results: list[dict[str, Any]]) -> str:
    statuses = {status, *(str(row.get("status")) for row in dataset_results)}
    if "failed" in statuses:
        return "critical"
    if "blocked" in statuses:
        return "high"
    if "warning" in statuses:
        return "medium"
    if statuses <= {"success", "skipped"}:
        return "low"
    return "unknown"


def _dataset_blocking_issues(dataset_code: str, closure: dict[str, Any], probe: dict[str, Any], status: str) -> list[str]:
    issues: list[str] = []
    dataset_prefixes = set(DEFAULT_DATASETS) | {str(item) for item in closure.get("dataset_codes") or []}
    for raw_issue in list(closure.get("blocking_issues") or []):
        for issue in _split_issues(str(raw_issue)):
            scoped_issue = _issue_for_dataset(issue, dataset_code, dataset_prefixes)
            if scoped_issue:
                issues.append(scoped_issue)
    if probe.get("error_message"):
        issues.extend(_split_issues(str(probe["error_message"])))
    if probe.get("missing_fields"):
        issues.append("missing_fields:" + ",".join(str(item) for item in probe.get("missing_fields") or []))
    if status == "blocked" and not issues:
        issues.append("pilot_dataset_blocked")
    return _dedupe(issues)


def _global_closure_issues(closure: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    dataset_prefixes = set(DEFAULT_DATASETS) | {str(item) for item in closure.get("dataset_codes") or []}
    for raw_issue in list(closure.get("blocking_issues") or []):
        for issue in _split_issues(str(raw_issue)):
            if issue.startswith("dataset_not_enabled:"):
                continue
            if issue.split(":", 1)[0] in dataset_prefixes:
                continue
            issues.append(issue)
    return _dedupe(issues)


def _issue_for_dataset(issue: str, dataset_code: str, dataset_prefixes: set[str]) -> str | None:
    if issue.startswith(f"{dataset_code}:"):
        return issue.split(":", 1)[1] or issue
    if issue.startswith("dataset_not_enabled:"):
        return issue if issue == f"dataset_not_enabled:{dataset_code}" else None
    if issue.split(":", 1)[0] in dataset_prefixes:
        return None
    return issue


def _split_issues(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _dataset_issues(dataset_results: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for result in dataset_results:
        for issue in result.get("blocking_issues") or []:
            issues.append(f"{result.get('dataset_code')}:{issue}")
    return _dedupe(issues)


def _next_actions(status: str, recommendation: str, issues: list[str], dataset_results: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if any("QDATA_VENDOR_BASE_URL" in issue for issue in issues):
        actions.append("configure QDATA_VENDOR_BASE_URL")
    if any("QDATA_VENDOR_TOKEN" in issue for issue in issues):
        actions.append("configure QDATA_VENDOR_TOKEN")
    if any("commercial_contract" in issue for issue in issues):
        actions.append("register commercial contract reference")
    if any("redistribution_policy" in issue for issue in issues):
        actions.append("confirm redistribution policy")
    if any("dataset_not_enabled" in issue for issue in issues):
        actions.append("enable missing vendor profile datasets")
    if any("missing_fields" in issue for issue in issues):
        actions.append("fix endpoint schema or vendor field mapping")
    if status == "blocked":
        actions.append("rerun theta3 live pilot with --allow-live --require-live after blockers are fixed")
    if status in {"success", "warning"} and recommendation in {"backup", "primary_candidate"}:
        actions.append("review signoff evidence and expand pilot universe")
    if any(row.get("status") == "warning" for row in dataset_results):
        actions.append("review warning dataset results before promotion")
    return _dedupe(actions or ["review theta3 live pilot evidence"])


def _dataset_next_actions(status: str, issues: list[str], probe: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if any("QDATA_VENDOR" in issue for issue in issues):
        actions.append("configure live vendor env")
    if any("dataset_not_enabled" in issue for issue in issues):
        actions.append("enable dataset in vendor profile")
    if probe.get("missing_fields"):
        actions.append("fix endpoint schema or field mapping")
    if status == "blocked":
        actions.append("rerun dataset pilot after blockers are fixed")
    if status in {"success", "warning"}:
        actions.append("include dataset in next pilot window")
    return _dedupe(actions or ["review dataset pilot evidence"])


def _insert_pilot_run(
    postgres_dsn: str,
    *,
    source_code: str,
    primary_source_code: str,
    closure: dict[str, Any],
    requested_by: str,
    trigger_mode: str,
    environment: str,
    pilot_scope: str,
    status: str,
    benchmark_status: str,
    signoff_status: str,
    recommendation: str,
    recommended_role: str,
    risk_level: str,
    dataset_codes: list[str],
    canary_symbols: list[str],
    windows: list[int],
    shard_size: int,
    max_symbols: int | None,
    allow_live: bool,
    require_live: bool,
    run_endpoint_probes: bool,
    run_onboarding: bool,
    run_benchmarks: bool,
    full_market: bool,
    dataset_results: list[dict[str, Any]],
    blocking_issues: list[str],
    next_actions: list[str],
    start_date: str,
    end_date: str,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    pilot_code = _run_code(source_code, status)
    counts = _status_counts(dataset_results)
    request_payload = {
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "dataset_codes": dataset_codes,
        "start_date": start_date,
        "end_date": end_date,
        "required_windows": windows,
        "canary_symbols": canary_symbols,
        "pilot_scope": pilot_scope,
        "allow_live": allow_live,
        "require_live": require_live,
        "run_endpoint_probes": run_endpoint_probes,
        "run_onboarding": run_onboarding,
        "run_benchmarks": run_benchmarks,
        "full_market": full_market,
    }
    response_payload = {
        "status": status,
        "recommendation": recommendation,
        "signoff_status": signoff_status,
        "risk_level": risk_level,
        "dataset_status_counts": counts,
        "external_side_effect": any(result.get("live_executed") for result in dataset_results),
    }
    evidence = {
        "closure_code": closure.get("closure_code"),
        "closure_status": closure.get("status"),
        "endpoint_status": closure.get("endpoint_status"),
        "onboarding_status": closure.get("onboarding_status"),
        "token_storage": "env_var_only",
    }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, source_code)
            primary_source_id = _lookup_source_id(cursor, primary_source_code) if primary_source_code else None
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_live_pilot_run (
                    pilot_code, source_id, primary_source_id, closure_id, closure_code,
                    requested_by, trigger_mode, environment, pilot_scope,
                    status, closure_status, endpoint_status, onboarding_status,
                    benchmark_status, signoff_status, recommendation, recommended_role,
                    risk_level, dataset_codes, canary_symbols, required_windows,
                    shard_size, max_symbols, allow_live, require_live,
                    run_endpoint_probes, run_onboarding, run_benchmarks, full_market,
                    live_base_url_present, live_token_present, dataset_result_count,
                    dataset_success_count, dataset_warning_count, dataset_blocked_count,
                    dataset_failed_count, blocking_issues, next_actions,
                    request_payload, response_payload, evidence, error_message,
                    started_at, finished_at, duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s, now()
                )
                RETURNING *
                """,
                (
                    pilot_code,
                    source_id,
                    primary_source_id,
                    closure.get("closure_id"),
                    closure.get("closure_code"),
                    requested_by,
                    trigger_mode,
                    environment,
                    pilot_scope,
                    status,
                    closure.get("status") or "planned",
                    closure.get("endpoint_status") or "planned",
                    closure.get("onboarding_status") or "planned",
                    benchmark_status,
                    signoff_status,
                    recommendation,
                    recommended_role,
                    risk_level,
                    dataset_codes,
                    canary_symbols,
                    windows,
                    shard_size,
                    max_symbols,
                    allow_live,
                    require_live,
                    run_endpoint_probes,
                    run_onboarding,
                    run_benchmarks,
                    full_market,
                    bool(closure.get("live_base_url_present")),
                    bool(closure.get("live_token_present")),
                    len(dataset_results),
                    counts.get("success", 0),
                    counts.get("warning", 0),
                    counts.get("blocked", 0),
                    counts.get("failed", 0),
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
            row = normalize_rows([dict(cursor.fetchone())])[0]
            row["source_code"] = source_code
            row["primary_source_code"] = primary_source_code
            return row


def _insert_dataset_results(postgres_dsn: str, run_row: dict[str, Any], closure: dict[str, Any], results: list[dict[str, Any]]) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, str(run_row["source_code"]))
            for result in results:
                dataset_id = _lookup_dataset_id(cursor, str(result["dataset_code"]))
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_live_pilot_dataset_result (
                        result_code, pilot_id, dataset_id, source_id, closure_id,
                        probe_code, gate_code, status, closure_status, endpoint_status,
                        schema_status, onboarding_status, gate_status, benchmark_status,
                        recommendation, recommended_role, risk_level, live_requested,
                        live_executed, row_count, missing_fields, blocking_issues,
                        next_actions, evidence, error_message, started_at, finished_at,
                        duration_ms, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s::jsonb, %s, %s, %s,
                        %s, now()
                    )
                    ON CONFLICT (result_code) DO NOTHING
                    """,
                    (
                        result["result_code"],
                        run_row["pilot_id"],
                        dataset_id,
                        source_id,
                        closure.get("closure_id"),
                        result.get("probe_code"),
                        result.get("gate_code"),
                        result["status"],
                        result["closure_status"],
                        result["endpoint_status"],
                        result["schema_status"],
                        result["onboarding_status"],
                        result["gate_status"],
                        result["benchmark_status"],
                        result["recommendation"],
                        result["recommended_role"],
                        result["risk_level"],
                        result["live_requested"],
                        result["live_executed"],
                        result.get("row_count"),
                        result.get("missing_fields") or [],
                        result.get("blocking_issues") or [],
                        result.get("next_actions") or [],
                        _json(result.get("evidence") or {}),
                        result.get("error_message"),
                        run_row["started_at"],
                        run_row["finished_at"],
                        run_row["duration_ms"],
                    ),
                )


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _gate_code_for_dataset(gate_codes: list[str], dataset_code: str) -> str | None:
    for code in gate_codes:
        if f"-{dataset_code}-" in code:
            return code
    return None


def _gate_status(gate_code: str | None, onboarding_status: str, dataset_status: str) -> str:
    if not gate_code:
        return "skipped"
    if dataset_status in {"blocked", "failed"}:
        return dataset_status
    return onboarding_status if onboarding_status in STATUSES else "planned"


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


def _normalize_codes(values: Iterable[str], name: str) -> list[str]:
    result = _dedupe([str(value).strip() for value in values if str(value).strip()])
    if not result:
        raise QDataValidationError(f"{name} is required")
    return result


def _normalize_symbols(values: Iterable[str]) -> list[str]:
    return _normalize_codes([value.upper() for value in values], "canary_symbols")


def _normalize_windows(windows: Iterable[int]) -> list[int]:
    result = sorted({int(window) for window in windows})
    if not result or any(window <= 0 for window in result):
        raise QDataValidationError("windows must contain positive integers")
    return result


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "runs": [
            "pilot_code",
            "source_code",
            "status",
            "pilot_scope",
            "closure_status",
            "endpoint_status",
            "onboarding_status",
            "benchmark_status",
            "signoff_status",
            "recommendation",
            "risk_level",
            "dataset_result_count",
            "closure_code",
            "live_base_url_present",
            "live_token_present",
            "error_message",
        ],
        "run": [
            "pilot_code",
            "source_code",
            "status",
            "signoff_status",
            "recommendation",
            "risk_level",
            "dataset_result_count",
            "closure_code",
            "error_message",
        ],
        "results": [
            "pilot_code",
            "result_code",
            "dataset_code",
            "status",
            "closure_status",
            "endpoint_status",
            "schema_status",
            "gate_status",
            "benchmark_status",
            "recommendation",
            "risk_level",
            "probe_code",
            "gate_code",
            "live_requested",
            "live_executed",
            "missing_fields",
            "error_message",
        ],
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _run_code(source_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"theta3-live-pilot-{source_code}-{status}-{digest}"[:180]


def _result_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"theta3-live-pilot-result-{source_code}-{dataset_code}-{status}-{digest}"[:180]


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


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Theta-3 vendor live pilot") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Theta-3 vendor live pilot")
    return _connect(postgres_dsn)
