from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from qdata.backend_utils import normalize_rows, parse_date
from qdata.chi5_route_feedback import filter_route_candidates_by_circuit, load_source_route_circuit_states
from qdata.exceptions import QDataValidationError


ROUTE_CONTEXTS = {"sync", "api", "worker", "smoke"}
ROUTE_MODES = {"default", "policy_weighted", "manual_override", "fallback"}
DECISION_STATUSES = {"selected", "success", "fallback_success", "fallback_failed", "failed", "skipped"}
SELECTED_ROLES = {"requested", "primary", "backup", "free_source", "fallback"}


def resolve_source_route(
    postgres_dsn: str | None,
    *,
    dataset_code: str,
    requested_source_code: str,
    as_of_date: str | date | None = None,
    request_key: str | None = None,
    decision_context: str = "sync",
    manual_source_code: str | None = None,
) -> dict[str, Any]:
    _validate_route_inputs(dataset_code, requested_source_code, decision_context)
    effective_date = _as_of_date(as_of_date)
    key = request_key or f"{decision_context}:{dataset_code}:{requested_source_code}:{effective_date.isoformat()}"
    if manual_source_code:
        return _default_decision(
            dataset_code=dataset_code,
            requested_source_code=requested_source_code,
            selected_source_code=manual_source_code,
            as_of_date=effective_date,
            request_key=key,
            decision_context=decision_context,
            route_mode="manual_override",
            selected_role="requested",
        )
    if not postgres_dsn:
        return _default_decision(
            dataset_code=dataset_code,
            requested_source_code=requested_source_code,
            selected_source_code=requested_source_code,
            as_of_date=effective_date,
            request_key=key,
            decision_context=decision_context,
            route_mode="default",
            selected_role="requested",
        )
    policies = load_active_route_policies(postgres_dsn, dataset_code=dataset_code, as_of_date=effective_date)
    if not policies:
        context = load_route_context(postgres_dsn, dataset_code=dataset_code, source_codes=[requested_source_code])
        return _default_decision(
            dataset_code=dataset_code,
            requested_source_code=requested_source_code,
            selected_source_code=requested_source_code,
            as_of_date=effective_date,
            request_key=key,
            decision_context=decision_context,
            route_mode="default",
            selected_role="requested",
            dataset_id=context.get("dataset_id"),
            requested_source_id=context.get("source_ids_by_code", {}).get(requested_source_code),
            source_ids_by_code=context.get("source_ids_by_code", {}),
        )
    policy = policies[0]
    candidates = build_route_candidates(policy, requested_source_code=requested_source_code)
    try:
        circuit_states = load_source_route_circuit_states(
            postgres_dsn,
            dataset_code=dataset_code,
            source_codes=[str(item.get("source_code")) for item in candidates if item.get("source_code")],
        )
    except Exception:
        circuit_states = {}
    routed_candidates, circuit_skipped_sources = filter_route_candidates_by_circuit(
        candidates,
        circuit_states,
        dataset_code=dataset_code,
    )
    candidates = routed_candidates
    selected = select_route_candidate(candidates, key)
    candidate_codes = _dedupe([item["source_code"] for item in candidates if item.get("source_code")])
    fallback_codes = [code for code in candidate_codes if code != selected["source_code"]]
    source_ids_by_code = {
        str(code): source_id
        for code, source_id in {
            policy.get("source_code"): policy.get("source_id"),
            policy.get("primary_source_code"): policy.get("primary_source_id"),
            policy.get("backup_source_code"): policy.get("backup_source_id"),
            requested_source_code: policy.get("requested_source_id"),
        }.items()
        if code and source_id is not None
    }
    return {
        "decision_code": _decision_code(decision_context, dataset_code, selected["source_code"], key),
        "policy_id": policy.get("policy_id"),
        "policy_code": policy.get("policy_code"),
        "dataset_id": policy.get("dataset_id"),
        "dataset_code": dataset_code,
        "requested_source_id": policy.get("requested_source_id"),
        "requested_source_code": requested_source_code,
        "selected_source_id": source_ids_by_code.get(selected["source_code"]),
        "selected_source_code": selected["source_code"],
        "final_source_id": source_ids_by_code.get(selected["source_code"]),
        "final_source_code": selected["source_code"],
        "primary_source_id": policy.get("source_id"),
        "primary_source_code": policy.get("source_code"),
        "backup_source_id": policy.get("backup_source_id") or policy.get("primary_source_id"),
        "backup_source_code": selected.get("backup_source_code") or policy.get("backup_source_code") or policy.get("primary_source_code"),
        "effective_date": policy.get("effective_date") or effective_date.isoformat(),
        "decision_context": decision_context,
        "route_mode": "policy_weighted",
        "decision_status": "selected",
        "selected_role": selected["role"],
        "primary_weight_pct": _float_or_zero(policy.get("primary_weight_pct")),
        "backup_weight_pct": _float_or_zero(policy.get("backup_weight_pct")),
        "free_source_weight_pct": _float_or_zero(policy.get("free_source_weight_pct")),
        "selected_weight_pct": selected["weight_pct"],
        "deterministic_bucket": deterministic_bucket(key),
        "candidate_sources": candidate_codes,
        "fallback_source_codes": fallback_codes,
        "attempt_sources": [],
        "fallback_attempted": False,
        "fallback_applied": False,
        "fallback_reason": None,
        "request_key": key,
        "source_ids_by_code": source_ids_by_code,
        "details": {
            "policy_code": policy.get("policy_code"),
            "candidate_weights": candidates,
            "circuit_skipped_sources": circuit_skipped_sources,
            "circuit_fail_open": bool(circuit_skipped_sources and set(circuit_skipped_sources) >= {str(item.get("source_code")) for item in routed_candidates if item.get("source_code")}),
        },
    }


