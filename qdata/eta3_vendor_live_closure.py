from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from time import monotonic
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.epsilon3_vendor_gate import (
    DEFAULT_PRIMARY_SOURCE_CODE,
    DEFAULT_SOURCE_CODE,
    _apply_profile_auth_default,
    _live_config_issues,
    _token_present,
)
from qdata.exceptions import QDataProviderError, QDataValidationError
from qdata.sources.field_mapping import normalize_vendor_row, rules_to_mapping
from qdata.theta import (
    DEFAULT_FIELD_MAPPINGS_BY_DATASET,
    load_active_field_mapping,
    load_vendor_runtime_config,
    redacted_vendor_config,
)
from qdata.zeta3_vendor_onboarding import (
    DEFAULT_CANARY_SYMBOLS,
    DEFAULT_DATASETS,
    DEFAULT_WINDOWS,
    run_vendor_onboarding,
)


STATUSES = {"planned", "success", "warning", "failed", "blocked", "skipped"}
TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
RECOMMENDATIONS = {"reject", "research_only", "backup", "primary_candidate"}
DEFAULT_ENDPOINT_PATHS = {
    "daily_bar": "/daily",
    "security_master": "/securities",
    "adjustment_factor": "/adjustment-factor",
    "limit_price_daily": "/limit-price",
}
PATH_ENV_BY_DATASET = {
    "daily_bar": "QDATA_VENDOR_DAILY_PATH",
    "security_master": "QDATA_VENDOR_SECURITY_MASTER_PATH",
    "adjustment_factor": "QDATA_VENDOR_ADJUSTMENT_FACTOR_PATH",
    "limit_price_daily": "QDATA_VENDOR_LIMIT_PRICE_DAILY_PATH",
}
REQUIRED_FIELDS_BY_DATASET = {
    "daily_bar": ("symbol", "trade_date", "close"),
    "security_master": ("symbol", "name"),
    "adjustment_factor": ("symbol", "trade_date", "factor_forward"),
    "limit_price_daily": ("symbol", "trade_date", "limit_up", "limit_down"),
}


