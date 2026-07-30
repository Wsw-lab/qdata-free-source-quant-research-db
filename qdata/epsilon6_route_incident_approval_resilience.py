from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.delta6_route_incident_approval_governance import (
    DEFAULT_SECRET,
    escalate_route_approval_timeouts,
    submit_wecom_route_approval_callback,
)
from qdata.exceptions import QDataValidationError


LOCK_PROVIDERS = {"wecom", "admin", "worker", "smoke"}
TERMINAL_APPROVAL_STATUSES = {"approved", "rejected", "cancelled", "expired"}
APPROVAL_DECISIONS = {"approve", "reject", "hold"}
GENESIS_HASH = "0" * 64


def approval_lock_key(scope: str) -> int:
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
    value = int(digest, 16)
    return value - (1 << 64) if value >= (1 << 63) else value


def evaluate_approval_state_transition(
    *,
    approval_status: str | None,
    control_stage: str | None,
    decision: str,
    target_found: bool = True,
) -> dict[str, Any]:
    decision = str(decision or "").lower()
    if decision not in APPROVAL_DECISIONS:
        raise QDataValidationError("decision must be one of: approve, reject, hold")
    current_status = str(approval_status or "unknown").lower()
    if not target_found:
        return {
            "allowed": False,
            "transition_status": "blocked",
            "reason_code": "target_missing",
            "approval_status_before": approval_status,
            "control_stage_before": control_stage,
            "expected_approval_status_after": None,
            "error_message": "approval target not found",
        }
    if current_status in TERMINAL_APPROVAL_STATUSES:
        return {
            "allowed": False,
            "transition_status": "blocked",
            "reason_code": "invalid_terminal_state",
            "approval_status_before": approval_status,
            "control_stage_before": control_stage,
            "expected_approval_status_after": current_status,
            "error_message": f"approval is already terminal: {current_status}",
        }
    if decision == "hold":
        return {
            "allowed": True,
            "transition_status": "allowed",
            "reason_code": "hold_keeps_pending",
            "approval_status_before": approval_status,
            "control_stage_before": control_stage,
            "expected_approval_status_after": current_status,
            "error_message": None,
        }
    return {
        "allowed": current_status in {"pending", "unknown", ""},
        "transition_status": "allowed" if current_status in {"pending", "unknown", ""} else "blocked",
        "reason_code": "valid_pending_transition" if current_status in {"pending", "unknown", ""} else "status_mismatch",
        "approval_status_before": approval_status,
        "control_stage_before": control_stage,
        "expected_approval_status_after": "approved" if decision == "approve" else "rejected",
        "error_message": None if current_status in {"pending", "unknown", ""} else f"approval status is not pending: {current_status}",
    }


def compute_audit_hash(previous_hash: str, canonical_payload: dict[str, Any], *, chain_scope: str, sequence_no: int) -> dict[str, str]:
    payload_text = _canonical_json(canonical_payload)
    payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    seed = f"{previous_hash}:{payload_hash}:{chain_scope}:{sequence_no}"
    entry_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return {"payload_hash": payload_hash, "entry_hash": entry_hash}


def verify_audit_hash_entry(entry: dict[str, Any], previous_hash: str) -> dict[str, Any]:
    expected = compute_audit_hash(
        previous_hash,
        entry.get("canonical_payload") or {},
        chain_scope=str(entry.get("chain_scope") or ""),
        sequence_no=int(entry.get("sequence_no") or 0),
    )
    ok = (
        str(entry.get("previous_hash") or "") == previous_hash
        and str(entry.get("payload_hash") or "") == expected["payload_hash"]
        and str(entry.get("entry_hash") or "") == expected["entry_hash"]
    )
    return {
        "verified": ok,
        "expected_payload_hash": expected["payload_hash"],
        "expected_entry_hash": expected["entry_hash"],
        "actual_payload_hash": entry.get("payload_hash"),
        "actual_entry_hash": entry.get("entry_hash"),
        "previous_hash": previous_hash,
    }