def load_active_route_policies(
    postgres_dsn: str | None,
    *,
    dataset_code: str,
    as_of_date: str | date | None = None,
) -> list[dict[str, Any]]:
    effective_date = _as_of_date(as_of_date)
    return _fetch_rows(
        postgres_dsn,
        """
        SELECT
            srwp.policy_id, srwp.policy_code,
            srwp.dataset_id, dc.dataset_code,
            srwp.source_id, ss.source_code,
            srwp.primary_source_id, ps.source_code AS primary_source_code,
            srwp.backup_source_id, bs.source_code AS backup_source_code,
            srwp.effective_date, srwp.end_date,
            srwp.policy_status, srwp.execution_mode,
            srwp.primary_weight_pct,
            srwp.backup_weight_pct,
            srwp.free_source_weight_pct,
            srwp.created_by,
            srwp.created_at, srwp.updated_at
        FROM qmeta.source_route_weight_policy srwp
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srwp.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = srwp.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = srwp.primary_source_id
        LEFT JOIN qmeta.source_system bs ON bs.source_id = srwp.backup_source_id
        WHERE dc.dataset_code = %s
          AND srwp.policy_status = 'active'
          AND srwp.effective_date <= %s
          AND (srwp.end_date IS NULL OR srwp.end_date >= %s)
        ORDER BY srwp.effective_date DESC, srwp.created_at DESC, srwp.policy_id DESC
        """,
        [dataset_code, effective_date, effective_date],
    )


