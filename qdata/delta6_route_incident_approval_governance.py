from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.gamma6_route_incident_approval_api import submit_route_incident_approval_command


APPROVAL_DECISIONS = {"approve", "reject", "hold"}
PROVIDERS = {"wecom"}
ROLE_CODES = {"route_requester", "route_approver", "route_risk_admin", "route_audit_viewer"}
HIGH_RISK_LEVELS = {"high", "critical"}
MAX_REQUIRED_APPROVALS = 5
DEFAULT_POLICY_CODE = "delta6-default-route-approval-policy"
DEFAULT_SECRET = "delta6-local-secret"
SENSITIVE_KEYS = {"token", "secret", "signature", "msg_signature", "password", "authorization"}


def verify_wecom_callback_signature(
    secret: str,
    timestamp: str | int | None,
    nonce: str | None,
    raw_body: bytes | str,
    signature: str | None,
    *,
    max_clock_skew_seconds: int = 300,
    now: datetime | None = None,
) -> dict[str, Any]:
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    if not timestamp or not nonce or not signature:
        return {
            "signature_status": "missing_signature",
            "verified": False,
            "error_message": "timestamp, nonce and signature are required",
        }
    try:
        timestamp_seconds = int(timestamp)
    except (TypeError, ValueError):
        return {
            "signature_status": "payload_invalid",
            "verified": False,
            "error_message": "timestamp must be an integer",
        }
    observed_now = now or datetime.now(timezone.utc)
    clock_skew_seconds = abs(int(observed_now.timestamp()) - timestamp_seconds)
    signing_text = f"{timestamp_seconds}\n{nonce}\n".encode("utf-8") + body
    expected = hmac.new(secret.encode("utf-8"), signing_text, hashlib.sha256).hexdigest()
    received = _normalize_signature(signature)
    if max_clock_skew_seconds >= 0 and clock_skew_seconds > max_clock_skew_seconds:
        return {
            "signature_status": "timestamp_skew",
            "verified": False,
            "timestamp_seconds": timestamp_seconds,
            "clock_skew_seconds": clock_skew_seconds,
            "expected_digest": expected,
            "received_digest": received,
            "error_message": "callback timestamp is outside allowed clock skew",
        }
    verified = hmac.compare_digest(expected, received)
    return {
        "signature_status": "verified" if verified else "invalid_signature",
        "verified": verified,
        "timestamp_seconds": timestamp_seconds,
        "clock_skew_seconds": clock_skew_seconds,
        "expected_digest": expected,
        "received_digest": received,
        "error_message": None if verified else "callback signature mismatch",
    }