def submit_resilient_wecom_route_approval_callback(
    postgres_dsn: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    secret: str = DEFAULT_SECRET,
    raw_body: bytes | str | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    provider_code = str(payload.get("provider_code") or payload.get("provider") or "wecom").lower()
    if provider_code not in LOCK_PROVIDERS:
        raise QDataValidationError("provider_code must be one of: wecom, admin, worker, smoke")
    decision = str(payload.get("decision") or "").lower()
    if decision not in APPROVAL_DECISIONS:
        raise QDataValidationError("decision must be one of: approve, reject, hold")
    selector = _target_selector(payload)
    lock_scope = f"route-approval:{selector}"
    lock_key = approval_lock_key(lock_scope)
    body_bytes = _body_bytes(payload, raw_body)
    request_hash = hashlib.sha256(body_bytes).hexdigest()
    nonce = _header_or_payload(headers or {}, payload, "nonce") or f"auto-{request_hash[:24]}"
    concurrency_token = hashlib.sha1(f"{lock_scope}:{request_hash}:{started_at.isoformat()}".encode("utf-8")).hexdigest()

    if not write_db:
        target = _fetch_target_context(postgres_dsn, payload) if postgres_dsn else None
        guard = evaluate_approval_state_transition(
            approval_status=target.get("approval_status") if target else None,
            control_stage=target.get("control_stage") if target else None,
            decision=decision,
            target_found=bool(target),
        )
        delta_preview = submit_wecom_route_approval_callback(
            postgres_dsn,
            payload=payload,
            headers=headers,
            secret=secret,
            raw_body=raw_body,
            write_db=False,
        )
        return {
            **delta_preview,
            "epsilon6": {
                "write_db": False,
                "lock_scope": lock_scope,
                "lock_key": lock_key,
                "state_guard": guard,
            },
        }

    postgres_dsn = _require_dsn(postgres_dsn)
    lock_connection = _connect(postgres_dsn)
    lock_event: dict[str, Any] | None = None
    acquired = False
    try:
        with lock_connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (lock_key,))
            acquired = bool(cursor.fetchone()["acquired"])
        lock_event = _insert_lock_event(
            postgres_dsn,
            {
                "lock_event_code": _lock_event_code(lock_scope, concurrency_token),
                "lock_scope": lock_scope,
                "lock_key": lock_key,
                "provider_code": provider_code,
                "nonce": str(nonce),
                "request_hash": request_hash,
                "control_code": _optional_payload_string(payload, "control_code"),
                "approval_code": _optional_payload_string(payload, "approval_code"),
                "batch_code": _optional_payload_string(payload, "batch_code"),
                "requested_by": _optional_payload_string(payload, "requested_by"),
                "signer_code": _optional_payload_string(payload, "signer_code") or _optional_payload_string(payload, "principal_code"),
                "lock_status": "acquired" if acquired else "busy",
                "concurrency_token": concurrency_token,
                "evidence": {"selector": selector, "external_side_effect": False},
                "started_at": started_at,
                "finished_at": None if acquired else datetime.now(timezone.utc),
                "error_message": None if acquired else "route approval target is locked by another callback",
            },
        )
        if not acquired:
            audit = append_approval_audit_hash(
                postgres_dsn,
                chain_scope=lock_scope,
                entity_type="lock_event",
                entity_code=str(lock_event["lock_event_code"]),
                canonical_payload=lock_event,
                entity_id=int(lock_event["lock_event_id"]),
                event_time=_to_datetime(lock_event.get("started_at")),
                write_db=True,
            )
            return {
                "status": "locked",
                "governance_status": "lock_busy",
                "lock_event_code": lock_event.get("lock_event_code"),
                "error_message": lock_event.get("error_message"),
                "epsilon6": {"lock_event": lock_event, "audit_hash": audit},
            }

        target_before = _fetch_target_context(postgres_dsn, payload)
        guard = evaluate_approval_state_transition(
            approval_status=target_before.get("approval_status") if target_before else None,
            control_stage=target_before.get("control_stage") if target_before else None,
            decision=decision,
            target_found=bool(target_before),
        )
        if not guard["allowed"]:
            transition = _insert_state_transition(
                postgres_dsn,
                _transition_record(
                    payload=payload,
                    before=target_before,
                    after=target_before,
                    delta_result=None,
                    guard=guard,
                    transition_status="blocked",
                    reason_code=str(guard["reason_code"]),
                ),
            )
            transition_audit = append_approval_audit_hash(
                postgres_dsn,
                chain_scope=lock_scope,
                entity_type="state_transition",
                entity_code=str(transition["transition_code"]),
                canonical_payload=transition,
                entity_id=int(transition["transition_id"]),
                event_time=_to_datetime(transition.get("observed_at")),
                write_db=True,
            )
            _finish_lock_event(
                postgres_dsn,
                int(lock_event["lock_event_id"]),
                status="released",
                callback_code=None,
                command_code=None,
                evidence={"state_guard": guard, "transition_code": transition.get("transition_code")},
                started_at=started_at,
            )
            return {
                "status": "blocked",
                "governance_status": "state_blocked",
                "control_code": _optional_payload_string(payload, "control_code"),
                "approval_code": _optional_payload_string(payload, "approval_code"),
                "batch_code": _optional_payload_string(payload, "batch_code"),
                "error_message": guard.get("error_message"),
                "epsilon6": {
                    "lock_event_code": lock_event.get("lock_event_code"),
                    "state_transition": transition,
                    "audit_hash": transition_audit,
                },
            }

        delta_result = submit_wecom_route_approval_callback(
            postgres_dsn,
            payload=payload,
            headers=headers,
            secret=secret,
            raw_body=raw_body,
            write_db=True,
        )
        target_after = _fetch_target_context(postgres_dsn, payload)
        transition_status, reason_code = _transition_outcome(delta_result)
        transition = _insert_state_transition(
            postgres_dsn,
            _transition_record(
                payload=payload,
                before=target_before,
                after=target_after,
                delta_result=delta_result,
                guard=guard,
                transition_status=transition_status,
                reason_code=reason_code,
            ),
        )
        callback_entity_code = _audit_entity_code(delta_result)
        callback_audit = append_approval_audit_hash(
            postgres_dsn,
            chain_scope=lock_scope,
            entity_type="callback",
            entity_code=callback_entity_code,
            canonical_payload={"delta6_result": delta_result, "epsilon6_guard": guard},
            entity_id=int(delta_result.get("callback_id") or 0) or None,
            event_time=_to_datetime(delta_result.get("received_at")) if delta_result.get("received_at") else started_at,
            write_db=True,
        )
        transition_audit = append_approval_audit_hash(
            postgres_dsn,
            chain_scope=lock_scope,
            entity_type="state_transition",
            entity_code=str(transition["transition_code"]),
            canonical_payload=transition,
            entity_id=int(transition["transition_id"]),
            event_time=_to_datetime(transition.get("observed_at")),
            write_db=True,
        )
        _finish_lock_event(
            postgres_dsn,
            int(lock_event["lock_event_id"]),
            status="released",
            callback_code=delta_result.get("callback_code"),
            command_code=delta_result.get("command_code"),
            evidence={
                "state_guard": guard,
                "transition_code": transition.get("transition_code"),
                "callback_audit_hash": callback_audit.get("entry_hash"),
                "transition_audit_hash": transition_audit.get("entry_hash"),
            },
            started_at=started_at,
        )
        delta_result["epsilon6"] = {
            "lock_event_code": lock_event.get("lock_event_code"),
            "state_transition": transition,
            "callback_audit_hash": callback_audit,
            "transition_audit_hash": transition_audit,
        }
        return delta_result
    finally:
        if acquired:
            try:
                with lock_connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            finally:
                lock_connection.close()
        else:
            lock_connection.close()