def load_route_context(postgres_dsn: str | None, *, dataset_code: str, source_codes: Iterable[str]) -> dict[str, Any]:
    codes = _dedupe([code for code in source_codes if code])
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT 'dataset' AS row_type, dc.dataset_id AS object_id, dc.dataset_code AS object_code
        FROM qmeta.dataset_catalog dc
        WHERE dc.dataset_code = %s
        UNION ALL
        SELECT 'source' AS row_type, ss.source_id AS object_id, ss.source_code AS object_code
        FROM qmeta.source_system ss
        WHERE ss.source_code = ANY(%s::text[])
        """,
        [dataset_code, codes],
    )
    source_ids: dict[str, int] = {}
    dataset_id = None
    for row in rows:
        if row.get("row_type") == "dataset":
            dataset_id = row.get("object_id")
        elif row.get("row_type") == "source":
            source_ids[str(row.get("object_code"))] = row.get("object_id")
    return {"dataset_id": dataset_id, "source_ids_by_code": source_ids}


def build_route_candidates(policy: dict[str, Any], *, requested_source_code: str) -> list[dict[str, Any]]:
    primary_source_code = str(policy.get("source_code") or requested_source_code)
    backup_source_code = str(policy.get("backup_source_code") or policy.get("primary_source_code") or requested_source_code)
    candidates = [
        {
            "role": "primary",
            "source_code": primary_source_code,
            "weight_pct": _float_or_zero(policy.get("primary_weight_pct")),
        },
        {
            "role": "backup",
            "source_code": backup_source_code,
            "weight_pct": _float_or_zero(policy.get("backup_weight_pct")),
        },
    ]
    free_weight = _float_or_zero(policy.get("free_source_weight_pct"))
    if free_weight > 0:
        free_source_code = _free_source_code(policy, requested_source_code=requested_source_code)
        candidates.append({"role": "free_source", "source_code": free_source_code, "weight_pct": free_weight})
    merged = _merge_candidates(candidates)
    if not merged:
        return [{"role": "requested", "source_code": requested_source_code, "weight_pct": 100.0}]
    return merged


def select_route_candidate(candidates: list[dict[str, Any]], request_key: str) -> dict[str, Any]:
    if not candidates:
        raise QDataValidationError("route candidates must not be empty")
    positive = [candidate for candidate in candidates if _float_or_zero(candidate.get("weight_pct")) > 0]
    if not positive:
        return {**candidates[0], "weight_pct": 0.0}
    total = sum(_float_or_zero(candidate.get("weight_pct")) for candidate in positive)
    threshold = deterministic_bucket(request_key) * total / 100.0
    cumulative = 0.0
    for candidate in positive:
        cumulative += _float_or_zero(candidate.get("weight_pct"))
        if threshold < cumulative:
            return dict(candidate)
    return dict(positive[-1])


def deterministic_bucket(request_key: str) -> float:
    digest = hashlib.sha1(request_key.encode("utf-8")).hexdigest()
    return round((int(digest[:12], 16) % 1_000_000) / 10_000, 4)


def finalize_route_decision(
    decision: dict[str, Any],
    *,
    final_source_code: str,
    status: str,
    attempt_sources: Iterable[str] | None = None,
    row_count: int | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    fallback_reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in DECISION_STATUSES:
        raise QDataValidationError("decision status is invalid")
    attempts = _dedupe(list(attempt_sources or []))
    selected = str(decision.get("selected_source_code") or "")
    source_ids_by_code = dict(decision.get("source_ids_by_code") or {})
    fallback_applied = bool(final_source_code and selected and final_source_code != selected)
    fallback_attempted = fallback_applied or len(attempts) > 1
    merged = dict(decision)
    merged.update(
        {
            "final_source_code": final_source_code,
            "final_source_id": source_ids_by_code.get(final_source_code, decision.get("final_source_id")),
            "decision_status": status,
            "attempt_sources": attempts,
            "fallback_attempted": fallback_attempted,
            "fallback_applied": fallback_applied,
            "fallback_reason": fallback_reason,
            "row_count": row_count,
            "duration_ms": duration_ms,
            "error_message": error_message,
            "details": {**dict(decision.get("details") or {}), **dict(details or {})},
        }
    )
    if fallback_applied:
        merged["route_mode"] = "fallback"
        merged["selected_role"] = "fallback"
    return merged


def write_source_route_decision_audit(
    postgres_dsn: str | None,
    decision: dict[str, Any],
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    best_effort: bool = True,
) -> dict[str, Any] | None:
    if not postgres_dsn:
        return None
    try:
        started = started_at or datetime.now(timezone.utc)
        finished = finished_at or datetime.now(timezone.utc)
        with _connect_required(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.source_route_decision_audit (
                        decision_code, policy_id, dataset_id,
                        requested_source_id, selected_source_id,
                        final_source_id, primary_source_id,
                        backup_source_id, request_id,
                        request_key, decision_context,
                        route_mode, decision_status,
                        selected_role, effective_date,
                        primary_weight_pct, backup_weight_pct,
                        free_source_weight_pct, selected_weight_pct,
                        deterministic_bucket, fallback_attempted,
                        fallback_applied, candidate_sources,
                        attempt_sources, fallback_reason,
                        row_count, duration_ms, error_message,
                        details, started_at, finished_at, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s::jsonb, %s, %s, now()
                    )
                    RETURNING *
                    """,
                    (
                        decision.get("decision_code") or _decision_code(
                            str(decision.get("decision_context") or "sync"),
                            str(decision.get("dataset_code") or "unknown"),
                            str(decision.get("final_source_code") or decision.get("selected_source_code") or "unknown"),
                            str(decision.get("request_key") or datetime.now(timezone.utc).isoformat()),
                        ),
                        decision.get("policy_id"),
                        decision.get("dataset_id"),
                        decision.get("requested_source_id"),
                        decision.get("selected_source_id"),
                        decision.get("final_source_id"),
                        decision.get("primary_source_id"),
                        decision.get("backup_source_id"),
                        decision.get("request_id"),
                        decision.get("request_key"),
                        decision.get("decision_context") or "sync",
                        decision.get("route_mode") or "default",
                        decision.get("decision_status") or "selected",
                        decision.get("selected_role") or "requested",
                        decision.get("effective_date"),
                        _float_or_zero(decision.get("primary_weight_pct")),
                        _float_or_zero(decision.get("backup_weight_pct")),
                        _float_or_zero(decision.get("free_source_weight_pct")),
                        _float_or_zero(decision.get("selected_weight_pct"), default=100.0),
                        _float_or_zero(decision.get("deterministic_bucket")),
                        bool(decision.get("fallback_attempted")),
                        bool(decision.get("fallback_applied")),
                        list(decision.get("candidate_sources") or []),
                        list(decision.get("attempt_sources") or []),
                        decision.get("fallback_reason"),
                        decision.get("row_count"),
                        decision.get("duration_ms"),
                        decision.get("error_message"),
                        json.dumps(decision.get("details") or {}, ensure_ascii=False, sort_keys=True),
                        started,
                        finished,
                    ),
                )
                return normalize_rows([dict(cursor.fetchone())])[0]
    except Exception:
        if best_effort:
            return None
        raise


