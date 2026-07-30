from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from qdata.backend_utils import date_range, normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omega_control import _redact_value


TRIGGER_MODES = {"manual", "scheduled", "api", "smoke", "demo"}
MESSAGE_TYPES = {"text", "markdown"}
RECEIPT_STATUSES = {"planned", "success", "failed", "blocked", "skipped"}
DEFAULT_PROFILE_CODE = "delta2-wecom-live-profile"
DEFAULT_SECRET_REF = "delta2-wecom-webhook-url"
PAYLOAD_LIMIT = 4000
MAX_WECOM_MARKDOWN_CHARS = 4096


def run_delta2_wecom_live_validation(
    postgres_dsn: str,
    *,
    profile_code: str = DEFAULT_PROFILE_CODE,
    requested_by: str = "delta2",
    title: str = "QData Delta-2 企业微信 live validation",
    message: str = "企业微信 live validation smoke",
    action_code: str | None = None,
    trigger_mode: str = "manual",
    message_type: str = "markdown",
    allow_external: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if not profile_code:
        raise QDataValidationError("profile_code is required")
    if not requested_by:
        raise QDataValidationError("requested_by is required")
    if trigger_mode not in TRIGGER_MODES:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, api, smoke, demo")
    if message_type not in MESSAGE_TYPES:
        raise QDataValidationError("message_type must be one of: text, markdown")
    started_at = datetime.now(timezone.utc)
    profile = _get_profile(postgres_dsn, profile_code)
    _validate_wecom_profile(profile)
    secret = _get_secret_ref(postgres_dsn, profile.get("secret_ref") or DEFAULT_SECRET_REF)
    endpoint = _endpoint_from_secret(secret)
    request_payload = build_wecom_message_payload(
        title=title,
        message=message,
        profile=profile,
        action_code=action_code,
        message_type=message_type,
    )

    status = "blocked"
    provider_status_code: int | None = None
    provider_errcode: int | None = None
    provider_errmsg: str | None = None
    response_payload: dict[str, Any] = {"external_side_effect": False}
    error_message: str | None = None
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None

    blocked_reason = _blocked_reason(
        profile=profile,
        endpoint=endpoint,
        allow_external=allow_external,
    )
    if blocked_reason:
        error_message = blocked_reason
        response_payload = {"blocked_by": blocked_reason, "external_side_effect": False}
    else:
        sent_at = datetime.now(timezone.utc)
        provider_status_code, provider_errcode, provider_errmsg, response_payload, error_message = _send_wecom_webhook(
            str(endpoint),
            request_payload,
            timeout_seconds=int(profile.get("timeout_seconds") or 10),
        )
        if provider_status_code and 200 <= provider_status_code < 300 and provider_errcode == 0:
            status = "success"
            acknowledged_at = datetime.now(timezone.utc)
            error_message = None
        else:
            status = "failed"

    return _insert_validation_and_receipt(
        postgres_dsn,
        profile=profile,
        requested_by=requested_by,
        trigger_mode=trigger_mode,
        status=status,
        message_type=message_type,
        endpoint_secret_ref=secret["secret_ref"],
        request_payload=request_payload,
        response_payload=response_payload,
        error_message=error_message,
        provider_status_code=provider_status_code,
        provider_errcode=provider_errcode,
        provider_errmsg=provider_errmsg,
        started_at=started_at,
        sent_at=sent_at,
        acknowledged_at=acknowledged_at,
        force=force,
    )


def build_wecom_message_payload(
    *,
    title: str,
    message: str,
    profile: dict[str, Any],
    action_code: str | None = None,
    message_type: str = "markdown",
) -> dict[str, Any]:
    if message_type not in MESSAGE_TYPES:
        raise QDataValidationError("message_type must be one of: text, markdown")
    content = _wecom_content(title=title, message=message, profile=profile, action_code=action_code)
    if message_type == "text":
        return {"msgtype": "text", "text": {"content": content}}
    return {"msgtype": "markdown", "markdown": {"content": content}}


def list_automation_live_receipts(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("receipt_code", "lr.receipt_code"),
            ("validation_code", "v.validation_code"),
            ("profile_code", "p.profile_code"),
            ("channel_code", "ch.channel_code"),
            ("provider_code", "lr.provider_code"),
            ("environment", "lr.environment"),
            ("message_type", "lr.message_type"),
            ("status", "lr.status"),
            ("requested_by", "lr.requested_by"),
            ("endpoint_secret_ref", "lr.endpoint_secret_ref"),
            ("provider_errcode", "lr.provider_errcode"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "lr.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            lr.receipt_id, lr.receipt_code, v.validation_code,
            p.profile_code, ch.channel_code, lr.provider_code, lr.environment,
            lr.message_type, lr.status, lr.requested_by,
            lr.endpoint_secret_ref, lr.provider_status_code,
            lr.provider_errcode, lr.provider_errmsg, lr.request_payload,
            lr.response_payload, lr.evidence, lr.error_message,
            lr.sent_at, lr.acknowledged_at, lr.created_at, lr.updated_at
        FROM qmeta.automation_live_provider_receipt lr
        LEFT JOIN qmeta.automation_channel_validation v ON v.validation_id = lr.validation_id
        LEFT JOIN qmeta.automation_channel_profile p ON p.profile_id = lr.profile_id
        LEFT JOIN qmeta.automation_external_channel ch ON ch.channel_id = lr.channel_id
        {where}
        ORDER BY lr.created_at DESC, lr.receipt_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_delta2_rows(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"delta2 resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _send_wecom_webhook(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int,
) -> tuple[int | None, int | None, str | None, dict[str, Any], str | None]:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(1, timeout_seconds)) as response:
            raw_body = response.read(PAYLOAD_LIMIT)
            status_code = int(response.status)
    except HTTPError as exc:
        raw_body = exc.read(PAYLOAD_LIMIT)
        status_code = int(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        return None, None, None, {"external_side_effect": True, "transport_error": str(exc)}, str(exc)

    text = _safe_decode(raw_body)
    parsed = _parse_json(text)
    errcode = _int_or_none(parsed.get("errcode")) if parsed else None
    errmsg = str(parsed.get("errmsg")) if parsed and parsed.get("errmsg") is not None else None
    response_payload = {
        "external_side_effect": True,
        "provider": "wecom",
        "status_code": status_code,
        "errcode": errcode,
        "errmsg": errmsg,
        "body": text[:PAYLOAD_LIMIT],
        "body_sha256": hashlib.sha256(raw_body).hexdigest()[:12],
    }
    if not (200 <= status_code < 300):
        return status_code, errcode, errmsg, response_payload, f"wecom http {status_code}"
    if errcode != 0:
        return status_code, errcode, errmsg, response_payload, f"wecom errcode {errcode}"
    return status_code, errcode, errmsg, response_payload, None


def _insert_validation_and_receipt(
    postgres_dsn: str,
    *,
    profile: dict[str, Any],
    requested_by: str,
    trigger_mode: str,
    status: str,
    message_type: str,
    endpoint_secret_ref: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    error_message: str | None,
    provider_status_code: int | None,
    provider_errcode: int | None,
    provider_errmsg: str | None,
    started_at: datetime,
    sent_at: datetime | None,
    acknowledged_at: datetime | None,
    force: bool,
) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc)
    validation_code = _code("delta2-wecom-validation", profile.get("profile_code"), status)
    receipt_code = _code("delta2-wecom-receipt", profile.get("profile_code"), status)
    readiness_status = "live_ready" if status == "success" else status if status in {"blocked", "failed"} else str(profile.get("readiness_status") or "not_configured")
    evidence = {
        "provider_code": "wecom",
        "environment": profile.get("environment"),
        "profile_code": profile.get("profile_code"),
        "channel_code": profile.get("channel_code"),
        "endpoint_secret_ref": endpoint_secret_ref,
        "endpoint_env_var": _endpoint_env_name(endpoint_secret_ref),
        "provider_status_code": provider_status_code,
        "provider_errcode": provider_errcode,
        "provider_errmsg": provider_errmsg,
        "external_side_effect": bool(sent_at),
        "force": force,
    }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.automation_channel_validation (
                    validation_code, profile_id, channel_id, dispatch_id,
                    validation_type, trigger_mode, status, requested_by,
                    target_secret_ref, request_payload, response_payload,
                    error_message, started_at, finished_at, duration_ms,
                    evidence, details, updated_at
                ) VALUES (
                    %s, %s, %s, NULL,
                    'live_dispatch', %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, now()
                )
                RETURNING *
                """,
                (
                    validation_code,
                    profile["profile_id"],
                    profile["channel_id"],
                    trigger_mode,
                    status,
                    requested_by,
                    endpoint_secret_ref,
                    _json(_redact_value("request_payload", request_payload)),
                    _json(_redact_value("response_payload", response_payload)),
                    error_message,
                    started_at,
                    finished_at,
                    _duration_ms(started_at, finished_at),
                    _json(_redact_value("evidence", evidence)),
                    _json({"source": "delta2"}),
                ),
            )
            validation = dict(cursor.fetchone())
            cursor.execute(
                """
                INSERT INTO qmeta.automation_live_provider_receipt (
                    receipt_code, validation_id, profile_id, channel_id,
                    provider_code, environment, message_type, status,
                    requested_by, endpoint_secret_ref, provider_status_code,
                    provider_errcode, provider_errmsg, request_payload,
                    response_payload, evidence, error_message,
                    sent_at, acknowledged_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    'wecom', %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s,
                    %s, %s, now()
                )
                RETURNING *
                """,
                (
                    receipt_code,
                    validation["validation_id"],
                    profile["profile_id"],
                    profile["channel_id"],
                    profile.get("environment"),
                    message_type,
                    status,
                    requested_by,
                    endpoint_secret_ref,
                    provider_status_code,
                    provider_errcode,
                    provider_errmsg,
                    _json(_redact_value("request_payload", request_payload)),
                    _json(_redact_value("response_payload", response_payload)),
                    _json(_redact_value("evidence", evidence)),
                    error_message,
                    sent_at,
                    acknowledged_at,
                ),
            )
            receipt = dict(cursor.fetchone())
            cursor.execute(
                """
                UPDATE qmeta.automation_channel_profile
                SET readiness_status = %s,
                    last_validation_code = %s,
                    last_validation_status = %s,
                    last_validated_at = %s,
                    updated_at = now()
                WHERE profile_id = %s
                """,
                (readiness_status, validation_code, status, finished_at, profile["profile_id"]),
            )
            receipt.update(
                {
                    "validation_code": validation_code,
                    "profile_code": profile.get("profile_code"),
                    "channel_code": profile.get("channel_code"),
                    "readiness_status": readiness_status,
                }
            )
            return normalize_rows([_redact_row(receipt)])[0]


def _validate_wecom_profile(profile: dict[str, Any]) -> None:
    if profile.get("provider_code") != "wecom":
        raise QDataValidationError("Delta-2 live validation requires provider_code=wecom")
    if profile.get("profile_status") != "active":
        raise QDataValidationError("profile must be active")
    if profile.get("channel_status") != "active":
        raise QDataValidationError("channel must be active")


def _blocked_reason(*, profile: dict[str, Any], endpoint: str | None, allow_external: bool) -> str | None:
    if profile.get("dry_run_only"):
        return "profile_dry_run_only"
    if not allow_external:
        return "external_live_dispatch_disabled"
    if not endpoint:
        return "missing_wecom_webhook_env"
    if not _valid_wecom_webhook_url(endpoint):
        return "invalid_wecom_webhook_url"
    return None


def _get_profile(postgres_dsn: str, profile_code: str) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    p.*, ch.channel_code, ch.channel_type,
                    ch.status AS channel_status, ch.timeout_seconds
                FROM qmeta.automation_channel_profile p
                JOIN qmeta.automation_external_channel ch ON ch.channel_id = p.channel_id
                WHERE p.profile_code = %s
                """,
                (profile_code,),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"unknown profile_code: {profile_code}")
            return dict(row)


def _get_secret_ref(postgres_dsn: str, secret_ref: str) -> dict[str, Any]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM qmeta.automation_secret_ref WHERE secret_ref = %s AND status = 'active'",
                (secret_ref,),
            )
            row = cursor.fetchone()
            if not row:
                raise QDataValidationError(f"unknown active secret_ref: {secret_ref}")
            return dict(row)


