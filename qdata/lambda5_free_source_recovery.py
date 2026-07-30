from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


ACTION_TYPES = {"retry_canary", "create_alert", "manual_review", "observe", "suppress"}
ACTION_STATUSES = {
    "planned",
    "skipped",
    "scheduled",
    "alerted",
    "review_required",
    "review_requested",
    "notified",
    "recovered",
    "suppressed",
    "failed",
    "success",
    "blocked",
}
RECOVERY_STATUSES = {"planned", "success", "warning", "failed", "skipped"}
TRIGGER_MODES = {"manual", "scheduled", "once", "smoke", "api"}
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
ALERT_TYPE = "free_source_recovery_required"


def run_free_source_recovery(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    lookback_hours: int = 24,
    source_codes: Iterable[str] | None = None,
    dataset_codes: Iterable[str] | None = None,
    requested_by: str = "lambda5",
    trigger_mode: str = "manual",
    environment: str = "local",
    dry_run: bool = False,
    max_actions: int = 50,
    min_retry_score: float = 75.0,
    write_alerts: bool = True,
    write_db: bool = True,
) -> dict[str, Any]:
    snapshot_date = _validate_inputs(as_of_date, lookback_hours, trigger_mode, max_actions, min_retry_score)
    requested_sources = _normalize_optional_codes(source_codes)
    requested_datasets = _normalize_optional_codes(dataset_codes)
    snapshots = _load_latest_reliability_snapshots(
        postgres_dsn,
        as_of_date=snapshot_date,
        lookback_hours=lookback_hours,
        source_codes=requested_sources,
        dataset_codes=requested_datasets,
    )
    actions = build_recovery_actions_from_snapshots(
        snapshots,
        dry_run=dry_run,
        max_actions=max_actions,
        min_retry_score=min_retry_score,
    )
    summary = summarize_recovery_actions(snapshots, actions, dry_run=dry_run)
    run = {
        "recovery_code": _recovery_code(snapshot_date, trigger_mode),
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "environment": environment,
        "as_of_date": snapshot_date.isoformat(),
        "lookback_hours": lookback_hours,
        "dry_run": dry_run,
        "status": summary["status"],
        "snapshot_count": len(snapshots),
        **{key: summary[key] for key in _summary_count_keys()},
        "blocking_issues": summary["blocking_issues"],
        "next_actions": summary["next_actions"],
        "evidence": {
            "source_codes": requested_sources or [],
            "dataset_codes": requested_datasets or [],
            "min_retry_score": min_retry_score,
            "max_actions": max_actions,
            "write_alerts": write_alerts,
            "policy": {
                "free_source_role": "research_validator_backup_only",
                "never_promote_to_commercial_primary": True,
            },
        },
    }
    if write_db:
        run, actions = _insert_recovery_plan(postgres_dsn, run, actions, write_alerts=write_alerts and not dry_run)
    else:
        run = {**run, "recovery_run_id": None, "duration_ms": 0, "created_alert_count": 0}
    return normalize_rows([{**run, "actions": actions}])[0]


def build_recovery_actions_from_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    max_actions: int = 50,
    min_retry_score: float = 75.0,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if max_actions <= 0:
        raise QDataValidationError("max_actions must be greater than 0")
    if min_retry_score < 0 or min_retry_score > 100:
        raise QDataValidationError("min_retry_score must be between 0 and 100")
    now = now or datetime.now(timezone.utc)
    planned: list[dict[str, Any]] = []
    for snapshot in snapshots:
        action = _action_from_snapshot(snapshot, dry_run=dry_run, min_retry_score=min_retry_score, now=now)
        if action:
            planned.append(action)
    planned.sort(key=_action_sort_key)
    return planned[:max_actions]


def summarize_recovery_actions(snapshots: list[dict[str, Any]], actions: list[dict[str, Any]], *, dry_run: bool = False) -> dict[str, Any]:
    retry_count = sum(1 for item in actions if item["action_type"] == "retry_canary")
    manual_review_count = sum(1 for item in actions if item["action_type"] == "manual_review")
    suppressed_count = sum(1 for item in actions if item["status"] in {"suppressed", "skipped"} or item["action_type"] == "suppress")
    alert_count = sum(1 for item in actions if item.get("should_alert") or item.get("alert_id"))
    blocked_count = sum(1 for item in actions if item["severity"] == "critical" or item["reason_code"].endswith("_blocked"))
    status = _summary_status(snapshots, actions, alert_count, manual_review_count, dry_run)
    return {
        "status": status,
        "action_count": len(actions),
        "retry_action_count": retry_count,
        "alert_action_count": alert_count,
        "manual_review_action_count": manual_review_count,
        "suppressed_action_count": suppressed_count,
        "blocked_action_count": blocked_count,
        "created_alert_count": 0,
        "blocking_issues": _summary_blocking_issues(actions),
        "next_actions": _summary_next_actions(actions),
    }


