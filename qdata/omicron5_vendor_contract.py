from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
PROCUREMENT_STATUSES = {"ready", "conditional", "review_required", "blocked", "no_contract"}
PROCUREMENT_ROLES = {"blocked", "research_only", "validator", "backup", "primary_candidate"}
ROLE_ORDER = {
    "blocked": 0,
    "research_only": 1,
    "validator": 2,
    "backup": 3,
    "primary_candidate": 4,
}
DEFAULT_VENDOR_SOURCE_CODES = ("vendor_http",)
DEFAULT_VENDOR_DATASETS = (
    "daily_bar",
    "security_master",
    "trading_calendar",
    "adjustment_factor",
    "limit_price_daily",
    "financial_metric_pit",
    "financial_statement_pit",
)


def run_vendor_contract_readiness_review(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    source_codes: Iterable[str] | None = None,
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "omicron5",
    trigger_mode: str = "manual",
    environment: str = "local",
    min_sla_uptime_pct: float = 99.5,
    min_rate_limit_per_min: int = 60,
    require_live_evidence: bool = False,
    write_db: bool = True,
) -> list[dict[str, Any]]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        min_sla_uptime_pct=min_sla_uptime_pct,
        min_rate_limit_per_min=min_rate_limit_per_min,
    )
    snapshot_date = _as_of_date(as_of_date)
    thresholds = _thresholds(
        min_sla_uptime_pct=min_sla_uptime_pct,
        min_rate_limit_per_min=min_rate_limit_per_min,
        require_live_evidence=require_live_evidence,
    )
    rows = _load_contract_inputs(
        _require_dsn(postgres_dsn),
        source_codes=_normalize_optional_codes(source_codes),
        dataset_codes=_normalize_optional_codes(dataset_codes),
    )
    snapshots = build_vendor_contract_snapshots(
        rows,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        thresholds=thresholds,
    )
    if not write_db:
        return normalize_rows(snapshots)
    return _insert_procurement_snapshots(_require_dsn(postgres_dsn), snapshots)