def _endpoint_from_secret(secret: dict[str, Any]) -> str | None:
    metadata = secret.get("metadata") or {}
    env_var = metadata.get("env_var")
    return os.getenv(str(env_var)) if env_var else None


def _endpoint_env_name(secret_ref: str | None) -> str | None:
    if secret_ref == DEFAULT_SECRET_REF:
        return "QDATA_DELTA2_WECOM_WEBHOOK_URL"
    return None


def _valid_wecom_webhook_url(value: str) -> bool:
    return value.startswith("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?") and "key=" in value


def _wecom_content(*, title: str, message: str, profile: dict[str, Any], action_code: str | None) -> str:
    lines = [
        f"**{_clean_line(title)}**",
        f"> profile: `{profile.get('profile_code')}`",
        f"> environment: `{profile.get('environment')}`",
    ]
    if action_code:
        lines.append(f"> action: `{_clean_line(action_code)}`")
    lines.extend(
        [
            "",
            _clean_message(message),
            "",
            '<font color="comment">QData Delta-2 live validation. 请确认企业微信群已收到这条测试消息。</font>',
        ]
    )
    content = "\n".join(lines)
    return content[:MAX_WECOM_MARKDOWN_CHARS]


def _clean_line(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", str(value)).strip()


def _clean_message(value: str) -> str:
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()[:MAX_WECOM_MARKDOWN_CHARS]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([_redact_row(dict(row)) for row in cursor.fetchall()])


def _redact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(key, value) for key, value in row.items()}


