from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.iota3_free_source_fabric import FREE_SOURCE_CANDIDATES


SNAPSHOT_STATUSES = {"no_data", "ready", "watch", "degraded", "rejected"}
RECOMMENDED_ROLES = {"validator", "backup", "research_only", "degraded", "reject"}
COMMERCIAL_CLEARANCES = {"clear", "review_required", "blocked"}
LICENSE_STATUSES = {"unknown", "local_smoke", "official_public", "research_only", "review_required", "blocked"}


@dataclass
class SourceDatasetStats:
    source_code: str
    dataset_code: str
    as_of_date: date
    lookback_hours: int
    observations: list[dict[str, Any]]


def score_free_source_reliability(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    lookback_hours: int = 24,
    source_codes: Iterable[str] | None = None,
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "kappa5",
    trigger_mode: str = "manual",
    environment: str = "local",
) -> list[dict[str, Any]]:
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    snapshot_date = _as_of_date(as_of_date)
    requested_sources = _normalize_optional_codes(source_codes)
    requested_datasets = _normalize_optional_codes(dataset_codes)
    rows = _load_fabric_result_rows(
        postgres_dsn,
        snapshot_date=snapshot_date,
        lookback_hours=lookback_hours,
        source_codes=requested_sources,
        dataset_codes=requested_datasets,
    )
    snapshots = build_reliability_snapshots_from_rows(
        rows,
        as_of_date=snapshot_date,
        lookback_hours=lookback_hours,
        source_codes=requested_sources,
        dataset_codes=requested_datasets,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        environment=environment,
    )
    return _insert_reliability_snapshots(postgres_dsn, snapshots)


def build_reliability_snapshots_from_rows(
    rows: list[dict[str, Any]],
    *,
    as_of_date: str | date | None = None,
    lookback_hours: int = 24,
    source_codes: Iterable[str] | None = None,
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "kappa5",
    trigger_mode: str = "manual",
    environment: str = "local",
) -> list[dict[str, Any]]:
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    snapshot_date = _as_of_date(as_of_date)
    requested_sources = _normalize_optional_codes(source_codes)
    requested_datasets = _normalize_optional_codes(dataset_codes)
    groups = _group_observations(rows, requested_sources, requested_datasets)
    if not groups and (requested_sources or requested_datasets):
        groups = _empty_groups(requested_sources, requested_datasets)
    snapshots = [
        _snapshot_from_stats(
            SourceDatasetStats(
                source_code=source_code,
                dataset_code=dataset_code,
                as_of_date=snapshot_date,
                lookback_hours=lookback_hours,
                observations=observations,
            ),
            requested_by=requested_by,
            trigger_mode=trigger_mode,
            environment=environment,
        )
        for (source_code, dataset_code), observations in sorted(groups.items())
    ]
    return snapshots