def run_vendor_live_closure(
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
    requested_by: str = "eta3",
    trigger_mode: str = "manual",
    environment: str = "local",
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
    profile_update_status = _profile_update_status(
        allow_profile_write=allow_profile_write,
        activate_profile=activate_profile,
        enable_profile_datasets=enable_profile_datasets,
        commercial_contract_ref=commercial_contract_ref,
        redistribution_allowed=redistribution_allowed,
        rate_limit_per_min=rate_limit_per_min,
    )
    if allow_profile_write and profile_update_status != "skipped":
        _update_vendor_profile(
            postgres_dsn,
            source_code=source_code,
            provider_name=str(profile.get("provider_name") or source_code),
            endpoint_base=config.base_url,
            enabled_dataset_codes=normalized_datasets if enable_profile_datasets else None,
            commercial_contract_ref=commercial_contract_ref,
            redistribution_allowed=redistribution_allowed,
            rate_limit_per_min=rate_limit_per_min or config.rate_limit_per_min,
            activate_profile=activate_profile,
        )
        profile = _fetch_vendor_profile(postgres_dsn, source_code)
        config = _apply_profile_auth_default(load_vendor_runtime_config(source_code), profile)

    live_issues = _live_config_issues(config)
    config_issues = ([] if allow_live else ["external_vendor_live_disabled"]) + live_issues
    profile_issues = _profile_issues(profile, normalized_datasets, require_active_profile=require_active_profile)
    contract_issues = _contract_issues(profile, require_contract=require_contract)
    if profile_update_status == "blocked":
        profile_issues.append("profile_write_not_allowed")
    preflight_issues = _dedupe(config_issues + profile_issues + contract_issues)
    live_ready = allow_live and not live_issues
    enabled_datasets = list(profile.get("enabled_datasets") or [])
    missing_datasets = [dataset_code for dataset_code in normalized_datasets if dataset_code not in set(enabled_datasets)]

    probe_results: list[dict[str, Any]] = []
    if run_endpoint_probes:
        for dataset_code in normalized_datasets:
            probe_results.append(
                _run_endpoint_probe(
                    postgres_dsn,
                    source_code=source_code,
                    dataset_code=dataset_code,
                    config=config,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    symbols=symbols,
                    allow_live=live_ready,
                    requested_allow_live=allow_live,
                    live_issues=live_issues,
                    dataset_enabled=dataset_code in set(enabled_datasets),
                )
            )

    onboarding: dict[str, Any] | None = None
    onboarding_error: str | None = None
    if run_onboarding:
        try:
            onboarding = run_vendor_onboarding(
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
                allow_live=live_ready,
                require_live=False,
                require_active_profile=require_active_profile,
                require_contract=require_contract,
                run_benchmarks=run_benchmarks and live_ready,
                full_market=full_market,
            )
        except Exception as exc:
            onboarding_error = str(exc)

    endpoint_status = _aggregate_field_status(probe_results, "status", default="skipped" if not run_endpoint_probes else "planned")
    onboarding_status = _onboarding_status(onboarding, onboarding_error, run_onboarding)
    status = _closure_status(preflight_issues, endpoint_status, onboarding_status, onboarding_error)
    recommendation, recommended_role = _recommendation(status, endpoint_status, onboarding)
    promotion_status = _promotion_status(status, recommendation)
    finished_at = datetime.now(timezone.utc)
    all_issues = _dedupe(preflight_issues + _probe_issues(probe_results) + ([f"onboarding_failed:{onboarding_error}"] if onboarding_error else []))
    run_row = _insert_closure_run(
        postgres_dsn,
        source_code=source_code,
        primary_source_code=primary_source_code,
        profile=profile,
        config=config,
        onboarding=onboarding,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        status=status,
        config_status="blocked" if config_issues else "success",
        profile_check_status="blocked" if profile_issues else "success",
        profile_update_status=profile_update_status,
        contract_status=_contract_status(profile, require_contract),
        endpoint_status=endpoint_status,
        onboarding_status=onboarding_status,
        promotion_status=promotion_status,
        recommendation=recommendation,
        recommended_role=recommended_role,
        dataset_codes=normalized_datasets,
        enabled_dataset_codes=enabled_datasets,
        missing_dataset_codes=missing_datasets,
        canary_symbols=symbols,
        windows=normalized_windows,
        shard_size=shard_size,
        max_symbols=max_symbols,
        allow_live=allow_live,
        require_live=require_live,
        allow_profile_write=allow_profile_write,
        activate_profile=activate_profile,
        enable_profile_datasets=enable_profile_datasets,
        run_endpoint_probes=run_endpoint_probes,
        run_onboarding=run_onboarding,
        run_benchmarks=run_benchmarks,
        full_market=full_market,
        probe_results=probe_results,
        blocking_issues=all_issues,
        next_actions=_next_actions(status, all_issues, missing_datasets),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        started_at=started_at,
        finished_at=finished_at,
    )
    _insert_endpoint_probes(postgres_dsn, run_row, probe_results)
    if require_live and status in {"blocked", "failed"}:
        raise QDataValidationError(run_row.get("error_message") or "vendor live closure blocked")
    return run_row


def list_vendor_live_closures(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("closure_code", "vlcr.closure_code"),
            ("run_code", "vlcr.closure_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vlcr.status"),
            ("config_status", "vlcr.config_status"),
            ("profile_check_status", "vlcr.profile_check_status"),
            ("profile_update_status", "vlcr.profile_update_status"),
            ("contract_status", "vlcr.contract_status"),
            ("endpoint_status", "vlcr.endpoint_status"),
            ("onboarding_status", "vlcr.onboarding_status"),
            ("promotion_status", "vlcr.promotion_status"),
            ("recommendation", "vlcr.recommendation"),
            ("recommended_role", "vlcr.recommended_role"),
            ("requested_by", "vlcr.requested_by"),
            ("trigger_mode", "vlcr.trigger_mode"),
            ("environment", "vlcr.environment"),
        ],
    )
    dataset_code = _param(params, "dataset_code")
    if dataset_code:
        where, values = _append_where(where, values, "%s = ANY(vlcr.dataset_codes)", dataset_code)
    where, values = _append_date_filter(where, values, params, "vlcr.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vlcr.closure_id, vlcr.closure_code, ss.source_code,
            ps.source_code AS primary_source_code, vlcr.onboarding_run_code,
            vlcr.requested_by, vlcr.trigger_mode, vlcr.environment,
            vlcr.status, vlcr.config_status, vlcr.profile_check_status,
            vlcr.profile_update_status, vlcr.contract_status,
            vlcr.endpoint_status, vlcr.onboarding_status, vlcr.promotion_status,
            vlcr.recommendation, vlcr.recommended_role,
            vlcr.dataset_codes, vlcr.enabled_dataset_codes, vlcr.missing_dataset_codes,
            vlcr.canary_symbols, vlcr.required_windows, vlcr.shard_size, vlcr.max_symbols,
            vlcr.allow_live, vlcr.require_live, vlcr.allow_profile_write,
            vlcr.activate_profile, vlcr.enable_profile_datasets,
            vlcr.run_endpoint_probes, vlcr.run_onboarding, vlcr.run_benchmarks,
            vlcr.full_market, vlcr.live_base_url_present, vlcr.live_token_present,
            vlcr.auth_mode, vlcr.profile_status, vlcr.profile_contract_ref_present,
            vlcr.redistribution_allowed, vlcr.rate_limit_per_min,
            vlcr.endpoint_probe_count, vlcr.endpoint_probe_success_count,
            vlcr.endpoint_probe_blocked_count, vlcr.endpoint_probe_failed_count,
            vlcr.gate_ids, vlcr.gate_codes, vlcr.blocking_issues,
            vlcr.next_actions, vlcr.error_message,
            vlcr.started_at, vlcr.finished_at, vlcr.duration_ms,
            vlcr.created_at, vlcr.updated_at
        FROM qmeta.vendor_live_closure_run vlcr
        JOIN qmeta.source_system ss ON ss.source_id = vlcr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vlcr.primary_source_id
        {where}
        ORDER BY vlcr.started_at DESC, vlcr.closure_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_live_probes(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("closure_code", "vlcr.closure_code"),
            ("run_code", "vlcr.closure_code"),
            ("probe_code", "vlep.probe_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("status", "vlep.status"),
            ("auth_status", "vlep.auth_status"),
            ("schema_status", "vlep.schema_status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "vlep.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vlep.probe_id, vlcr.closure_code, vlep.probe_code,
            dc.dataset_code, ss.source_code, vlep.status,
            vlep.auth_status, vlep.schema_status, vlep.endpoint_path,
            vlep.method, vlep.live_requested, vlep.live_executed,
            vlep.http_status_code, vlep.row_count, vlep.expected_fields,
            vlep.observed_fields, vlep.missing_fields, vlep.latency_ms,
            vlep.error_message, vlep.started_at, vlep.finished_at,
            vlep.duration_ms, vlep.created_at, vlep.updated_at
        FROM qmeta.vendor_live_endpoint_probe vlep
        JOIN qmeta.vendor_live_closure_run vlcr ON vlcr.closure_id = vlep.closure_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vlep.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = vlep.source_id
        {where}
        ORDER BY vlep.started_at DESC, vlep.probe_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_eta3_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"eta3 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _run_endpoint_probe(
    postgres_dsn: str,
    *,
    source_code: str,
    dataset_code: str,
    config,
    start_date: str,
    end_date: str,
    symbols: list[str],
    allow_live: bool,
    requested_allow_live: bool,
    live_issues: list[str],
    dataset_enabled: bool,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    endpoint_path = _endpoint_path(dataset_code, config)
    expected_fields = _expected_fields(dataset_code)
    blocking_issues: list[str] = []
    if not requested_allow_live:
        blocking_issues.append("external_vendor_live_disabled")
    blocking_issues.extend(live_issues)
    if not dataset_enabled:
        blocking_issues.append(f"dataset_not_enabled:{dataset_code}")
    if not allow_live or blocking_issues:
        finished_at = datetime.now(timezone.utc)
        return {
            "dataset_code": dataset_code,
            "source_code": source_code,
            "probe_code": _probe_code(source_code, dataset_code, "blocked"),
            "status": "blocked",
            "auth_status": "blocked" if live_issues else "skipped",
            "schema_status": "skipped",
            "endpoint_path": endpoint_path,
            "method": "GET",
            "live_requested": requested_allow_live,
            "live_executed": False,
            "expected_fields": expected_fields,
            "observed_fields": [],
            "missing_fields": expected_fields,
            "request_payload": _probe_request_payload(dataset_code, endpoint_path, start_date, end_date, symbols, config),
            "response_payload": {"external_side_effect": False},
            "evidence": {"blocking_issues": _dedupe(blocking_issues), "token_storage": "env_var_only"},
            "error_message": "; ".join(_dedupe(blocking_issues)) if blocking_issues else None,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": _duration_ms(started_at, finished_at),
        }

    try:
        payload, http_status, latency_ms = _request_json(config, endpoint_path, start_date, end_date, symbols)
        rows = _payload_rows(payload, config.response_rows_key)
        field_mapping, field_transforms = _field_mapping(postgres_dsn, source_code, dataset_code)
        normalized_rows = [normalize_vendor_row(row, field_mapping, field_transforms) for row in rows[:20]]
        observed_fields = sorted({field for row in normalized_rows for field in row})
        missing_fields = sorted(set(expected_fields) - set(observed_fields))
        schema_status = "success"
        status = "success"
        error_message = None
        if not rows:
            schema_status = "failed"
            status = "failed"
            error_message = "empty_live_response"
        elif missing_fields:
            schema_status = "failed"
            status = "failed"
            error_message = "missing_fields:" + ",".join(missing_fields)
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        return {
            "dataset_code": dataset_code,
            "source_code": source_code,
            "probe_code": _probe_code(source_code, dataset_code, "failed"),
            "status": "failed",
            "auth_status": "success",
            "schema_status": "failed",
            "endpoint_path": endpoint_path,
            "method": "GET",
            "live_requested": requested_allow_live,
            "live_executed": True,
            "expected_fields": expected_fields,
            "observed_fields": [],
            "missing_fields": expected_fields,
            "request_payload": _probe_request_payload(dataset_code, endpoint_path, start_date, end_date, symbols, config),
            "response_payload": {"external_side_effect": True},
            "evidence": {"error_type": exc.__class__.__name__, "token_storage": "env_var_only"},
            "error_message": str(exc),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": _duration_ms(started_at, finished_at),
        }
    finished_at = datetime.now(timezone.utc)
    return {
        "dataset_code": dataset_code,
        "source_code": source_code,
        "probe_code": _probe_code(source_code, dataset_code, status),
        "status": status,
        "auth_status": "success",
        "schema_status": schema_status,
        "endpoint_path": endpoint_path,
        "method": "GET",
        "live_requested": requested_allow_live,
        "live_executed": True,
        "http_status_code": http_status,
        "row_count": len(rows),
        "expected_fields": expected_fields,
        "observed_fields": observed_fields,
        "missing_fields": missing_fields,
        "latency_ms": int(latency_ms),
        "request_payload": _probe_request_payload(dataset_code, endpoint_path, start_date, end_date, symbols, config),
        "response_payload": {
            "row_count": len(rows),
            "observed_fields": observed_fields,
            "sample_row_keys": sorted(list(rows[0].keys())) if rows else [],
            "external_side_effect": True,
        },
        "evidence": {"token_storage": "env_var_only", "endpoint_contract": "json_rows"},
        "error_message": error_message,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
    }


def _request_json(config, endpoint_path: str, start_date: str, end_date: str, symbols: list[str]) -> tuple[Any, int, int]:
    if not config.base_url:
        raise QDataValidationError("QDATA_VENDOR_BASE_URL is required")
    params = {
        "trade_date": start_date,
        "start_date": start_date,
        "end_date": end_date,
        "symbols": ",".join(symbols),
    }
    headers = {"Accept": "application/json"}
    query = dict(params)
    if config.auth_mode == "bearer":
        if not config.token:
            raise QDataValidationError("QDATA_VENDOR_TOKEN is required for bearer auth")
        headers["Authorization"] = f"Bearer {config.token}"
    elif config.auth_mode == "header":
        if not config.token:
            raise QDataValidationError("QDATA_VENDOR_TOKEN is required for header auth")
        headers[config.api_key_header] = config.token
    elif config.auth_mode == "query":
        if not config.token:
            raise QDataValidationError("QDATA_VENDOR_TOKEN is required for query auth")
        query[config.query_token_param] = config.token
    elif config.auth_mode == "basic":
        if not config.username or not config.password:
            raise QDataValidationError("QDATA_VENDOR_USERNAME_OR_PASSWORD is required for basic auth")
        encoded = base64.b64encode(f"{config.username}:{config.password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    url = urljoin(config.base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}{urlencode({key: value for key, value in query.items() if value})}"
    request = Request(url, headers=headers)
    started = monotonic()
    try:
        response = urlopen(request, timeout=config.timeout)
        status_code = int(getattr(response, "status", 200))
        raw = response.read()
    except HTTPError as exc:
        raise QDataProviderError(f"vendor endpoint returned HTTP {exc.code}") from exc
    latency_ms = int((monotonic() - started) * 1000)
    return json.loads(raw.decode("utf-8")), status_code, latency_ms


def _payload_rows(payload: Any, rows_key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get(rows_key)
        if rows is None and rows_key != "rows":
            rows = payload.get("rows")
        if rows is None and rows_key != "data":
            rows = payload.get("data")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise QDataProviderError("vendor response does not contain a list of rows")


def _field_mapping(postgres_dsn: str, source_code: str, dataset_code: str) -> tuple[dict[str, str], dict[str, str]]:
    try:
        return load_active_field_mapping(postgres_dsn, source_code, dataset_code)
    except Exception:
        rules = DEFAULT_FIELD_MAPPINGS_BY_DATASET.get(dataset_code, [])
        return rules_to_mapping(rules)


def _expected_fields(dataset_code: str) -> list[str]:
    rules = DEFAULT_FIELD_MAPPINGS_BY_DATASET.get(dataset_code, [])
    required = {rule.internal_field for rule in rules if rule.is_required}
    required.update(REQUIRED_FIELDS_BY_DATASET.get(dataset_code, ("symbol",)))
    return sorted(required)


def _endpoint_path(dataset_code: str, config) -> str:
    env_name = PATH_ENV_BY_DATASET.get(dataset_code)
    if env_name and os.getenv(env_name):
        return str(os.getenv(env_name))
    if dataset_code == "daily_bar":
        return str(config.daily_path or DEFAULT_ENDPOINT_PATHS["daily_bar"])
    return DEFAULT_ENDPOINT_PATHS.get(dataset_code, f"/{dataset_code}")


def _probe_request_payload(dataset_code: str, endpoint_path: str, start_date: str, end_date: str, symbols: list[str], config) -> dict[str, Any]:
    return {
        "dataset_code": dataset_code,
        "endpoint_path": endpoint_path,
        "method": "GET",
        "params": {
            "trade_date": start_date,
            "start_date": start_date,
            "end_date": end_date,
            "symbol_count": len(symbols),
        },
        "auth_mode": config.auth_mode,
        "token_storage": "env_var_only",
    }


def _profile_update_status(
    *,
    allow_profile_write: bool,
    activate_profile: bool,
    enable_profile_datasets: bool,
    commercial_contract_ref: str | None,
    redistribution_allowed: bool | None,
    rate_limit_per_min: int | None,
) -> str:
    requested = bool(activate_profile or enable_profile_datasets or commercial_contract_ref or redistribution_allowed is not None or rate_limit_per_min)
    if not requested:
        return "skipped"
    return "success" if allow_profile_write else "blocked"


def _profile_issues(profile: dict[str, Any], dataset_codes: list[str], *, require_active_profile: bool) -> list[str]:
    issues: list[str] = []
    if not profile.get("profile_id"):
        issues.append("missing_vendor_profile")
    if require_active_profile and profile.get("profile_status") != "active":
        issues.append(f"profile_not_active:{profile.get('profile_status') or 'missing'}")
    enabled = set(profile.get("enabled_datasets") or [])
    for dataset_code in dataset_codes:
        if dataset_code not in enabled:
            issues.append(f"dataset_not_enabled:{dataset_code}")
    if not profile.get("rate_limit_per_min"):
        issues.append("missing_rate_limit_per_min")
    return _dedupe(issues)


def _contract_issues(profile: dict[str, Any], *, require_contract: bool) -> list[str]:
    if not require_contract:
        return []
    issues: list[str] = []
    if not profile.get("commercial_contract_ref"):
        issues.append("missing_commercial_contract_ref")
    if profile.get("redistribution_allowed") is None:
        issues.append("redistribution_policy_unknown")
    return issues


def _contract_status(profile: dict[str, Any], require_contract: bool) -> str:
    if not require_contract:
        return "skipped"
    return "contracted" if profile.get("commercial_contract_ref") else "missing"


def _aggregate_field_status(rows: list[dict[str, Any]], field: str, *, default: str = "planned") -> str:
    statuses = {str(row.get(field)) for row in rows if row.get(field)}
    if not statuses:
        return default
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if statuses <= {"success", "skipped"}:
        return "success"
    return "planned"


def _onboarding_status(onboarding: dict[str, Any] | None, onboarding_error: str | None, run_onboarding: bool) -> str:
    if onboarding_error:
        return "failed"
    if not run_onboarding:
        return "skipped"
    return str(onboarding.get("status") if onboarding else "planned")


def _closure_status(preflight_issues: list[str], endpoint_status: str, onboarding_status: str, onboarding_error: str | None) -> str:
    if onboarding_error or endpoint_status == "failed" or onboarding_status == "failed":
        return "failed"
    if preflight_issues or endpoint_status == "blocked" or onboarding_status == "blocked":
        return "blocked"
    if endpoint_status == "warning" or onboarding_status == "warning":
        return "warning"
    if endpoint_status in {"success", "skipped"} and onboarding_status in {"success", "skipped"}:
        return "success"
    return "planned"


def _recommendation(status: str, endpoint_status: str, onboarding: dict[str, Any] | None) -> tuple[str, str]:
    if status == "failed":
        return "reject", "reject"
    if status == "blocked":
        return "research_only", "research_only"
    if onboarding and onboarding.get("recommendation") == "primary_candidate" and endpoint_status == "success":
        return "primary_candidate", "primary_candidate"
    if status in {"success", "warning"}:
        return "backup", "backup"
    return "research_only", "research_only"


def _promotion_status(status: str, recommendation: str) -> str:
    if status in {"blocked", "failed"}:
        return status
    if recommendation == "primary_candidate":
        return "success"
    if recommendation == "backup":
        return "warning"
    return "planned"


def _probe_issues(probe_results: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for result in probe_results:
        if result.get("error_message"):
            issues.append(f"{result.get('dataset_code')}:{result.get('error_message')}")
    return _dedupe(issues)


def _next_actions(status: str, issues: list[str], missing_datasets: list[str]) -> list[str]:
    actions: list[str] = []
    if any("QDATA_VENDOR_BASE_URL" in issue for issue in issues):
        actions.append("configure QDATA_VENDOR_BASE_URL")
    if any("QDATA_VENDOR_TOKEN" in issue for issue in issues):
        actions.append("configure QDATA_VENDOR_TOKEN")
    if any("commercial_contract" in issue for issue in issues):
        actions.append("register commercial contract reference")
    if any("redistribution_policy" in issue for issue in issues):
        actions.append("confirm redistribution policy")
    if missing_datasets:
        actions.append("enable vendor profile datasets: " + ",".join(missing_datasets))
    if any("missing_fields" in issue for issue in issues):
        actions.append("fix vendor field mapping or endpoint response schema")
    if status == "blocked":
        actions.append("rerun eta3 live closure with --allow-live after blockers are fixed")
    if status in {"success", "warning"}:
        actions.append("increase --max-symbols and run full-market onboarding")
    return _dedupe(actions or ["review eta3 live closure evidence"])


def _insert_closure_run(
    postgres_dsn: str,
    *,
    source_code: str,
    primary_source_code: str,
    profile: dict[str, Any],
    config,
    onboarding: dict[str, Any] | None,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    status: str,
    config_status: str,
    profile_check_status: str,
    profile_update_status: str,
    contract_status: str,
    endpoint_status: str,
    onboarding_status: str,
    promotion_status: str,
    recommendation: str,
    recommended_role: str,
    dataset_codes: list[str],
    enabled_dataset_codes: list[str],
    missing_dataset_codes: list[str],
    canary_symbols: list[str],
    windows: list[int],
    shard_size: int,
    max_symbols: int | None,
    allow_live: bool,
    require_live: bool,
    allow_profile_write: bool,
    activate_profile: bool,
    enable_profile_datasets: bool,
    run_endpoint_probes: bool,
    run_onboarding: bool,
    run_benchmarks: bool,
    full_market: bool,
    probe_results: list[dict[str, Any]],
    blocking_issues: list[str],
    next_actions: list[str],
    start_date: str,
    end_date: str,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    _validate_status(status)
    if recommendation not in RECOMMENDATIONS:
        raise QDataValidationError(f"unknown closure recommendation: {recommendation}")
    closure_code = _run_code(source_code, status)
    counts = _probe_status_counts(probe_results)
    request_payload = {
        "source_code": source_code,
        "primary_source_code": primary_source_code,
        "dataset_codes": dataset_codes,
        "start_date": start_date,
        "end_date": end_date,
        "required_windows": windows,
        "canary_symbols": canary_symbols,
        "allow_live": allow_live,
        "allow_profile_write": allow_profile_write,
        "run_endpoint_probes": run_endpoint_probes,
        "run_onboarding": run_onboarding,
        "run_benchmarks": run_benchmarks,
        "full_market": full_market,
    }
    response_payload = {
        "status": status,
        "recommendation": recommendation,
        "endpoint_status_counts": counts,
        "onboarding_run_code": onboarding.get("run_code") if onboarding else None,
        "external_side_effect": any(result.get("live_executed") for result in probe_results) or bool(onboarding and onboarding.get("allow_live")),
    }
    evidence = {
        "config": redacted_vendor_config(config),
        "profile": _profile_evidence(profile),
        "token_storage": "env_var_only",
        "probe_count": len(probe_results),
    }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, source_code)
            primary_source_id = _lookup_source_id(cursor, primary_source_code) if primary_source_code else None
            cursor.execute(
                """
                INSERT INTO qmeta.vendor_live_closure_run (
                    closure_code, source_id, profile_id, primary_source_id, onboarding_run_id,
                    requested_by, trigger_mode, environment, status,
                    config_status, profile_check_status, profile_update_status, contract_status,
                    endpoint_status, onboarding_status, promotion_status,
                    recommendation, recommended_role, dataset_codes, enabled_dataset_codes,
                    missing_dataset_codes, canary_symbols, required_windows, shard_size, max_symbols,
                    allow_live, require_live, allow_profile_write, activate_profile,
                    enable_profile_datasets, run_endpoint_probes, run_onboarding,
                    run_benchmarks, full_market, live_base_url_env, live_token_env,
                    live_base_url_present, live_token_present, auth_mode, profile_status,
                    profile_contract_ref_present, redistribution_allowed, rate_limit_per_min,
                    endpoint_probe_count, endpoint_probe_success_count,
                    endpoint_probe_blocked_count, endpoint_probe_failed_count,
                    onboarding_run_code, gate_ids, gate_codes, blocking_issues,
                    next_actions, request_payload, response_payload, evidence,
                    error_message, started_at, finished_at, duration_ms, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, 'QDATA_VENDOR_BASE_URL', 'QDATA_VENDOR_TOKEN',
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, now()
                )
                RETURNING *
                """,
                (
                    closure_code,
                    source_id,
                    profile.get("profile_id"),
                    primary_source_id,
                    onboarding.get("run_id") if onboarding else None,
                    requested_by,
                    trigger_mode,
                    environment,
                    status,
                    config_status,
                    profile_check_status,
                    profile_update_status,
                    contract_status,
                    endpoint_status,
                    onboarding_status,
                    promotion_status,
                    recommendation,
                    recommended_role,
                    dataset_codes,
                    enabled_dataset_codes,
                    missing_dataset_codes,
                    canary_symbols,
                    windows,
                    shard_size,
                    max_symbols,
                    allow_live,
                    require_live,
                    allow_profile_write,
                    activate_profile,
                    enable_profile_datasets,
                    run_endpoint_probes,
                    run_onboarding,
                    run_benchmarks,
                    full_market,
                    bool(config.base_url),
                    _token_present(config),
                    config.auth_mode,
                    profile.get("profile_status"),
                    bool(profile.get("commercial_contract_ref")),
                    profile.get("redistribution_allowed"),
                    profile.get("rate_limit_per_min") or config.rate_limit_per_min,
                    len(probe_results),
                    counts.get("success", 0),
                    counts.get("blocked", 0),
                    counts.get("failed", 0),
                    onboarding.get("run_code") if onboarding else None,
                    list(onboarding.get("gate_ids") or []) if onboarding else [],
                    list(onboarding.get("gate_codes") or []) if onboarding else [],
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


def _insert_endpoint_probes(postgres_dsn: str, run_row: dict[str, Any], probes: list[dict[str, Any]]) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            source_id = _lookup_source_id(cursor, str(run_row["source_code"]))
            for probe in probes:
                dataset_id = _lookup_dataset_id(cursor, str(probe["dataset_code"]))
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_live_endpoint_probe (
                        probe_code, closure_id, dataset_id, source_id,
                        status, auth_status, schema_status, endpoint_path, method,
                        live_requested, live_executed, http_status_code, row_count,
                        expected_fields, observed_fields, missing_fields, latency_ms,
                        request_payload, response_payload, evidence, error_message,
                        started_at, finished_at, duration_ms, updated_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s,
                        %s, %s, %s, now()
                    )
                    ON CONFLICT (probe_code) DO NOTHING
                    """,
                    (
                        probe["probe_code"],
                        run_row["closure_id"],
                        dataset_id,
                        source_id,
                        probe["status"],
                        probe["auth_status"],
                        probe["schema_status"],
                        probe["endpoint_path"],
                        probe["method"],
                        probe["live_requested"],
                        probe["live_executed"],
                        probe.get("http_status_code"),
                        probe.get("row_count"),
                        probe.get("expected_fields") or [],
                        probe.get("observed_fields") or [],
                        probe.get("missing_fields") or [],
                        probe.get("latency_ms"),
                        _json(probe.get("request_payload") or {}),
                        _json(probe.get("response_payload") or {}),
                        _json(probe.get("evidence") or {}),
                        probe.get("error_message"),
                        probe["started_at"],
                        probe["finished_at"],
                        probe["duration_ms"],
                    ),
                )


def _update_vendor_profile(
    postgres_dsn: str,
    *,
    source_code: str,
    provider_name: str,
    endpoint_base: str | None,
    enabled_dataset_codes: list[str] | None,
    commercial_contract_ref: str | None,
    redistribution_allowed: bool | None,
    rate_limit_per_min: int | None,
    activate_profile: bool,
) -> None:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.vendor_integration_profile vip
                SET endpoint_base = COALESCE(%s, endpoint_base),
                    enabled_datasets = CASE WHEN %s THEN %s ELSE enabled_datasets END,
                    commercial_contract_ref = COALESCE(%s, commercial_contract_ref),
                    redistribution_allowed = COALESCE(%s, redistribution_allowed),
                    rate_limit_per_min = COALESCE(%s, rate_limit_per_min),
                    status = CASE WHEN %s THEN 'active' ELSE status END,
                    details = details || %s::jsonb,
                    updated_at = now()
                FROM qmeta.source_system ss
                WHERE ss.source_id = vip.source_id
                  AND ss.source_code = %s
                  AND vip.provider_name = %s
                RETURNING vip.profile_id
                """,
                (
                    endpoint_base,
                    enabled_dataset_codes is not None,
                    enabled_dataset_codes or [],
                    commercial_contract_ref,
                    redistribution_allowed,
                    rate_limit_per_min,
                    activate_profile,
                    _json({"eta3_live_closure": {"updated_at": datetime.now(timezone.utc).isoformat(), "token_storage": "env_var_only"}}),
                    source_code,
                    provider_name,
                ),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"vendor profile not found: {source_code}/{provider_name}")


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


def _profile_evidence(profile: dict[str, Any]) -> dict[str, Any]:
    contract_ref = profile.get("commercial_contract_ref")
    return {
        "profile_id": profile.get("profile_id"),
        "profile_status": profile.get("profile_status"),
        "auth_mode": profile.get("auth_mode"),
        "enabled_datasets": profile.get("enabled_datasets"),
        "contract_ref_present": bool(contract_ref),
        "contract_ref_fingerprint": _fingerprint(str(contract_ref)) if contract_ref else None,
        "redistribution_allowed": profile.get("redistribution_allowed"),
        "rate_limit_per_min": profile.get("rate_limit_per_min"),
    }


def _probe_status_counts(probe_results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in probe_results:
        status = str(result.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


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
            "closure_code",
            "source_code",
            "status",
            "config_status",
            "profile_check_status",
            "contract_status",
            "endpoint_status",
            "onboarding_status",
            "promotion_status",
            "recommendation",
            "dataset_codes",
            "missing_dataset_codes",
            "live_base_url_present",
            "live_token_present",
            "error_message",
        ],
        "run": [
            "closure_code",
            "source_code",
            "status",
            "recommendation",
            "endpoint_probe_count",
            "onboarding_run_code",
            "live_base_url_present",
            "live_token_present",
            "error_message",
        ],
        "probes": [
            "closure_code",
            "probe_code",
            "dataset_code",
            "status",
            "auth_status",
            "schema_status",
            "endpoint_path",
            "live_requested",
            "live_executed",
            "row_count",
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
    return f"eta3-live-closure-{source_code}-{status}-{digest}"[:180]


def _probe_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"eta3-live-probe-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _validate_status(status: str) -> None:
    if status not in STATUSES:
        raise QDataValidationError(f"unknown closure status: {status}")


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


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Eta-3 vendor live closure") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Eta-3 vendor live closure")
    return _connect(postgres_dsn)