def _where_equal(params: dict[str, list[str]], fields: list[tuple[str, str]]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for param_name, column_name in fields:
        value = _param(params, param_name)
        if value in (None, ""):
            continue
        clauses.append(f"{column_name} = %s")
        values.append(_int_or_none(value) if param_name == "provider_errcode" else value)
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


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred_by_resource = {
        "receipts": [
            "receipt_code",
            "validation_code",
            "profile_code",
            "channel_code",
            "provider_code",
            "environment",
            "message_type",
            "status",
            "provider_status_code",
            "provider_errcode",
            "provider_errmsg",
            "error_message",
        ]
    }
    preferred = preferred_by_resource.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _code(prefix: str, *parts: object) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha1(":".join(str(part) for part in (*parts, stamp)).encode("utf-8")).hexdigest()[:10]
    body = "-".join(_slug(str(part)) for part in parts if part not in (None, ""))
    return f"{prefix}-{body}-{digest}"[:180]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value)).strip("-").lower() or "unknown"


def _duration_ms(started_at: datetime, finished_at: datetime | None = None) -> int:
    finished = finished_at or datetime.now(timezone.utc)
    return int((finished - started_at).total_seconds() * 1000)


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _parse_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        raise QDataValidationError("psycopg is required for Delta-2 WeCom live validation") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Delta-2 WeCom live validation")
    return _connect(postgres_dsn)