def evaluate_route_approval_rbac(
    *,
    signer_code: str,
    requested_by: str,
    role_bindings: list[dict[str, Any]],
    target: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not signer_code:
        raise QDataValidationError("signer_code is required")
    if _bool(policy.get("require_distinct_requester"), True):
        target_requester = str(target.get("requested_by") or "")
        if signer_code == requested_by or (target_requester and signer_code == target_requester):
            return _rbac_denied("policy_denied", "requester cannot approve the same route incident", target=target)
    required_roles = {"route_approver", "route_risk_admin"}
    if _bool(policy.get("require_risk_admin_for_high"), False) and str(target.get("safety_level") or "").lower() in HIGH_RISK_LEVELS:
        required_roles = {"route_risk_admin"}
    matching = [
        binding
        for binding in role_bindings
        if binding.get("role_code") in required_roles and _binding_matches_target(binding, target)
    ]
    if not matching:
        return _rbac_denied(
            "missing_binding",
            f"signer requires one of {','.join(sorted(required_roles))} for this route incident",
            target=target,
        )
    selected = sorted(matching, key=_binding_specificity, reverse=True)[0]
    return {
        "allowed": True,
        "reason_code": "allowed",
        "binding_id": selected.get("binding_id"),
        "binding_code": selected.get("binding_code"),
        "role_code": selected.get("role_code"),
        "required_roles": sorted(required_roles),
        "issues": [],
        "evidence": {
            "dataset_code": target.get("dataset_code"),
            "source_code": target.get("source_code"),
            "safety_level": target.get("safety_level"),
            "binding_scope": {
                "dataset_code": selected.get("dataset_code"),
                "source_code": selected.get("source_code"),
                "safety_level": selected.get("safety_level"),
            },
        },
    }


def evaluate_approval_timeout(command: dict[str, Any], *, now: datetime | None, policy: dict[str, Any]) -> dict[str, Any]:
    observed_now = now or datetime.now(timezone.utc)
    started_at = _to_datetime(command.get("started_at"))
    timeout_minutes = int(policy.get("timeout_minutes") or 240)
    due_at = started_at + timedelta(minutes=timeout_minutes)
    overdue = observed_now >= due_at
    overdue_minutes = max(int((observed_now - due_at).total_seconds() // 60), 0) if overdue else 0
    return {
        "overdue": overdue,
        "timeout_minutes": timeout_minutes,
        "due_at": due_at,
        "overdue_minutes": overdue_minutes,
        "reason_code": "approval_timeout" if overdue else "within_sla",
    }


def redact_callback_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if key.lower() in SENSITIVE_KEYS or any(word in key.lower() for word in SENSITIVE_KEYS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_callback_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_callback_payload(item) for item in payload]
    return payload


def ensure_route_approval_role_binding(
    postgres_dsn: str,
    *,
    principal_code: str,
    role_code: str,
    dataset_code: str = "*",
    source_code: str = "*",
    safety_level: str = "*",
    created_by: str = "delta6",
    binding_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if role_code not in ROLE_CODES:
        raise QDataValidationError("role_code must be a Delta-6 route approval role")
    if not principal_code:
        raise QDataValidationError("principal_code is required")
    code = binding_code or _role_binding_code(principal_code, role_code, dataset_code, source_code, safety_level)
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_role_binding (
                    binding_code, principal_code, role_code, dataset_code,
                    source_code, safety_level, status, created_by, details, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, 'active', %s, %s::jsonb, now()
                )
                ON CONFLICT (binding_code) DO UPDATE SET
                    principal_code = EXCLUDED.principal_code,
                    role_code = EXCLUDED.role_code,
                    dataset_code = EXCLUDED.dataset_code,
                    source_code = EXCLUDED.source_code,
                    safety_level = EXCLUDED.safety_level,
                    status = 'active',
                    created_by = EXCLUDED.created_by,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING *
                """,
                (
                    code,
                    principal_code,
                    role_code,
                    dataset_code or "*",
                    source_code or "*",
                    safety_level or "*",
                    created_by,
                    _json(details or {}),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def ensure_route_approval_policy(
    postgres_dsn: str,
    *,
    policy_code: str = DEFAULT_POLICY_CODE,
    dataset_code: str = "*",
    source_code: str = "*",
    safety_level: str = "*",
    min_approvals: int = 2,
    require_distinct_requester: bool = True,
    require_risk_admin_for_high: bool = False,
    require_wecom_signature: bool = True,
    timeout_minutes: int = 240,
    replay_window_minutes: int = 1440,
    max_clock_skew_seconds: int = 300,
    escalation_principal_code: str = "platform-ops",
    created_by: str = "delta6",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if min_approvals < 1 or min_approvals > MAX_REQUIRED_APPROVALS:
        raise QDataValidationError("min_approvals must be between 1 and 5")
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_policy (
                    policy_code, dataset_code, source_code, safety_level,
                    status, min_approvals, require_distinct_requester,
                    require_risk_admin_for_high, require_wecom_signature,
                    timeout_minutes, replay_window_minutes, max_clock_skew_seconds,
                    escalation_principal_code, created_by, details, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    'active', %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s::jsonb, now()
                )
                ON CONFLICT (policy_code) DO UPDATE SET
                    dataset_code = EXCLUDED.dataset_code,
                    source_code = EXCLUDED.source_code,
                    safety_level = EXCLUDED.safety_level,
                    status = 'active',
                    min_approvals = EXCLUDED.min_approvals,
                    require_distinct_requester = EXCLUDED.require_distinct_requester,
                    require_risk_admin_for_high = EXCLUDED.require_risk_admin_for_high,
                    require_wecom_signature = EXCLUDED.require_wecom_signature,
                    timeout_minutes = EXCLUDED.timeout_minutes,
                    replay_window_minutes = EXCLUDED.replay_window_minutes,
                    max_clock_skew_seconds = EXCLUDED.max_clock_skew_seconds,
                    escalation_principal_code = EXCLUDED.escalation_principal_code,
                    created_by = EXCLUDED.created_by,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING *
                """,
                (
                    policy_code,
                    dataset_code or "*",
                    source_code or "*",
                    safety_level or "*",
                    min_approvals,
                    require_distinct_requester,
                    require_risk_admin_for_high,
                    require_wecom_signature,
                    timeout_minutes,
                    replay_window_minutes,
                    max_clock_skew_seconds,
                    escalation_principal_code,
                    created_by,
                    _json(details or {}),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def submit_wecom_route_approval_callback(
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
    if provider_code not in PROVIDERS:
        raise QDataValidationError("provider_code must be one of: wecom")
    decision = str(payload.get("decision") or "").lower()
    signer_code = str(payload.get("signer_code") or payload.get("principal_code") or "")
    requested_by = str(payload.get("requested_by") or "wecom")
    control_code = _optional_payload_string(payload, "control_code")
    approval_code = _optional_payload_string(payload, "approval_code")
    batch_code = _optional_payload_string(payload, "batch_code")
    _validate_callback_selector(
        decision=decision,
        signer_code=signer_code,
        control_code=control_code,
        approval_code=approval_code,
        batch_code=batch_code,
    )
    body = _canonical_body(payload) if raw_body is None else raw_body
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    request_hash = hashlib.sha256(body_bytes).hexdigest()
    header_map = _normalize_headers(headers or {})
    timestamp = _header_or_payload(header_map, payload, "timestamp")
    nonce = _header_or_payload(header_map, payload, "nonce") or _nonce_from_hash(request_hash)
    signature = _header_or_payload(header_map, payload, "signature")

    target = _fetch_target_context(
        postgres_dsn,
        control_code=control_code,
        approval_code=approval_code,
        batch_code=batch_code,
    )
    policy = _fetch_matching_policy(postgres_dsn, target or {})
    required_approvals = max(_int_payload(payload, "required_approvals", int(policy.get("min_approvals") or 1)), int(policy.get("min_approvals") or 1))
    signature_result = verify_wecom_callback_signature(
        secret,
        timestamp,
        nonce,
        body_bytes,
        signature,
        max_clock_skew_seconds=int(policy.get("max_clock_skew_seconds") or 300),
        now=started_at,
    ) if _bool(policy.get("require_wecom_signature"), True) else {
        "signature_status": "verified",
        "verified": True,
        "timestamp_seconds": int(timestamp or started_at.timestamp()),
        "clock_skew_seconds": 0,
        "expected_digest": None,
        "received_digest": _normalize_signature(signature),
        "error_message": None,
    }
    timestamp_seconds = int(signature_result.get("timestamp_seconds") or timestamp or started_at.timestamp())
    base_record = {
        "provider_code": provider_code,
        "nonce": str(nonce),
        "timestamp_seconds": timestamp_seconds,
        "request_hash": request_hash,
        "signature_digest": signature_result.get("received_digest"),
        "policy_id": policy.get("policy_id"),
        "policy_code": policy.get("policy_code"),
        "control_code": control_code,
        "approval_code": approval_code,
        "batch_code": batch_code,
        "decision": decision,
        "requested_by": requested_by,
        "signer_code": signer_code,
        "required_approvals": required_approvals,
        "raw_payload_redacted": redact_callback_payload(payload),
        "evidence": {
            "signature": _public_signature_evidence(signature_result),
            "target": target or {},
            "policy": _policy_summary(policy),
        },
    }
    if not signature_result.get("verified"):
        record = {
            **base_record,
            "callback_code": _callback_code(provider_code, str(nonce), request_hash, started_at),
            "signature_status": str(signature_result.get("signature_status") or "invalid_signature"),
            "governance_status": "payload_invalid" if signature_result.get("signature_status") == "payload_invalid" else "invalid_signature",
            "response_payload": {"accepted": False},
            "error_message": str(signature_result.get("error_message") or "callback signature rejected"),
            "processed_at": datetime.now(timezone.utc),
        }
        inserted = _insert_callback(postgres_dsn, record, write_db=write_db)
        if write_db:
            _insert_escalation(
                postgres_dsn,
                reason_code="invalid_signature",
                severity="high",
                owner_principal_code=str(policy.get("escalation_principal_code") or "platform-ops"),
                callback=inserted,
                command=None,
                evidence=record["evidence"],
                error_message=record["error_message"],
            )
        return inserted

    replay = _fetch_callback_replay(postgres_dsn, provider_code=provider_code, nonce=str(nonce)) if write_db else None
    if replay:
        replay_result = _mark_callback_replay(postgres_dsn, replay) if write_db else replay
        replay_result.update(
            {
                "signature_status": "replay_rejected",
                "governance_status": "replay_rejected",
                "replay_detected": True,
                "error_message": "callback nonce was already processed",
            }
        )
        if write_db:
            _insert_escalation(
                postgres_dsn,
                reason_code="replay_rejected",
                severity="medium",
                owner_principal_code=str(policy.get("escalation_principal_code") or "platform-ops"),
                callback=replay_result,
                command=None,
                evidence={"provider_code": provider_code, "nonce": str(nonce), "request_hash": request_hash},
                error_message="callback nonce was already processed",
            )
        return replay_result

    if not target:
        record = {
            **base_record,
            "callback_code": _callback_code(provider_code, str(nonce), request_hash, started_at),
            "signature_status": "verified",
            "governance_status": "denied",
            "response_payload": {"accepted": False},
            "error_message": "approval target not found",
            "processed_at": datetime.now(timezone.utc),
        }
        inserted = _insert_callback(postgres_dsn, record, write_db=write_db)
        if write_db:
            _insert_escalation(
                postgres_dsn,
                reason_code="policy_denied",
                severity="high",
                owner_principal_code=str(policy.get("escalation_principal_code") or "platform-ops"),
                callback=inserted,
                command=None,
                evidence=record["evidence"],
                error_message=record["error_message"],
            )
        return inserted

    bindings = _fetch_active_role_bindings(postgres_dsn, signer_code)
    rbac = evaluate_route_approval_rbac(
        signer_code=signer_code,
        requested_by=requested_by,
        role_bindings=bindings,
        target=target,
        policy=policy,
    )
    if not rbac["allowed"]:
        record = {
            **base_record,
            "callback_code": _callback_code(provider_code, str(nonce), request_hash, started_at),
            "signature_status": "verified",
            "governance_status": "denied",
            "binding_id": rbac.get("binding_id"),
            "binding_code": rbac.get("binding_code"),
            "response_payload": {"accepted": False, "rbac": rbac},
            "evidence": {**base_record["evidence"], "rbac": rbac},
            "error_message": str(rbac.get("error_message") or "approval RBAC denied"),
            "processed_at": datetime.now(timezone.utc),
        }
        inserted = _insert_callback(postgres_dsn, record, write_db=write_db)
        if write_db:
            _insert_escalation(
                postgres_dsn,
                reason_code=str(rbac.get("reason_code") or "policy_denied"),
                severity="high",
                owner_principal_code=str(policy.get("escalation_principal_code") or "platform-ops"),
                callback=inserted,
                command=None,
                evidence=record["evidence"],
                error_message=record["error_message"],
            )
        return inserted

    idempotency_key = _bounded_key(str(payload.get("idempotency_key") or f"delta6:{provider_code}:{nonce}:{target.get('control_code') or control_code or approval_code or batch_code}"))
    if not write_db:
        return normalize_rows([
            {
                **base_record,
                "callback_code": _callback_code(provider_code, str(nonce), request_hash, started_at),
                "signature_status": "verified",
                "governance_status": "accepted",
                "binding_id": rbac.get("binding_id"),
                "binding_code": rbac.get("binding_code"),
                "idempotency_key": idempotency_key,
                "response_payload": {"accepted": True, "rbac": rbac},
                "evidence": {**base_record["evidence"], "rbac": rbac, "write_db": False},
                "processed_at": datetime.now(timezone.utc),
            }
        ])[0]

    gamma = submit_route_incident_approval_command(
        postgres_dsn,
        decision=decision,
        requested_by=requested_by,
        principal_code=signer_code,
        control_code=control_code,
        approval_code=approval_code,
        batch_code=batch_code,
        idempotency_key=idempotency_key,
        required_approvals=required_approvals,
        trigger_mode=str(payload.get("trigger_mode") or "api"),
        notify_wecom=False,
        allow_wecom_external=False,
        write_db=True,
    )
    processed_at = datetime.now(timezone.utc)
    record = {
        **base_record,
        "callback_code": _callback_code(provider_code, str(nonce), request_hash, started_at),
        "signature_status": "verified",
        "governance_status": _governance_status_from_gamma(gamma, decision),
        "binding_id": rbac.get("binding_id"),
        "binding_code": rbac.get("binding_code"),
        "command_id": gamma.get("command_id"),
        "command_code": gamma.get("command_code"),
        "idempotency_key": idempotency_key,
        "response_payload": {"accepted": True, "gamma6": gamma, "rbac": rbac},
        "evidence": {**base_record["evidence"], "rbac": rbac, "external_side_effect": False},
        "error_message": gamma.get("error_message"),
        "processed_at": processed_at,
        "duration_ms": int((processed_at - started_at).total_seconds() * 1000),
    }
    return _insert_callback(postgres_dsn, record, write_db=True)


def escalate_route_approval_timeouts(
    postgres_dsn: str,
    *,
    limit: int = 100,
    now: datetime | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    observed_now = now or datetime.now(timezone.utc)
    commands = _fetch_pending_commands(postgres_dsn, limit=limit)
    escalations: list[dict[str, Any]] = []
    for command in commands:
        policy = _fetch_matching_policy(postgres_dsn, command)
        timeout = evaluate_approval_timeout(command, now=observed_now, policy=policy)
        if not timeout["overdue"]:
            continue
        escalation = _build_timeout_escalation(command, policy, timeout)
        if write_db:
            escalation = _insert_escalation_record(postgres_dsn, escalation)
        escalations.append(normalize_rows([escalation])[0])
    return {
        "status": "warning" if escalations else "healthy",
        "checked_count": len(commands),
        "escalation_count": len(escalations),
        "escalations": escalations,
    }


def cancel_route_incident_approval(
    postgres_dsn: str,
    *,
    requested_by: str,
    reason: str,
    control_code: str | None = None,
    approval_code: str | None = None,
) -> dict[str, Any]:
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if not reason:
        raise QDataValidationError("reason is required")
    if bool(control_code) == bool(approval_code):
        raise QDataValidationError("exactly one of control_code or approval_code is required")
    target = _fetch_target_context(postgres_dsn, control_code=control_code, approval_code=approval_code, batch_code=None)
    if not target:
        raise QDataValidationError("approval target not found")
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.automation_approval
                SET status = 'cancelled',
                    decided_by = %s,
                    decision_reason = %s,
                    decided_at = now(),
                    updated_at = now()
                WHERE approval_id = %s
                  AND status = 'pending'
                """,
                (requested_by, reason, target.get("approval_id")),
            )
            cursor.execute(
                """
                UPDATE qmeta.source_route_incident_control
                SET approval_status = 'cancelled',
                    control_stage = 'blocked',
                    details = COALESCE(details, '{}'::jsonb) || %s::jsonb,
                    updated_at = now()
                WHERE control_id = %s
                  AND approval_status = 'pending'
                """,
                (
                    _json({"delta6_cancel": {"requested_by": requested_by, "reason": reason}}),
                    target.get("control_id"),
                ),
            )
    escalation = _insert_escalation_record(
        postgres_dsn,
        {
            "escalation_code": _escalation_code("cancel_requested", control_code=str(target.get("control_code") or "")),
            "callback_id": None,
            "command_id": None,
            "command_code": None,
            "control_code": target.get("control_code"),
            "approval_code": target.get("approval_code"),
            "reason_code": "cancel_requested",
            "status": "resolved",
            "severity": "medium",
            "owner_principal_code": requested_by,
            "due_at": None,
            "evidence": {"target": target, "requested_by": requested_by, "reason": reason},
            "error_message": None,
        },
    )
    return {"status": "cancelled", "target": normalize_rows([target])[0], "escalation": escalation}


def list_route_incident_approval_role_bindings(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("binding_code", "b.binding_code"),
            ("principal_code", "b.principal_code"),
            ("role_code", "b.role_code"),
            ("dataset_code", "b.dataset_code"),
            ("source_code", "b.source_code"),
            ("safety_level", "b.safety_level"),
            ("status", "b.status"),
            ("created_by", "b.created_by"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "b.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            b.binding_id, b.binding_code, b.principal_code, b.role_code,
            b.dataset_code, b.source_code, b.safety_level, b.status,
            b.effective_at, b.expires_at, b.created_by, b.revoked_by,
            b.revoked_at, b.details, b.created_at, b.updated_at
        FROM qmeta.source_route_incident_approval_role_binding b
        {where}
        ORDER BY b.updated_at DESC, b.binding_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_policies(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("policy_code", "p.policy_code"),
            ("dataset_code", "p.dataset_code"),
            ("source_code", "p.source_code"),
            ("safety_level", "p.safety_level"),
            ("status", "p.status"),
            ("created_by", "p.created_by"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            p.policy_id, p.policy_code, p.dataset_code, p.source_code,
            p.safety_level, p.status, p.min_approvals,
            p.require_distinct_requester, p.require_risk_admin_for_high,
            p.require_wecom_signature, p.timeout_minutes,
            p.replay_window_minutes, p.max_clock_skew_seconds,
            p.escalation_principal_code, p.created_by, p.details,
            p.created_at, p.updated_at
        FROM qmeta.source_route_incident_approval_policy p
        {where}
        ORDER BY p.updated_at DESC, p.policy_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_callbacks(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("callback_code", "c.callback_code"),
            ("provider_code", "c.provider_code"),
            ("signature_status", "c.signature_status"),
            ("governance_status", "c.governance_status"),
            ("policy_code", "c.policy_code"),
            ("binding_code", "c.binding_code"),
            ("command_code", "c.command_code"),
            ("control_code", "c.control_code"),
            ("approval_code", "c.approval_code"),
            ("batch_code", "c.batch_code"),
            ("decision", "c.decision"),
            ("requested_by", "c.requested_by"),
            ("signer_code", "c.signer_code"),
            ("idempotency_key", "c.idempotency_key"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "c.received_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            c.callback_id, c.callback_code, c.provider_code, c.nonce,
            c.timestamp_seconds, c.request_hash, c.signature_digest,
            c.signature_status, c.governance_status, c.policy_code,
            c.binding_code, c.command_code, c.idempotency_key,
            c.control_code, c.approval_code, c.batch_code, c.decision,
            c.requested_by, c.signer_code, c.required_approvals,
            c.replay_count, c.received_at, c.processed_at, c.duration_ms,
            c.raw_payload_redacted, c.response_payload, c.evidence,
            c.error_message, c.created_at, c.updated_at
        FROM qmeta.source_route_incident_approval_callback c
        {where}
        ORDER BY c.received_at DESC, c.callback_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_route_incident_approval_escalations(
    postgres_dsn: str | None,
    params: dict[str, list[str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("escalation_code", "e.escalation_code"),
            ("command_code", "e.command_code"),
            ("control_code", "e.control_code"),
            ("approval_code", "e.approval_code"),
            ("reason_code", "e.reason_code"),
            ("status", "e.status"),
            ("severity", "e.severity"),
            ("owner_principal_code", "e.owner_principal_code"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "e.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            e.escalation_id, e.escalation_code, cb.callback_code,
            e.command_code, e.control_code, e.approval_code,
            e.reason_code, e.status, e.severity, e.owner_principal_code,
            e.due_at, e.acknowledged_by, e.acknowledged_at,
            e.resolved_by, e.resolved_at, e.evidence,
            e.error_message, e.created_at, e.updated_at
        FROM qmeta.source_route_incident_approval_escalation e
        LEFT JOIN qmeta.source_route_incident_approval_callback cb ON cb.callback_id = e.callback_id
        {where}
        ORDER BY e.created_at DESC, e.escalation_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_delta6_report(payload: dict[str, Any]) -> str:
    return (
        "delta6_route_incident_approval_governance "
        f"status={payload.get('governance_status') or payload.get('status')} "
        f"callback_code={payload.get('callback_code')} "
        f"signature={payload.get('signature_status')} "
        f"decision={payload.get('decision')} "
        f"signer={payload.get('signer_code')} "
        f"command_code={payload.get('command_code')} "
        f"replay_count={payload.get('replay_count')}"
    )


def format_delta6_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"delta6 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _fetch_target_context(
    postgres_dsn: str,
    *,
    control_code: str | None,
    approval_code: str | None,
    batch_code: str | None,
) -> dict[str, Any] | None:
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


def _fetch_matching_policy(postgres_dsn: str, target: dict[str, Any]) -> dict[str, Any]:
    dataset_code = str(target.get("dataset_code") or "*")
    source_code = str(target.get("source_code") or "*")
    safety_level = str(target.get("safety_level") or "*")
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT *
        FROM qmeta.source_route_incident_approval_policy
        WHERE status = 'active'
          AND dataset_code IN (%s, '*')
          AND source_code IN (%s, '*')
          AND safety_level IN (%s, '*')
        ORDER BY
          ((dataset_code <> '*')::int + (source_code <> '*')::int + (safety_level <> '*')::int) DESC,
          updated_at DESC,
          policy_id DESC
        LIMIT 1
        """,
        [dataset_code, source_code, safety_level],
    )
    if rows:
        return rows[0]
    return {
        "policy_code": DEFAULT_POLICY_CODE,
        "min_approvals": 2,
        "require_distinct_requester": True,
        "require_risk_admin_for_high": False,
        "require_wecom_signature": True,
        "timeout_minutes": 240,
        "replay_window_minutes": 1440,
        "max_clock_skew_seconds": 300,
        "escalation_principal_code": "platform-ops",
    }


def _fetch_active_role_bindings(postgres_dsn: str, principal_code: str) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        SELECT *
        FROM qmeta.source_route_incident_approval_role_binding
        WHERE principal_code = %s
          AND status = 'active'
          AND effective_at <= now()
          AND (expires_at IS NULL OR expires_at > now())
        ORDER BY updated_at DESC, binding_id DESC
        """,
        [principal_code],
    )


def _fetch_callback_replay(postgres_dsn: str, *, provider_code: str, nonce: str) -> dict[str, Any] | None:
    rows = _fetch_rows(
        postgres_dsn,
        """
        SELECT *
        FROM qmeta.source_route_incident_approval_callback
        WHERE provider_code = %s
          AND nonce = %s
        LIMIT 1
        """,
        [provider_code, nonce],
    )
    return rows[0] if rows else None


def _mark_callback_replay(postgres_dsn: str, callback: dict[str, Any]) -> dict[str, Any]:
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.source_route_incident_approval_callback
                SET replay_count = replay_count + 1,
                    updated_at = now()
                WHERE callback_id = %s
                RETURNING *
                """,
                (callback["callback_id"],),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _insert_callback(postgres_dsn: str, callback: dict[str, Any], *, write_db: bool) -> dict[str, Any]:
    processed_at = callback.get("processed_at") or datetime.now(timezone.utc)
    received_at = callback.get("received_at") or datetime.now(timezone.utc)
    duration_ms = callback.get("duration_ms")
    if duration_ms is None:
        duration_ms = int((processed_at - received_at).total_seconds() * 1000) if isinstance(processed_at, datetime) and isinstance(received_at, datetime) else 0
    prepared = {
        **callback,
        "received_at": received_at,
        "processed_at": processed_at,
        "duration_ms": duration_ms,
    }
    if not write_db:
        return normalize_rows([prepared])[0]
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_callback (
                    callback_code, provider_code, nonce, timestamp_seconds,
                    request_hash, signature_digest, signature_status,
                    governance_status, policy_id, policy_code, binding_id,
                    binding_code, command_id, command_code, idempotency_key,
                    control_code, approval_code, batch_code, decision,
                    requested_by, signer_code, required_approvals, received_at,
                    processed_at, duration_ms, raw_payload_redacted,
                    response_payload, evidence, error_message, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s, now()
                )
                RETURNING *
                """,
                (
                    prepared["callback_code"],
                    prepared["provider_code"],
                    prepared["nonce"],
                    prepared["timestamp_seconds"],
                    prepared["request_hash"],
                    prepared.get("signature_digest"),
                    prepared["signature_status"],
                    prepared["governance_status"],
                    prepared.get("policy_id"),
                    prepared.get("policy_code"),
                    prepared.get("binding_id"),
                    prepared.get("binding_code"),
                    prepared.get("command_id"),
                    prepared.get("command_code"),
                    prepared.get("idempotency_key"),
                    prepared.get("control_code"),
                    prepared.get("approval_code"),
                    prepared.get("batch_code"),
                    prepared.get("decision"),
                    prepared.get("requested_by"),
                    prepared.get("signer_code"),
                    prepared.get("required_approvals", 1),
                    prepared.get("received_at"),
                    prepared.get("processed_at"),
                    prepared.get("duration_ms"),
                    _json(prepared.get("raw_payload_redacted") or {}),
                    _json(prepared.get("response_payload") or {}),
                    _json(prepared.get("evidence") or {}),
                    prepared.get("error_message"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _insert_escalation(
    postgres_dsn: str,
    *,
    reason_code: str,
    severity: str,
    owner_principal_code: str,
    callback: dict[str, Any] | None,
    command: dict[str, Any] | None,
    evidence: dict[str, Any],
    error_message: str | None,
    status: str = "open",
) -> dict[str, Any]:
    record = {
        "escalation_code": _escalation_code(
            reason_code,
            callback_code=callback.get("callback_code") if callback else None,
            command_code=command.get("command_code") if command else None,
            control_code=(callback or command or {}).get("control_code"),
        ),
        "callback_id": callback.get("callback_id") if callback else None,
        "command_id": command.get("command_id") if command else None,
        "command_code": (callback or command or {}).get("command_code"),
        "control_code": (callback or command or {}).get("control_code"),
        "approval_code": (callback or command or {}).get("approval_code"),
        "reason_code": reason_code,
        "status": status,
        "severity": severity,
        "owner_principal_code": owner_principal_code,
        "due_at": None,
        "evidence": evidence,
        "error_message": error_message,
    }
    return _insert_escalation_record(postgres_dsn, record)


def _insert_escalation_record(postgres_dsn: str, escalation: dict[str, Any]) -> dict[str, Any]:
    with _connect(_require_dsn(postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_incident_approval_escalation (
                    escalation_code, callback_id, command_id, command_code,
                    control_code, approval_code, reason_code, status, severity,
                    owner_principal_code, due_at, evidence, error_message, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s, now()
                )
                ON CONFLICT (escalation_code) DO UPDATE SET
                    callback_id = COALESCE(EXCLUDED.callback_id, qmeta.source_route_incident_approval_escalation.callback_id),
                    command_id = COALESCE(EXCLUDED.command_id, qmeta.source_route_incident_approval_escalation.command_id),
                    status = CASE
                        WHEN qmeta.source_route_incident_approval_escalation.status = 'resolved' THEN 'resolved'
                        ELSE EXCLUDED.status
                    END,
                    severity = EXCLUDED.severity,
                    owner_principal_code = EXCLUDED.owner_principal_code,
                    evidence = qmeta.source_route_incident_approval_escalation.evidence || EXCLUDED.evidence,
                    error_message = COALESCE(EXCLUDED.error_message, qmeta.source_route_incident_approval_escalation.error_message),
                    updated_at = now()
                RETURNING *
                """,
                (
                    escalation["escalation_code"],
                    escalation.get("callback_id"),
                    escalation.get("command_id"),
                    escalation.get("command_code"),
                    escalation.get("control_code"),
                    escalation.get("approval_code"),
                    escalation["reason_code"],
                    escalation.get("status", "open"),
                    escalation.get("severity", "high"),
                    escalation.get("owner_principal_code", "platform-ops"),
                    escalation.get("due_at"),
                    _json(escalation.get("evidence") or {}),
                    escalation.get("error_message"),
                ),
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def _fetch_pending_commands(postgres_dsn: str, *, limit: int) -> list[dict[str, Any]]:
    return _fetch_rows(
        postgres_dsn,
        """
        SELECT
            c.command_id, c.command_code, c.control_code, c.approval_code,
            c.batch_code, c.status, c.decision, c.requested_by,
            c.principal_code, c.required_approvals, c.approval_count,
            c.quorum_status, c.started_at, c.command_issues,
            i.dataset_code, i.source_code, i.safety_level
        FROM qmeta.source_route_incident_approval_command c
        LEFT JOIN LATERAL (
            SELECT dataset_code, source_code, safety_level
            FROM qmeta.source_route_incident_approval_command_item
            WHERE command_id = c.command_id
            ORDER BY item_id
            LIMIT 1
        ) i ON TRUE
        WHERE c.status = 'pending_quorum'
        ORDER BY c.started_at ASC, c.command_id ASC
        LIMIT %s
        """,
        [limit],
    )


def _build_timeout_escalation(command: dict[str, Any], policy: dict[str, Any], timeout: dict[str, Any]) -> dict[str, Any]:
    return {
        "escalation_code": _escalation_code("approval_timeout", command_code=str(command.get("command_code"))),
        "callback_id": None,
        "command_id": command.get("command_id"),
        "command_code": command.get("command_code"),
        "control_code": command.get("control_code"),
        "approval_code": command.get("approval_code"),
        "reason_code": "approval_timeout",
        "status": "open",
        "severity": "high",
        "owner_principal_code": policy.get("escalation_principal_code") or "platform-ops",
        "due_at": timeout.get("due_at"),
        "evidence": {"command": command, "policy": _policy_summary(policy), "timeout": timeout},
        "error_message": "route incident approval quorum exceeded timeout",
    }


def _validate_callback_selector(
    *,
    decision: str,
    signer_code: str,
    control_code: str | None,
    approval_code: str | None,
    batch_code: str | None,
) -> None:
    if decision not in APPROVAL_DECISIONS:
        raise QDataValidationError("decision must be one of: approve, reject, hold")
    if not signer_code:
        raise QDataValidationError("signer_code is required")
    selectors = [bool(control_code), bool(approval_code), bool(batch_code)]
    if sum(selectors) != 1:
        raise QDataValidationError("exactly one of control_code, approval_code or batch_code is required")


def _binding_matches_target(binding: dict[str, Any], target: dict[str, Any]) -> bool:
    if binding.get("status", "active") != "active":
        return False
    return (
        _scope_matches(binding.get("dataset_code"), target.get("dataset_code"))
        and _scope_matches(binding.get("source_code"), target.get("source_code"))
        and _scope_matches(binding.get("safety_level"), target.get("safety_level"))
    )


def _binding_specificity(binding: dict[str, Any]) -> int:
    return sum(1 for key in ("dataset_code", "source_code", "safety_level") if str(binding.get(key) or "*") != "*")


def _scope_matches(scope: Any, value: Any) -> bool:
    scope_text = str(scope or "*")
    return scope_text == "*" or scope_text == str(value or "")


def _rbac_denied(reason_code: str, error_message: str, *, target: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed": False,
        "reason_code": reason_code,
        "error_message": error_message,
        "issues": [reason_code],
        "evidence": {
            "dataset_code": target.get("dataset_code"),
            "source_code": target.get("source_code"),
            "safety_level": target.get("safety_level"),
        },
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
        raise QDataValidationError("psycopg is required for Delta-6 route incident approval governance") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _canonical_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _header_or_payload(headers: dict[str, str], payload: dict[str, Any], name: str) -> str | None:
    aliases = {
        "timestamp": ["x-qdata-timestamp", "x-wecom-timestamp", "x-wx-timestamp", "timestamp"],
        "nonce": ["x-qdata-nonce", "x-wecom-nonce", "x-wx-nonce", "nonce"],
        "signature": ["x-qdata-signature", "x-wecom-signature", "x-wx-signature", "msg_signature", "signature"],
    }[name]
    for alias in aliases:
        if headers.get(alias):
            return headers[alias]
    for alias in aliases:
        if payload.get(alias):
            return str(payload[alias])
    return None


def _normalize_signature(signature: str | None) -> str | None:
    if signature is None:
        return None
    text = str(signature).strip()
    if text.lower().startswith("sha256="):
        return text.split("=", 1)[1].strip().lower()
    return text.lower()


def _public_signature_evidence(signature_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "signature_status": signature_result.get("signature_status"),
        "clock_skew_seconds": signature_result.get("clock_skew_seconds"),
        "expected_digest_tail": str(signature_result.get("expected_digest") or "")[-8:],
        "received_digest_tail": str(signature_result.get("received_digest") or "")[-8:],
    }


def _policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_code": policy.get("policy_code"),
        "min_approvals": policy.get("min_approvals"),
        "require_distinct_requester": policy.get("require_distinct_requester"),
        "require_risk_admin_for_high": policy.get("require_risk_admin_for_high"),
        "require_wecom_signature": policy.get("require_wecom_signature"),
        "timeout_minutes": policy.get("timeout_minutes"),
        "escalation_principal_code": policy.get("escalation_principal_code"),
    }


def _governance_status_from_gamma(gamma: dict[str, Any], decision: str) -> str:
    status = str(gamma.get("status") or "")
    if status == "pending_quorum":
        return "pending_quorum"
    if status == "applied" and decision == "hold":
        return "held"
    if status == "applied" and decision == "reject":
        return "rejected"
    if status == "applied":
        return "applied"
    if status == "failed":
        return "failed"
    return "accepted"


def _optional_payload_string(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value in (None, ""):
        return None
    return str(value)


def _int_payload(payload: dict[str, Any], name: str, default: int) -> int:
    value = payload.get(name, default)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise QDataValidationError(f"{name} must be an integer") from exc
    if result < 1 or result > MAX_REQUIRED_APPROVALS:
        raise QDataValidationError(f"{name} must be between 1 and 5")
    return result


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    raise QDataValidationError("started_at must be a datetime")


def _callback_code(provider_code: str, nonce: str, request_hash: str, started_at: datetime) -> str:
    stamp = started_at.strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(f"{provider_code}:{nonce}:{request_hash}:{stamp}".encode("utf-8")).hexdigest()[:12]
    return f"delta6-callback-{digest}"[:180]


def _escalation_code(
    reason_code: str,
    *,
    callback_code: str | None = None,
    command_code: str | None = None,
    control_code: str | None = None,
) -> str:
    seed = f"{reason_code}:{callback_code or ''}:{command_code or ''}:{control_code or ''}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"delta6-escalation-{digest}"[:180]


def _role_binding_code(principal_code: str, role_code: str, dataset_code: str, source_code: str, safety_level: str) -> str:
    digest = hashlib.sha1(f"{principal_code}:{role_code}:{dataset_code}:{source_code}:{safety_level}".encode("utf-8")).hexdigest()[:12]
    return f"delta6-role-{digest}"[:180]


def _nonce_from_hash(request_hash: str) -> str:
    return f"auto-{request_hash[:24]}"


def _bounded_key(value: str) -> str:
    if len(value) <= 220:
        return value
    return f"delta6-key-{hashlib.sha1(value.encode('utf-8')).hexdigest()}"


def _param(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = params.get(name)
    if not values:
        return default
    return values[-1]


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "role_bindings": [
            "binding_code",
            "principal_code",
            "role_code",
            "dataset_code",
            "source_code",
            "safety_level",
            "status",
            "effective_at",
            "expires_at",
        ],
        "policies": [
            "policy_code",
            "dataset_code",
            "source_code",
            "safety_level",
            "status",
            "min_approvals",
            "require_distinct_requester",
            "require_risk_admin_for_high",
            "require_wecom_signature",
            "timeout_minutes",
        ],
        "callbacks": [
            "received_at",
            "callback_code",
            "provider_code",
            "signature_status",
            "governance_status",
            "decision",
            "signer_code",
            "control_code",
            "command_code",
            "required_approvals",
            "replay_count",
            "error_message",
        ],
        "escalations": [
            "created_at",
            "escalation_code",
            "reason_code",
            "status",
            "severity",
            "owner_principal_code",
            "command_code",
            "control_code",
            "approval_code",
            "error_message",
        ],
    }
    preferred = preferred_by_resource.get(resource, preferred_by_resource["callbacks"])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _require_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Delta-6 route incident approval governance")
    return postgres_dsn