def list_free_source_recovery_runs(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("recovery_code", "fsrr.recovery_code"),
            ("requested_by", "fsrr.requested_by"),
            ("trigger_mode", "fsrr.trigger_mode"),
            ("environment", "fsrr.environment"),
            ("status", "fsrr.status"),
        ],
    )
    as_of = _param(params, "as_of_date")
    if as_of:
        where, values = _append_where(where, values, "fsrr.as_of_date = %s", parse_date(as_of, "as_of_date"))
    where, values = _append_date_filter(where, values, params, "fsrr.as_of_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsrr.recovery_run_id, fsrr.recovery_code, fsrr.requested_by,
            fsrr.trigger_mode, fsrr.environment, fsrr.as_of_date,
            fsrr.lookback_hours, fsrr.dry_run, fsrr.status,
            fsrr.snapshot_count, fsrr.action_count, fsrr.retry_action_count,
            fsrr.alert_action_count, fsrr.manual_review_action_count,
            fsrr.suppressed_action_count, fsrr.blocked_action_count,
            fsrr.created_alert_count, fsrr.blocking_issues, fsrr.next_actions,
            fsrr.evidence, fsrr.error_message, fsrr.started_at,
            fsrr.finished_at, fsrr.duration_ms, fsrr.created_at,
            fsrr.updated_at
        FROM qmeta.free_source_recovery_run fsrr
        {where}
        ORDER BY fsrr.started_at DESC, fsrr.recovery_run_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_free_source_recovery_actions(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("action_code", "fsra.action_code"),
            ("recovery_code", "fsrr.recovery_code"),
            ("source_code", "ss.source_code"),
            ("dataset_code", "dc.dataset_code"),
            ("action_type", "fsra.action_type"),
            ("status", "fsra.status"),
            ("severity", "fsra.severity"),
            ("reason_code", "fsra.reason_code"),
            ("recommended_role", "fsra.recommended_role"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "fsra.created_at::date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            fsra.action_id, fsra.action_code, fsrr.recovery_code,
            fsrs.snapshot_code, ss.source_code, dc.dataset_code,
            fsra.action_type, fsra.status, fsra.severity,
            fsra.reason_code, fsra.recommended_role,
            fsra.reliability_score, fsra.retry_after_minutes,
            fsra.next_retry_at, fsra.alert_id, ae.alert_key,
            fsra.degradation_reasons, fsra.recovery_actions,
            fsra.evidence, fsra.error_message, fsra.created_at,
            fsra.updated_at
        FROM qmeta.free_source_recovery_action fsra
        JOIN qmeta.free_source_recovery_run fsrr ON fsrr.recovery_run_id = fsra.recovery_run_id
        LEFT JOIN qmeta.free_source_reliability_snapshot fsrs ON fsrs.snapshot_id = fsra.snapshot_id
        LEFT JOIN qmeta.source_system ss ON ss.source_id = fsra.source_id
        LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsra.dataset_id
        LEFT JOIN qmeta.alert_event ae ON ae.alert_id = fsra.alert_id
        {where}
        ORDER BY fsra.created_at DESC, fsra.action_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_lambda5_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"lambda5 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _validate_inputs(
    as_of_date: str | date | None,
    lookback_hours: int,
    trigger_mode: str,
    max_actions: int,
    min_retry_score: float,
) -> date:
    if lookback_hours <= 0:
        raise QDataValidationError("lookback_hours must be greater than 0")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: api, manual, once, scheduled, smoke")
    if max_actions <= 0:
        raise QDataValidationError("max_actions must be greater than 0")
    if min_retry_score < 0 or min_retry_score > 100:
        raise QDataValidationError("min_retry_score must be between 0 and 100")
    return _as_of_date(as_of_date)


def _action_from_snapshot(
    snapshot: dict[str, Any],
    *,
    dry_run: bool,
    min_retry_score: float,
    now: datetime,
) -> dict[str, Any] | None:
    status = str(snapshot.get("status") or "no_data")
    score = _float_or_none(snapshot.get("reliability_score")) or 0.0
    reasons = _list_value(snapshot.get("degradation_reasons"))
    recovery_actions = _list_value(snapshot.get("recovery_actions"))
    source_code = str(snapshot.get("source_code") or "")
    dataset_code = str(snapshot.get("dataset_code") or "")
    if status == "ready" and score >= min_retry_score:
        return None
    if status == "ready":
        action_type = "observe"
        severity = "low"
        reason_code = "score_below_retry_threshold"
        retry_after = None
    elif status == "watch":
        action_type = "observe"
        severity = "low"
        reason_code = "source_watch"
        retry_after = None
    elif status == "no_data":
        action_type = "retry_canary"
        severity = "medium"
        reason_code = "no_recent_observations"
        retry_after = 30
    elif status == "rejected" or _needs_manual_review(snapshot, reasons):
        action_type = "manual_review"
        severity = "critical" if status == "rejected" or _commercial_blocked(snapshot) else "high"
        reason_code = _manual_review_reason(snapshot, reasons)
        retry_after = None
    else:
        action_type = "retry_canary"
        severity = "high"
        reason_code = "source_degraded"
        retry_after = _retry_after_minutes(snapshot, reasons)
    action_status = _action_status(action_type, severity, dry_run)
    should_alert = (not dry_run) and SEVERITY_RANK[severity] >= SEVERITY_RANK["high"] and action_type in {"retry_canary", "manual_review"}
    next_retry_at = (now + timedelta(minutes=retry_after)).isoformat() if retry_after else None
    return {
        "action_code": _action_code(source_code, dataset_code, action_type, reason_code),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_code": snapshot.get("snapshot_code"),
        "source_id": snapshot.get("source_id"),
        "dataset_id": snapshot.get("dataset_id"),
        "source_code": source_code,
        "dataset_code": dataset_code,
        "action_type": action_type,
        "status": action_status,
        "severity": severity,
        "reason_code": reason_code,
        "recommended_role": snapshot.get("recommended_role") or "research_only",
        "reliability_score": score,
        "retry_after_minutes": retry_after,
        "next_retry_at": next_retry_at,
        "alert_id": None,
        "degradation_reasons": reasons,
        "recovery_actions": recovery_actions or _default_recovery_actions(action_type, source_code, dataset_code),
        "should_alert": should_alert,
        "evidence": _action_evidence(snapshot, action_type, reason_code, min_retry_score, dry_run),
    }


def _needs_manual_review(snapshot: dict[str, Any], reasons: list[str]) -> bool:
    status = str(snapshot.get("status") or "")
    if status in {"ready", "watch", "no_data"}:
        return False
    if _commercial_blocked(snapshot):
        return True
    return any(_matches_reason(reason, ("token", "missing bearer", "provider_not_implemented", "scaffold", "license", "commercial_clearance")) for reason in reasons)


def _commercial_blocked(snapshot: dict[str, Any]) -> bool:
    return str(snapshot.get("commercial_clearance") or "") == "blocked" or str(snapshot.get("license_status") or "") == "blocked"


def _manual_review_reason(snapshot: dict[str, Any], reasons: list[str]) -> str:
    if _commercial_blocked(snapshot):
        return "commercial_clearance_blocked"
    if any(_matches_reason(reason, ("token", "missing bearer")) for reason in reasons):
        return "token_missing"
    if any(_matches_reason(reason, ("provider_not_implemented", "scaffold")) for reason in reasons):
        return "provider_scaffold"
    if any(_matches_reason(reason, ("license", "commercial_clearance")) for reason in reasons):
        return "license_review_required"
    return "source_rejected"


def _retry_after_minutes(snapshot: dict[str, Any], reasons: list[str]) -> int:
    failures = int(snapshot.get("consecutive_failure_count") or 0)
    minutes = min(240, 15 * max(1, failures + 1))
    if any(_matches_reason(reason, ("timeout", "timed out", "connection", "socket")) for reason in reasons):
        minutes = max(minutes, 60)
    return minutes


def _action_status(action_type: str, severity: str, dry_run: bool) -> str:
    if dry_run:
        return "planned"
    if action_type == "retry_canary":
        return "scheduled"
    if action_type == "manual_review":
        return "review_required"
    if action_type == "suppress":
        return "suppressed"
    return "success" if severity in {"info", "low"} else "planned"


def _default_recovery_actions(action_type: str, source_code: str, dataset_code: str) -> list[str]:
    if action_type == "retry_canary":
        return [f"rerun Iota-5 fabric canary for {source_code}/{dataset_code}", "keep source out of production fallback until score recovers"]
    if action_type == "manual_review":
        return [f"review license, token and adapter readiness for {source_code}/{dataset_code}", "keep source as research evidence only until approved"]
    return [f"keep observing {source_code}/{dataset_code} against authorized primary data"]


def _action_evidence(snapshot: dict[str, Any], action_type: str, reason_code: str, min_retry_score: float, dry_run: bool) -> dict[str, Any]:
    return {
        "snapshot_status": snapshot.get("status"),
        "snapshot_code": snapshot.get("snapshot_code"),
        "commercial_clearance": snapshot.get("commercial_clearance"),
        "license_status": snapshot.get("license_status"),
        "min_retry_score": min_retry_score,
        "dry_run": dry_run,
        "action_policy": {
            "action_type": action_type,
            "reason_code": reason_code,
            "free_source_never_promotes_to_commercial_primary": True,
        },
    }


def _load_latest_reliability_snapshots(
    postgres_dsn: str,
    *,
    as_of_date: date,
    lookback_hours: int,
    source_codes: list[str] | None,
    dataset_codes: list[str] | None,
) -> list[dict[str, Any]]:
    until = datetime.combine(as_of_date, datetime.max.time(), tzinfo=timezone.utc)
    since = datetime.combine(as_of_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1, hours=-lookback_hours)
    where = "WHERE fsrs.created_at >= %s AND fsrs.created_at <= %s"
    values: list[Any] = [since, until]
    if source_codes:
        where, values = _append_where(where, values, "ss.source_code = ANY(%s::text[])", source_codes)
    if dataset_codes:
        where, values = _append_where(where, values, "dc.dataset_code = ANY(%s::text[])", dataset_codes)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM (
            SELECT DISTINCT ON (fsrs.source_id, fsrs.dataset_id)
                fsrs.snapshot_id, fsrs.snapshot_code, fsrs.source_id,
                fsrs.dataset_id, ss.source_code, dc.dataset_code,
                fsrs.as_of_date, fsrs.lookback_hours, fsrs.status,
                fsrs.recommended_role, fsrs.reliability_score,
                fsrs.success_rate, fsrs.coverage_rate,
                fsrs.conflict_rate_bps, fsrs.observation_count,
                fsrs.success_count, fsrs.warning_count, fsrs.failed_count,
                fsrs.blocked_count, fsrs.consecutive_failure_count,
                fsrs.license_status, fsrs.commercial_clearance,
                fsrs.last_success_at, fsrs.last_failure_at,
                fsrs.degradation_reasons, fsrs.recovery_actions,
                fsrs.evidence, fsrs.created_at, fsrs.updated_at
            FROM qmeta.free_source_reliability_snapshot fsrs
            JOIN qmeta.source_system ss ON ss.source_id = fsrs.source_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = fsrs.dataset_id
            {where}
            ORDER BY fsrs.source_id, fsrs.dataset_id, fsrs.as_of_date DESC, fsrs.created_at DESC, fsrs.snapshot_id DESC
        ) latest
        ORDER BY latest.created_at DESC, latest.reliability_score ASC, latest.snapshot_id DESC
        """,
        values,
    )


def _insert_recovery_plan(
    postgres_dsn: str,
    run: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    write_alerts: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started_at = datetime.now(timezone.utc)
    created_alert_count = 0
    inserted_actions: list[dict[str, Any]] = []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.free_source_recovery_run (
                    recovery_code, requested_by, trigger_mode, environment,
                    as_of_date, lookback_hours, dry_run, status,
                    snapshot_count, action_count, retry_action_count,
                    alert_action_count, manual_review_action_count,
                    suppressed_action_count, blocked_action_count,
                    created_alert_count, blocking_issues, next_actions,
                    evidence, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, 'planned',
                    %s, 0, 0,
                    0, 0,
                    0, 0,
                    0, %s, %s,
                    %s::jsonb, now()
                )
                RETURNING recovery_run_id, started_at
                """,
                (
                    run["recovery_code"],
                    run["requested_by"],
                    run["trigger_mode"],
                    run["environment"],
                    run["as_of_date"],
                    run["lookback_hours"],
                    run["dry_run"],
                    run["snapshot_count"],
                    run["blocking_issues"],
                    run["next_actions"],
                    _json(run["evidence"]),
                ),
            )
            row = cursor.fetchone()
            recovery_run_id = int(row["recovery_run_id"])
            for action in actions:
                alert_id = None
                action_status = action["status"]
                if write_alerts and action.get("should_alert"):
                    alert_id = _upsert_alert_event(cursor, run, action)
                    created_alert_count += 1
                    action_status = "alerted"
                inserted_actions.append(_insert_action(cursor, recovery_run_id, {**action, "status": action_status, "alert_id": alert_id}))
            run = _finish_run(cursor, recovery_run_id, run, inserted_actions, created_alert_count, _duration_ms(started_at))
    return run, inserted_actions


def _upsert_alert_event(cursor, run: dict[str, Any], action: dict[str, Any]) -> int:
    alert_key = f"lambda5:{action['source_code']}:{action['dataset_code']}:{action['reason_code']}"
    cursor.execute(
        """
        INSERT INTO qmeta.alert_event (
            alert_key, dataset_id, source_id, trade_date, alert_type,
            severity, status, metric_name, metric_value, threshold_value,
            message, details, last_seen_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, 'open', 'free_source_reliability_score', %s, %s,
            %s, %s::jsonb, now(), now()
        )
        ON CONFLICT (alert_key) DO UPDATE SET
            dataset_id = EXCLUDED.dataset_id,
            source_id = EXCLUDED.source_id,
            trade_date = EXCLUDED.trade_date,
            alert_type = EXCLUDED.alert_type,
            severity = EXCLUDED.severity,
            status = 'open',
            metric_name = EXCLUDED.metric_name,
            metric_value = EXCLUDED.metric_value,
            threshold_value = EXCLUDED.threshold_value,
            message = EXCLUDED.message,
            details = EXCLUDED.details,
            last_seen_at = now(),
            resolved_at = NULL,
            updated_at = now()
        RETURNING alert_id
        """,
        (
            alert_key,
            action.get("dataset_id"),
            action.get("source_id"),
            run["as_of_date"],
            ALERT_TYPE,
            action["severity"],
            action.get("reliability_score"),
            (run.get("evidence") or {}).get("min_retry_score"),
            _alert_message(action),
            _json(
                {
                    "recovery_code": run["recovery_code"],
                    "action_code": action["action_code"],
                    "snapshot_code": action.get("snapshot_code"),
                    "reason_code": action["reason_code"],
                    "recovery_actions": action.get("recovery_actions") or [],
                }
            ),
        ),
    )
    return int(cursor.fetchone()["alert_id"])


def _insert_action(cursor, recovery_run_id: int, action: dict[str, Any]) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.free_source_recovery_action (
            action_code, recovery_run_id, snapshot_id, source_id, dataset_id,
            action_type, status, severity, reason_code, recommended_role,
            reliability_score, retry_after_minutes, next_retry_at, alert_id,
            degradation_reasons, recovery_actions, evidence, error_message,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s::jsonb, %s,
            now()
        )
        RETURNING action_id, action_code, recovery_run_id, snapshot_id,
            source_id, dataset_id, action_type, status, severity,
            reason_code, recommended_role, reliability_score,
            retry_after_minutes, next_retry_at, alert_id,
            degradation_reasons, recovery_actions, evidence,
            error_message, created_at, updated_at
        """,
        (
            action["action_code"],
            recovery_run_id,
            action.get("snapshot_id"),
            action.get("source_id"),
            action.get("dataset_id"),
            action["action_type"],
            action["status"],
            action["severity"],
            action["reason_code"],
            action["recommended_role"],
            action["reliability_score"],
            action.get("retry_after_minutes"),
            action.get("next_retry_at"),
            action.get("alert_id"),
            action["degradation_reasons"],
            action["recovery_actions"],
            _json(action["evidence"]),
            action.get("error_message"),
        ),
    )
    row = dict(cursor.fetchone())
    return normalize_rows(
        [
            {
                **row,
                "source_code": action.get("source_code"),
                "dataset_code": action.get("dataset_code"),
                "snapshot_code": action.get("snapshot_code"),
                "should_alert": action.get("should_alert", False),
            }
        ]
    )[0]


def _finish_run(
    cursor,
    recovery_run_id: int,
    run: dict[str, Any],
    actions: list[dict[str, Any]],
    created_alert_count: int,
    duration_ms: int,
) -> dict[str, Any]:
    summary = summarize_recovery_actions([], actions, dry_run=bool(run["dry_run"]))
    status = run["status"] if run["status"] == "skipped" or not actions else summary["status"]
    cursor.execute(
        """
        UPDATE qmeta.free_source_recovery_run
        SET status = %s,
            finished_at = now(),
            duration_ms = %s,
            action_count = %s,
            retry_action_count = %s,
            alert_action_count = %s,
            manual_review_action_count = %s,
            suppressed_action_count = %s,
            blocked_action_count = %s,
            created_alert_count = %s,
            blocking_issues = %s,
            next_actions = %s,
            updated_at = now()
        WHERE recovery_run_id = %s
        RETURNING recovery_run_id, recovery_code, requested_by, trigger_mode,
            environment, as_of_date, lookback_hours, dry_run, status,
            snapshot_count, action_count, retry_action_count,
            alert_action_count, manual_review_action_count,
            suppressed_action_count, blocked_action_count,
            created_alert_count, blocking_issues, next_actions, evidence,
            error_message, started_at, finished_at, duration_ms,
            created_at, updated_at
        """,
        (
            status,
            duration_ms,
            len(actions),
            summary["retry_action_count"],
            summary["alert_action_count"],
            summary["manual_review_action_count"],
            summary["suppressed_action_count"],
            summary["blocked_action_count"],
            created_alert_count,
            summary["blocking_issues"],
            summary["next_actions"],
            recovery_run_id,
        ),
    )
    return dict(cursor.fetchone())


def _summary_status(snapshots: list[dict[str, Any]], actions: list[dict[str, Any]], alert_count: int, manual_review_count: int, dry_run: bool) -> str:
    if not snapshots and not actions:
        return "skipped"
    if any(item.get("status") == "failed" for item in actions):
        return "failed"
    if dry_run and actions:
        return "warning"
    if alert_count or manual_review_count or any(SEVERITY_RANK.get(item.get("severity", "info"), 0) >= SEVERITY_RANK["high"] for item in actions):
        return "warning"
    return "success"


def _summary_blocking_issues(actions: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for action in actions:
        if SEVERITY_RANK.get(str(action.get("severity") or "info"), 0) >= SEVERITY_RANK["high"]:
            issues.append(str(action["reason_code"]))
        issues.extend(str(item) for item in action.get("degradation_reasons") or [] if _matches_reason(str(item), ("blocked", "token", "license", "commercial", "rejected", "failed")))
    return _dedupe(issues)[:20]


def _summary_next_actions(actions: list[dict[str, Any]]) -> list[str]:
    next_actions: list[str] = []
    for action in actions:
        next_actions.extend(str(item) for item in action.get("recovery_actions") or [])
    if actions:
        next_actions.append("review /admin/free-source-recovery-actions before enabling any production fallback")
    return _dedupe(next_actions)[:20]


def _summary_count_keys() -> list[str]:
    return [
        "action_count",
        "retry_action_count",
        "alert_action_count",
        "manual_review_action_count",
        "suppressed_action_count",
        "blocked_action_count",
        "created_alert_count",
    ]


def _action_sort_key(action: dict[str, Any]) -> tuple[int, int, str, str]:
    action_priority = {"manual_review": 0, "retry_canary": 1, "observe": 2, "suppress": 3, "create_alert": 4}
    return (-SEVERITY_RANK.get(action["severity"], 0), action_priority.get(action["action_type"], 9), action["source_code"], action["dataset_code"])


def _alert_message(action: dict[str, Any]) -> str:
    return (
        f"Free source {action['source_code']}/{action['dataset_code']} requires {action['action_type']} "
        f"because {action['reason_code']} (score={action.get('reliability_score')})."
    )


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
        "recovery_code",
        "action_code",
        "source_code",
        "dataset_code",
        "status",
        "action_type",
        "severity",
        "reason_code",
        "reliability_score",
        "retry_after_minutes",
        "created_alert_count",
        "action_count",
        "manual_review_action_count",
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


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _matches_reason(reason: str, needles: tuple[str, ...]) -> bool:
    lower = str(reason).lower()
    return any(needle in lower for needle in needles)


def _recovery_code(as_of_date: date, trigger_mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{as_of_date}:{trigger_mode}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"lambda5-free-source-recovery-{as_of_date.isoformat()}-{digest}"[:180]


def _action_code(source_code: str, dataset_code: str, action_type: str, reason_code: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{source_code}:{dataset_code}:{action_type}:{reason_code}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"lambda5-{source_code}-{dataset_code}-{action_type}-{digest}"[:180]


def _duration_ms(start: datetime, end: datetime | None = None) -> int:
    finished = end or datetime.now(timezone.utc)
    return int((finished - start).total_seconds() * 1000)


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


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Lambda-5 free source recovery") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Lambda-5 free source recovery")
    return _connect(postgres_dsn)
