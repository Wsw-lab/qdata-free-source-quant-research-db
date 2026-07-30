from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.iota3_free_source_fabric import DEFAULT_DATASETS, FREE_SOURCE_CANDIDATES


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
ADMISSION_STATUSES = {"approved", "conditional", "review_required", "blocked", "no_data"}
ADMISSION_ROLES = {"blocked", "research_only", "validator", "backup", "primary_candidate"}
ROLE_ORDER = {
    "blocked": 0,
    "research_only": 1,
    "validator": 2,
    "backup": 3,
    "primary_candidate": 4,
}
DEFAULT_ADMISSION_DATASETS = tuple(dict.fromkeys(DEFAULT_DATASETS + ("financial_metric_pit", "financial_statement_pit")))


def run_free_source_admission_review(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    lookback_days: int = 30,
    source_codes: Iterable[str] | None = None,
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "xi5",
    trigger_mode: str = "manual",
    environment: str = "local",
    min_validator_score: float = 55.0,
    min_backup_score: float = 75.0,
    min_primary_score: float = 90.0,
    min_coverage_rate: float = 0.95,
    max_conflict_rate_bps: float = 5.0,
    write_db: bool = True,
) -> list[dict[str, Any]]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        lookback_days=lookback_days,
        min_validator_score=min_validator_score,
        min_backup_score=min_backup_score,
        min_primary_score=min_primary_score,
        min_coverage_rate=min_coverage_rate,
        max_conflict_rate_bps=max_conflict_rate_bps,
    )
    snapshot_date = _as_of_date(as_of_date)
    thresholds = _thresholds(
        min_validator_score=min_validator_score,
        min_backup_score=min_backup_score,
        min_primary_score=min_primary_score,
        min_coverage_rate=min_coverage_rate,
        max_conflict_rate_bps=max_conflict_rate_bps,
    )
    rows = _load_admission_inputs(
        _require_dsn(postgres_dsn),
        lookback_days=lookback_days,
        source_codes=_normalize_optional_codes(source_codes),
        dataset_codes=_normalize_optional_codes(dataset_codes),
    )
    snapshots = build_admission_snapshots(
        rows,
        as_of_date=snapshot_date,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
        thresholds=thresholds,
    )
    if not write_db:
        return normalize_rows(snapshots)
    return _insert_admission_snapshots(_require_dsn(postgres_dsn), snapshots)


