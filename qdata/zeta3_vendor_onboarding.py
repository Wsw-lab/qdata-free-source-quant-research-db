from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.epsilon3_vendor_gate import (
    DEFAULT_PRIMARY_SOURCE_CODE,
    DEFAULT_SOURCE_CODE,
    _apply_profile_auth_default,
    _live_config_issues,
    _token_present,
    run_vendor_live_gate,
)
from qdata.exceptions import QDataValidationError
from qdata.theta import load_vendor_runtime_config, redacted_vendor_config


DEFAULT_DATASETS = ("daily_bar", "security_master", "adjustment_factor", "limit_price_daily")
DEFAULT_CANARY_SYMBOLS = ("600519.SH", "000001.SZ")
DEFAULT_WINDOWS = (5, 20, 60)
TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
STATUSES = {"planned", "success", "warning", "failed", "blocked", "skipped"}
RECOMMENDATIONS = {"reject", "research_only", "backup", "primary_candidate"}


def run_vendor_onboarding(
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
    requested_by: str = "zeta3",
    trigger_mode: str = "manual",
    environment: str = "local",
    allow_live: bool = False,
    require_live: bool = False,
    require_active_profile: bool = True,
    require_contract: bool = True,
    run_canary: bool = True,
    run_gates: bool = True,
    run_benchmarks: bool = False,
    full_market: bool = False,
) -> dict[str, Any]:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if not environment:
        raise QDataValidationError("environment is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    if shard_size <= 0:
        raise QDataValidationError("shard_size must be greater than 0")
    if max_symbols is not None and max_symbols <= 0:
        raise QDataValidationError("max_symbols must be greater than 0")
    start, end = date_range(start_date, end_date)
    normalized_datasets = _normalize_codes(dataset_codes, "dataset_codes")
    normalized_windows = _normalize_windows(windows)
    symbols = _normalize_symbols(canary_symbols or list(DEFAULT_CANARY_SYMBOLS))
    started_at = datetime.now(timezone.utc)

    profile = _fetch_vendor_profile(postgres_dsn, source_code)
    config = _apply_profile_auth_default(load_vendor_runtime_config(source_code), profile)
    live_issues = _live_config_issues(config)
    preflight_issues = _preflight_issues(
        profile,
        config,
        dataset_codes=normalized_datasets,
        live_issues=live_issues,
        allow_live=allow_live,
        require_active_profile=require_active_profile,
        require_contract=require_contract,
    )
    live_ready = allow_live and not live_issues
    gate_ids: list[int] = []
    gate_codes: list[str] = []
    dataset_results: list[dict[str, Any]] = []

    for dataset_code in normalized_datasets:
        result_started = datetime.now(timezone.utc)
        dataset_issues = _dataset_preflight_issues(profile, dataset_code)
        if not allow_live:
            dataset_issues.append("external_vendor_live_disabled")
        dataset_issues.extend(live_issues)
        if require_contract:
            dataset_issues.extend(_contract_issues(profile))
        if require_active_profile and profile.get("profile_status") != "active":
            dataset_issues.append(f"profile_not_active:{profile.get('profile_status') or 'missing'}")
        dataset_issues = _dedupe(dataset_issues)
        gate: dict[str, Any] | None = None
        gate_error: str | None = None
        live_benchmark_supported = dataset_code == "daily_bar"
        benchmark_this_dataset = run_benchmarks and live_benchmark_supported
        if run_benchmarks and not live_benchmark_supported:
            dataset_issues.append(f"live_benchmark_not_implemented:{dataset_code}")
        if run_gates:
            try:
                gate = run_vendor_live_gate(
                    postgres_dsn,
                    dataset_code=dataset_code,
                    source_code=source_code,
                    primary_source_code=primary_source_code,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    windows=normalized_windows,
                    symbols=None if full_market else symbols,
                    shard_size=shard_size,
                    max_symbols=max_symbols,
                    requested_by=requested_by,
                    trigger_mode=trigger_mode,
                    allow_live=live_ready,
                    require_live=False,
                    require_active_profile=require_active_profile,
                    require_contract=require_contract,
                    run_benchmarks=benchmark_this_dataset and live_ready,
                )
                if gate.get("gate_id"):
                    gate_ids.append(int(gate["gate_id"]))
                if gate.get("gate_code"):
                    gate_codes.append(str(gate["gate_code"]))
            except Exception as exc:
                gate_error = str(exc)
                dataset_issues.append(f"gate_failed:{exc}")
        else:
            dataset_issues.append("vendor_gate_skipped")
        result_finished = datetime.now(timezone.utc)
        dataset_results.append(
            _dataset_result(
                dataset_code=dataset_code,
                source_code=source_code,
                primary_source_code=primary_source_code,
                gate=gate,
                issues=_dedupe(dataset_issues),
                gate_error=gate_error,
                windows=normalized_windows,
                symbols=symbols,
                shard_size=shard_size,
                max_symbols=max_symbols,
                allow_live=allow_live,
                run_canary=run_canary,
                run_benchmarks=benchmark_this_dataset and live_ready,
                full_market=full_market,
                started_at=result_started,
                finished_at=result_finished,
            )
        )

    status = _aggregate_status(preflight_issues, dataset_results)
    recommendation, recommended_role = _recommendation(status, dataset_results, preflight_issues)
    finished_at = datetime.now(timezone.utc)
    run_row = _insert_onboarding_run(
        postgres_dsn,
        source_code=source_code,
        primary_source_code=primary_source_code,
        profile=profile,
        config=config,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        status=status,
        preflight_status=_preflight_status(preflight_issues),
        canary_status=_aggregate_field_status(dataset_results, "canary_status"),
        gate_status=_aggregate_field_status(dataset_results, "gate_status"),
        orchestration_status=_orchestration_status(status, full_market, preflight_issues),
        recommendation=recommendation,
        recommended_role=recommended_role,
        dataset_codes=normalized_datasets,
        canary_symbols=symbols,
        windows=normalized_windows,
        shard_size=shard_size,
        max_symbols=max_symbols,
        allow_live=allow_live,
        require_live=require_live,
        require_active_profile=require_active_profile,
        require_contract=require_contract,
        run_canary=run_canary,
        run_gates=run_gates,
        run_benchmarks=run_benchmarks,
        full_market=full_market,
        gate_ids=gate_ids,
        gate_codes=gate_codes,
        blocking_issues=_dedupe(preflight_issues),
        next_actions=_next_actions(status, preflight_issues, dataset_results),
        dataset_results=dataset_results,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        started_at=started_at,
        finished_at=finished_at,
    )
    _insert_dataset_results(postgres_dsn, run_row, dataset_results)
    if require_live and status == "blocked":
        raise QDataValidationError(run_row.get("error_message") or "vendor onboarding blocked")
    return run_row


def list_vendor_onboarding_runs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "vor.run_code"),
            ("onboarding_code", "vor.run_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vor.status"),
            ("preflight_status", "vor.preflight_status"),
            ("canary_status", "vor.canary_status"),
            ("gate_status", "vor.gate_status"),
            ("recommendation", "vor.recommendation"),
            ("recommended_role", "vor.recommended_role"),
            ("trigger_mode", "vor.trigger_mode"),
            ("requested_by", "vor.requested_by"),
            ("environment", "vor.environment"),
        ],
    )
    dataset_code = _param(params, "dataset_code")
    if dataset_code:
        where, values = _append_where(where, values, "%s = ANY(vor.dataset_codes)", dataset_code)
    where, values = _append_date_filter(where, values, params, "vor.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vor.run_id, vor.run_code, ss.source_code, ps.source_code AS primary_source_code,
            vor.requested_by, vor.trigger_mode, vor.environment, vor.status,
            vor.preflight_status, vor.canary_status, vor.gate_status, vor.orchestration_status,
            vor.recommendation, vor.recommended_role, vor.dataset_codes, vor.canary_symbols,
            vor.required_windows, vor.shard_size, vor.max_symbols,
            vor.allow_live, vor.require_live, vor.require_active_profile, vor.require_contract,
            vor.run_canary, vor.run_gates, vor.run_benchmarks, vor.full_market,
            vor.live_base_url_present, vor.live_token_present, vor.auth_mode,
            vor.profile_status, vor.contract_status, vor.redistribution_allowed,
            vor.rate_limit_per_min, vor.gate_ids, vor.gate_codes,
            vor.blocking_issues, vor.next_actions, vor.error_message,
            vor.started_at, vor.finished_at, vor.duration_ms, vor.created_at, vor.updated_at
        FROM qmeta.vendor_onboarding_run vor
        JOIN qmeta.source_system ss ON ss.source_id = vor.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vor.primary_source_id
        {where}
        ORDER BY vor.started_at DESC, vor.run_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_onboarding_results(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("run_code", "vor.run_code"),
            ("onboarding_code", "vor.run_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vodr.stage_status"),
            ("preflight_status", "vodr.preflight_status"),
            ("canary_status", "vodr.canary_status"),
            ("gate_status", "vodr.gate_status"),
            ("recommendation", "vodr.recommendation"),
            ("recommended_role", "vodr.recommended_role"),
            ("gate_code", "vlgr.gate_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vodr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vodr.result_id, vor.run_code, dc.dataset_code, ss.source_code,
            ps.source_code AS primary_source_code, vlgr.gate_code,
            vodr.stage_status, vodr.preflight_status, vodr.canary_status, vodr.gate_status,
            vodr.recommendation, vodr.recommended_role,
            vodr.required_windows, vodr.executed_windows, vodr.shard_size,
            vodr.max_symbols, vodr.symbol_count, vodr.live_requested, vodr.live_executed,
            vodr.blocking_issues, vodr.next_actions, vodr.error_message,
            vodr.started_at, vodr.finished_at, vodr.duration_ms,
            vodr.created_at, vodr.updated_at
        FROM qmeta.vendor_onboarding_dataset_result vodr
        JOIN qmeta.vendor_onboarding_run vor ON vor.run_id = vodr.run_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vodr.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = vodr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vodr.primary_source_id
        LEFT JOIN qmeta.vendor_live_gate_run vlgr ON vlgr.gate_id = vodr.gate_id
        {where}
        ORDER BY vodr.started_at DESC, vodr.result_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_zeta3_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"zeta3 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _preflight_issues(
    profile: dict[str, Any],
    config,
    *,
    dataset_codes: list[str],
    live_issues: list[str],
    allow_live: bool,
    require_active_profile: bool,
    require_contract: bool,
) -> list[str]:
    issues: list[str] = []
    if not profile.get("profile_id"):
        issues.append("missing_vendor_profile")
    if require_active_profile and profile.get("profile_status") != "active":
        issues.append(f"profile_not_active:{profile.get('profile_status') or 'missing'}")
    if not allow_live:
        issues.append("external_vendor_live_disabled")
    issues.extend(live_issues)
    enabled = set(profile.get("enabled_datasets") or [])
    for dataset_code in dataset_codes:
        if dataset_code not in enabled:
            issues.append(f"dataset_not_enabled:{dataset_code}")
    if require_contract:
        issues.extend(_contract_issues(profile))
    if not profile.get("rate_limit_per_min") and not config.rate_limit_per_min:
        issues.append("missing_rate_limit_per_min")
    return _dedupe(issues)


def _contract_issues(profile: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not profile.get("commercial_contract_ref"):
        issues.append("missing_commercial_contract_ref")
    if profile.get("redistribution_allowed") is None:
        issues.append("redistribution_policy_unknown")
    return issues


def _dataset_preflight_issues(profile: dict[str, Any], dataset_code: str) -> list[str]:
    enabled = set(profile.get("enabled_datasets") or [])
    if dataset_code not in enabled:
        return [f"dataset_not_enabled:{dataset_code}"]
    return []


def _dataset_result(
    *,
    dataset_code: str,
    source_code: str,
    primary_source_code: str,
    gate: dict[str, Any] | None,
    issues: list[str],
    gate_error: str | None,
    windows: list[int],
    symbols: list[str],
    shard_size: int,
    max_symbols: int | None,
    allow_live: bool,
    run_canary: bool,
    run_benchmarks: bool,
    full_market: bool,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    gate_status = gate.get("status") if gate else ("failed" if gate_error else "skipped")
    preflight_status = "blocked" if issues else "success"
    live_executed = bool(gate and gate.get("run_mode") == "live" and gate.get("executed_windows"))
    canary_status = _canary_status(run_canary, issues, allow_live, live_executed)
    stage_status = _result_status(preflight_status, canary_status, gate_status)
    recommendation, role = _result_recommendation(stage_status, gate)
    all_issues = _dedupe(issues + list(gate.get("blocking_issues") or []) if gate else issues)
    return {
        "dataset_code": dataset_code,
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "gate_id": gate.get("gate_id") if gate else None,
        "gate_code": gate.get("gate_code") if gate else None,
        "stage_status": stage_status,
        "preflight_status": preflight_status,
        "canary_status": canary_status,
        "gate_status": gate_status,
        "recommendation": recommendation,
        "recommended_role": role,
        "required_windows": windows,
        "executed_windows": list(gate.get("executed_windows") or []) if gate else [],
        "shard_size": shard_size,
        "max_symbols": max_symbols,
        "symbol_count": None if full_market else len(symbols),
        "live_requested": allow_live,
        "live_executed": live_executed,
        "blocking_issues": all_issues,
        "next_actions": _result_next_actions(stage_status, all_issues),
        "evidence": {
            "gate_code": gate.get("gate_code") if gate else None,
            "gate_status": gate_status,
            "canary_symbols": symbols,
            "full_market": full_market,
            "external_side_effect": live_executed,
        },
        "error_message": gate_error or ("; ".join(all_issues) if stage_status == "blocked" and all_issues else None),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
    }


def _canary_status(run_canary: bool, issues: list[str], allow_live: bool, live_executed: bool) -> str:
    if not run_canary:
        return "skipped"
    if issues:
        return "blocked"
    if live_executed:
        return "success"
    return "planned" if allow_live else "blocked"


def _result_status(preflight_status: str, canary_status: str, gate_status: str) -> str:
    statuses = {preflight_status, canary_status, gate_status}
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if statuses <= {"success", "skipped"}:
        return "success"
    return "planned"


def _result_recommendation(stage_status: str, gate: dict[str, Any] | None) -> tuple[str, str]:
    if stage_status == "success" and gate and gate.get("recommendation") == "approve_primary":
        return "primary_candidate", "primary_candidate"
    if stage_status in {"success", "warning"}:
        return "backup", "backup"
    if stage_status == "failed":
        return "reject", "reject"
    return "research_only", "research_only"


def _aggregate_status(preflight_issues: list[str], results: list[dict[str, Any]]) -> str:
    statuses = {result["stage_status"] for result in results}
    if "failed" in statuses:
        return "failed"
    if preflight_issues or "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if statuses and statuses <= {"success", "skipped"}:
        return "success"
    return "planned"


def _aggregate_field_status(results: list[dict[str, Any]], field: str) -> str:
    statuses = {str(result.get(field)) for result in results if result.get(field)}
    if not statuses:
        return "planned"
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if statuses <= {"success", "skipped"}:
        return "success"
    return "planned"


def _preflight_status(issues: list[str]) -> str:
    return "blocked" if issues else "success"


def _orchestration_status(status: str, full_market: bool, issues: list[str]) -> str:
    if status in {"failed", "blocked"}:
        return status
    return "success" if full_market and not issues else "planned"


def _recommendation(status: str, results: list[dict[str, Any]], preflight_issues: list[str]) -> tuple[str, str]:
    if status == "failed":
        return "reject", "reject"
    if status == "blocked" or preflight_issues:
        return "research_only", "research_only"
    if all(result.get("recommendation") == "primary_candidate" for result in results):
        return "primary_candidate", "primary_candidate"
    return "backup", "backup"


def _next_actions(status: str, issues: list[str], results: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if any("QDATA_VENDOR_BASE_URL" in issue for issue in issues):
        actions.append("configure QDATA_VENDOR_BASE_URL")
    if any("QDATA_VENDOR_TOKEN" in issue for issue in issues):
        actions.append("configure QDATA_VENDOR_TOKEN")
    if any("commercial_contract" in issue for issue in issues):
        actions.append("register commercial contract reference")
    if any("redistribution_policy" in issue for issue in issues):
        actions.append("confirm redistribution policy")
    if any("rate_limit" in issue for issue in issues):
        actions.append("confirm vendor production rate limit")
    if status == "blocked":
        actions.append("rerun zeta3 onboarding with --allow-live after preflight is clean")
    if status in {"success", "warning"}:
        actions.append("increase --max-symbols and run full-market 5/20/60 windows")
    if any(result.get("gate_status") == "failed" for result in results):
        actions.append("fix failed dataset gate before promotion")
    return _dedupe(actions or ["review vendor onboarding evidence"])


def _result_next_actions(status: str, issues: list[str]) -> list[str]:
    if status == "blocked":
        return _dedupe([
            "fix dataset preflight blockers",
            "rerun dataset gate with --allow-live",
            "keep dataset role research_only",
        ])
    if status == "failed":
        return ["fix dataset gate error", "rerun onboarding"]
    return ["review dataset gate evidence", "expand canary symbols"]


def _insert_onboarding_run(
    postgres_dsn: str,
    *,
    source_code: str,
    primary_source_code: str,
    profile: dict[str, Any],
    config,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    status: str,
    preflight_status: str,
    canary_status: str,
    gate_status: str,
    orchestration_status: str,
    recommendation: str,
    recommended_role: str,
    dataset_codes: list[str],
    canary_symbols: list[str],
    windows: list[int],
    shard_size: int,
    max_symbols: int | None,
    allow_live: bool,
    require_live: bool,
    require_active_profile: bool,
    require_contract: bool,
    run_canary: bool,
    run_gates: bool,
    run_benchmarks: bool,
    full_market: bool,
    gate_ids: list[int],
    gate_codes: list[str],
    blocking_issues: list[str],
    next_actions: list[str],
    dataset_results: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    _validate_status(status)
    if recommendation not in RECOMMENDATIONS:
        raise QDataValidationError(f"unknown onboarding recommendation: {recommendation}")
    run_code = _run_code(source_code, status)
    evidence = {
        "config": redacted_vendor_config(config),
        "profile": _profile_evidence(profile),
        "dataset_result_count": len(dataset_results),
        "token_storage": "env_var_only",
    }
    request_payload = {
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "dataset_codes": dataset_codes,
        "start_date": start_date,
        "end_date": end_date,
        "required_windows": windows,
        "canary_symbols": canary_symbols,
        "shard_size": shard_size,
        "max_symbols": max_symbols,
        "allow_live": allow_live,
        "run_benchmarks": run_benchmarks,
        "full_market": full_market,
    }
    response_payload = {
        "status": status,
        "recommendation": recommendation,
        "dataset_status_counts": _status_counts(dataset_results),
        "gate_codes": gate_codes,
        "external_side_effect": any(result.get("live_executed") for result in dataset_results),
    }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, source_code)
            primary_source_id = _lookup_source_id(cursor, primary_source_code) if primary_source_code else None
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_onboarding_run (
                    run_code, source_id, profile_id, primary_source_id,
                    requested_by, trigger_mode, environment, status,
                    preflight_status, canary_status, gate_status, orchestration_status,
                    recommendation, recommended_role, dataset_codes, canary_symbols,
                    required_windows, shard_size, max_symbols,
                    allow_live, require_live, require_active_profile, require_contract,
                    run_canary, run_gates, run_benchmarks, full_market,
                    live_base_url_env, live_token_env, live_base_url_present, live_token_present,
                    auth_mode, profile_status, contract_status, redistribution_allowed,
                    rate_limit_per_min, gate_ids, gate_codes, blocking_issues, next_actions,
                    request_payload, response_payload, evidence, error_message,
                    started_at, finished_at, duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    'QDATA_VENDOR_BASE_URL', 'QDATA_VENDOR_TOKEN', %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s, now()
                )
                RETURNING *
                """,
                (
                    run_code,
                    source_id,
                    profile.get("profile_id"),
                    primary_source_id,
                    requested_by,
                    trigger_mode,
                    environment,
                    status,
                    preflight_status,
                    canary_status,
                    gate_status,
                    orchestration_status,
                    recommendation,
                    recommended_role,
                    dataset_codes,
                    canary_symbols,
                    windows,
                    shard_size,
                    max_symbols,
                    allow_live,
                    require_live,
                    require_active_profile,
                    require_contract,
                    run_canary,
                    run_gates,
                    run_benchmarks,
                    full_market,
                    bool(config.base_url),
                    _token_present(config),
                    config.auth_mode,
                    profile.get("profile_status"),
                    "contracted" if profile.get("commercial_contract_ref") else "missing",
                    profile.get("redistribution_allowed"),
                    profile.get("rate_limit_per_min") or config.rate_limit_per_min,
                    gate_ids,
                    gate_codes,
                    blocking_issues,
                    next_actions,
                    _json(request_payload),
                    _json(response_payload),
                    _json(evidence),
                    "; ".join(blocking_issues) if status == "blocked" and blocking_issues else None,
                    started_at,
                    finished_at,
                    _duration_ms(started_at, finished_at),
                ),
            )
            row = normalize_rows([dict(cursor.fetchone())])[0]
            row["source_code"] = source_code
            row["primary_source_code"] = primary_source_code
            return row


def _insert_dataset_results(postgres_dsn: str, run_row: dict[str, Any], results: list[dict[str, Any]]) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, str(run_row["source_code"]))
            primary_source_id = _lookup_source_id(cursor, str(run_row["primary_source_code"])) if run_row.get("primary_source_code") else None
            for result in results:
                dataset_id = _lookup_dataset_id(cursor, str(result["dataset_code"]))
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_onboarding_dataset_result (
                        run_id, dataset_id, source_id, primary_source_id, gate_id,
                        stage_status, preflight_status, canary_status, gate_status,
                        recommendation, recommended_role, required_windows, executed_windows,
                        shard_size, max_symbols, symbol_count, live_requested, live_executed,
                        blocking_issues, next_actions, evidence, error_message,
                        started_at, finished_at, duration_ms, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s,
                        %s, %s, %s, now()
                    )
                    ON CONFLICT (run_id, dataset_id) DO UPDATE SET
                        gate_id = EXCLUDED.gate_id,
                        stage_status = EXCLUDED.stage_status,
                        preflight_status = EXCLUDED.preflight_status,
                        canary_status = EXCLUDED.canary_status,
                        gate_status = EXCLUDED.gate_status,
                        recommendation = EXCLUDED.recommendation,
                        recommended_role = EXCLUDED.recommended_role,
                        required_windows = EXCLUDED.required_windows,
                        executed_windows = EXCLUDED.executed_windows,
                        shard_size = EXCLUDED.shard_size,
                        max_symbols = EXCLUDED.max_symbols,
                        symbol_count = EXCLUDED.symbol_count,
                        live_requested = EXCLUDED.live_requested,
                        live_executed = EXCLUDED.live_executed,
                        blocking_issues = EXCLUDED.blocking_issues,
                        next_actions = EXCLUDED.next_actions,
                        evidence = EXCLUDED.evidence,
                        error_message = EXCLUDED.error_message,
                        finished_at = EXCLUDED.finished_at,
                        duration_ms = EXCLUDED.duration_ms,
                        updated_at = now()
                    """,
                    (
                        run_row["run_id"],
                        dataset_id,
                        source_id,
                        primary_source_id,
                        result.get("gate_id"),
                        result["stage_status"],
                        result["preflight_status"],
                        result["canary_status"],
                        result["gate_status"],
                        result["recommendation"],
                        result["recommended_role"],
                        result["required_windows"],
                        result["executed_windows"],
                        result["shard_size"],
                        result["max_symbols"],
                        result["symbol_count"],
                        result["live_requested"],
                        result["live_executed"],
                        result["blocking_issues"],
                        result["next_actions"],
                        _json(result["evidence"]),
                        result.get("error_message"),
                        result["started_at"],
                        result["finished_at"],
                        result["duration_ms"],
                    ),
                )


def _profile_evidence(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": profile.get("profile_id"),
        "profile_status": profile.get("profile_status"),
        "auth_mode": profile.get("auth_mode"),
        "enabled_datasets": profile.get("enabled_datasets"),
        "contract_ref_present": bool(profile.get("commercial_contract_ref")),
        "redistribution_allowed": profile.get("redistribution_allowed"),
        "rate_limit_per_min": profile.get("rate_limit_per_min"),
    }


def _fetch_vendor_profile(postgres_dsn: str, source_code: str) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    vip.profile_id, ss.source_code, vip.provider_name, vip.auth_mode,
                    vip.endpoint_base, vip.enabled_datasets, vip.rate_limit_per_min,
                    vip.retry_limit, vip.timeout_ms, vip.license_scope,
                    vip.redistribution_allowed, vip.commercial_contract_ref,
                    vip.status AS profile_status, vip.owner, vip.details
                FROM qmeta.source_system ss
                LEFT JOIN qmeta.vendor_integration_profile vip ON vip.source_id = ss.source_id
                WHERE ss.source_code = %s
                ORDER BY vip.updated_at DESC NULLS LAST
                LIMIT 1
                """,
                (source_code,),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"source not found: {source_code}")
            return dict(row)


def _status_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("stage_status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "runs": [
            "run_code",
            "source_code",
            "status",
            "preflight_status",
            "canary_status",
            "gate_status",
            "recommendation",
            "recommended_role",
            "dataset_codes",
            "live_base_url_present",
            "live_token_present",
            "contract_status",
            "error_message",
        ],
        "run": [
            "run_code",
            "source_code",
            "status",
            "preflight_status",
            "canary_status",
            "gate_status",
            "recommendation",
            "dataset_codes",
            "live_base_url_present",
            "live_token_present",
            "error_message",
        ],
        "results": [
            "run_code",
            "dataset_code",
            "stage_status",
            "preflight_status",
            "canary_status",
            "gate_status",
            "recommendation",
            "gate_code",
            "error_message",
        ],
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _where_equal(params: dict[str, list[str]], fields: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for param_name, column_name in fields:
        value = _param(params, param_name)
        if value in (None, ""):
            continue
        clauses.append(f"{column_name} = %s")
        values.append(value)
    if not clauses:
        return "", values
    return "WHERE " + " AND ".join(clauses), values


def _append_date_filter(where: str, values: list[Any], params: dict[str, list[str]], column: str) -> tuple[str, list[Any]]:
    start = _param(params, "start_date")
    end = _param(params, "end_date")
    if start and end:
        date_range(start, end)
        return _append_where(where, values, f"{column}::date BETWEEN %s AND %s", start, end)
    if start:
        parse_date(start, "start_date")
        return _append_where(where, values, f"{column}::date >= %s", start)
    if end:
        parse_date(end, "end_date")
        return _append_where(where, values, f"{column}::date <= %s", end)
    return where, values


def _append_where(where: str, values: list[Any], clause: str, *new_values: Any) -> tuple[str, list[Any]]:
    prefix = " AND " if where else "WHERE "
    return f"{where}{prefix}{clause}", values + list(new_values)


def _normalize_codes(values: Iterable[str], field_name: str) -> list[str]:
    result = _dedupe([str(value).strip() for value in values if str(value).strip()])
    if not result:
        raise QDataValidationError(f"{field_name} is required")
    return result


def _normalize_symbols(values: Iterable[str]) -> list[str]:
    return _dedupe([str(value).strip().upper() for value in values if str(value).strip()])


def _normalize_windows(windows: Iterable[int]) -> list[int]:
    result = sorted({int(window) for window in windows})
    if not result or any(window <= 0 for window in result):
        raise QDataValidationError("windows must contain positive integers")
    return result


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _run_code(source_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"zeta3-onboarding-{source_code}-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _validate_status(status: str) -> None:
    if status not in STATUSES:
        raise QDataValidationError(f"unknown onboarding status: {status}")


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


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Zeta-3 vendor onboarding") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Zeta-3 vendor onboarding")
    return _connect(postgres_dsn)
