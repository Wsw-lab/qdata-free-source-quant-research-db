from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
HEALTH_STATUSES = {"healthy", "warning", "degraded", "circuit_open", "no_data", "failed", "skipped"}
CIRCUIT_STATUSES = {"closed", "open", "half_open", "disabled"}
PROBE_STATUSES = {"planned", "probed", "recovered", "failed", "skipped"}
DEFAULT_ROUTE_FEEDBACK_SCHEDULE = "chi5_source_route_feedback_15m"


def run_source_route_feedback_monitor(
    postgres_dsn: str,
    *,
    requested_by: str = "chi5",
    trigger_mode: str = "manual",
    environment: str = "local",
    lookback_hours: int = 24,
    min_request_count: int = 1,
    min_success_rate: float = 0.95,
    max_failure_rate: float = 0.10,
    max_fallback_rate: float = 0.20,
    max_empty_rate: float = 0.20,
    max_latency_p95_ms: float = 2000.0,
    circuit_open_minutes: int = 30,
    recovery_probe_min_success_rate: float = 1.0,
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_inputs(
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        lookback_hours=lookback_hours,
        min_request_count=min_request_count,
        min_success_rate=min_success_rate,
        max_failure_rate=max_failure_rate,
        max_fallback_rate=max_fallback_rate,
        max_empty_rate=max_empty_rate,
        max_latency_p95_ms=max_latency_p95_ms,
        circuit_open_minutes=circuit_open_minutes,
        recovery_probe_min_success_rate=recovery_probe_min_success_rate,
    )
    now = datetime.now(timezone.utc)
    metrics = fetch_route_health_metrics(_require_dsn(postgres_dsn), lookback_hours=lookback_hours)
    previous_states = load_source_route_circuit_states(_require_dsn(postgres_dsn), metrics=metrics)
    thresholds = {
        "min_request_count": min_request_count,
        "min_success_rate": min_success_rate,
        "max_failure_rate": max_failure_rate,
        "max_fallback_rate": max_fallback_rate,
        "max_empty_rate": max_empty_rate,
        "max_latency_p95_ms": max_latency_p95_ms,
        "circuit_open_minutes": circuit_open_minutes,
        "recovery_probe_min_success_rate": recovery_probe_min_success_rate,
    }
    snapshots = [
        build_route_health_snapshot(
            metric,
            previous_states.get((int(metric["dataset_id"]), int(metric["source_id"]))),
            requested_by=requested_by,
            trigger_mode=trigger_mode,
            environment=environment,
            as_of_at=now,
            lookback_hours=lookback_hours,
            thresholds=thresholds,
        )
        for metric in metrics
    ]
    if not write_db:
        return _summary(snapshots, probes=[])
    persisted_snapshots: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    for snapshot in snapshots:
        persisted = insert_route_health_snapshot(_require_dsn(postgres_dsn), snapshot)
        persisted_snapshots.append(persisted)
        breaker = upsert_source_route_circuit_breaker(
            _require_dsn(postgres_dsn),
            persisted,
            circuit_open_minutes=circuit_open_minutes,
            as_of_at=now,
        )
        probe = maybe_write_recovery_probe(
            _require_dsn(postgres_dsn),
            persisted,
            breaker,
            recovery_probe_min_success_rate=recovery_probe_min_success_rate,
            requested_by=requested_by,
            trigger_mode=trigger_mode,
            environment=environment,
            as_of_at=now,
        )
        if probe:
            probes.append(probe)
    return _summary(persisted_snapshots, probes=probes)


def fetch_route_health_metrics(postgres_dsn: str, *, lookback_hours: int) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        postgres_dsn,
        """
        WITH recent AS (
            SELECT *
            FROM qmeta.source_route_decision_audit
            WHERE started_at >= now() - (%s::int * INTERVAL '1 hour')
              AND dataset_id IS NOT NULL
              AND selected_source_id IS NOT NULL
        ),
        observations AS (
            SELECT
                dataset_id,
                selected_source_id AS source_id,
                1 AS request_count,
                1 AS selected_count,
                CASE WHEN final_source_id = selected_source_id THEN 1 ELSE 0 END AS final_count,
                CASE WHEN decision_status = 'success' AND final_source_id = selected_source_id THEN 1 ELSE 0 END AS success_count,
                CASE WHEN decision_status IN ('failed', 'fallback_success', 'fallback_failed') THEN 1 ELSE 0 END AS failed_count,
                CASE WHEN fallback_applied THEN 1 ELSE 0 END AS fallback_count,
                CASE WHEN COALESCE(row_count, 0) = 0 THEN 1 ELSE 0 END AS empty_count,
                COALESCE(duration_ms, 0)::numeric AS duration_ms
            FROM recent
            UNION ALL
            SELECT
                dataset_id,
                final_source_id AS source_id,
                1 AS request_count,
                0 AS selected_count,
                1 AS final_count,
                CASE WHEN decision_status IN ('success', 'fallback_success') THEN 1 ELSE 0 END AS success_count,
                CASE WHEN decision_status IN ('failed', 'fallback_failed') THEN 1 ELSE 0 END AS failed_count,
                0 AS fallback_count,
                CASE WHEN COALESCE(row_count, 0) = 0 THEN 1 ELSE 0 END AS empty_count,
                COALESCE(duration_ms, 0)::numeric AS duration_ms
            FROM recent
            WHERE final_source_id IS NOT NULL
              AND final_source_id <> selected_source_id
        ),
        grouped AS (
            SELECT
                dataset_id,
                source_id,
                COUNT(*)::int AS observation_count,
                COALESCE(SUM(request_count), 0)::int AS request_count,
                COALESCE(SUM(selected_count), 0)::int AS selected_count,
                COALESCE(SUM(final_count), 0)::int AS final_count,
                COALESCE(SUM(success_count), 0)::int AS success_count,
                COALESCE(SUM(failed_count), 0)::int AS failed_count,
                COALESCE(SUM(fallback_count), 0)::int AS fallback_count,
                COALESCE(SUM(empty_count), 0)::int AS empty_count,
                COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), 0)::numeric(14, 4) AS latency_p95_ms
            FROM observations
            WHERE source_id IS NOT NULL
            GROUP BY dataset_id, source_id
        )
        SELECT
            g.dataset_id,
            dc.dataset_code,
            g.source_id,
            ss.source_code,
            g.observation_count,
            g.request_count,
            g.selected_count,
            g.final_count,
            g.success_count,
            g.failed_count,
            g.fallback_count,
            g.empty_count,
            COALESCE(g.success_count::numeric / NULLIF(g.request_count, 0), 0)::numeric(8, 4) AS success_rate,
            COALESCE(g.failed_count::numeric / NULLIF(g.request_count, 0), 0)::numeric(8, 4) AS failure_rate,
            COALESCE(g.fallback_count::numeric / NULLIF(g.request_count, 0), 0)::numeric(8, 4) AS fallback_rate,
            COALESCE(g.empty_count::numeric / NULLIF(g.request_count, 0), 0)::numeric(8, 4) AS empty_rate,
            g.latency_p95_ms
        FROM grouped g
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = g.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = g.source_id
        ORDER BY dc.dataset_code, ss.source_code
        """,
        [lookback_hours],
    )
    return rows