def build_admission_snapshots(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    requested_by: str = "xi5",
    trigger_mode: str = "manual",
    environment: str = "local",
    thresholds: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot_date = _as_of_date(as_of_date)
    thresholds = thresholds or _thresholds()
    snapshots: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("source_code") or ""), str(item.get("dataset_code") or ""))):
        evaluation = evaluate_source_admission(row, thresholds)
        reliability_evidence = _json_object(row.get("reliability_evidence"))
        latest_fabric_code, latest_fabric_status = _latest_fabric_evidence(reliability_evidence)
        evidence = {
            "requested_by": requested_by,
            "trigger_mode": trigger_mode,
            "environment": environment,
            "thresholds": thresholds,
            "source": {
                "source_code": row.get("source_code"),
                "source_type": row.get("source_type"),
                "license_scope": row.get("source_license_scope"),
                "candidate_notes": _candidate_notes(str(row.get("source_code") or "")),
            },
            "profile": _profile_evidence(row),
            "reliability": {
                "snapshot_code": row.get("reliability_snapshot_code"),
                "status": row.get("reliability_status") or "no_data",
                "score": _float(row.get("reliability_score")),
                "observation_count": _int(row.get("observation_count")),
                "latest_fabric_code": latest_fabric_code,
                "latest_fabric_status": latest_fabric_status,
                "samples": reliability_evidence.get("observation_samples") or [],
            },
            "policy": {
                "free_source_requires_contract_for_primary": True,
                "free_source_without_redistribution_rights_is_not_production_core": True,
                "approved_requires_contract_terms_quota_and_reliability": True,
            },
        }
        snapshot = {
            "snapshot_code": _snapshot_code(
                str(row["source_code"]),
                str(row["dataset_code"]),
                str(evaluation["status"]),
            ),
            "source_id": row["source_id"],
            "dataset_id": row["dataset_id"],
            "profile_id": row.get("profile_id"),
            "reliability_snapshot_id": row.get("reliability_snapshot_id"),
            "source_code": row["source_code"],
            "dataset_code": row["dataset_code"],
            "as_of_date": snapshot_date.isoformat(),
            "requested_by": requested_by,
            "trigger_mode": trigger_mode,
            "environment": environment,
            "status": evaluation["status"],
            "admission_role": evaluation["admission_role"],
            "max_allowed_role": row.get("max_allowed_role") or "research_only",
            "license_type": row.get("license_type") or "unknown",
            "license_status": row.get("license_status") or "unknown",
            "commercial_clearance": row.get("commercial_clearance") or "blocked",
            "redistribution_allowed": row.get("redistribution_allowed") or "unknown",
            "contract_status": row.get("contract_status") or "none",
            "contract_ref": row.get("contract_ref"),
            "terms_review_status": row.get("terms_review_status") or "missing",
            "api_terms_url": row.get("api_terms_url"),
            "rate_limit_per_min": row.get("rate_limit_per_min"),
            "daily_quota": row.get("daily_quota"),
            "reliability_status": row.get("reliability_status") or "no_data",
            "reliability_score": _float(row.get("reliability_score")),
            "success_rate": _float_or_none(row.get("success_rate")),
            "coverage_rate": _float_or_none(row.get("coverage_rate")),
            "conflict_rate_bps": _float_or_none(row.get("conflict_rate_bps")),
            "observation_count": _int(row.get("observation_count")),
            "reliability_snapshot_code": row.get("reliability_snapshot_code"),
            "latest_fabric_code": latest_fabric_code,
            "latest_fabric_status": latest_fabric_status,
            "blocking_issues": evaluation["blocking_issues"],
            "required_actions": evaluation["required_actions"],
            "evidence": evidence,
            "error_message": None,
        }
        snapshots.append(snapshot)
    return snapshots