def list_source_route_decision_audits(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("decision_code", "srda.decision_code"),
            ("policy_code", "srwp.policy_code"),
            ("dataset_code", "dc.dataset_code"),
            ("requested_source_code", "req.source_code"),
            ("selected_source_code", "sel.source_code"),
            ("final_source_code", "fin.source_code"),
            ("decision_context", "srda.decision_context"),
            ("route_mode", "srda.route_mode"),
            ("decision_status", "srda.decision_status"),
            ("selected_role", "srda.selected_role"),
        ],
    )
    start = _param(params, "start_date")
    end = _param(params, "end_date")
    if start:
        where, values = _append_where(where, values, "srda.started_at::date >= %s", parse_date(start, "start_date"))
    if end:
        where, values = _append_where(where, values, "srda.started_at::date <= %s", parse_date(end, "end_date"))
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            srda.decision_id, srda.decision_code,
            srwp.policy_code, dc.dataset_code,
            req.source_code AS requested_source_code,
            sel.source_code AS selected_source_code,
            fin.source_code AS final_source_code,
            ps.source_code AS primary_source_code,
            bs.source_code AS backup_source_code,
            srda.request_id, srda.request_key,
            srda.decision_context, srda.route_mode,
            srda.decision_status, srda.selected_role,
            srda.effective_date,
            srda.primary_weight_pct,
            srda.backup_weight_pct,
            srda.free_source_weight_pct,
            srda.selected_weight_pct,
            srda.deterministic_bucket,
            srda.fallback_attempted,
            srda.fallback_applied,
            srda.candidate_sources,
            srda.attempt_sources,
            srda.fallback_reason,
            srda.row_count, srda.duration_ms,
            srda.error_message, srda.started_at,
            srda.finished_at, srda.created_at
        FROM qmeta.source_route_decision_audit srda
        LEFT JOIN qmeta.source_route_weight_policy srwp ON srwp.policy_id = srda.policy_id
        LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = srda.dataset_id
        LEFT JOIN qmeta.source_system req ON req.source_id = srda.requested_source_id
        LEFT JOIN qmeta.source_system sel ON sel.source_id = srda.selected_source_id
        LEFT JOIN qmeta.source_system fin ON fin.source_id = srda.final_source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = srda.primary_source_id
        LEFT JOIN qmeta.source_system bs ON bs.source_id = srda.backup_source_id
        {where}
        ORDER BY srda.started_at DESC, srda.decision_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def route_meta(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not decision:
        return None
    return {
        "policy_code": decision.get("policy_code"),
        "dataset_code": decision.get("dataset_code"),
        "requested_source_code": decision.get("requested_source_code"),
        "selected_source_code": decision.get("selected_source_code"),
        "final_source_code": decision.get("final_source_code"),
        "decision_context": decision.get("decision_context"),
        "route_mode": decision.get("route_mode"),
        "decision_status": decision.get("decision_status"),
        "selected_role": decision.get("selected_role"),
        "candidate_sources": decision.get("candidate_sources") or [],
        "fallback_applied": bool(decision.get("fallback_applied")),
        "deterministic_bucket": decision.get("deterministic_bucket"),
        "circuit_skipped_sources": (decision.get("details") or {}).get("circuit_skipped_sources") or [],
        "circuit_fail_open": bool((decision.get("details") or {}).get("circuit_fail_open")),
    }


def format_phi5_rows(resource: str, rows: list[dict[str, Any]] | dict[str, Any]) -> str:
    data_rows = [rows] if isinstance(rows, dict) else list(rows or [])
    lines = [f"phi5 resource={resource} rows={len(data_rows)}"]
    for row in data_rows:
        keys = [
            "decision_code",
            "policy_code",
            "dataset_code",
            "requested_source_code",
            "selected_source_code",
            "final_source_code",
            "decision_context",
            "route_mode",
            "decision_status",
            "fallback_applied",
            "row_count",
        ]
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _default_decision(
    *,
    dataset_code: str,
    requested_source_code: str,
    selected_source_code: str,
    as_of_date: date,
    request_key: str,
    decision_context: str,
    route_mode: str,
    selected_role: str,
    dataset_id: int | None = None,
    requested_source_id: int | None = None,
    source_ids_by_code: dict[str, int] | None = None,
) -> dict[str, Any]:
    source_ids = dict(source_ids_by_code or {})
    selected_source_id = source_ids.get(selected_source_code, requested_source_id if selected_source_code == requested_source_code else None)
    return {
        "decision_code": _decision_code(decision_context, dataset_code, selected_source_code, request_key),
        "policy_id": None,
        "policy_code": None,
        "dataset_id": dataset_id,
        "dataset_code": dataset_code,
        "requested_source_id": requested_source_id,
        "requested_source_code": requested_source_code,
        "selected_source_id": selected_source_id,
        "selected_source_code": selected_source_code,
        "final_source_id": selected_source_id,
        "final_source_code": selected_source_code,
        "primary_source_id": selected_source_id,
        "primary_source_code": selected_source_code,
        "backup_source_id": None,
        "backup_source_code": None,
        "effective_date": as_of_date.isoformat(),
        "decision_context": decision_context,
        "route_mode": route_mode,
        "decision_status": "selected",
        "selected_role": selected_role,
        "primary_weight_pct": 100.0,
        "backup_weight_pct": 0.0,
        "free_source_weight_pct": 0.0,
        "selected_weight_pct": 100.0,
        "deterministic_bucket": deterministic_bucket(request_key),
        "candidate_sources": [selected_source_code],
        "fallback_source_codes": [],
        "attempt_sources": [],
        "fallback_attempted": False,
        "fallback_applied": False,
        "fallback_reason": None,
        "request_key": request_key,
        "source_ids_by_code": source_ids,
        "details": {"policy_code": None, "candidate_weights": []},
    }


def _merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        source_code = str(candidate.get("source_code") or "")
        weight = _float_or_zero(candidate.get("weight_pct"))
        if not source_code or weight <= 0:
            continue
        existing = merged.get(source_code)
        if existing:
            existing["weight_pct"] = round(_float_or_zero(existing.get("weight_pct")) + weight, 4)
            existing["role"] = existing.get("role") or candidate.get("role")
        else:
            merged[source_code] = {"role": candidate.get("role") or "backup", "source_code": source_code, "weight_pct": round(weight, 4)}
    return list(merged.values())


def _free_source_code(policy: dict[str, Any], *, requested_source_code: str) -> str:
    backup = policy.get("backup_source_code")
    primary = policy.get("primary_source_code")
    return str(backup or primary or requested_source_code)


def _validate_route_inputs(dataset_code: str, requested_source_code: str, decision_context: str) -> None:
    if not dataset_code:
        raise QDataValidationError("dataset_code is required")
    if not requested_source_code:
        raise QDataValidationError("requested_source_code is required")
    if decision_context not in ROUTE_CONTEXTS:
        raise QDataValidationError("decision_context must be one of: api, smoke, sync, worker")


def _as_of_date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return parse_date(str(value), "as_of_date")


def _decision_code(decision_context: str, dataset_code: str, source_code: str, request_key: str) -> str:
    digest = hashlib.sha1(f"{decision_context}:{dataset_code}:{source_code}:{request_key}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")).hexdigest()[:12]
    return f"phi5-route-{decision_context}-{dataset_code}-{source_code}-{digest}"[:180]


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


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Phi-5 route policy runtime") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[-1]


def _dedupe(items: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _float_or_zero(value: Any, *, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