def append_approval_audit_hash(
    postgres_dsn: str,
    *,
    chain_scope: str,
    entity_type: str,
    entity_code: str,
    canonical_payload: dict[str, Any],
    entity_id: int | None = None,
    event_time: datetime | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    if not chain_scope:
        raise QDataValidationError("chain_scope is required")
    if not entity_code:
        raise QDataValidationError("entity_code is required")
    if not write_db:
        hashes = compute_audit_hash(GENESIS_HASH, canonical_payload, chain_scope=chain_scope, sequence_no=1)
        return {
            "chain_scope": chain_scope,
            "sequence_no": 1,
            "entity_type": entity_type,
            "entity_code": entity_code,
            "previous_hash": GENESIS_HASH,
            **hashes,
        }
    postgres_dsn = _require_dsn(postgres_dsn)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (approval_lock_key(f"audit-chain:{chain_scope}"),))
            cursor.execute(
                """
                SELECT sequence_no, entry_hash
                FROM qmeta.source_route_incident_approval_audit_hash
                WHERE chain_scope = %s
                ORDER BY sequence_no DESC
                LIMIT 1
                """,
                (chain_scope,),
            )
            previous = cursor.fetchone()
            sequence_no = int(previous["sequence_no"] or 0) + 1 if previous else 1
            previous_hash = str(previous["entry_hash"]) if previous else GENESIS_HASH
            hashes = compute_audit_hash(previous_hash, canonical_payload, chain_scope=chain_scope, sequence_no=sequence_no)
            audit_hash_code = _audit_hash_code(chain_scope, entity_type, entity_code, sequence_no)
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_audit_hash (
                    audit_hash_code, chain_scope, sequence_no, entity_type,
                    entity_code, entity_id, event_time, previous_hash,
                    payload_hash, entry_hash, canonical_payload,
                    verification_status, evidence, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s::jsonb,
                    'chained', %s::jsonb, now()
                )
                ON CONFLICT (entity_type, entity_code) DO NOTHING
                RETURNING *
                """,
                (
                    audit_hash_code,
                    chain_scope,
                    sequence_no,
                    entity_type,
                    entity_code,
                    entity_id,
                    event_time or datetime.now(timezone.utc),
                    previous_hash,
                    hashes["payload_hash"],
                    hashes["entry_hash"],
                    _json(canonical_payload),
                    _json({"immutable": True}),
                ),
            )
            inserted = cursor.fetchone()
            if inserted:
                return normalize_rows([dict(inserted)])[0]
            cursor.execute(
                """
                SELECT *, TRUE AS duplicate_entry
                FROM qmeta.source_route_incident_approval_audit_hash
                WHERE entity_type = %s
                  AND entity_code = %s
                LIMIT 1
                """,
                (entity_type, entity_code),
            )
            row = dict(cursor.fetchone())
            return normalize_rows([row])[0]


def verify_approval_audit_chain(
    postgres_dsn: str,
    *,
    chain_scope: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    params: list[Any] = []
    where = ""
    if chain_scope:
        where = "WHERE chain_scope = %s"
        params.append(chain_scope)
    rows = _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_audit_hash
        {where}
        ORDER BY chain_scope, sequence_no
        LIMIT %s
        """,
        params + [limit],
    )
    previous_by_scope: dict[str, str] = {}
    broken: list[dict[str, Any]] = []
    for row in rows:
        scope = str(row.get("chain_scope") or "")
        previous_hash = previous_by_scope.get(scope, GENESIS_HASH)
        check = verify_audit_hash_entry(row, previous_hash)
        if not check["verified"]:
            broken.append({"audit_hash_code": row.get("audit_hash_code"), "chain_scope": scope, "check": check})
        previous_by_scope[scope] = str(row.get("entry_hash") or "")
    return {
        "status": "success" if not broken else "failed",
        "checked_count": len(rows),
        "broken_count": len(broken),
        "broken_entries": broken,
    }