def evaluate_source_admission(row: dict[str, Any], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = thresholds or _thresholds()
    min_validator_score = float(thresholds.get("min_validator_score", 55.0))
    min_backup_score = float(thresholds.get("min_backup_score", 75.0))
    min_primary_score = float(thresholds.get("min_primary_score", 90.0))
    min_coverage_rate = float(thresholds.get("min_coverage_rate", 0.95))
    max_conflict_rate_bps = float(thresholds.get("max_conflict_rate_bps", 5.0))

    reliability_status = str(row.get("reliability_status") or "no_data")
    reliability_score = _float(row.get("reliability_score"))
    coverage_rate = _float_or_none(row.get("coverage_rate"))
    conflict_rate_bps = _float_or_none(row.get("conflict_rate_bps"))
    observation_count = _int(row.get("observation_count"))
    license_status = str(row.get("license_status") or "unknown")
    commercial_clearance = str(row.get("commercial_clearance") or "blocked")
    redistribution_allowed = str(row.get("redistribution_allowed") or "unknown")
    contract_status = str(row.get("contract_status") or "none")
    terms_review_status = str(row.get("terms_review_status") or "missing")
    profile_status = str(row.get("profile_status") or "active")
    max_allowed_role = str(row.get("max_allowed_role") or "research_only")
    rate_limit_per_min = _int(row.get("rate_limit_per_min"))
    daily_quota = _int(row.get("daily_quota"))

    issues: list[str] = []
    if observation_count <= 0 or reliability_status == "no_data":
        issues.append("no_recent_reliability_snapshot")
    if reliability_status in {"rejected", "degraded"}:
        issues.append(f"reliability_status_{reliability_status}")
    if reliability_score < min_validator_score:
        issues.append(f"reliability_score_below_validator:{reliability_score:.4f}/{min_validator_score:.4f}")
    if coverage_rate is None:
        issues.append("coverage_rate_missing")
    elif coverage_rate < min_coverage_rate:
        issues.append(f"coverage_rate_below_primary:{coverage_rate:.6f}/{min_coverage_rate:.6f}")
    if conflict_rate_bps is None:
        issues.append("conflict_rate_missing")
    elif conflict_rate_bps > max_conflict_rate_bps:
        issues.append(f"conflict_rate_above_primary:{conflict_rate_bps:.6f}/{max_conflict_rate_bps:.6f}")
    if profile_status in {"inactive", "expired", "blocked"}:
        issues.append(f"profile_status_{profile_status}")
    if license_status in {"unknown", "research_only", "review_required", "blocked", "local_smoke"}:
        issues.append(f"license_status_{license_status}")
    if commercial_clearance != "clear":
        issues.append(f"commercial_clearance_{commercial_clearance}")
    if redistribution_allowed != "yes":
        issues.append(f"redistribution_allowed_{redistribution_allowed}")
    if contract_status != "active":
        issues.append(f"contract_status_{contract_status}")
    if terms_review_status != "approved":
        issues.append(f"terms_review_status_{terms_review_status}")
    if rate_limit_per_min <= 0:
        issues.append("rate_limit_per_min_missing")
    if daily_quota <= 0:
        issues.append("daily_quota_missing")

    legal_blocked = (
        profile_status == "blocked"
        or license_status == "blocked"
        or contract_status in {"expired", "terminated"}
        or terms_review_status in {"rejected", "expired"}
    )
    has_recent_data = observation_count > 0 and reliability_status != "no_data"
    primary_legal = (
        commercial_clearance == "clear"
        and redistribution_allowed == "yes"
        and contract_status == "active"
        and terms_review_status == "approved"
        and license_status in {"contracted", "approved", "official_public"}
        and rate_limit_per_min > 0
        and daily_quota > 0
    )
    primary_reliable = (
        reliability_status == "ready"
        and reliability_score >= min_primary_score
        and (coverage_rate or 0.0) >= min_coverage_rate
        and (conflict_rate_bps or 0.0) <= max_conflict_rate_bps
    )

    if not has_recent_data:
        status = "no_data"
        role = "blocked"
    elif legal_blocked:
        status = "blocked"
        role = "blocked"
    elif reliability_status == "rejected" or reliability_score < min_validator_score:
        status = "blocked"
        role = "blocked"
    elif primary_legal and primary_reliable:
        role = _cap_role("primary_candidate", max_allowed_role)
        status = "approved" if role == "primary_candidate" else "conditional"
    elif primary_legal and reliability_score >= min_backup_score:
        role = _cap_role("backup", max_allowed_role)
        status = "conditional"
    else:
        desired_role = "backup" if reliability_score >= min_backup_score else "validator"
        role = _cap_role(desired_role, max_allowed_role)
        if role == "blocked":
            status = "blocked"
        elif commercial_clearance == "review_required" or redistribution_allowed == "unknown" or terms_review_status in {"missing", "pending"}:
            status = "review_required"
        else:
            status = "conditional"

    actions = build_required_actions(issues, status, role)
    return {
        "status": status,
        "admission_role": role,
        "blocking_issues": _dedupe(issues),
        "required_actions": actions,
    }


def build_required_actions(issues: list[str], status: str, role: str) -> list[str]:
    issue_text = " ".join(issues)
    actions: list[str] = []
    if "no_recent_reliability_snapshot" in issues:
        actions.append("Run Iota-5/Kappa-5 canary and reliability scoring before using this source in routing decisions.")
    if "reliability_status_rejected" in issues or "reliability_status_degraded" in issues or "reliability_score_below_validator" in issue_text:
        actions.append("Keep the source out of automatic fallback until reliability score and latest canary recover.")
    if "commercial_clearance_" in issue_text or "license_status_" in issue_text:
        actions.append("Obtain written commercial-use clearance and record it in the Xi-5 admission profile.")
    if "redistribution_allowed_" in issue_text:
        actions.append("Confirm redistribution/cache rights before exposing derived data to clients.")
    if "contract_status_" in issue_text:
        actions.append("Attach an active contract_ref or keep the source as research/validation evidence only.")
    if "terms_review_status_" in issue_text:
        actions.append("Complete legal terms review and mark terms_review_status=approved before production promotion.")
    if "rate_limit_per_min_missing" in issues or "daily_quota_missing" in issues:
        actions.append("Record production rate limit and daily quota so schedulers can enforce source capacity.")
    if "coverage_rate_below_primary" in issue_text or "conflict_rate_above_primary" in issue_text:
        actions.append("Compare against an authorized primary source and fix coverage/conflict gaps before backup or primary use.")
    if status == "approved":
        actions.append("Allow controlled primary-candidate pilot with Pi/Theta evidence and ongoing Nu-5 health monitoring.")
    elif role in {"validator", "backup"}:
        actions.append("Use only as validation or fallback evidence until all primary admission blockers are closed.")
    else:
        actions.append("Do not route production traffic to this source.")
    return _dedupe(actions)


def list_free_source_admission_profiles(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("profile_code", "fsap.profile_code"),
            ("source_code", "ss.source_code"),
            ("license_type", "fsap.license_type"),
            ("license_status", "fsap.license_status"),
            ("commercial_clearance", "fsap.commercial_clearance"),
            ("redistribution_allowed", "fsap.redistribution_allowed"),
            ("contract_status", "fsap.contract_status"),
            ("terms_review_status", "fsap.terms_review_status"),
            ("max_allowed_role", "fsap.max_allowed_role"),
            ("status", "fsap.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsap.profile_id, fsap.profile_code, ss.source_code,
            ss.source_name, ss.source_type, fsap.provider_name,
            fsap.license_type, fsap.license_status,
            fsap.commercial_clearance, fsap.redistribution_allowed,
            fsap.contract_status, fsap.contract_ref,
            fsap.terms_review_status, fsap.api_terms_url,
            fsap.rate_limit_per_min, fsap.daily_quota,
            fsap.max_allowed_role, fsap.status, fsap.reviewed_by,
            fsap.reviewed_at, fsap.expires_at, fsap.evidence,
            fsap.created_at, fsap.updated_at
        FROM qmeta.free_source_admission_profile fsap
        JOIN qmeta.source_system ss ON ss.source_id = fsap.source_id
        {where}
        ORDER BY fsap.updated_at DESC, ss.source_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_free_source_admission_snapshots(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "fsas.snapshot_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "fsas.status"),
            ("admission_role", "fsas.admission_role"),
            ("license_type", "fsas.license_type"),
            ("license_status", "fsas.license_status"),
            ("commercial_clearance", "fsas.commercial_clearance"),
            ("redistribution_allowed", "fsas.redistribution_allowed"),
            ("contract_status", "fsas.contract_status"),
            ("terms_review_status", "fsas.terms_review_status"),
            ("max_allowed_role", "fsas.max_allowed_role"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "fsas.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "fsas.as_of_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsas.admission_id, fsas.snapshot_code, ss.source_code,
            dc.dataset_code, fsas.as_of_date, fsas.requested_by,
            fsas.trigger_mode, fsas.environment, fsas.status,
            fsas.admission_role, fsas.max_allowed_role,
            fsas.license_type, fsas.license_status,
            fsas.commercial_clearance, fsas.redistribution_allowed,
            fsas.contract_status, fsas.contract_ref,
            fsas.terms_review_status, fsas.api_terms_url,
            fsas.rate_limit_per_min, fsas.daily_quota,
            fsas.reliability_status, fsas.reliability_score,
            fsas.success_rate, fsas.coverage_rate, fsas.conflict_rate_bps,
            fsas.observation_count, fsas.reliability_snapshot_code,
            fsas.latest_fabric_code, fsas.latest_fabric_status,
            fsas.blocking_issues, fsas.required_actions,
            fsas.evidence, fsas.error_message,
            fsas.created_at, fsas.updated_at
        FROM qmeta.free_source_admission_snapshot fsas
        JOIN qmeta.source_system ss ON ss.source_id = fsas.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsas.dataset_id
        {where}
        ORDER BY fsas.as_of_date DESC, fsas.created_at DESC, fsas.admission_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_xi5_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"xi5 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_admission_inputs(
    postgres_dsn: str,
    *,
    lookback_days: int,
    source_codes: list[str] | None,
    dataset_codes: list[str] | None,
) -> list[dict[str, Any]]:
    profiles = _load_profiles(postgres_dsn, source_codes)
    datasets = _load_datasets(postgres_dsn, dataset_codes)
    reliability = _load_latest_reliability(postgres_dsn, lookback_days, source_codes, dataset_codes)
    reliability_by_pair = {(row["source_code"], row["dataset_code"]): row for row in reliability}
    dataset_by_code = {row["dataset_code"]: row for row in datasets}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for profile in profiles:
        source_code = str(profile["source_code"])
        candidate = FREE_SOURCE_CANDIDATES.get(source_code)
        supported = set(candidate.supported_datasets if candidate else dataset_by_code)
        for dataset_code, dataset in sorted(dataset_by_code.items()):
            pair = (source_code, dataset_code)
            if dataset_code not in supported and pair not in reliability_by_pair:
                continue
            seen.add(pair)
            rows.append(_merge_input_row(profile, dataset, reliability_by_pair.get(pair)))
    for pair, rel in sorted(reliability_by_pair.items()):
        if pair in seen:
            continue
        profile = next((item for item in profiles if item["source_code"] == pair[0]), None)
        dataset = dataset_by_code.get(pair[1])
        if profile and dataset:
            rows.append(_merge_input_row(profile, dataset, rel))
    return normalize_rows(rows)


def _load_profiles(postgres_dsn: str, source_codes: list[str] | None) -> list[dict[str, Any]]:
    where = ["ss.is_active = TRUE", "fsap.status = 'active'"]
    values: list[Any] = []
    if source_codes:
        where.append("ss.source_code = ANY(%s::text[])")
        values.append(source_codes)
    else:
        where.append("ss.source_code = ANY(%s::text[])")
        values.append(sorted(FREE_SOURCE_CANDIDATES))
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ss.source_id, ss.source_code, ss.source_name,
            ss.source_type, ss.license_scope AS source_license_scope,
            ss.update_frequency, ss.latency_level, ss.owner AS source_owner,
            fsap.profile_id, fsap.profile_code, fsap.provider_name,
            fsap.license_type, fsap.license_status,
            fsap.commercial_clearance, fsap.redistribution_allowed,
            fsap.contract_status, fsap.contract_ref,
            fsap.terms_review_status, fsap.api_terms_url,
            fsap.rate_limit_per_min, fsap.daily_quota,
            fsap.max_allowed_role, fsap.status AS profile_status,
            fsap.reviewed_by, fsap.reviewed_at, fsap.expires_at,
            fsap.evidence AS profile_evidence
        FROM qmeta.free_source_admission_profile fsap
        JOIN qmeta.source_system ss ON ss.source_id = fsap.source_id
        WHERE {' AND '.join(where)}
        ORDER BY ss.source_code
        """,
        values,
    )


def _load_datasets(postgres_dsn: str, dataset_codes: list[str] | None) -> list[dict[str, Any]]:
    where = ["is_active = TRUE"]
    values: list[Any] = []
    if dataset_codes:
        where.append("dataset_code = ANY(%s::text[])")
        values.append(dataset_codes)
    else:
        where.append("dataset_code = ANY(%s::text[])")
        values.append(list(DEFAULT_ADMISSION_DATASETS))
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT dataset_id, dataset_code, dataset_name, asset_type, frequency, storage_layer, pit_required
        FROM qmeta.dataset_catalog
        WHERE {' AND '.join(where)}
        ORDER BY dataset_code
        """,
        values,
    )


def _load_latest_reliability(
    postgres_dsn: str,
    lookback_days: int,
    source_codes: list[str] | None,
    dataset_codes: list[str] | None,
) -> list[dict[str, Any]]:
    filters = ["fsrs.created_at >= now() - (%s::int * INTERVAL '1 day')"]
    values: list[Any] = [lookback_days]
    if source_codes:
        filters.append("ss.source_code = ANY(%s::text[])")
        values.append(source_codes)
    if dataset_codes:
        filters.append("dc.dataset_code = ANY(%s::text[])")
        values.append(dataset_codes)
    return _fetch_rows(
        postgres_dsn,
        f"""
        WITH ranked AS (
            SELECT
                fsrs.snapshot_id AS reliability_snapshot_id,
                fsrs.snapshot_code AS reliability_snapshot_code,
                ss.source_code,
                dc.dataset_code,
                fsrs.as_of_date AS reliability_as_of_date,
                fsrs.status AS reliability_status,
                fsrs.recommended_role AS reliability_recommended_role,
                fsrs.reliability_score,
                fsrs.success_rate,
                fsrs.coverage_rate,
                fsrs.conflict_rate_bps,
                fsrs.observation_count,
                fsrs.license_status AS reliability_license_status,
                fsrs.commercial_clearance AS reliability_commercial_clearance,
                fsrs.degradation_reasons,
                fsrs.recovery_actions,
                fsrs.evidence AS reliability_evidence,
                fsrs.created_at AS reliability_created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY fsrs.source_id, fsrs.dataset_id
                    ORDER BY fsrs.as_of_date DESC, fsrs.created_at DESC, fsrs.snapshot_id DESC
                ) AS rn
            FROM qmeta.free_source_reliability_snapshot fsrs
            JOIN qmeta.source_system ss ON ss.source_id = fsrs.source_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsrs.dataset_id
            WHERE {' AND '.join(filters)}
        )
        SELECT *
        FROM ranked
        WHERE rn = 1
        ORDER BY source_code, dataset_code
        """,
        values,
    )


def _merge_input_row(profile: dict[str, Any], dataset: dict[str, Any], reliability: dict[str, Any] | None) -> dict[str, Any]:
    row = {
        **profile,
        "dataset_id": dataset["dataset_id"],
        "dataset_code": dataset["dataset_code"],
        "dataset_name": dataset["dataset_name"],
        "asset_type": dataset.get("asset_type"),
        "frequency": dataset.get("frequency"),
        "storage_layer": dataset.get("storage_layer"),
        "pit_required": dataset.get("pit_required"),
        "reliability_snapshot_id": None,
        "reliability_snapshot_code": None,
        "reliability_status": "no_data",
        "reliability_score": 0.0,
        "success_rate": None,
        "coverage_rate": None,
        "conflict_rate_bps": None,
        "observation_count": 0,
        "reliability_evidence": {},
    }
    if reliability:
        row.update(reliability)
    return row


def _insert_admission_snapshots(postgres_dsn: str, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not snapshots:
        return []
    inserted: list[dict[str, Any]] = []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for snapshot in snapshots:
                cursor.execute(
                    """
                    INSERT INTO qmeta.free_source_admission_snapshot (
                        snapshot_code, source_id, dataset_id, profile_id,
                        reliability_snapshot_id, as_of_date, requested_by,
                        trigger_mode, environment, status, admission_role,
                        max_allowed_role, license_type, license_status,
                        commercial_clearance, redistribution_allowed,
                        contract_status, contract_ref, terms_review_status,
                        api_terms_url, rate_limit_per_min, daily_quota,
                        reliability_status, reliability_score, success_rate,
                        coverage_rate, conflict_rate_bps, observation_count,
                        reliability_snapshot_code, latest_fabric_code,
                        latest_fabric_status, blocking_issues,
                        required_actions, evidence, error_message, updated_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s::jsonb, %s, now()
                    )
                    RETURNING
                        admission_id, snapshot_code,
                        (SELECT source_code FROM qmeta.source_system WHERE source_id = qmeta.free_source_admission_snapshot.source_id) AS source_code,
                        (SELECT dataset_code FROM qmeta.dataset_catalog WHERE dataset_id = qmeta.free_source_admission_snapshot.dataset_id) AS dataset_code,
                        as_of_date, requested_by, trigger_mode,
                        environment, status, admission_role, max_allowed_role,
                        license_type, license_status, commercial_clearance,
                        redistribution_allowed, contract_status, contract_ref,
                        terms_review_status, rate_limit_per_min, daily_quota,
                        reliability_status, reliability_score, success_rate,
                        coverage_rate, conflict_rate_bps, observation_count,
                        reliability_snapshot_code, latest_fabric_code,
                        latest_fabric_status, blocking_issues, required_actions,
                        evidence, error_message, created_at, updated_at
                    """,
                    (
                        snapshot["snapshot_code"],
                        snapshot["source_id"],
                        snapshot["dataset_id"],
                        snapshot.get("profile_id"),
                        snapshot.get("reliability_snapshot_id"),
                        snapshot["as_of_date"],
                        snapshot["requested_by"],
                        snapshot["trigger_mode"],
                        snapshot["environment"],
                        snapshot["status"],
                        snapshot["admission_role"],
                        snapshot["max_allowed_role"],
                        snapshot["license_type"],
                        snapshot["license_status"],
                        snapshot["commercial_clearance"],
                        snapshot["redistribution_allowed"],
                        snapshot["contract_status"],
                        snapshot.get("contract_ref"),
                        snapshot["terms_review_status"],
                        snapshot.get("api_terms_url"),
                        snapshot.get("rate_limit_per_min"),
                        snapshot.get("daily_quota"),
                        snapshot["reliability_status"],
                        snapshot["reliability_score"],
                        snapshot.get("success_rate"),
                        snapshot.get("coverage_rate"),
                        snapshot.get("conflict_rate_bps"),
                        snapshot["observation_count"],
                        snapshot.get("reliability_snapshot_code"),
                        snapshot.get("latest_fabric_code"),
                        snapshot.get("latest_fabric_status"),
                        snapshot["blocking_issues"],
                        snapshot["required_actions"],
                        _json(snapshot["evidence"]),
                        snapshot.get("error_message"),
                    ),
                )
                inserted.append(dict(cursor.fetchone()))
    return normalize_rows(inserted)


def _thresholds(
    *,
    min_validator_score: float = 55.0,
    min_backup_score: float = 75.0,
    min_primary_score: float = 90.0,
    min_coverage_rate: float = 0.95,
    max_conflict_rate_bps: float = 5.0,
) -> dict[str, Any]:
    return {
        "min_validator_score": min_validator_score,
        "min_backup_score": min_backup_score,
        "min_primary_score": min_primary_score,
        "min_coverage_rate": min_coverage_rate,
        "max_conflict_rate_bps": max_conflict_rate_bps,
    }


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    lookback_days: int,
    min_validator_score: float,
    min_backup_score: float,
    min_primary_score: float,
    min_coverage_rate: float,
    max_conflict_rate_bps: float,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, once, scheduled, smoke")
    if lookback_days <= 0:
        raise QDataValidationError("lookback_days must be greater than 0")
    if not (0 <= min_validator_score <= min_backup_score <= min_primary_score <= 100):
        raise QDataValidationError("score thresholds must be ordered between 0 and 100")
    if min_coverage_rate < 0 or min_coverage_rate > 1:
        raise QDataValidationError("min_coverage_rate must be between 0 and 1")
    if max_conflict_rate_bps < 0:
        raise QDataValidationError("max_conflict_rate_bps must be greater than or equal to 0")


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
        "profile_code",
        "source_code",
        "dataset_code",
        "status",
        "admission_role",
        "max_allowed_role",
        "license_type",
        "license_status",
        "commercial_clearance",
        "redistribution_allowed",
        "contract_status",
        "terms_review_status",
        "reliability_status",
        "reliability_score",
        "blocking_issues",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _latest_fabric_evidence(evidence: dict[str, Any]) -> tuple[str | None, str | None]:
    samples = evidence.get("observation_samples")
    if isinstance(samples, list) and samples:
        sample = samples[0] if isinstance(samples[0], dict) else {}
        return sample.get("fabric_code"), sample.get("status")
    return None, None


def _profile_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_code": row.get("profile_code"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "expires_at": row.get("expires_at"),
        "evidence": _json_object(row.get("profile_evidence")),
    }


def _candidate_notes(source_code: str) -> str:
    candidate = FREE_SOURCE_CANDIDATES.get(source_code)
    return candidate.notes if candidate else ""


def _cap_role(desired_role: str, max_allowed_role: str) -> str:
    desired_rank = ROLE_ORDER.get(desired_role, 0)
    max_rank = ROLE_ORDER.get(max_allowed_role, ROLE_ORDER["research_only"])
    capped_rank = min(desired_rank, max_rank)
    for role, rank in ROLE_ORDER.items():
        if rank == capped_rank:
            return role
    return "blocked"


def _as_of_date(value: str | date | None) -> date:
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
    return f"xi5-admission-{source_code}-{dataset_code}-{status}-{digest}"[:180]


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


def _int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Xi-5 free source admission") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    return _connect(_require_dsn(postgres_dsn))


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Xi-5 free source admission")
    return postgres_dsn