def build_vendor_contract_snapshots(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    requested_by: str = "omicron5",
    trigger_mode: str = "manual",
    environment: str = "local",
    thresholds: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    thresholds = thresholds or _thresholds()
    snapshots: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        evaluation = evaluate_vendor_contract_readiness(row, thresholds, as_of_date=snapshot_date)
        snapshot = {
            "snapshot_code": _snapshot_code(
                str(row.get("source_code") or "unknown"),
                str(row.get("dataset_code") or "unknown"),
                str(evaluation["status"]),
            ),
            "source_id": row["source_id"],
            "dataset_id": row["dataset_id"],
            "contract_id": row.get("contract_id"),
            "entitlement_id": row.get("entitlement_id"),
            "profile_id": row.get("profile_id"),
            "source_code": row.get("source_code"),
            "dataset_code": row.get("dataset_code"),
            "contract_code": row.get("contract_code"),
            "entitlement_code": row.get("entitlement_code"),
            "as_of_date": snapshot_date.isoformat(),
            "requested_by": requested_by,
            "trigger_mode": trigger_mode,
            "environment": environment,
            "status": evaluation["status"],
            "procurement_role": evaluation["procurement_role"],
            "readiness_score": evaluation["readiness_score"],
            "procurement_status": row.get("procurement_status") or "review_required",
            "contract_status": row.get("contract_status") or "none",
            "commercial_clearance": row.get("commercial_clearance") or "review_required",
            "redistribution_allowed": row.get("redistribution_allowed") or "unknown",
            "contract_production_use_allowed": _bool(row.get("contract_production_use_allowed")),
            "entitlement_status": row.get("entitlement_status") or "review_required",
            "entitlement_allowed_role": row.get("entitlement_allowed_role") or "validator",
            "entitlement_commercial_use_allowed": _bool(row.get("entitlement_commercial_use_allowed")),
            "entitlement_redistribution_allowed": row.get("entitlement_redistribution_allowed") or "unknown",
            "entitlement_production_use_allowed": _bool(row.get("entitlement_production_use_allowed")),
            "contract_ref": row.get("contract_ref"),
            "contract_end_date": _date_iso(row.get("contract_end_date")),
            "next_review_at": row.get("next_review_at"),
            "rate_limit_per_min": _effective_int(row.get("entitlement_rate_limit_per_min"), row.get("contract_rate_limit_per_min")),
            "daily_quota": _effective_int(row.get("entitlement_daily_quota"), row.get("contract_daily_quota")),
            "monthly_quota": _int_or_none(row.get("contract_monthly_quota")),
            "sla_uptime_pct": _effective_float(row.get("entitlement_sla_uptime_pct"), row.get("contract_sla_uptime_pct")),
            "max_delay_minutes": _int_or_none(row.get("max_delay_minutes")),
            "vendor_profile_status": row.get("vendor_profile_status"),
            "pi_readiness_status": row.get("pi_readiness_status"),
            "pi_recommendation": row.get("pi_recommendation"),
            "live_gate_status": row.get("live_gate_status"),
            "onboarding_status": row.get("onboarding_status"),
            "live_closure_status": row.get("live_closure_status"),
            "live_pilot_status": row.get("live_pilot_status"),
            "latest_review_code": row.get("latest_review_code"),
            "latest_gate_code": row.get("latest_gate_code"),
            "latest_onboarding_code": row.get("latest_onboarding_code"),
            "latest_closure_code": row.get("latest_closure_code"),
            "latest_pilot_code": row.get("latest_pilot_code"),
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": evaluation["required_actions"],
            "evidence": _snapshot_evidence(row, thresholds, requested_by, trigger_mode, environment),
            "error_message": None,
        }
        snapshots.append(snapshot)
    return snapshots


def evaluate_vendor_contract_readiness(
    row: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    *,
    as_of_date: str | date | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or _thresholds()
    snapshot_date = _as_of_date(as_of_date)
    min_sla_uptime_pct = float(thresholds.get("min_sla_uptime_pct", 99.5))
    min_rate_limit_per_min = int(thresholds.get("min_rate_limit_per_min", 60))
    require_live_evidence = bool(thresholds.get("require_live_evidence", False))

    contract_id = row.get("contract_id")
    entitlement_id = row.get("entitlement_id")
    procurement_status = str(row.get("procurement_status") or "review_required")
    contract_status = str(row.get("contract_status") or "none")
    commercial_clearance = str(row.get("commercial_clearance") or "review_required")
    redistribution_allowed = str(row.get("redistribution_allowed") or "unknown")
    contract_prod = _bool(row.get("contract_production_use_allowed"))
    contract_ref = row.get("contract_ref")
    contract_end_date = _parse_optional_date(row.get("contract_end_date"))
    next_review_at = row.get("next_review_at")
    entitlement_status = str(row.get("entitlement_status") or "review_required")
    allowed_role = str(row.get("entitlement_allowed_role") or "validator")
    ent_commercial = _bool(row.get("entitlement_commercial_use_allowed"))
    ent_redistribution = str(row.get("entitlement_redistribution_allowed") or "unknown")
    ent_prod = _bool(row.get("entitlement_production_use_allowed"))
    schema_status = str(row.get("schema_status") or "pending")
    field_mapping_status = str(row.get("field_mapping_status") or "pending")
    profile_status = str(row.get("vendor_profile_status") or "testing")
    contract_profile_status = str(row.get("contract_profile_status") or "active")
    entitlement_profile_status = str(row.get("entitlement_profile_status") or "active")
    rate_limit_per_min = _effective_int(row.get("entitlement_rate_limit_per_min"), row.get("contract_rate_limit_per_min"))
    daily_quota = _effective_int(row.get("entitlement_daily_quota"), row.get("contract_daily_quota"))
    sla_uptime_pct = _effective_float(row.get("entitlement_sla_uptime_pct"), row.get("contract_sla_uptime_pct"))
    max_delay_minutes = _int_or_none(row.get("max_delay_minutes"))
    pi_status = str(row.get("pi_readiness_status") or "missing")
    pi_recommendation = str(row.get("pi_recommendation") or "missing")
    live_gate_status = str(row.get("live_gate_status") or "missing")
    onboarding_status = str(row.get("onboarding_status") or "missing")
    live_closure_status = str(row.get("live_closure_status") or "missing")
    live_pilot_status = str(row.get("live_pilot_status") or "missing")

    issues: list[str] = []
    if not contract_id:
        issues.append("contract_profile_missing")
    if not entitlement_id:
        issues.append("dataset_entitlement_missing")
    if procurement_status != "active":
        issues.append(f"procurement_status_{procurement_status}")
    if contract_status != "active":
        issues.append(f"contract_status_{contract_status}")
    if commercial_clearance != "clear":
        issues.append(f"commercial_clearance_{commercial_clearance}")
    if redistribution_allowed != "yes":
        issues.append(f"redistribution_allowed_{redistribution_allowed}")
    if not contract_prod:
        issues.append("contract_production_use_not_allowed")
    if not contract_ref:
        issues.append("contract_ref_missing")
    if contract_end_date and contract_end_date < snapshot_date:
        issues.append("contract_expired")
    if _is_overdue_timestamp(next_review_at):
        issues.append("contract_review_overdue")
    if entitlement_status != "active":
        issues.append(f"entitlement_status_{entitlement_status}")
    if allowed_role == "blocked":
        issues.append("entitlement_role_blocked")
    if not ent_commercial:
        issues.append("entitlement_commercial_use_not_allowed")
    if ent_redistribution != "yes":
        issues.append(f"entitlement_redistribution_allowed_{ent_redistribution}")
    if not ent_prod:
        issues.append("entitlement_production_use_not_allowed")
    if schema_status != "validated":
        issues.append(f"schema_status_{schema_status}")
    if field_mapping_status != "validated":
        issues.append(f"field_mapping_status_{field_mapping_status}")
    if profile_status not in {"active"}:
        issues.append(f"vendor_profile_status_{profile_status}")
    if contract_profile_status in {"inactive", "expired", "blocked"}:
        issues.append(f"contract_profile_status_{contract_profile_status}")
    if entitlement_profile_status in {"inactive", "expired", "blocked"}:
        issues.append(f"entitlement_profile_status_{entitlement_profile_status}")
    if rate_limit_per_min is None:
        issues.append("rate_limit_per_min_missing")
    elif rate_limit_per_min < min_rate_limit_per_min:
        issues.append(f"rate_limit_per_min_below_threshold:{rate_limit_per_min}/{min_rate_limit_per_min}")
    if daily_quota is None:
        issues.append("daily_quota_missing")
    if sla_uptime_pct is None:
        issues.append("sla_uptime_pct_missing")
    elif sla_uptime_pct < min_sla_uptime_pct:
        issues.append(f"sla_uptime_pct_below_threshold:{sla_uptime_pct:.3f}/{min_sla_uptime_pct:.3f}")
    if max_delay_minutes is None:
        issues.append("max_delay_minutes_missing")

    live_blocked = any(status in {"blocked", "failed", "rejected"} for status in (pi_status, live_gate_status, onboarding_status, live_closure_status, live_pilot_status))
    if live_blocked:
        issues.append("latest_live_or_readiness_evidence_blocked")
    live_ready = (
        pi_status == "ready"
        and pi_recommendation in {"approve_primary", "approve_backup"}
        and live_gate_status in {"success", "warning"}
        and onboarding_status in {"success", "warning"}
        and live_closure_status in {"success", "warning"}
        and live_pilot_status in {"success", "warning"}
    )
    if require_live_evidence and not live_ready:
        issues.append("live_evidence_not_ready")

    hard_block = (
        not contract_id
        or not entitlement_id
        or procurement_status in {"blocked", "suspended", "expired", "terminated"}
        or contract_status in {"expired", "terminated"}
        or commercial_clearance == "blocked"
        or redistribution_allowed == "no"
        or entitlement_status in {"blocked", "expired", "suspended"}
        or ent_redistribution == "no"
        or allowed_role == "blocked"
        or contract_profile_status in {"expired", "blocked"}
        or entitlement_profile_status in {"expired", "blocked"}
        or live_blocked
    )
    primary_rights = (
        procurement_status == "active"
        and contract_status == "active"
        and commercial_clearance == "clear"
        and redistribution_allowed == "yes"
        and contract_prod
        and bool(contract_ref)
        and entitlement_status == "active"
        and ent_commercial
        and ent_redistribution == "yes"
        and ent_prod
        and schema_status == "validated"
        and field_mapping_status == "validated"
        and rate_limit_per_min is not None
        and rate_limit_per_min >= min_rate_limit_per_min
        and daily_quota is not None
        and sla_uptime_pct is not None
        and sla_uptime_pct >= min_sla_uptime_pct
        and max_delay_minutes is not None
        and profile_status == "active"
        and not (contract_end_date and contract_end_date < snapshot_date)
    )

    if not contract_id or not entitlement_id:
        status = "no_contract"
        role = "blocked"
    elif hard_block:
        status = "blocked"
        role = "blocked"
    elif primary_rights and (live_ready or not require_live_evidence):
        role = _cap_role("primary_candidate", allowed_role)
        status = "ready" if role == "primary_candidate" else "conditional"
    elif contract_status == "active" and entitlement_status == "active" and commercial_clearance == "clear":
        role = _cap_role("backup", allowed_role)
        status = "conditional" if role != "blocked" else "blocked"
    else:
        role = _cap_role("validator", allowed_role)
        status = "review_required" if role != "blocked" else "blocked"

    return {
        "status": status,
        "procurement_role": role,
        "readiness_score": _readiness_score(issues, primary_rights, live_ready, require_live_evidence),
        "blocking_issues": _dedupe(issues),
        "required_actions": build_vendor_contract_required_actions(issues, status, role),
    }


def build_vendor_contract_required_actions(issues: list[str], status: str, role: str) -> list[str]:
    issue_text = " ".join(issues)
    actions: list[str] = []
    if "contract_profile_missing" in issues or "dataset_entitlement_missing" in issues:
        actions.append("Create vendor contract profile and dataset entitlement before procurement routing.")
    if "procurement_status_" in issue_text or "contract_status_" in issue_text or "contract_ref_missing" in issues:
        actions.append("Attach signed master data contract, contract_ref and active procurement approval.")
    if "commercial_clearance_" in issue_text or "commercial_use_not_allowed" in issue_text:
        actions.append("Record written commercial-use clearance at contract and dataset level.")
    if "redistribution_allowed_" in issue_text:
        actions.append("Confirm redistribution/cache rights before exposing vendor data or derived datasets to clients.")
    if "production_use_not_allowed" in issue_text:
        actions.append("Mark production-use rights only after legal and vendor account terms explicitly allow production traffic.")
    if "schema_status_" in issue_text or "field_mapping_status_" in issue_text:
        actions.append("Validate endpoint schema and field mapping with Eta-3/Theta-3 evidence.")
    if "rate_limit_per_min" in issue_text or "daily_quota_missing" in issues:
        actions.append("Record production rate limit and daily quota so schedulers can enforce vendor capacity.")
    if "sla_uptime_pct" in issue_text or "max_delay_minutes_missing" in issues:
        actions.append("Record SLA uptime, delivery delay and support tier before primary-source procurement.")
    if "latest_live_or_readiness_evidence_blocked" in issues or "live_evidence_not_ready" in issues:
        actions.append("Run Pi/Epsilon-3/Zeta-3/Eta-3/Theta-3 evidence until latest live gate and pilot are no longer blocked.")
    if status == "ready":
        actions.append("Allow controlled primary-candidate procurement and keep Xi-5/Nu-5 monitoring active.")
    elif role in {"validator", "backup"}:
        actions.append("Use this vendor only as validation or fallback evidence until primary blockers are closed.")
    else:
        actions.append("Do not route production traffic to this vendor dataset.")
    return _dedupe(actions)


def list_vendor_contract_profiles(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("contract_code", "vcp.contract_code"),
            ("source_code", "ss.source_code"),
            ("provider_name", "vcp.provider_name"),
            ("procurement_status", "vcp.procurement_status"),
            ("contract_status", "vcp.contract_status"),
            ("commercial_clearance", "vcp.commercial_clearance"),
            ("redistribution_allowed", "vcp.redistribution_allowed"),
            ("status", "vcp.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vcp.contract_id, vcp.contract_code, ss.source_code,
            vcp.provider_name, vcp.vendor_account_code,
            vcp.procurement_status, vcp.contract_status,
            vcp.commercial_clearance, vcp.redistribution_allowed,
            vcp.production_use_allowed, vcp.contract_ref,
            vcp.contract_owner, vcp.legal_owner, vcp.business_owner,
            vcp.contract_start_date, vcp.contract_end_date,
            vcp.sla_tier, vcp.sla_uptime_pct, vcp.support_sla_hours,
            vcp.rate_limit_per_min, vcp.daily_quota, vcp.monthly_quota,
            vcp.billing_model, vcp.billing_currency,
            vcp.monthly_fee, vcp.unit_cost, vcp.data_scope,
            vip.status AS vendor_profile_status,
            vcp.status, vcp.reviewed_by, vcp.reviewed_at,
            vcp.next_review_at, vcp.evidence, vcp.created_at, vcp.updated_at
        FROM qmeta.vendor_contract_profile vcp
        JOIN qmeta.source_system ss ON ss.source_id = vcp.source_id
        LEFT JOIN qmeta.vendor_integration_profile vip ON vip.profile_id = vcp.profile_id
        {where}
        ORDER BY vcp.updated_at DESC, vcp.contract_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_contract_entitlements(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("entitlement_code", "vcde.entitlement_code"),
            ("contract_code", "vcp.contract_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("entitlement_status", "vcde.entitlement_status"),
            ("allowed_role", "vcde.allowed_role"),
            ("schema_status", "vcde.schema_status"),
            ("field_mapping_status", "vcde.field_mapping_status"),
            ("status", "vcde.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vcde.entitlement_id, vcde.entitlement_code,
            vcp.contract_code, ss.source_code, dc.dataset_code,
            vcde.entitlement_status, vcde.allowed_role,
            vcde.commercial_use_allowed, vcde.redistribution_allowed,
            vcde.production_use_allowed, vcde.delivery_mode,
            vcde.frequency, vcde.latency_level, vcde.endpoint_path,
            vcde.schema_status, vcde.field_mapping_status,
            vcde.rate_limit_per_min, vcde.daily_quota,
            vcde.max_delay_minutes, vcde.sla_uptime_pct,
            vcde.effective_from, vcde.effective_to,
            vcde.blocking_issues, vcde.required_actions,
            vcde.status, vcde.evidence, vcde.created_at, vcde.updated_at
        FROM qmeta.vendor_contract_dataset_entitlement vcde
        JOIN qmeta.vendor_contract_profile vcp ON vcp.contract_id = vcde.contract_id
        JOIN qmeta.source_system ss ON ss.source_id = vcde.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vcde.dataset_id
        {where}
        ORDER BY vcde.updated_at DESC, ss.source_code, dc.dataset_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_procurement_readiness(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "vprs.snapshot_code"),
            ("contract_code", "vcp.contract_code"),
            ("entitlement_code", "vcde.entitlement_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vprs.status"),
            ("procurement_role", "vprs.procurement_role"),
            ("contract_status", "vprs.contract_status"),
            ("commercial_clearance", "vprs.commercial_clearance"),
            ("redistribution_allowed", "vprs.redistribution_allowed"),
            ("entitlement_status", "vprs.entitlement_status"),
            ("environment", "vprs.environment"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "vprs.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "vprs.as_of_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vprs.snapshot_id, vprs.snapshot_code,
            ss.source_code, dc.dataset_code,
            vcp.contract_code, vcde.entitlement_code,
            vprs.as_of_date, vprs.requested_by,
            vprs.trigger_mode, vprs.environment,
            vprs.status, vprs.procurement_role,
            vprs.readiness_score, vprs.procurement_status,
            vprs.contract_status, vprs.commercial_clearance,
            vprs.redistribution_allowed,
            vprs.contract_production_use_allowed,
            vprs.entitlement_status, vprs.entitlement_allowed_role,
            vprs.entitlement_commercial_use_allowed,
            vprs.entitlement_redistribution_allowed,
            vprs.entitlement_production_use_allowed,
            vprs.contract_ref, vprs.contract_end_date,
            vprs.rate_limit_per_min, vprs.daily_quota,
            vprs.monthly_quota, vprs.sla_uptime_pct,
            vprs.max_delay_minutes, vprs.vendor_profile_status,
            vprs.pi_readiness_status, vprs.pi_recommendation,
            vprs.live_gate_status, vprs.onboarding_status,
            vprs.live_closure_status, vprs.live_pilot_status,
            vprs.latest_review_code, vprs.latest_gate_code,
            vprs.latest_onboarding_code, vprs.latest_closure_code,
            vprs.latest_pilot_code, vprs.blocking_issues,
            vprs.required_actions, vprs.evidence,
            vprs.error_message, vprs.created_at, vprs.updated_at
        FROM qmeta.vendor_procurement_readiness_snapshot vprs
        JOIN qmeta.source_system ss ON ss.source_id = vprs.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vprs.dataset_id
        LEFT JOIN qmeta.vendor_contract_profile vcp ON vcp.contract_id = vprs.contract_id
        LEFT JOIN qmeta.vendor_contract_dataset_entitlement vcde ON vcde.entitlement_id = vprs.entitlement_id
        {where}
        ORDER BY vprs.as_of_date DESC, vprs.created_at DESC, vprs.snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_omicron5_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"omicron5 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_contract_inputs(
    postgres_dsn: str,
    *,
    source_codes: list[str] | None,
    dataset_codes: list[str] | None,
) -> list[dict[str, Any]]:
    filters = ["ss.is_active = TRUE", "vcp.status = 'active'", "vcde.status = 'active'"]
    values: list[Any] = []
    if source_codes:
        filters.append("ss.source_code = ANY(%s::text[])")
        values.append(source_codes)
    else:
        filters.append("ss.source_code = ANY(%s::text[])")
        values.append(list(DEFAULT_VENDOR_SOURCE_CODES))
    if dataset_codes:
        filters.append("dc.dataset_code = ANY(%s::text[])")
        values.append(dataset_codes)
    else:
        filters.append("dc.dataset_code = ANY(%s::text[])")
        values.append(list(DEFAULT_VENDOR_DATASETS))
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ss.source_id, ss.source_code, ss.source_name,
            dc.dataset_id, dc.dataset_code, dc.dataset_name,
            vcp.contract_id, vcp.contract_code, vcp.profile_id,
            vcp.provider_name, vcp.procurement_status,
            vcp.contract_status, vcp.commercial_clearance,
            vcp.redistribution_allowed,
            vcp.production_use_allowed AS contract_production_use_allowed,
            vcp.contract_ref, vcp.contract_end_date, vcp.next_review_at,
            vcp.rate_limit_per_min AS contract_rate_limit_per_min,
            vcp.daily_quota AS contract_daily_quota,
            vcp.monthly_quota AS contract_monthly_quota,
            vcp.sla_uptime_pct AS contract_sla_uptime_pct,
            vcp.status AS contract_profile_status,
            vcp.evidence AS contract_evidence,
            vcde.entitlement_id, vcde.entitlement_code,
            vcde.entitlement_status,
            vcde.allowed_role AS entitlement_allowed_role,
            vcde.commercial_use_allowed AS entitlement_commercial_use_allowed,
            vcde.redistribution_allowed AS entitlement_redistribution_allowed,
            vcde.production_use_allowed AS entitlement_production_use_allowed,
            vcde.schema_status, vcde.field_mapping_status,
            vcde.rate_limit_per_min AS entitlement_rate_limit_per_min,
            vcde.daily_quota AS entitlement_daily_quota,
            vcde.sla_uptime_pct AS entitlement_sla_uptime_pct,
            vcde.max_delay_minutes, vcde.blocking_issues AS entitlement_blocking_issues,
            vcde.required_actions AS entitlement_required_actions,
            vcde.status AS entitlement_profile_status,
            vcde.evidence AS entitlement_evidence,
            vip.status AS vendor_profile_status,
            latest_pi.review_code AS latest_review_code,
            latest_pi.status AS pi_readiness_status,
            latest_pi.recommendation AS pi_recommendation,
            latest_gate.gate_code AS latest_gate_code,
            latest_gate.status AS live_gate_status,
            latest_onboarding.run_code AS latest_onboarding_code,
            latest_onboarding.status AS onboarding_status,
            latest_closure.closure_code AS latest_closure_code,
            latest_closure.status AS live_closure_status,
            latest_pilot.pilot_code AS latest_pilot_code,
            latest_pilot.status AS live_pilot_status
        FROM qmeta.vendor_contract_dataset_entitlement vcde
        JOIN qmeta.vendor_contract_profile vcp ON vcp.contract_id = vcde.contract_id
        JOIN qmeta.source_system ss ON ss.source_id = vcde.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vcde.dataset_id
        LEFT JOIN qmeta.vendor_integration_profile vip ON vip.profile_id = vcp.profile_id
        LEFT JOIN LATERAL (
            SELECT review_code, status, recommendation
            FROM qmeta.vendor_readiness_review vrr
            WHERE vrr.source_id = vcde.source_id
              AND vrr.dataset_id = vcde.dataset_id
            ORDER BY vrr.review_date DESC, vrr.updated_at DESC, vrr.review_id DESC
            LIMIT 1
        ) latest_pi ON TRUE
        LEFT JOIN LATERAL (
            SELECT gate_code, status
            FROM qmeta.vendor_live_gate_run vlgr
            WHERE vlgr.source_id = vcde.source_id
              AND vlgr.dataset_id = vcde.dataset_id
            ORDER BY vlgr.started_at DESC, vlgr.gate_id DESC
            LIMIT 1
        ) latest_gate ON TRUE
        LEFT JOIN LATERAL (
            SELECT run_code, status
            FROM qmeta.vendor_onboarding_run vor
            WHERE vor.source_id = vcde.source_id
              AND dc.dataset_code = ANY(vor.dataset_codes)
            ORDER BY vor.started_at DESC, vor.run_id DESC
            LIMIT 1
        ) latest_onboarding ON TRUE
        LEFT JOIN LATERAL (
            SELECT closure_code, status
            FROM qmeta.vendor_live_closure_run vlcr
            WHERE vlcr.source_id = vcde.source_id
              AND dc.dataset_code = ANY(vlcr.dataset_codes)
            ORDER BY vlcr.started_at DESC, vlcr.closure_id DESC
            LIMIT 1
        ) latest_closure ON TRUE
        LEFT JOIN LATERAL (
            SELECT pilot_code, status
            FROM qmeta.vendor_live_pilot_run vlpr
            WHERE vlpr.source_id = vcde.source_id
              AND dc.dataset_code = ANY(vlpr.dataset_codes)
            ORDER BY vlpr.started_at DESC, vlpr.pilot_id DESC
            LIMIT 1
        ) latest_pilot ON TRUE
        WHERE {' AND '.join(filters)}
        ORDER BY ss.source_code, dc.dataset_code
        """,
        values,
    )


def _insert_procurement_snapshots(postgres_dsn: str, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not snapshots:
        return []
    inserted: list[dict[str, Any]] = []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for snapshot in snapshots:
                cursor.execute(
                    """
                    INSERT INTO qmeta.vendor_procurement_readiness_snapshot (
                        snapshot_code, source_id, dataset_id, contract_id,
                        entitlement_id, profile_id, as_of_date, requested_by,
                        trigger_mode, environment, status, procurement_role,
                        readiness_score, procurement_status, contract_status,
                        commercial_clearance, redistribution_allowed,
                        contract_production_use_allowed, entitlement_status,
                        entitlement_allowed_role, entitlement_commercial_use_allowed,
                        entitlement_redistribution_allowed, entitlement_production_use_allowed,
                        contract_ref, contract_end_date, next_review_at,
                        rate_limit_per_min, daily_quota, monthly_quota,
                        sla_uptime_pct, max_delay_minutes, vendor_profile_status,
                        pi_readiness_status, pi_recommendation, live_gate_status,
                        onboarding_status, live_closure_status, live_pilot_status,
                        latest_review_code, latest_gate_code, latest_onboarding_code,
                        latest_closure_code, latest_pilot_code, blocking_issues,
                        required_actions, evidence, error_message, updated_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s::jsonb, %s, now()
                    )
                    RETURNING
                        snapshot_id, snapshot_code,
                        (SELECT source_code FROM qmeta.source_system WHERE source_id = qmeta.vendor_procurement_readiness_snapshot.source_id) AS source_code,
                        (SELECT dataset_code FROM qmeta.dataset_catalog WHERE dataset_id = qmeta.vendor_procurement_readiness_snapshot.dataset_id) AS dataset_code,
                        as_of_date, requested_by, trigger_mode, environment,
                        status, procurement_role, readiness_score,
                        procurement_status, contract_status,
                        commercial_clearance, redistribution_allowed,
                        entitlement_status, entitlement_allowed_role,
                        rate_limit_per_min, daily_quota, sla_uptime_pct,
                        max_delay_minutes, pi_readiness_status,
                        live_gate_status, live_pilot_status,
                        blocking_issues, required_actions,
                        evidence, error_message, created_at, updated_at
                    """,
                    (
                        snapshot["snapshot_code"],
                        snapshot["source_id"],
                        snapshot["dataset_id"],
                        snapshot.get("contract_id"),
                        snapshot.get("entitlement_id"),
                        snapshot.get("profile_id"),
                        snapshot["as_of_date"],
                        snapshot["requested_by"],
                        snapshot["trigger_mode"],
                        snapshot["environment"],
                        snapshot["status"],
                        snapshot["procurement_role"],
                        snapshot["readiness_score"],
                        snapshot["procurement_status"],
                        snapshot["contract_status"],
                        snapshot["commercial_clearance"],
                        snapshot["redistribution_allowed"],
                        snapshot["contract_production_use_allowed"],
                        snapshot["entitlement_status"],
                        snapshot["entitlement_allowed_role"],
                        snapshot["entitlement_commercial_use_allowed"],
                        snapshot["entitlement_redistribution_allowed"],
                        snapshot["entitlement_production_use_allowed"],
                        snapshot.get("contract_ref"),
                        snapshot.get("contract_end_date"),
                        snapshot.get("next_review_at"),
                        snapshot.get("rate_limit_per_min"),
                        snapshot.get("daily_quota"),
                        snapshot.get("monthly_quota"),
                        snapshot.get("sla_uptime_pct"),
                        snapshot.get("max_delay_minutes"),
                        snapshot.get("vendor_profile_status"),
                        snapshot.get("pi_readiness_status"),
                        snapshot.get("pi_recommendation"),
                        snapshot.get("live_gate_status"),
                        snapshot.get("onboarding_status"),
                        snapshot.get("live_closure_status"),
                        snapshot.get("live_pilot_status"),
                        snapshot.get("latest_review_code"),
                        snapshot.get("latest_gate_code"),
                        snapshot.get("latest_onboarding_code"),
                        snapshot.get("latest_closure_code"),
                        snapshot.get("latest_pilot_code"),
                        snapshot["blocking_issues"],
                        snapshot["required_actions"],
                        _json(snapshot["evidence"]),
                        snapshot.get("error_message"),
                    ),
                )
                inserted.append(dict(cursor.fetchone()))
    return normalize_rows(inserted)


def _snapshot_evidence(
    row: dict[str, Any],
    thresholds: dict[str, Any],
    requested_by: str,
    trigger_mode: str,
    environment: str,
) -> dict[str, Any]:
    return {
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "thresholds": thresholds,
        "source": {
            "source_code": row.get("source_code"),
            "provider_name": row.get("provider_name"),
            "vendor_profile_status": row.get("vendor_profile_status"),
        },
        "contract": {
            "contract_code": row.get("contract_code"),
            "contract_ref_present": bool(row.get("contract_ref")),
            "evidence": _json_object(row.get("contract_evidence")),
        },
        "entitlement": {
            "entitlement_code": row.get("entitlement_code"),
            "schema_status": row.get("schema_status"),
            "field_mapping_status": row.get("field_mapping_status"),
            "evidence": _json_object(row.get("entitlement_evidence")),
        },
        "live_evidence": {
            "pi_review_code": row.get("latest_review_code"),
            "pi_status": row.get("pi_readiness_status"),
            "pi_recommendation": row.get("pi_recommendation"),
            "gate_code": row.get("latest_gate_code"),
            "gate_status": row.get("live_gate_status"),
            "onboarding_code": row.get("latest_onboarding_code"),
            "onboarding_status": row.get("onboarding_status"),
            "closure_code": row.get("latest_closure_code"),
            "closure_status": row.get("live_closure_status"),
            "pilot_code": row.get("latest_pilot_code"),
            "pilot_status": row.get("live_pilot_status"),
        },
        "policy": {
            "primary_candidate_requires_active_contract": True,
            "primary_candidate_requires_dataset_entitlement": True,
            "primary_candidate_requires_redistribution_and_production_rights": True,
            "primary_candidate_requires_quota_sla_and_schema": True,
        },
    }


def _thresholds(
    *,
    min_sla_uptime_pct: float = 99.5,
    min_rate_limit_per_min: int = 60,
    require_live_evidence: bool = False,
) -> dict[str, Any]:
    return {
        "min_sla_uptime_pct": min_sla_uptime_pct,
        "min_rate_limit_per_min": min_rate_limit_per_min,
        "require_live_evidence": require_live_evidence,
    }


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    min_sla_uptime_pct: float,
    min_rate_limit_per_min: int,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, once, scheduled, smoke")
    if min_sla_uptime_pct < 0 or min_sla_uptime_pct > 100:
        raise QDataValidationError("min_sla_uptime_pct must be between 0 and 100")
    if min_rate_limit_per_min <= 0:
        raise QDataValidationError("min_rate_limit_per_min must be greater than 0")


def _readiness_score(issues: list[str], primary_rights: bool, live_ready: bool, require_live_evidence: bool) -> float:
    if primary_rights and (live_ready or not require_live_evidence):
        return 100.0 if live_ready or not require_live_evidence else 92.0
    score = 100.0
    penalties = {
        "contract_profile_missing": 100,
        "dataset_entitlement_missing": 100,
        "contract_status_": 14,
        "procurement_status_": 10,
        "commercial_clearance_": 14,
        "redistribution_allowed_": 12,
        "production_use_not_allowed": 12,
        "entitlement_status_": 10,
        "entitlement_commercial_use_not_allowed": 10,
        "entitlement_redistribution_allowed_": 10,
        "schema_status_": 8,
        "field_mapping_status_": 8,
        "rate_limit_per_min": 8,
        "daily_quota_missing": 8,
        "sla_uptime_pct": 8,
        "max_delay_minutes_missing": 4,
        "latest_live_or_readiness_evidence_blocked": 20,
        "live_evidence_not_ready": 12,
    }
    for issue in issues:
        score -= next((penalty for prefix, penalty in penalties.items() if issue.startswith(prefix) or prefix in issue), 4)
    return round(max(0.0, min(100.0, score)), 4)


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
        where, values = _append_where(where, values, f"{column} >= %s", parse_date(start, "start_date"))
    if end:
        where, values = _append_where(where, values, f"{column} <= %s", parse_date(end, "end_date"))
    return where, values


def _report_keys(row: dict[str, Any]) -> list[str]:
    preferred = [
        "as_of_date",
        "snapshot_code",
        "contract_code",
        "entitlement_code",
        "source_code",
        "dataset_code",
        "status",
        "procurement_role",
        "readiness_score",
        "procurement_status",
        "contract_status",
        "commercial_clearance",
        "redistribution_allowed",
        "entitlement_status",
        "entitlement_allowed_role",
        "rate_limit_per_min",
        "daily_quota",
        "sla_uptime_pct",
        "pi_readiness_status",
        "live_gate_status",
        "live_pilot_status",
        "blocking_issues",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _cap_role(desired_role: str, max_allowed_role: str) -> str:
    desired_rank = ROLE_ORDER.get(desired_role, 0)
    max_rank = ROLE_ORDER.get(max_allowed_role, ROLE_ORDER["validator"])
    capped_rank = min(desired_rank, max_rank)
    for role, rank in ROLE_ORDER.items():
        if rank == capped_rank:
            return role
    return "blocked"


def _as_of_date(value: str | date | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        return parse_date(value, "as_of_date")
    return datetime.now(timezone.utc).date()


def _normalize_optional_codes(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = _dedupe(str(value).strip() for value in values if str(value).strip())
    return normalized or None


def _snapshot_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"omicron5-procurement-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


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


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def _effective_int(primary: Any, fallback: Any) -> int | None:
    value = primary if primary not in (None, "") else fallback
    return _int_or_none(value)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _effective_float(primary: Any, fallback: Any) -> float | None:
    value = primary if primary not in (None, "") else fallback
    if value in (None, ""):
        return None
    return float(value)


def _parse_optional_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return parse_date(value, "contract_end_date")
    return None


def _date_iso(value: Any) -> str | None:
    parsed = _parse_optional_date(value)
    return parsed.isoformat() if parsed else None


def _is_overdue_timestamp(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, datetime):
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
        return value < now
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return parsed < now
    return False


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Omicron-5 vendor contract readiness") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    return _connect(_require_dsn(postgres_dsn))


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Omicron-5 vendor contract readiness")
    return postgres_dsn