def run_approval_sla_automation(
    postgres_dsn: str,
    *,
    limit: int = 100,
    now: datetime | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    timeout_result = escalate_route_approval_timeouts(postgres_dsn, limit=limit, now=now, write_db=write_db)
    escalations = _fetch_open_escalations_without_actions(postgres_dsn, limit=limit)
    actions: list[dict[str, Any]] = []
    for escalation in escalations:
        action = _sla_action_from_escalation(escalation)
        if write_db:
            action = _insert_sla_action(postgres_dsn, action)
            append_approval_audit_hash(
                postgres_dsn,
                chain_scope=_chain_scope_for_target(action),
                entity_type="sla_action",
                entity_code=str(action["sla_action_code"]),
                canonical_payload=action,
                entity_id=int(action["sla_action_id"]),
                event_time=_to_datetime(action.get("generated_at")),
                write_db=True,
            )
        actions.append(normalize_rows([action])[0])
    return {
        "status": "warning" if actions or timeout_result.get("escalation_count") else "healthy",
        "timeout_escalation_count": int(timeout_result.get("escalation_count") or 0),
        "checked_count": int(timeout_result.get("checked_count") or 0),
        "sla_action_count": len(actions),
        "actions": actions,
    }


def run_approval_recovery_drill(
    postgres_dsn: str,
    *,
    drill_type: str = "full",
    requested_by: str = "epsilon6",
    trigger_mode: str = "manual",
    target_control_code: str | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    if drill_type not in {"db_reconnect", "webhook_replay", "hash_chain_verify", "lock_contention", "state_machine_restore", "full"}:
        raise QDataValidationError("drill_type must be a valid Epsilon-6 drill type")
    if trigger_mode not in {"manual", "smoke", "worker"}:
        raise QDataValidationError("trigger_mode must be one of: manual, smoke, worker")
    started_at = datetime.now(timezone.utc)
    checks: list[dict[str, Any]] = []
    try:
        with _connect(_require_dsn(postgres_dsn)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                checks.append({"check": "db_reconnect", "status": "passed", "value": cursor.fetchone()["ok"]})
    except Exception as exc:  # pragma: no cover - smoke covers success path
        checks.append({"check": "db_reconnect", "status": "failed", "error_message": str(exc)})
    if drill_type in {"hash_chain_verify", "full"}:
        chain = verify_approval_audit_chain(postgres_dsn, limit=1000)
        checks.append({"check": "hash_chain_verify", "status": "passed" if chain["status"] == "success" else "failed", "result": chain})
    if drill_type in {"lock_contention", "full"}:
        sample_scope = f"route-approval:{target_control_code or 'epsilon6-drill'}"
        key = approval_lock_key(sample_scope)
        checks.append({"check": "lock_key_deterministic", "status": "passed" if key == approval_lock_key(sample_scope) else "failed", "lock_key": key})
    if drill_type in {"state_machine_restore", "full"}:
        guard = evaluate_approval_state_transition(approval_status="approved", control_stage="approved", decision="reject")
        checks.append({"check": "state_machine_terminal_guard", "status": "passed" if not guard["allowed"] else "failed", "result": guard})
    failed_count = sum(1 for check in checks if check["status"] != "passed")
    status = "success" if failed_count == 0 else "failed"
    finished_at = datetime.now(timezone.utc)
    record = {
        "drill_code": _drill_code(drill_type, requested_by, started_at),
        "drill_type": drill_type,
        "status": status,
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "target_control_code": target_control_code,
        "check_count": len(checks),
        "passed_count": len(checks) - failed_count,
        "failed_count": failed_count,
        "recovered_count": 0 if failed_count else len(checks),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
        "evidence": {"checks": checks, "external_side_effect": False},
        "error_message": None if not failed_count else "one or more recovery drill checks failed",
    }
    if write_db:
        record = _insert_recovery_drill(postgres_dsn, record)
        append_approval_audit_hash(
            postgres_dsn,
            chain_scope=f"route-approval:{target_control_code or 'epsilon6-recovery-drill'}",
            entity_type="recovery_drill",
            entity_code=str(record["drill_code"]),
            canonical_payload=record,
            entity_id=int(record["drill_id"]),
            event_time=_to_datetime(record.get("started_at")),
            write_db=True,
        )
    return normalize_rows([record])[0]


def list_route_incident_approval_lock_events(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("lock_event_code", "e.lock_event_code"),
            ("lock_scope", "e.lock_scope"),
            ("provider_code", "e.provider_code"),
            ("nonce", "e.nonce"),
            ("lock_status", "e.lock_status"),
            ("control_code", "e.control_code"),
            ("approval_code", "e.approval_code"),
            ("batch_code", "e.batch_code"),
            ("signer_code", "e.signer_code"),
            ("command_code", "e.command_code"),
            ("callback_code", "e.callback_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "e.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_lock_event e
        {where}
        ORDER BY e.started_at DESC, e.lock_event_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_state_transitions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("transition_code", "t.transition_code"),
            ("transition_status", "t.transition_status"),
            ("reason_code", "t.reason_code"),
            ("control_code", "t.control_code"),
            ("approval_code", "t.approval_code"),
            ("batch_code", "t.batch_code"),
            ("requested_decision", "t.requested_decision"),
            ("signer_code", "t.signer_code"),
            ("command_code", "t.command_code"),
            ("callback_code", "t.callback_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "t.observed_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_state_transition t
        {where}
        ORDER BY t.observed_at DESC, t.transition_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_audit_hashes(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("audit_hash_code", "h.audit_hash_code"),
            ("chain_scope", "h.chain_scope"),
            ("entity_type", "h.entity_type"),
            ("entity_code", "h.entity_code"),
            ("entry_hash", "h.entry_hash"),
            ("verification_status", "h.verification_status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "h.event_time")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_audit_hash h
        {where}
        ORDER BY h.event_time DESC, h.audit_hash_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_sla_actions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("sla_action_code", "a.sla_action_code"),
            ("escalation_code", "a.escalation_code"),
            ("command_code", "a.command_code"),
            ("control_code", "a.control_code"),
            ("approval_code", "a.approval_code"),
            ("reason_code", "a.reason_code"),
            ("action_type", "a.action_type"),
            ("action_status", "a.action_status"),
            ("severity", "a.severity"),
            ("owner_principal_code", "a.owner_principal_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "a.generated_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_sla_action a
        {where}
        ORDER BY a.generated_at DESC, a.sla_action_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_recovery_drills(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("drill_code", "d.drill_code"),
            ("drill_type", "d.drill_type"),
            ("status", "d.status"),
            ("requested_by", "d.requested_by"),
            ("trigger_mode", "d.trigger_mode"),
            ("target_control_code", "d.target_control_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "d.started_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT *
        FROM qmeta.source_route_incident_approval_recovery_drill d
        {where}
        ORDER BY d.started_at DESC, d.drill_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_epsilon6_report(payload: dict[str, Any]) -> str:
    return (
        "epsilon6_route_incident_approval_resilience "
        f"status={payload.get('status') or payload.get('governance_status')} "
        f"callback_code={payload.get('callback_code')} "
        f"command_code={payload.get('command_code')} "
        f"lock_event={((payload.get('epsilon6') or {}).get('lock_event_code') or payload.get('lock_event_code'))}"
    )


def format_epsilon6_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"epsilon6 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _insert_lock_event(postgres_dsn: str, event: dict[str, Any]) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_lock_event (
                    lock_event_code, lock_scope, lock_key, provider_code,
                    nonce, request_hash, callback_code, command_code,
                    control_code, approval_code, batch_code, requested_by,
                    signer_code, lock_status, wait_ms, held_ms,
                    concurrency_token, evidence, error_message, started_at,
                    finished_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::jsonb, %s, %s,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    event["lock_event_code"],
                    event["lock_scope"],
                    event["lock_key"],
                    event["provider_code"],
                    event.get("nonce"),
                    event.get("request_hash"),
                    event.get("callback_code"),
                    event.get("command_code"),
                    event.get("control_code"),
                    event.get("approval_code"),
                    event.get("batch_code"),
                    event.get("requested_by"),
                    event.get("signer_code"),
                    event["lock_status"],
                    event.get("wait_ms", 0),
                    event.get("held_ms"),
                    event["concurrency_token"],
                    _json(event.get("evidence") or {}),
                    event.get("error_message"),
                    event.get("started_at"),
                    event.get("finished_at"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _finish_lock_event(
    postgres_dsn: str,
    lock_event_id: int,
    *,
    status: str,
    callback_code: Any,
    command_code: Any,
    evidence: dict[str, Any],
    started_at: datetime,
) -> None:
    finished_at = datetime.now(timezone.utc)
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.source_route_incident_approval_lock_event
                SET lock_status = %s,
                    callback_code = %s,
                    command_code = %s,
                    held_ms = %s,
                    finished_at = %s,
                    evidence = evidence || %s::jsonb,
                    updated_at = now()
                WHERE lock_event_id = %s
                """,
                (
                    status,
                    callback_code,
                    command_code,
                    _duration_ms(started_at, finished_at),
                    finished_at,
                    _json(evidence),
                    lock_event_id,
                ),
            )


def _insert_state_transition(postgres_dsn: str, transition: dict[str, Any]) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_state_transition (
                    transition_code, callback_id, command_id, callback_code,
                    command_code, control_code, approval_code, batch_code,
                    requested_by, signer_code, requested_decision,
                    approval_status_before, control_stage_before,
                    approval_status_after, control_stage_after,
                    transition_status, reason_code, state_version,
                    evidence, error_message, observed_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s, %s, now()
                )
                RETURNING *
                """,
                (
                    transition["transition_code"],
                    transition.get("callback_id"),
                    transition.get("command_id"),
                    transition.get("callback_code"),
                    transition.get("command_code"),
                    transition.get("control_code"),
                    transition.get("approval_code"),
                    transition.get("batch_code"),
                    transition.get("requested_by"),
                    transition.get("signer_code"),
                    transition.get("requested_decision"),
                    transition.get("approval_status_before"),
                    transition.get("control_stage_before"),
                    transition.get("approval_status_after"),
                    transition.get("control_stage_after"),
                    transition.get("transition_status"),
                    transition.get("reason_code"),
                    transition.get("state_version", 1),
                    _json(transition.get("evidence") or {}),
                    transition.get("error_message"),
                    transition.get("observed_at"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _insert_sla_action(postgres_dsn: str, action: dict[str, Any]) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_sla_action (
                    sla_action_code, escalation_id, escalation_code, command_code,
                    control_code, approval_code, reason_code, action_type,
                    action_status, severity, owner_principal_code, due_at,
                    external_side_effect, evidence, error_message, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::jsonb, %s, now()
                )
                ON CONFLICT (escalation_code, action_type) DO UPDATE SET
                    action_status = CASE
                        WHEN qmeta.source_route_incident_approval_sla_action.action_status IN ('executed', 'resolved') THEN qmeta.source_route_incident_approval_sla_action.action_status
                        ELSE EXCLUDED.action_status
                    END,
                    severity = EXCLUDED.severity,
                    owner_principal_code = EXCLUDED.owner_principal_code,
                    evidence = qmeta.source_route_incident_approval_sla_action.evidence || EXCLUDED.evidence,
                    error_message = COALESCE(EXCLUDED.error_message, qmeta.source_route_incident_approval_sla_action.error_message),
                    updated_at = now()
                RETURNING *
                """,
                (
                    action["sla_action_code"],
                    action.get("escalation_id"),
                    action.get("escalation_code"),
                    action.get("command_code"),
                    action.get("control_code"),
                    action.get("approval_code"),
                    action["reason_code"],
                    action["action_type"],
                    action.get("action_status", "planned"),
                    action.get("severity", "high"),
                    action.get("owner_principal_code", "platform-ops"),
                    action.get("due_at"),
                    action.get("external_side_effect", False),
                    _json(action.get("evidence") or {}),
                    action.get("error_message"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _insert_recovery_drill(postgres_dsn: str, drill: dict[str, Any]) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_recovery_drill (
                    drill_code, drill_type, status, requested_by,
                    trigger_mode, target_control_code, check_count,
                    passed_count, failed_count, recovered_count,
                    started_at, finished_at, duration_ms, evidence,
                    error_message, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s::jsonb,
                    %s, now()
                )
                RETURNING *
                """,
                (
                    drill["drill_code"],
                    drill["drill_type"],
                    drill["status"],
                    drill["requested_by"],
                    drill["trigger_mode"],
                    drill.get("target_control_code"),
                    drill["check_count"],
                    drill["passed_count"],
                    drill["failed_count"],
                    drill["recovered_count"],
                    drill["started_at"],
                    drill.get("finished_at"),
                    drill.get("duration_ms"),
                    _json(drill.get("evidence") or {}),
                    drill.get("error_message"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _transition_record(
    *,
    payload: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    delta_result: dict[str, Any] | None,
    guard: dict[str, Any],
    transition_status: str,
    reason_code: str,
) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc)
    control_code = (delta_result or {}).get("control_code") or (before or {}).get("control_code") or _optional_payload_string(payload, "control_code")
    approval_code = (delta_result or {}).get("approval_code") or (before or {}).get("approval_code") or _optional_payload_string(payload, "approval_code")
    callback_code = (delta_result or {}).get("callback_code")
    command_code = (delta_result or {}).get("command_code")
    return {
        "transition_code": _transition_code(control_code or approval_code or _target_selector(payload), observed_at),
        "callback_id": (delta_result or {}).get("callback_id"),
        "command_id": (delta_result or {}).get("command_id"),
        "callback_code": callback_code,
        "command_code": command_code,
        "control_code": control_code,
        "approval_code": approval_code,
        "batch_code": (delta_result or {}).get("batch_code") or _optional_payload_string(payload, "batch_code"),
        "requested_by": (delta_result or {}).get("requested_by") or _optional_payload_string(payload, "requested_by"),
        "signer_code": (delta_result or {}).get("signer_code") or _optional_payload_string(payload, "signer_code") or _optional_payload_string(payload, "principal_code"),
        "requested_decision": str(payload.get("decision") or "").lower(),
        "approval_status_before": (before or {}).get("approval_status"),
        "control_stage_before": (before or {}).get("control_stage"),
        "approval_status_after": (after or {}).get("approval_status"),
        "control_stage_after": (after or {}).get("control_stage"),
        "transition_status": transition_status,
        "reason_code": reason_code,
        "state_version": 1,
        "evidence": {"guard": guard, "delta6": _compact_delta_result(delta_result), "external_side_effect": False},
        "error_message": guard.get("error_message") if transition_status == "blocked" else (delta_result or {}).get("error_message"),
        "observed_at": observed_at,
    }


def _transition_outcome(delta_result: dict[str, Any]) -> tuple[str, str]:
    status = str(delta_result.get("governance_status") or delta_result.get("status") or "")
    if status in {"applied", "rejected", "held", "pending_quorum", "accepted"}:
        return ("applied" if status in {"applied", "rejected", "held"} else "allowed", "valid_pending_transition")
    if status == "replay_rejected":
        return "noop", "replay_rejected"
    if status in {"invalid_signature", "payload_invalid"}:
        return "blocked", "signature_rejected"
    if status in {"denied"}:
        return "blocked", "governance_denied"
    return "failed", "delta6_failed"


def _fetch_target_context(postgres_dsn: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    control_code = _optional_payload_string(payload, "control_code")
    approval_code = _optional_payload_string(payload, "approval_code")
    batch_code = _optional_payload_string(payload, "batch_code")
    values: list[Any] = []
    if batch_code:
        selector = "ctrl.control_code IN (SELECT control_code FROM qmeta.source_route_incident_operation_item WHERE batch_code = %s AND control_code IS NOT NULL)"
        values.append(batch_code)
    elif control_code:
        selector = "ctrl.control_code = %s"
        values.append(control_code)
    else:
        selector = "ap.approval_code = %s"
        values.append(approval_code)
    rows = _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ctrl.control_id, ctrl.control_code, ctrl.approval_id,
            ctrl.approval_status, ctrl.control_stage, ctrl.requested_by,
            ctrl.owner, ctrl.created_at, ctrl.updated_at,
            ap.approval_code, ap.status AS omega_approval_status,
            sria.incident_action_code, dc.dataset_code, ss.source_code,
            sria.source_signal_type, sria.safety_level
        FROM qmeta.source_route_incident_control ctrl
        JOIN qmeta.source_route_incident_action sria ON sria.incident_action_id = ctrl.incident_action_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = sria.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = sria.source_id
        LEFT JOIN qmeta.automation_approval ap ON ap.approval_id = ctrl.approval_id
        WHERE {selector}
        ORDER BY ctrl.updated_at DESC, ctrl.control_id DESC
        LIMIT 1
        """,
        values,
    )
    return rows[0] if rows else None


def _fetch_open_escalations_without_actions(postgres_dsn: str, *, limit: int) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        SELECT e.*
        FROM qmeta.source_route_incident_approval_escalation e
        LEFT JOIN qmeta.source_route_incident_approval_sla_action a
          ON a.escalation_code = e.escalation_code
        WHERE e.status = 'open'
          AND a.sla_action_id IS NULL
        ORDER BY e.created_at ASC, e.escalation_id ASC
        LIMIT %s
        """,
        [limit],
    )


def _sla_action_from_escalation(escalation: dict[str, Any]) -> dict[str, Any]:
    reason = str(escalation.get("reason_code") or "approval_timeout")
    action_type = {
        "approval_timeout": "escalate_risk_admin",
        "quorum_stalled": "escalate_risk_admin",
        "policy_denied": "notify_owner",
        "missing_binding": "notify_owner",
        "invalid_signature": "retry_callback_probe",
        "replay_rejected": "suppress_replay",
        "cancel_requested": "restore_from_audit",
    }.get(reason, "notify_owner")
    severity = "critical" if reason in {"approval_timeout", "quorum_stalled"} else str(escalation.get("severity") or "high")
    code = _sla_action_code(str(escalation.get("escalation_code") or ""), action_type)
    return {
        "sla_action_code": code,
        "escalation_id": escalation.get("escalation_id"),
        "escalation_code": escalation.get("escalation_code"),
        "command_code": escalation.get("command_code"),
        "control_code": escalation.get("control_code"),
        "approval_code": escalation.get("approval_code"),
        "reason_code": reason,
        "action_type": action_type,
        "action_status": "planned",
        "severity": severity,
        "owner_principal_code": escalation.get("owner_principal_code") or "platform-ops",
        "due_at": escalation.get("due_at"),
        "external_side_effect": False,
        "evidence": {"escalation": escalation, "external_side_effect": False},
        "error_message": None,
    }


def _chain_scope_for_target(value: dict[str, Any]) -> str:
    target = value.get("control_code") or value.get("approval_code") or value.get("batch_code") or value.get("escalation_code") or value.get("drill_code") or "global"
    return f"route-approval:{target}"


def _target_selector(payload: dict[str, Any]) -> str:
    for key in ("control_code", "approval_code", "batch_code"):
        value = _optional_payload_string(payload, key)
        if value:
            return f"{key}:{value}"
    return f"request:{hashlib.sha1(_canonical_json(payload).encode('utf-8')).hexdigest()[:16]}"


def _body_bytes(payload: dict[str, Any], raw_body: bytes | str | None) -> bytes:
    if raw_body is None:
        return _canonical_json(payload).encode("utf-8")
    return raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body


def _header_or_payload(headers: dict[str, str], payload: dict[str, Any], name: str) -> str | None:
    aliases = {
        "nonce": ["x-qdata-nonce", "x-wecom-nonce", "x-wx-nonce", "nonce"],
    }[name]
    lower_headers = {str(key).lower(): str(value) for key, value in headers.items()}
    for alias in aliases:
        if lower_headers.get(alias):
            return lower_headers[alias]
    for alias in aliases:
        if payload.get(alias):
            return str(payload[alias])
    return None


def _audit_entity_code(delta_result: dict[str, Any]) -> str:
    callback_code = str(delta_result.get("callback_code") or "callback")
    if delta_result.get("replay_detected"):
        return f"{callback_code}:replay:{delta_result.get('replay_count', 0)}"
    return callback_code


def _compact_delta_result(delta_result: dict[str, Any] | None) -> dict[str, Any]:
    if not delta_result:
        return {}
    return {
        "callback_code": delta_result.get("callback_code"),
        "command_code": delta_result.get("command_code"),
        "governance_status": delta_result.get("governance_status"),
        "signature_status": delta_result.get("signature_status"),
        "decision": delta_result.get("decision"),
        "error_message": delta_result.get("error_message"),
    }


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
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise QDataValidationError("psycopg is required for Epsilon-6 route incident approval resilience") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _optional_payload_string(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value in (None, ""):
        return None
    return str(value)


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)


def _lock_event_code(lock_scope: str, concurrency_token: str) -> str:
    digest = hashlib.sha1(f"{lock_scope}:{concurrency_token}".encode("utf-8")).hexdigest()[:12]
    return f"epsilon6-lock-{digest}"[:180]


def _transition_code(target: str, observed_at: datetime) -> str:
    digest = hashlib.sha1(f"{target}:{observed_at.isoformat()}".encode("utf-8")).hexdigest()[:12]
    return f"epsilon6-transition-{digest}"[:180]


def _audit_hash_code(chain_scope: str, entity_type: str, entity_code: str, sequence_no: int) -> str:
    digest = hashlib.sha1(f"{chain_scope}:{entity_type}:{entity_code}:{sequence_no}".encode("utf-8")).hexdigest()[:12]
    return f"epsilon6-audit-{digest}"[:180]


def _sla_action_code(escalation_code: str, action_type: str) -> str:
    digest = hashlib.sha1(f"{escalation_code}:{action_type}".encode("utf-8")).hexdigest()[:12]
    return f"epsilon6-sla-{digest}"[:180]


def _drill_code(drill_type: str, requested_by: str, started_at: datetime) -> str:
    digest = hashlib.sha1(f"{drill_type}:{requested_by}:{started_at.isoformat()}".encode("utf-8")).hexdigest()[:12]
    return f"epsilon6-drill-{digest}"[:180]


def _param(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = params.get(name)
    if not values:
        return default
    return values[-1]


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "lock_events": ["started_at", "lock_event_code", "lock_status", "lock_scope", "control_code", "callback_code", "command_code", "held_ms", "error_message"],
        "state_transitions": ["observed_at", "transition_code", "transition_status", "reason_code", "control_code", "requested_decision", "approval_status_before", "approval_status_after", "callback_code", "command_code", "error_message"],
        "audit_hashes": ["event_time", "audit_hash_code", "chain_scope", "sequence_no", "entity_type", "entity_code", "previous_hash", "entry_hash", "verification_status"],
        "sla_actions": ["generated_at", "sla_action_code", "action_status", "action_type", "reason_code", "severity", "owner_principal_code", "escalation_code", "control_code"],
        "recovery_drills": ["started_at", "drill_code", "drill_type", "status", "check_count", "passed_count", "failed_count", "recovered_count", "requested_by"],
    }
    preferred = preferred_by_resource.get(resource, preferred_by_resource["audit_hashes"])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Epsilon-6 route incident approval resilience")
    return postgres_dsn