def build_route_health_snapshot(
    metric: dict[str, Any],
    previous_state: dict[str, Any] | None,
    *,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    as_of_at: datetime,
    lookback_hours: int,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    evaluation = evaluate_route_health(metric, previous_state, thresholds, as_of_at=as_of_at)
    runbook_actions = build_route_health_runbook(metric, evaluation["health_issues"], evaluation["circuit_action"])
    return {
        "snapshot_code": _snapshot_code(str(metric["dataset_code"]), str(metric["source_code"]), as_of_at),
        "dataset_id": metric["dataset_id"],
        "dataset_code": metric["dataset_code"],
        "source_id": metric["source_id"],
        "source_code": metric["source_code"],
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "as_of_at": as_of_at,
        "lookback_hours": lookback_hours,
        "status": evaluation["status"],
        "previous_circuit_status": evaluation.get("previous_circuit_status"),
        "circuit_status": evaluation["circuit_status"],
        "circuit_action": evaluation["circuit_action"],
        "request_count": _int(metric.get("request_count")),
        "selected_count": _int(metric.get("selected_count")),
        "final_count": _int(metric.get("final_count")),
        "success_count": _int(metric.get("success_count")),
        "failed_count": _int(metric.get("failed_count")),
        "fallback_count": _int(metric.get("fallback_count")),
        "empty_count": _int(metric.get("empty_count")),
        "success_rate": _float(metric.get("success_rate")),
        "failure_rate": _float(metric.get("failure_rate")),
        "fallback_rate": _float(metric.get("fallback_rate")),
        "empty_rate": _float(metric.get("empty_rate")),
        "latency_p95_ms": _float(metric.get("latency_p95_ms")),
        "min_request_count": int(thresholds["min_request_count"]),
        "min_success_rate": float(thresholds["min_success_rate"]),
        "max_failure_rate": float(thresholds["max_failure_rate"]),
        "max_fallback_rate": float(thresholds["max_fallback_rate"]),
        "max_empty_rate": float(thresholds["max_empty_rate"]),
        "max_latency_p95_ms": float(thresholds["max_latency_p95_ms"]),
        "open_until": evaluation.get("open_until"),
        "health_issues": evaluation["health_issues"],
        "runbook_actions": runbook_actions,
        "evidence": {
            "thresholds": thresholds,
            "previous_circuit": previous_state or {},
            "metric": metric,
        },
        "error_message": None,
    }


def evaluate_route_health(
    metric: dict[str, Any],
    previous_state: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    *,
    as_of_at: datetime | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or {}
    as_of_at = as_of_at or datetime.now(timezone.utc)
    min_request_count = int(thresholds.get("min_request_count", 1))
    min_success_rate = float(thresholds.get("min_success_rate", 0.95))
    max_failure_rate = float(thresholds.get("max_failure_rate", 0.10))
    max_fallback_rate = float(thresholds.get("max_fallback_rate", 0.20))
    max_empty_rate = float(thresholds.get("max_empty_rate", 0.20))
    max_latency_p95_ms = float(thresholds.get("max_latency_p95_ms", 2000.0))
    circuit_open_minutes = int(thresholds.get("circuit_open_minutes", 30))

    request_count = _int(metric.get("request_count"))
    success_rate = _float(metric.get("success_rate"))
    failure_rate = _float(metric.get("failure_rate"))
    fallback_rate = _float(metric.get("fallback_rate"))
    empty_rate = _float(metric.get("empty_rate"))
    latency_p95_ms = _float(metric.get("latency_p95_ms"))
    previous_status = previous_state.get("status") if previous_state else None
    previous_open_until = _parse_datetime(previous_state.get("open_until")) if previous_state else None

    issues: list[str] = []
    if request_count < min_request_count:
        issues.append("route_insufficient_recent_decisions")
    if success_rate < min_success_rate:
        issues.append("route_success_rate_below_threshold")
    if failure_rate > max_failure_rate:
        issues.append("route_failure_rate_high")
    if fallback_rate > max_fallback_rate:
        issues.append("route_fallback_rate_high")
    if empty_rate > max_empty_rate:
        issues.append("route_empty_rate_high")
    if max_latency_p95_ms > 0 and latency_p95_ms > max_latency_p95_ms:
        issues.append("route_latency_p95_high")

    hard_issue = any(
        issue in issues
        for issue in {
            "route_success_rate_below_threshold",
            "route_failure_rate_high",
            "route_fallback_rate_high",
            "route_empty_rate_high",
            "route_latency_p95_high",
        }
    )
    if previous_status == "disabled":
        return {
            "status": "skipped",
            "previous_circuit_status": previous_status,
            "circuit_status": "disabled",
            "circuit_action": "skip_disabled",
            "open_until": previous_open_until,
            "health_issues": _unique(issues + ["route_circuit_disabled"]),
        }
    if request_count == 0:
        return {
            "status": "no_data",
            "previous_circuit_status": previous_status,
            "circuit_status": "closed" if previous_status != "open" else "open",
            "circuit_action": "none" if previous_status != "open" else "keep_open",
            "open_until": previous_open_until,
            "health_issues": _unique(issues or ["route_no_recent_decisions"]),
        }
    if previous_status == "open" and previous_open_until and previous_open_until <= as_of_at and not hard_issue:
        return {
            "status": "healthy",
            "previous_circuit_status": previous_status,
            "circuit_status": "closed",
            "circuit_action": "close_circuit",
            "open_until": None,
            "health_issues": [],
        }
    if previous_status == "open" and previous_open_until and previous_open_until > as_of_at:
        return {
            "status": "circuit_open",
            "previous_circuit_status": previous_status,
            "circuit_status": "open",
            "circuit_action": "keep_open",
            "open_until": previous_open_until,
            "health_issues": _unique(issues + ["route_circuit_open"]),
        }
    if hard_issue:
        return {
            "status": "degraded",
            "previous_circuit_status": previous_status,
            "circuit_status": "open",
            "circuit_action": "open_circuit",
            "open_until": as_of_at + timedelta(minutes=circuit_open_minutes),
            "health_issues": _unique(issues),
        }
    if issues:
        return {
            "status": "warning",
            "previous_circuit_status": previous_status,
            "circuit_status": "half_open" if previous_status == "open" else "closed",
            "circuit_action": "half_open_probe" if previous_status == "open" else "none",
            "open_until": previous_open_until,
            "health_issues": _unique(issues),
        }
    return {
        "status": "healthy",
        "previous_circuit_status": previous_status,
        "circuit_status": "closed",
        "circuit_action": "close_circuit" if previous_status in {"open", "half_open"} else "none",
        "open_until": None,
        "health_issues": [],
    }


def build_route_health_runbook(metric: dict[str, Any], issues: list[str], circuit_action: str) -> list[str]:
    actions: list[str] = []
    issue_set = set(issues)
    if "route_failure_rate_high" in issue_set or "route_success_rate_below_threshold" in issue_set:
        actions.append("Inspect the latest Source Route Decisions for provider errors before increasing route weight again.")
    if "route_fallback_rate_high" in issue_set:
        actions.append("Keep this source below primary weight until fallback_applied normalizes in the next Chi-5 snapshot.")
    if "route_empty_rate_high" in issue_set:
        actions.append("Check provider calendar, symbol coverage and empty response handling for this dataset/source pair.")
    if "route_latency_p95_high" in issue_set:
        actions.append("Reduce weight or shard requests while investigating provider latency and timeout behavior.")
    if circuit_action == "open_circuit":
        actions.append("Circuit opened: Phi-5 resolver will skip this source while open_until is in the future.")
    if circuit_action == "close_circuit":
        actions.append("Recovery probe passed: source can re-enter normal weighted routing.")
    if not actions:
        actions.append("Continue scheduled Chi-5 monitoring; no immediate route action is required.")
    actions.append(
        f"Current source={metric.get('source_code')} dataset={metric.get('dataset_code')} "
        f"success_rate={metric.get('success_rate')} fallback_rate={metric.get('fallback_rate')}."
    )
    return _unique(actions)


def load_source_route_circuit_states(
    postgres_dsn: str | None,
    *,
    dataset_code: str | None = None,
    source_codes: list[str] | None = None,
    metrics: list[dict[str, Any]] | None = None,
) -> dict[Any, dict[str, Any]]:
    if not postgres_dsn:
        return {}
    where: list[str] = []
    values: list[Any] = []
    if dataset_code:
        where.append("dc.dataset_code = %s")
        values.append(dataset_code)
    if source_codes:
        where.append("ss.source_code = ANY(%s::text[])")
        values.append(source_codes)
    if metrics:
        pairs = [(int(row["dataset_id"]), int(row["source_id"])) for row in metrics if row.get("dataset_id") and row.get("source_id")]
        if not pairs:
            return {}
        dataset_ids = [pair[0] for pair in pairs]
        source_ids = [pair[1] for pair in pairs]
        where.append("(srcb.dataset_id, srcb.source_id) IN (SELECT * FROM unnest(%s::bigint[], %s::bigint[]))")
        values.extend([dataset_ids, source_ids])
    clause = "WHERE " + " AND ".join(where) if where else ""
    rows = _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            srcb.breaker_id, srcb.breaker_code,
            srcb.dataset_id, dc.dataset_code,
            srcb.source_id, ss.source_code,
            srcb.status, srcb.opened_at,
            srcb.half_open_at, srcb.closed_at,
            srcb.open_until, srcb.last_snapshot_id,
            srcb.last_probe_id, srcb.open_reason,
            srcb.failure_rate, srcb.fallback_rate,
            srcb.empty_rate, srcb.latency_p95_ms,
            srcb.health_issues, srcb.details,
            srcb.updated_at
        FROM qmeta.source_route_circuit_breaker srcb
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srcb.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = srcb.source_id
        {clause}
        """,
        values,
    )
    states: dict[Any, dict[str, Any]] = {}
    for row in rows:
        states[(int(row["dataset_id"]), int(row["source_id"]))] = row
        states[(str(row["dataset_code"]), str(row["source_code"]))] = row
    return states


def filter_route_candidates_by_circuit(
    candidates: list[dict[str, Any]],
    circuit_states: dict[Any, dict[str, Any]],
    *,
    dataset_code: str,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    now = now or datetime.now(timezone.utc)
    filtered: list[dict[str, Any]] = []
    skipped: list[str] = []
    for candidate in candidates:
        source_code = str(candidate.get("source_code") or "")
        state = circuit_states.get((dataset_code, source_code))
        if _is_circuit_open(state, now=now):
            skipped.append(source_code)
            continue
        filtered.append(candidate)
    return (filtered or candidates, _unique(skipped))


def insert_route_health_snapshot(postgres_dsn: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_health_snapshot (
                    snapshot_code, dataset_id, source_id,
                    requested_by, trigger_mode, environment,
                    as_of_at, lookback_hours, status,
                    previous_circuit_status, circuit_status,
                    circuit_action, request_count, selected_count,
                    final_count, success_count, failed_count,
                    fallback_count, empty_count, success_rate,
                    failure_rate, fallback_rate, empty_rate,
                    latency_p95_ms, min_request_count,
                    min_success_rate, max_failure_rate,
                    max_fallback_rate, max_empty_rate,
                    max_latency_p95_ms, open_until,
                    health_issues, runbook_actions,
                    evidence, error_message, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s::jsonb, %s, now()
                )
                RETURNING *
                """,
                (
                    snapshot["snapshot_code"],
                    snapshot["dataset_id"],
                    snapshot["source_id"],
                    snapshot["requested_by"],
                    snapshot["trigger_mode"],
                    snapshot["environment"],
                    snapshot["as_of_at"],
                    snapshot["lookback_hours"],
                    snapshot["status"],
                    snapshot.get("previous_circuit_status"),
                    snapshot["circuit_status"],
                    snapshot["circuit_action"],
                    snapshot["request_count"],
                    snapshot["selected_count"],
                    snapshot["final_count"],
                    snapshot["success_count"],
                    snapshot["failed_count"],
                    snapshot["fallback_count"],
                    snapshot["empty_count"],
                    snapshot["success_rate"],
                    snapshot["failure_rate"],
                    snapshot["fallback_rate"],
                    snapshot["empty_rate"],
                    snapshot["latency_p95_ms"],
                    snapshot["min_request_count"],
                    snapshot["min_success_rate"],
                    snapshot["max_failure_rate"],
                    snapshot["max_fallback_rate"],
                    snapshot["max_empty_rate"],
                    snapshot["max_latency_p95_ms"],
                    snapshot.get("open_until"),
                    snapshot["health_issues"],
                    snapshot["runbook_actions"],
                    _json(snapshot["evidence"]),
                    snapshot.get("error_message"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0] | {
                "dataset_code": snapshot.get("dataset_code"),
                "source_code": snapshot.get("source_code"),
            }


def upsert_source_route_circuit_breaker(
    postgres_dsn: str,
    snapshot: dict[str, Any],
    *,
    circuit_open_minutes: int,
    as_of_at: datetime,
) -> dict[str, Any]:
    action = snapshot.get("circuit_action")
    status = snapshot.get("circuit_status") or "closed"
    opened_at = as_of_at if action == "open_circuit" else None
    half_open_at = as_of_at if action == "half_open_probe" else None
    closed_at = as_of_at if action == "close_circuit" or status == "closed" else None
    open_until = snapshot.get("open_until")
    open_reason = ", ".join(snapshot.get("health_issues") or []) or None
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_circuit_breaker (
                    breaker_code, dataset_id, source_id,
                    status, opened_at, half_open_at,
                    closed_at, open_until, last_snapshot_id,
                    open_reason, failure_rate, fallback_rate,
                    empty_rate, latency_p95_ms, health_issues,
                    details, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, now()
                )
                ON CONFLICT (dataset_id, source_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    opened_at = CASE
                        WHEN EXCLUDED.status = 'open' AND qmeta.source_route_circuit_breaker.status <> 'open'
                        THEN EXCLUDED.opened_at
                        ELSE qmeta.source_route_circuit_breaker.opened_at
                    END,
                    half_open_at = CASE
                        WHEN EXCLUDED.status = 'half_open' THEN EXCLUDED.half_open_at
                        WHEN EXCLUDED.status IN ('open', 'closed') THEN NULL
                        ELSE qmeta.source_route_circuit_breaker.half_open_at
                    END,
                    closed_at = CASE
                        WHEN EXCLUDED.status = 'closed' THEN EXCLUDED.closed_at
                        ELSE NULL
                    END,
                    open_until = EXCLUDED.open_until,
                    last_snapshot_id = EXCLUDED.last_snapshot_id,
                    open_reason = EXCLUDED.open_reason,
                    failure_rate = EXCLUDED.failure_rate,
                    fallback_rate = EXCLUDED.fallback_rate,
                    empty_rate = EXCLUDED.empty_rate,
                    latency_p95_ms = EXCLUDED.latency_p95_ms,
                    health_issues = EXCLUDED.health_issues,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING *
                """,
                (
                    _breaker_code(str(snapshot["dataset_code"]), str(snapshot["source_code"])),
                    snapshot["dataset_id"],
                    snapshot["source_id"],
                    status,
                    opened_at,
                    half_open_at,
                    closed_at,
                    open_until,
                    snapshot["snapshot_id"],
                    open_reason,
                    snapshot["failure_rate"],
                    snapshot["fallback_rate"],
                    snapshot["empty_rate"],
                    snapshot["latency_p95_ms"],
                    snapshot["health_issues"],
                    _json({"snapshot_code": snapshot.get("snapshot_code"), "circuit_open_minutes": circuit_open_minutes}),
                ),
            )
            row = normalize_rows([dict(cursor.fetchone())])[0]
            row["dataset_code"] = snapshot.get("dataset_code")
            row["source_code"] = snapshot.get("source_code")
            return row


def maybe_write_recovery_probe(
    postgres_dsn: str,
    snapshot: dict[str, Any],
    breaker: dict[str, Any],
    *,
    recovery_probe_min_success_rate: float,
    requested_by: str,
    trigger_mode: str,
    environment: str,
    as_of_at: datetime,
) -> dict[str, Any] | None:
    previous_status = snapshot.get("previous_circuit_status")
    action = snapshot.get("circuit_action")
    if previous_status not in {"open", "half_open"} and action != "half_open_probe":
        return None
    observed_request_count = _int(snapshot.get("request_count"))
    observed_success_count = _int(snapshot.get("success_count"))
    observed_failed_count = _int(snapshot.get("failed_count"))
    observed_success_rate = _float(snapshot.get("success_rate"))
    recovered = action == "close_circuit" and observed_success_rate >= recovery_probe_min_success_rate
    status = "recovered" if recovered else "failed" if observed_request_count else "skipped"
    decision_summary = "close_circuit" if recovered else "keep_open" if status == "failed" else "waiting_for_probe_decisions"
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_recovery_probe (
                    probe_code, breaker_id, snapshot_id,
                    dataset_id, source_id, requested_by,
                    trigger_mode, environment, status,
                    probe_started_at, probe_finished_at,
                    observed_request_count, observed_success_count,
                    observed_failed_count, observed_success_rate,
                    required_success_rate, decision_summary,
                    details, error_message, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s::jsonb, %s, now()
                )
                RETURNING *
                """,
                (
                    _probe_code(str(snapshot["dataset_code"]), str(snapshot["source_code"]), as_of_at),
                    breaker.get("breaker_id"),
                    snapshot["snapshot_id"],
                    snapshot["dataset_id"],
                    snapshot["source_id"],
                    requested_by,
                    trigger_mode,
                    environment,
                    status,
                    as_of_at,
                    as_of_at,
                    observed_request_count,
                    observed_success_count,
                    observed_failed_count,
                    observed_success_rate,
                    recovery_probe_min_success_rate,
                    decision_summary,
                    _json({"snapshot_code": snapshot.get("snapshot_code"), "health_issues": snapshot.get("health_issues") or []}),
                    None if status != "failed" else "route recovery probe did not meet success-rate requirement",
                ),
            )
            probe = normalize_rows([dict(cursor.fetchone())])[0]
            cursor.execute(
                """
                UPDATE qmeta.source_route_circuit_breaker
                SET last_probe_id = %s, updated_at = now()
                WHERE breaker_id = %s
                """,
                (probe["probe_id"], breaker.get("breaker_id")),
            )
            probe["dataset_code"] = snapshot.get("dataset_code")
            probe["source_code"] = snapshot.get("source_code")
            return probe


def list_source_route_health_snapshots(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "srhs.snapshot_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("status", "srhs.status"),
            ("circuit_status", "srhs.circuit_status"),
            ("circuit_action", "srhs.circuit_action"),
            ("requested_by", "srhs.requested_by"),
            ("trigger_mode", "srhs.trigger_mode"),
            ("environment", "srhs.environment"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "srhs.as_of_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            srhs.snapshot_id, srhs.snapshot_code,
            dc.dataset_code, ss.source_code,
            srhs.requested_by, srhs.trigger_mode,
            srhs.environment, srhs.as_of_at,
            srhs.lookback_hours, srhs.status,
            srhs.previous_circuit_status,
            srhs.circuit_status, srhs.circuit_action,
            srhs.request_count, srhs.selected_count,
            srhs.final_count, srhs.success_count,
            srhs.failed_count, srhs.fallback_count,
            srhs.empty_count, srhs.success_rate,
            srhs.failure_rate, srhs.fallback_rate,
            srhs.empty_rate, srhs.latency_p95_ms,
            srhs.open_until, srhs.health_issues,
            srhs.runbook_actions, srhs.error_message,
            srhs.created_at
        FROM qmeta.source_route_health_snapshot srhs
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srhs.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = srhs.source_id
        {where}
        ORDER BY srhs.as_of_at DESC, srhs.snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_source_route_circuit_breakers(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("breaker_code", "srcb.breaker_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("status", "srcb.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            srcb.breaker_id, srcb.breaker_code,
            dc.dataset_code, ss.source_code,
            srcb.status, srcb.opened_at,
            srcb.half_open_at, srcb.closed_at,
            srcb.open_until, srhs.snapshot_code,
            srp.probe_code, srcb.open_reason,
            srcb.failure_rate, srcb.fallback_rate,
            srcb.empty_rate, srcb.latency_p95_ms,
            srcb.health_issues, srcb.updated_at
        FROM qmeta.source_route_circuit_breaker srcb
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srcb.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = srcb.source_id
        LEFT JOIN qmeta.source_route_health_snapshot srhs ON srhs.snapshot_id = srcb.last_snapshot_id
        LEFT JOIN qmeta.source_route_recovery_probe srp ON srp.probe_id = srcb.last_probe_id
        {where}
        ORDER BY srcb.updated_at DESC, srcb.breaker_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_source_route_recovery_probes(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("probe_code", "srp.probe_code"),
            ("breaker_code", "srcb.breaker_code"),
            ("snapshot_code", "srhs.snapshot_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("status", "srp.status"),
            ("decision_summary", "srp.decision_summary"),
            ("requested_by", "srp.requested_by"),
            ("trigger_mode", "srp.trigger_mode"),
            ("environment", "srp.environment"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "srp.probe_started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            srp.probe_id, srp.probe_code,
            srcb.breaker_code, srhs.snapshot_code,
            dc.dataset_code, ss.source_code,
            srp.requested_by, srp.trigger_mode,
            srp.environment, srp.status,
            srp.probe_started_at, srp.probe_finished_at,
            srp.observed_request_count,
            srp.observed_success_count,
            srp.observed_failed_count,
            srp.observed_success_rate,
            srp.required_success_rate,
            srp.decision_summary,
            srp.error_message, srp.created_at
        FROM qmeta.source_route_recovery_probe srp
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srp.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = srp.source_id
        LEFT JOIN qmeta.source_route_circuit_breaker srcb ON srcb.breaker_id = srp.breaker_id
        LEFT JOIN qmeta.source_route_health_snapshot srhs ON srhs.snapshot_id = srp.snapshot_id
        {where}
        ORDER BY srp.probe_started_at DESC, srp.probe_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_chi5_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    data_rows = [rows] if isinstance(rows, dict) else list(rows or [])
    lines = [f"chi5 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _summary(snapshots: list[dict[str, Any]], *, probes: list[dict[str, Any]]) -> dict[str, Any]:
    status = _overall_status(snapshots)
    return {
        "status": status,
        "snapshot_count": len(snapshots),
        "healthy_count": sum(1 for row in snapshots if row.get("status") == "healthy"),
        "warning_count": sum(1 for row in snapshots if row.get("status") == "warning"),
        "degraded_count": sum(1 for row in snapshots if row.get("status") == "degraded"),
        "circuit_open_count": sum(1 for row in snapshots if row.get("circuit_status") == "open"),
        "circuit_closed_count": sum(1 for row in snapshots if row.get("circuit_status") == "closed"),
        "recovery_probe_count": len(probes),
        "recovered_probe_count": sum(1 for row in probes if row.get("status") == "recovered"),
        "failed_probe_count": sum(1 for row in probes if row.get("status") == "failed"),
        "snapshots": normalize_rows(snapshots),
        "probes": normalize_rows(probes),
    }


def _overall_status(snapshots: list[dict[str, Any]]) -> str:
    if any(row.get("status") in {"degraded", "circuit_open", "failed"} for row in snapshots):
        return "critical"
    if any(row.get("status") in {"warning", "no_data"} for row in snapshots):
        return "warning"
    if any(row.get("status") == "healthy" for row in snapshots):
        return "healthy"
    return "skipped"


def _is_circuit_open(state: dict[str, Any] | None, *, now: datetime) -> bool:
    if not state or state.get("status") != "open":
        return False
    open_until = _parse_datetime(state.get("open_until"))
    return open_until is None or open_until > now


def _validate_inputs(
    *,
    requested_by: str,
    trigger_mode: str,
    lookback_hours: int,
    min_request_count: int,
    min_success_rate: float,
    max_failure_rate: float,
    max_fallback_rate: float,
    max_empty_rate: float,
    max_latency_p95_ms: float,
    circuit_open_minutes: int,
    recovery_probe_min_success_rate: float,
) -> None:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, once, scheduled, smoke")
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    if min_request_count < 0:
        raise QDataValidationError("min_request_count must be greater than or equal to 0")
    for name, value in {
        "min_success_rate": min_success_rate,
        "max_failure_rate": max_failure_rate,
        "max_fallback_rate": max_fallback_rate,
        "max_empty_rate": max_empty_rate,
        "recovery_probe_min_success_rate": recovery_probe_min_success_rate,
    }.items():
        if value < 0 or value > 1:
            raise QDataValidationError(f"{name} must be between 0 and 1")
    if max_latency_p95_ms < 0:
        raise QDataValidationError("max_latency_p95_ms must be greater than or equal to 0")
    if circuit_open_minutes < 0:
        raise QDataValidationError("circuit_open_minutes must be greater than or equal to 0")


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
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _connect(postgres_dsn: str | None):
    dsn = _require_dsn(postgres_dsn)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Chi-5 route feedback") from exc
    return psycopg.connect(dsn, row_factory=dict_row)


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required")
    return postgres_dsn


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[-1]


def _snapshot_code(dataset_code: str, source_code: str, as_of_at: datetime) -> str:
    digest = hashlib.sha1(f"{dataset_code}:{source_code}:{as_of_at.isoformat()}".encode("utf-8")).hexdigest()[:12]
    return f"chi5-route-health-{dataset_code}-{source_code}-{digest}"[:180]


def _breaker_code(dataset_code: str, source_code: str) -> str:
    return f"chi5-route-breaker-{dataset_code}-{source_code}"[:180]


def _probe_code(dataset_code: str, source_code: str, as_of_at: datetime) -> str:
    digest = hashlib.sha1(f"probe:{dataset_code}:{source_code}:{as_of_at.isoformat()}".encode("utf-8")).hexdigest()[:12]
    return f"chi5-route-probe-{dataset_code}-{source_code}-{digest}"[:180]


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _report_keys(row: dict[str, Any]) -> list[str]:
    preferred = [
        "as_of_at",
        "snapshot_code",
        "breaker_code",
        "probe_code",
        "dataset_code",
        "source_code",
        "status",
        "circuit_status",
        "circuit_action",
        "request_count",
        "success_count",
        "failed_count",
        "fallback_count",
        "success_rate",
        "failure_rate",
        "fallback_rate",
        "latency_p95_ms",
        "open_until",
        "decision_summary",
        "observed_success_rate",
        "health_issues",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _unique(items: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)