def list_free_source_reliability_snapshots(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "fsrs.snapshot_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "fsrs.status"),
            ("recommended_role", "fsrs.recommended_role"),
            ("license_status", "fsrs.license_status"),
            ("commercial_clearance", "fsrs.commercial_clearance"),
        ],
    )
    as_of_date = _param(params, "as_of_date")
    if as_of_date:
        where, values = _append_where(where, values, "fsrs.as_of_date = %s", parse_date(as_of_date, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "fsrs.as_of_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsrs.snapshot_id, fsrs.snapshot_code, ss.source_code,
            dc.dataset_code, fsrs.as_of_date, fsrs.lookback_hours,
            fsrs.status, fsrs.recommended_role, fsrs.reliability_score,
            fsrs.success_rate, fsrs.coverage_rate, fsrs.conflict_rate_bps,
            fsrs.observation_count, fsrs.success_count, fsrs.warning_count,
            fsrs.failed_count, fsrs.blocked_count,
            fsrs.consecutive_failure_count, fsrs.license_status,
            fsrs.commercial_clearance, fsrs.last_success_at,
            fsrs.last_failure_at, fsrs.degradation_reasons,
            fsrs.recovery_actions, fsrs.evidence, fsrs.created_at,
            fsrs.updated_at
        FROM qmeta.free_source_reliability_snapshot fsrs
        JOIN qmeta.source_system ss ON ss.source_id = fsrs.source_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsrs.dataset_id
        {where}
        ORDER BY fsrs.as_of_date DESC, fsrs.reliability_score DESC, fsrs.snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_kappa5_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"kappa5 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _load_fabric_result_rows(
    postgres_dsn: str,
    *,
    snapshot_date: date,
    lookback_hours: int,
    source_codes: list[str] | None,
    dataset_codes: list[str] | None,
) -> list[dict[str, Any]]:
    since = datetime.combine(snapshot_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1, hours=-lookback_hours)
    until = datetime.combine(snapshot_date, datetime.max.time(), tzinfo=timezone.utc)
    where = "WHERE fsfdr.started_at >= %s AND fsfdr.started_at <= %s"
    values: list[Any] = [since, until]
    if source_codes:
        where, values = _append_where(where, values, "fsfdr.source_codes && %s::text[]", source_codes)
    if dataset_codes:
        where, values = _append_where(where, values, "dc.dataset_code = ANY(%s::text[])", dataset_codes)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsfr.fabric_code, fsfdr.result_code, dc.dataset_code,
            fsfdr.status, fsfdr.coverage_status, fsfdr.consistency_status,
            fsfdr.license_status, fsfdr.freshness_status,
            fsfdr.recommendation, fsfdr.recommended_role,
            fsfdr.risk_level, fsfdr.baseline_source_code,
            fsfdr.source_codes, fsfdr.executed_sources,
            fsfdr.blocked_sources, fsfdr.missing_sources,
            fsfdr.license_blocking_sources, fsfdr.usable_source_count,
            fsfdr.coverage_rate, fsfdr.conflict_rate_bps,
            fsfdr.blocking_issues, fsfdr.next_actions,
            fsfdr.error_message, fsfdr.started_at, fsfdr.finished_at
        FROM qmeta.free_source_fabric_dataset_result fsfdr
        JOIN qmeta.free_source_fabric_run fsfr ON fsfr.fabric_id = fsfdr.fabric_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsfdr.dataset_id
        {where}
        ORDER BY fsfdr.started_at DESC, fsfdr.result_id DESC
        """,
        values,
    )


def _group_observations(
    rows: list[dict[str, Any]],
    source_codes: list[str] | None,
    dataset_codes: list[str] | None,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    source_filter = set(source_codes or [])
    dataset_filter = set(dataset_codes or [])
    for row in rows:
        dataset_code = str(row.get("dataset_code") or "").strip()
        if not dataset_code or dataset_filter and dataset_code not in dataset_filter:
            continue
        for source_code in _row_sources(row):
            if source_filter and source_code not in source_filter:
                continue
            observation = _source_observation(row, source_code, dataset_code)
            groups.setdefault((source_code, dataset_code), []).append(observation)
    return groups


def _empty_groups(source_codes: list[str] | None, dataset_codes: list[str] | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
    sources = source_codes or sorted(FREE_SOURCE_CANDIDATES)
    datasets = dataset_codes or ["daily_bar"]
    return {(source_code, dataset_code): [] for source_code in sources for dataset_code in datasets}


def _row_sources(row: dict[str, Any]) -> list[str]:
    codes = _list_value(row.get("source_codes"))
    if codes:
        return codes
    return _list_value(row.get("executed_sources")) + _list_value(row.get("blocked_sources")) + _list_value(row.get("missing_sources"))


def _source_observation(row: dict[str, Any], source_code: str, dataset_code: str) -> dict[str, Any]:
    executed = set(_list_value(row.get("executed_sources")))
    blocked = set(_list_value(row.get("blocked_sources")))
    missing = set(_list_value(row.get("missing_sources")))
    license_blocking = set(_list_value(row.get("license_blocking_sources")))
    source_status = "success" if source_code in executed else "blocked"
    if source_code in blocked or source_code in missing:
        source_status = "failed" if _has_source_failed(row, source_code) else "blocked"
    if source_status == "success" and str(row.get("status")) == "warning":
        source_status = "warning"
    issue_candidates = _source_issues(row, source_code, license_blocking)
    return {
        "fabric_code": row.get("fabric_code"),
        "result_code": row.get("result_code"),
        "source_code": source_code,
        "dataset_code": dataset_code,
        "status": source_status,
        "dataset_status": row.get("status"),
        "coverage_status": row.get("coverage_status"),
        "consistency_status": row.get("consistency_status"),
        "license_status": _candidate_license(source_code),
        "coverage_rate": _float_or_none(row.get("coverage_rate")) if source_status in {"success", "warning"} else 0.0,
        "conflict_rate_bps": _float_or_none(row.get("conflict_rate_bps")) if source_status in {"success", "warning"} else 0.0,
        "blocking_issues": issue_candidates,
        "next_actions": _list_value(row.get("next_actions")),
        "error_message": row.get("error_message"),
        "started_at": _datetime_or_none(row.get("started_at")),
        "finished_at": _datetime_or_none(row.get("finished_at")),
    }


def _snapshot_from_stats(
    stats: SourceDatasetStats,
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
) -> dict[str, Any]:
    observations = sorted(stats.observations, key=lambda item: item.get("started_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    observation_count = len(observations)
    success_count = sum(1 for item in observations if item.get("status") in {"success", "warning"})
    warning_count = sum(1 for item in observations if item.get("status") == "warning")
    failed_count = sum(1 for item in observations if item.get("status") == "failed")
    blocked_count = sum(1 for item in observations if item.get("status") == "blocked")
    success_rate = round(success_count / observation_count, 6) if observation_count else None
    coverage_values = [_float_or_none(item.get("coverage_rate")) for item in observations if item.get("coverage_rate") is not None]
    conflict_values = [_float_or_none(item.get("conflict_rate_bps")) for item in observations if item.get("conflict_rate_bps") is not None]
    coverage_rate = round(sum(value for value in coverage_values if value is not None) / len(coverage_values), 6) if coverage_values else None
    conflict_rate_bps = round(max([value for value in conflict_values if value is not None] or [0.0]), 6) if observation_count else None
    consecutive_failure_count = _consecutive_failures(observations)
    last_success_at = _last_time(observations, {"success", "warning"})
    last_failure_at = _last_time(observations, {"failed", "blocked"})
    license_status = _candidate_license(stats.source_code)
    commercial_clearance = _commercial_clearance(stats.source_code, license_status)
    reasons = _degradation_reasons(
        source_code=stats.source_code,
        observation_count=observation_count,
        success_count=success_count,
        failed_count=failed_count,
        blocked_count=blocked_count,
        consecutive_failure_count=consecutive_failure_count,
        license_status=license_status,
        commercial_clearance=commercial_clearance,
        conflict_rate_bps=conflict_rate_bps,
        observations=observations,
    )
    score = _reliability_score(
        observation_count=observation_count,
        success_rate=success_rate,
        consecutive_failure_count=consecutive_failure_count,
        license_status=license_status,
        commercial_clearance=commercial_clearance,
        conflict_rate_bps=conflict_rate_bps,
        reasons=reasons,
    )
    status, recommended_role = _status_and_role(
        observation_count=observation_count,
        success_count=success_count,
        score=score,
        consecutive_failure_count=consecutive_failure_count,
        commercial_clearance=commercial_clearance,
    )
    recovery_actions = _recovery_actions(
        stats.source_code,
        status,
        recommended_role,
        reasons,
        commercial_clearance,
        license_status,
    )
    evidence = {
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "source_notes": FREE_SOURCE_CANDIDATES.get(stats.source_code).notes if stats.source_code in FREE_SOURCE_CANDIDATES else "",
        "observation_samples": [_redact_observation(item) for item in observations[:8]],
        "policy": {
            "free_source_never_promotes_to_commercial_primary": True,
            "status_thresholds": {"ready": 75, "watch": 55, "degraded": 35},
        },
    }
    return {
        "snapshot_code": _snapshot_code(stats.source_code, stats.dataset_code, status),
        "source_code": stats.source_code,
        "dataset_code": stats.dataset_code,
        "as_of_date": stats.as_of_date.isoformat(),
        "lookback_hours": stats.lookback_hours,
        "status": status,
        "recommended_role": recommended_role,
        "reliability_score": round(score, 4),
        "success_rate": success_rate,
        "coverage_rate": coverage_rate,
        "conflict_rate_bps": conflict_rate_bps,
        "observation_count": observation_count,
        "success_count": success_count,
        "warning_count": warning_count,
        "failed_count": failed_count,
        "blocked_count": blocked_count,
        "consecutive_failure_count": consecutive_failure_count,
        "license_status": license_status,
        "commercial_clearance": commercial_clearance,
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "last_failure_at": last_failure_at.isoformat() if last_failure_at else None,
        "degradation_reasons": reasons,
        "recovery_actions": recovery_actions,
        "evidence": evidence,
    }


def _reliability_score(
    *,
    observation_count: int,
    success_rate: float | None,
    consecutive_failure_count: int,
    license_status: str,
    commercial_clearance: str,
    conflict_rate_bps: float | None,
    reasons: list[str],
) -> float:
    if observation_count <= 0:
        return 0.0
    rate = success_rate or 0.0
    score = 100.0
    score -= (1.0 - rate) * 45.0
    score -= min(consecutive_failure_count * 8.0, 24.0)
    if license_status in {"research_only", "review_required", "blocked"}:
        score -= 20.0
    elif license_status == "official_public":
        score -= 8.0
    elif license_status == "local_smoke":
        score -= 12.0
    if commercial_clearance == "review_required":
        score -= 10.0
    elif commercial_clearance == "blocked":
        score -= 16.0
    conflict = conflict_rate_bps or 0.0
    if conflict > 100:
        score -= 12.0
    elif conflict > 5:
        score -= 6.0
    if any(_matches_reason(reason, ("token_missing", "timeout", "provider_not_implemented", "scaffold")) for reason in reasons):
        score -= 8.0
    return max(0.0, min(100.0, score))


def _status_and_role(
    *,
    observation_count: int,
    success_count: int,
    score: float,
    consecutive_failure_count: int,
    commercial_clearance: str,
) -> tuple[str, str]:
    if observation_count <= 0:
        return "no_data", "research_only"
    if success_count <= 0 and consecutive_failure_count >= 2:
        return "rejected", "reject"
    if score < 35:
        return "rejected", "reject"
    if score < 55 or consecutive_failure_count > 0:
        return "degraded", "degraded"
    if score < 75:
        return "watch", "research_only"
    if commercial_clearance == "clear":
        return "ready", "validator"
    return "ready", "backup"


def _degradation_reasons(
    *,
    source_code: str,
    observation_count: int,
    success_count: int,
    failed_count: int,
    blocked_count: int,
    consecutive_failure_count: int,
    license_status: str,
    commercial_clearance: str,
    conflict_rate_bps: float | None,
    observations: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    if observation_count <= 0:
        reasons.append("no_recent_fabric_observations")
    if success_count <= 0 and observation_count > 0:
        reasons.append(f"no_successful_observations:{source_code}")
    if failed_count > 0:
        reasons.append(f"failed_observations:{failed_count}")
    if blocked_count > 0:
        reasons.append(f"blocked_observations:{blocked_count}")
    if consecutive_failure_count > 0:
        reasons.append(f"consecutive_failures:{consecutive_failure_count}")
    if license_status in {"research_only", "review_required", "blocked"}:
        reasons.append(f"license_{license_status}")
    if commercial_clearance != "clear":
        reasons.append(f"commercial_clearance_{commercial_clearance}")
    if (conflict_rate_bps or 0.0) > 5:
        reasons.append(f"conflict_rate_bps:{conflict_rate_bps}")
    for observation in observations:
        for issue in observation.get("blocking_issues") or []:
            if source_code in issue or _matches_reason(issue, ("external_free_source_disabled", "token", "timeout", "scaffold", "provider_not_implemented", "no_rows")):
                reasons.append(str(issue))
    return _dedupe(reasons)


def _recovery_actions(
    source_code: str,
    status: str,
    recommended_role: str,
    reasons: list[str],
    commercial_clearance: str,
    license_status: str,
) -> list[str]:
    actions: list[str] = []
    if "no_recent_fabric_observations" in reasons:
        actions.append("schedule a fresh Iota-5 fabric canary before routing traffic")
    if any(_matches_reason(reason, ("token", "tushare", "missing bearer")) for reason in reasons):
        actions.append("configure and validate the required free-source token in the secret store")
    if any(_matches_reason(reason, ("timeout", "connection", "socket")) for reason in reasons):
        actions.append("rerun canary with network timeout guard and mark source degraded until stable")
    if any(_matches_reason(reason, ("provider_not_implemented", "scaffold")) for reason in reasons):
        actions.append("keep source catalog-only until the provider adapter is implemented")
    if any(_matches_reason(reason, ("external_free_source_disabled",)) for reason in reasons):
        actions.append("rerun with explicit external-source approval after terms review")
    if commercial_clearance != "clear" or license_status in {"research_only", "review_required", "blocked"}:
        actions.append("use as research/validation evidence only until commercial reuse is approved")
    if status in {"degraded", "rejected"} or recommended_role in {"degraded", "reject"}:
        actions.append("exclude from automatic production fallback until the next successful snapshot")
    return _dedupe(actions or ["keep source under observation and compare against authorized primary data"])


def _insert_reliability_snapshots(postgres_dsn: str, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not snapshots:
        return []
    inserted: list[dict[str, Any]] = []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for snapshot in snapshots:
                source_id = _lookup_source_id(cursor, str(snapshot["source_code"]))
                dataset_id = _lookup_dataset_id(cursor, str(snapshot["dataset_code"]))
                cursor.execute(
                    """
                    INSERT INTO qmeta.free_source_reliability_snapshot (
                        snapshot_code, source_id, dataset_id, as_of_date,
                        lookback_hours, status, recommended_role,
                        reliability_score, success_rate, coverage_rate,
                        conflict_rate_bps, observation_count, success_count,
                        warning_count, failed_count, blocked_count,
                        consecutive_failure_count, license_status,
                        commercial_clearance, last_success_at, last_failure_at,
                        degradation_reasons, recovery_actions, evidence,
                        updated_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s::jsonb,
                        now()
                    )
                    RETURNING
                        snapshot_id, snapshot_code,
                        (SELECT source_code FROM qmeta.source_system WHERE source_id = qmeta.free_source_reliability_snapshot.source_id) AS source_code,
                        (SELECT dataset_code FROM qmeta.dataset_catalog WHERE dataset_id = qmeta.free_source_reliability_snapshot.dataset_id) AS dataset_code,
                        as_of_date, lookback_hours, status,
                        recommended_role, reliability_score, success_rate,
                        coverage_rate, conflict_rate_bps, observation_count,
                        success_count, warning_count, failed_count,
                        blocked_count, consecutive_failure_count,
                        license_status, commercial_clearance, last_success_at,
                        last_failure_at, degradation_reasons, recovery_actions,
                        evidence, created_at, updated_at
                    """,
                    (
                        snapshot["snapshot_code"],
                        source_id,
                        dataset_id,
                        snapshot["as_of_date"],
                        snapshot["lookback_hours"],
                        snapshot["status"],
                        snapshot["recommended_role"],
                        snapshot["reliability_score"],
                        snapshot["success_rate"],
                        snapshot["coverage_rate"],
                        snapshot["conflict_rate_bps"],
                        snapshot["observation_count"],
                        snapshot["success_count"],
                        snapshot["warning_count"],
                        snapshot["failed_count"],
                        snapshot["blocked_count"],
                        snapshot["consecutive_failure_count"],
                        snapshot["license_status"],
                        snapshot["commercial_clearance"],
                        snapshot["last_success_at"],
                        snapshot["last_failure_at"],
                        snapshot["degradation_reasons"],
                        snapshot["recovery_actions"],
                        _json(snapshot["evidence"]),
                    ),
                )
                inserted.append(dict(cursor.fetchone()))
    return normalize_rows(inserted)


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


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred = [
        "snapshot_code",
        "source_code",
        "dataset_code",
        "as_of_date",
        "status",
        "recommended_role",
        "reliability_score",
        "success_rate",
        "coverage_rate",
        "conflict_rate_bps",
        "consecutive_failure_count",
        "license_status",
        "commercial_clearance",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _as_of_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return parse_date(value, "as_of_date")
    return datetime.now(timezone.utc).date()


def _normalize_optional_codes(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    result = _dedupe(str(value).strip() for value in values if str(value).strip())
    return result or None


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = []
            if isinstance(payload, list):
                return [str(item).strip() for item in payload if str(item).strip()]
        return [item.strip().strip('"').strip("'") for item in text.strip("{}").split(",") if item.strip()]
    return [str(value)]


def _has_source_failed(row: dict[str, Any], source_code: str) -> bool:
    return any(str(issue).startswith(f"source_failed:{source_code}") for issue in _list_value(row.get("blocking_issues")))


def _source_issues(row: dict[str, Any], source_code: str, license_blocking: set[str]) -> list[str]:
    issues: list[str] = []
    for issue in _list_value(row.get("blocking_issues")):
        if source_code in issue or issue.startswith("insufficient_successful_sources") or issue.startswith("commercial_clearance_required"):
            issues.append(issue)
    if source_code in license_blocking:
        issues.append(f"license_blocking:{source_code}")
    if row.get("error_message") and source_code in str(row["error_message"]):
        issues.append(str(row["error_message"]))
    return _dedupe(issues)


def _candidate_license(source_code: str) -> str:
    candidate = FREE_SOURCE_CANDIDATES.get(source_code)
    if not candidate:
        return "unknown"
    return candidate.license_status if candidate.license_status in LICENSE_STATUSES else "unknown"


def _commercial_clearance(source_code: str, license_status: str) -> str:
    candidate = FREE_SOURCE_CANDIDATES.get(source_code)
    if candidate and candidate.commercial_allowed and license_status not in {"research_only", "review_required", "blocked"}:
        return "clear"
    if license_status in {"official_public", "review_required"}:
        return "review_required"
    return "blocked"


def _consecutive_failures(observations: list[dict[str, Any]]) -> int:
    count = 0
    for observation in observations:
        if observation.get("status") in {"success", "warning"}:
            break
        count += 1
    return count


def _last_time(observations: list[dict[str, Any]], statuses: set[str]) -> datetime | None:
    for observation in observations:
        if observation.get("status") in statuses:
            return _datetime_or_none(observation.get("started_at"))
    return None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _matches_reason(reason: str, needles: tuple[str, ...]) -> bool:
    lower = str(reason).lower()
    return any(needle in lower for needle in needles)


def _redact_observation(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "fabric_code": observation.get("fabric_code"),
        "result_code": observation.get("result_code"),
        "status": observation.get("status"),
        "coverage_rate": observation.get("coverage_rate"),
        "conflict_rate_bps": observation.get("conflict_rate_bps"),
        "blocking_issues": observation.get("blocking_issues") or [],
        "started_at": observation.get("started_at").isoformat() if isinstance(observation.get("started_at"), datetime) else observation.get("started_at"),
    }


def _snapshot_code(source_code: str, dataset_code: str, status: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{status}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"kappa5-free-source-{source_code}-{dataset_code}-{status}-{digest}"[:180]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


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


def _json(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Kappa-5 free source reliability") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Kappa-5 free source reliability")
    return _connect(postgres_dsn)
