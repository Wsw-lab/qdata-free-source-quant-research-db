from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4

from qdata import Client
from qdata.api.audit import write_api_audit
from qdata.api.auth import AuthError, TokenAuth, TokenIdentity
from qdata.api.formatters import format_response, to_json_bytes
from qdata.backend_utils import response
from qdata.epsilon6_route_incident_approval_resilience import submit_resilient_wecom_route_approval_callback
from qdata.exceptions import QDataNotFoundError, QDataValidationError
from qdata.gamma6_route_incident_approval_api import submit_route_incident_approval_command
from qdata.iota import DATASET_SCOPE_BY_ENDPOINT, authorize_dataset_access
from qdata.kappa import KappaResult, dispatch_kappa_endpoint, is_kappa_path
from qdata.phi5_route_policy import (
    finalize_route_decision,
    resolve_source_route,
    route_meta,
    write_source_route_decision_audit,
)
from qdata.xi_billing import check_budget_allowed
from qdata.zeta6_route_incident_approval_release import verify_wecom_callback_signature_rotating


ClientFactory = Callable[[], Client]
KappaFactory = Callable[[str, dict[str, list[str]]], KappaResult]

ADMIN_WRITE_PATHS = {
    "/admin/source-route-incident-approval-commands",
    "/admin/source-route-incident-approval-wecom-callbacks",
}
SIGNED_WECOM_CALLBACK_PATHS = {
    "/webhooks/wecom/source-route-incident-approval-callbacks",
}


def create_handler(
    *,
    postgres_dsn: str | None = None,
    clickhouse_dsn: str | None = None,
    tokens: list[str] | None = None,
    token_scopes: list[str] | None = None,
    default_backend: str = "auto",
    client_factory: ClientFactory | None = None,
    kappa_factory: KappaFactory | None = None,
) -> type[BaseHTTPRequestHandler]:
    auth = TokenAuth.from_env(postgres_dsn=postgres_dsn, tokens=tokens, token_scopes=token_scopes)
    browser_console_token = _first_configured_token(tokens)

    class QDataAPIHandler(BaseHTTPRequestHandler):
        server_version = "QDataAPI/0.1"

        def do_GET(self) -> None:
            self._handle_get()

        def do_POST(self) -> None:
            self._handle_post()

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _handle_get(self) -> None:
            started_at = datetime.now(timezone.utc)
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query, keep_blank_values=False)
            api_name = parsed.path.strip("/") or "root"
            response_format = _param(params, "format", "json")
            request_id = f"req_{uuid4().hex[:12]}"
            identity: TokenIdentity | None = None
            row_count: int | None = None
            audit_status = "failed"
            error_message: str | None = None
            route_summary: dict[str, Any] | None = None
            try:
                if parsed.path in {"", "/"}:
                    location = "/admin/console"
                    if browser_console_token:
                        location = f"{location}?token={quote(browser_console_token)}"
                    row_count = 0
                    audit_status = "success"
                    self._redirect(location)
                    return

                if parsed.path == "/health":
                    payload = {
                        "request_id": request_id,
                        "status": "success",
                        "data": [{"service": "qdata-api", "status": "ok"}],
                        "meta": {"row_count": 1},
                        "errors": [],
                    }
                    body, content_type = format_response(payload, response_format)
                    row_count = 1
                    audit_status = "success"
                    self._send(200, body, content_type)
                    return

                identity = auth.authenticate(_auth_headers(self.headers, parsed.path, params), required_scope=_required_scope(parsed.path))
                self._authorize_dataset(parsed.path, params, identity, request_id)
                self._authorize_budget(api_name, identity)
                if parsed.path == "/admin/console":
                    result = kappa_factory(parsed.path, params) if kappa_factory else dispatch_kappa_endpoint(postgres_dsn, parsed.path, params)
                    html = result.rows[0]["html"] if result.rows else ""
                    row_count = 1
                    audit_status = "success"
                    self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                    return
                payload = self._dispatch(parsed.path, params)
                request_id = payload.get("request_id", request_id)
                row_count = len(payload.get("data", []))
                route_summary = payload.get("meta", {}).get("route_policy")
                body, content_type = format_response(payload, response_format)
                audit_status = payload.get("status", "success")
                self._send(200, body, content_type)
            except AuthError as exc:
                error_message = exc.message
                self._send_error(exc.status_code, request_id, exc.message)
            except QDataNotFoundError as exc:
                error_message = str(exc)
                self._send_error(404, request_id, str(exc))
            except QDataValidationError as exc:
                error_message = str(exc)
                status_code = 503 if "pyarrow is required" in str(exc) else 400
                self._send_error(status_code, request_id, str(exc))
            except Exception as exc:
                error_message = str(exc)
                self._send_error(500, request_id, "internal server error")
            finally:
                finished_at = datetime.now(timezone.utc)
                write_api_audit(
                    postgres_dsn,
                    token_id=identity.token_id if identity else None,
                    tenant_id=identity.tenant_id if identity else None,
                    project_id=identity.project_id if identity else None,
                    principal_id=identity.principal_id if identity else None,
                    api_name=api_name,
                    request_id=request_id,
                    request_summary=_request_summary(parsed.path, params, route_summary),
                    response_format=response_format,
                    status=audit_status,
                    row_count=row_count,
                    error_message=error_message,
                    started_at=started_at,
                    finished_at=finished_at,
                    client_ip=self.client_address[0] if self.client_address else None,
                    user_agent=self.headers.get("User-Agent"),
                )

        def _handle_post(self) -> None:
            started_at = datetime.now(timezone.utc)
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query, keep_blank_values=False)
            api_name = parsed.path.strip("/") or "root"
            response_format = _param(params, "format", "json")
            request_id = f"req_{uuid4().hex[:12]}"
            identity: TokenIdentity | None = None
            row_count: int | None = None
            audit_status = "failed"
            error_message: str | None = None
            try:
                if _is_signed_wecom_callback_path(parsed.path):
                    identity = None
                else:
                    identity = auth.authenticate(_auth_headers(self.headers, parsed.path, params), required_scope=_required_scope(parsed.path))
                    self._authorize_budget(api_name, identity)
                payload = self._dispatch_post(parsed.path, params, identity)
                request_id = payload.get("request_id", request_id)
                row_count = len(payload.get("data", []))
                body, content_type = format_response(payload, response_format)
                audit_status = payload.get("status", "success")
                self._send(200, body, content_type)
            except AuthError as exc:
                error_message = exc.message
                self._send_error(exc.status_code, request_id, exc.message)
            except QDataNotFoundError as exc:
                error_message = str(exc)
                self._send_error(404, request_id, str(exc))
            except QDataValidationError as exc:
                error_message = str(exc)
                self._send_error(400, request_id, str(exc))
            except Exception as exc:
                error_message = str(exc)
                self._send_error(500, request_id, "internal server error")
            finally:
                finished_at = datetime.now(timezone.utc)
                write_api_audit(
                    postgres_dsn,
                    token_id=identity.token_id if identity else None,
                    tenant_id=identity.tenant_id if identity else None,
                    project_id=identity.project_id if identity else None,
                    principal_id=identity.principal_id if identity else None,
                    api_name=api_name,
                    request_id=request_id,
                    request_summary=_request_summary(parsed.path, params, None),
                    response_format=response_format,
                    status=audit_status,
                    row_count=row_count,
                    error_message=error_message,
                    started_at=started_at,
                    finished_at=finished_at,
                    client_ip=self.client_address[0] if self.client_address else None,
                    user_agent=self.headers.get("User-Agent"),
                )

        def _authorize_dataset(self, path: str, params: dict[str, list[str]], identity: TokenIdentity, request_id: str) -> None:
            dataset_code = DATASET_SCOPE_BY_ENDPOINT.get(path.strip("/"))
            if not dataset_code:
                return
            fields = _list_param(params, "fields")
            if path == "/matrix":
                field = _param(params, "field")
                fields = [field] if field else None
            decision = authorize_dataset_access(
                postgres_dsn,
                tenant_id=identity.tenant_id,
                project_id=identity.project_id,
                principal_id=identity.principal_id,
                dataset_code=dataset_code,
                access_level="read",
                fields=fields,
                token_id=identity.token_id,
                api_name=path.strip("/") or "root",
                request_id=request_id,
                write_audit=True,
                audit_details={"path": path},
            )
            if not decision.allowed:
                raise AuthError(403, decision.reason or "dataset access denied")

        def _authorize_budget(self, api_name: str, identity: TokenIdentity) -> None:
            decision = check_budget_allowed(postgres_dsn, identity=identity, api_name=api_name)
            if not decision.allowed:
                raise AuthError(402, decision.reason or "budget hard limit exceeded")

        def _dispatch(self, path: str, params: dict[str, list[str]]) -> dict[str, Any]:
            if is_kappa_path(path):
                result = kappa_factory(path, params) if kappa_factory else dispatch_kappa_endpoint(postgres_dsn, path, params)
                payload = response(result.rows, [f"kappa:{result.resource}"], "latest")
                payload["meta"].update(result.meta)
                return payload
            if path not in {"/price", "/constraints", "/tradable-universe", "/matrix"}:
                raise QDataNotFoundError(f"unknown endpoint: {path}")
            client = client_factory() if client_factory else Client(
                backend=default_backend,
                postgres_dsn=postgres_dsn,
                clickhouse_dsn=clickhouse_dsn,
                default_format="records",
            )
            try:
                route_decision = self._resolve_api_route_decision(path, params)
                route_started_at = datetime.now(timezone.utc)
                if path == "/price":
                    payload = client.get_price(
                        symbols=_list_param(params, "symbols"),
                        security_ids=_int_list_param(params, "security_ids"),
                        universe=_param(params, "universe"),
                        start_date=_required(params, "start_date"),
                        end_date=_required(params, "end_date"),
                        frequency=_param(params, "frequency", "1d"),
                        adjust=_param(params, "adjust", "none"),
                        fields=_list_param(params, "fields"),
                        query_mode=_param(params, "query_mode", "latest"),
                        asof_time=_param(params, "asof_time"),
                        data_version=_param(params, "data_version"),
                        output_format="json",
                    )
                    self._attach_route_policy(payload, route_decision, route_started_at)
                    return payload
                if path == "/constraints":
                    payload = client.get_trading_constraints(
                        symbols=_list_param(params, "symbols"),
                        universe=_param(params, "universe"),
                        start_date=_required(params, "start_date"),
                        end_date=_required(params, "end_date"),
                        fields=_list_param(params, "fields"),
                        output_format="json",
                    )
                    self._attach_route_policy(payload, route_decision, route_started_at)
                    return payload
                if path == "/tradable-universe":
                    payload = client.get_tradable_universe(
                        asof_date=_required(params, "asof_date"),
                        symbols=_list_param(params, "symbols"),
                        universe=_param(params, "universe"),
                        exclude_st=_bool_param(params, "exclude_st", True),
                        exclude_suspended=_bool_param(params, "exclude_suspended", True),
                        exclude_new_listing=_bool_param(params, "exclude_new_listing", True),
                        exclude_delisting_period=_bool_param(params, "exclude_delisting_period", True),
                        min_list_days=int(_param(params, "min_list_days", "30")),
                        output_format="json",
                    )
                    self._attach_route_policy(payload, route_decision, route_started_at)
                    return payload
                price_payload = client.get_price(
                    symbols=_list_param(params, "symbols"),
                    security_ids=_int_list_param(params, "security_ids"),
                    universe=_param(params, "universe"),
                    start_date=_required(params, "start_date"),
                    end_date=_required(params, "end_date"),
                    frequency=_param(params, "frequency", "1d"),
                    adjust=_param(params, "adjust", "none"),
                    fields=[_param(params, "field", "close")],
                    query_mode=_param(params, "query_mode", "latest"),
                    asof_time=_param(params, "asof_time"),
                    data_version=_param(params, "data_version"),
                    output_format="json",
                )
                symbols = _list_param(params, "symbols") or _symbols_from_rows(price_payload["data"])
                field_name = _param(params, "field", "close")
                matrix = _to_matrix(price_payload["data"], symbols, field_name)
                payload = response(matrix, price_payload["meta"].get("data_versions", ["matrix:api"]), "latest")
                self._attach_route_policy(payload, route_decision, route_started_at)
                return payload
            finally:
                close = getattr(client, "close", None)
                if close:
                    close()

        def _dispatch_post(self, path: str, params: dict[str, list[str]], identity: TokenIdentity | None) -> dict[str, Any]:
            if path == "/admin/source-route-incident-approval-commands":
                if identity is None:
                    raise AuthError(401, "missing bearer token")
                body = _read_json_body(self)
                requested_by = str(body.get("requested_by") or identity.owner or identity.token_name or "api")
                principal_code = str(body.get("principal_code") or identity.owner or identity.token_name or requested_by)
                result = submit_route_incident_approval_command(
                    _require_postgres_dsn(postgres_dsn),
                    decision=str(body.get("decision") or ""),
                    requested_by=requested_by,
                    principal_code=principal_code,
                    control_code=_optional_body_string(body, "control_code"),
                    approval_code=_optional_body_string(body, "approval_code"),
                    batch_code=_optional_body_string(body, "batch_code"),
                    idempotency_key=_optional_body_string(body, "idempotency_key") or self.headers.get("Idempotency-Key"),
                    required_approvals=_int_body(body, "required_approvals", 1),
                    trigger_mode=str(body.get("trigger_mode") or "api"),
                    notify_wecom=_bool_body(body, "notify_wecom", False),
                    allow_wecom_external=_bool_body(body, "allow_wecom_external", False),
                )
                payload = response([result], [f"gamma6:{result.get('command_code', 'approval-command')}"], "latest")
                payload["meta"].update({"row_count": 1, "write_operation": "route_incident_approval_command"})
                return payload
            if path in {"/admin/source-route-incident-approval-wecom-callbacks", *SIGNED_WECOM_CALLBACK_PATHS}:
                body, raw_body = _read_json_body_with_raw(self)
                callback_headers = _headers_dict(self.headers)
                current_secret = os.getenv("QDATA_DELTA6_WECOM_CALLBACK_SECRET", "delta6-local-secret")
                next_secret = os.getenv("QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT", "")
                rotation = verify_wecom_callback_signature_rotating(
                    raw_body,
                    callback_headers,
                    payload=body,
                    current_secret=current_secret,
                    next_secret=next_secret,
                    max_clock_skew_seconds=int(os.getenv("QDATA_ZETA6_WECOM_MAX_CLOCK_SKEW_SECONDS", "300")),
                )
                selected_secret = next_secret if rotation.get("verified_secret_label") == "next" and next_secret else current_secret
                result = submit_resilient_wecom_route_approval_callback(
                    _require_postgres_dsn(postgres_dsn),
                    payload=body,
                    headers=callback_headers,
                    secret=selected_secret,
                    raw_body=raw_body,
                    write_db=True,
                )
                result.setdefault("zeta6", {})["secret_rotation"] = rotation
                payload = response([result], [f"epsilon6:{result.get('callback_code') or result.get('lock_event_code') or 'approval-callback'}", "zeta6:secret-rotation"], "latest")
                payload["meta"].update({"row_count": 1, "write_operation": "route_incident_approval_release_wecom_callback"})
                return payload
            else:
                raise QDataNotFoundError(f"unknown endpoint: {path}")

        def _resolve_api_route_decision(self, path: str, params: dict[str, list[str]]) -> dict[str, Any] | None:
            dataset_code = _route_dataset_code(path, params)
            if not dataset_code or not postgres_dsn:
                return None
            try:
                as_of_date = _param(params, "end_date") or _param(params, "asof_date")
                return resolve_source_route(
                    postgres_dsn,
                    dataset_code=dataset_code,
                    requested_source_code=_param(params, "source", "csv") or "csv",
                    as_of_date=as_of_date,
                    request_key=_api_route_request_key(path, params),
                    decision_context="api",
                )
            except Exception:
                return None

        def _attach_route_policy(self, payload: dict[str, Any], route_decision: dict[str, Any] | None, started_at: datetime) -> None:
            if not route_decision:
                return
            finalized = finalize_route_decision(
                route_decision,
                final_source_code=str(route_decision.get("selected_source_code") or route_decision.get("requested_source_code") or "csv"),
                status="success" if payload.get("status") == "success" else "failed",
                attempt_sources=[str(route_decision.get("selected_source_code") or route_decision.get("requested_source_code") or "csv")],
                row_count=len(payload.get("data") or []),
                duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
                error_message=None if payload.get("status") == "success" else "api payload failed",
                details={"api_meta_data_versions": payload.get("meta", {}).get("data_versions") or []},
            )
            finalized["request_id"] = payload.get("request_id")
            write_source_route_decision_audit(postgres_dsn, finalized, started_at=started_at, finished_at=datetime.now(timezone.utc))
            payload.setdefault("meta", {})["route_policy"] = route_meta(finalized)

        def _send_error(self, status_code: int, request_id: str, message: str) -> None:
            payload = {
                "request_id": request_id,
                "status": "failed",
                "data": [],
                "meta": {"row_count": 0},
                "errors": [{"message": message}],
            }
            self._send(status_code, to_json_bytes(payload, status_code), "application/json; charset=utf-8")

        def _send(self, status_code: int, body: bytes, content_type: str) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return QDataAPIHandler


def run_server(
    host: str = "127.0.0.1",
    port: int = 18080,
    *,
    postgres_dsn: str | None = None,
    clickhouse_dsn: str | None = None,
    tokens: list[str] | None = None,
    token_scopes: list[str] | None = None,
    default_backend: str = "auto",
) -> None:
    handler = create_handler(
        postgres_dsn=postgres_dsn,
        clickhouse_dsn=clickhouse_dsn,
        tokens=tokens,
        token_scopes=token_scopes,
        default_backend=default_backend,
    )
    server = ThreadingHTTPServer((host, port), handler)
    try:
        print(f"qdata_api=http://{host}:{port} backend={default_backend}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("qdata_api=stopped", flush=True)
    finally:
        server.server_close()


def _param(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = params.get(name)
    if not values:
        return default
    return values[-1]


def _first_configured_token(tokens: list[str] | None) -> str | None:
    configured = [token for token in (tokens or []) if token]
    if configured:
        return configured[0]
    env_tokens = [item.strip() for item in os.getenv("QDATA_API_TOKENS", "").split(",") if item.strip()]
    return env_tokens[0] if env_tokens else None


def _auth_headers(headers: Any, path: str, params: dict[str, list[str]]) -> Any:
    if path != "/admin/console":
        return headers
    browser_token = _param(params, "token")
    if not browser_token:
        return headers
    if headers.get("Authorization") or headers.get("authorization") or headers.get("X-API-Token") or headers.get("x-api-token"):
        return headers
    merged = {key: value for key, value in headers.items()}
    merged["Authorization"] = f"Bearer {browser_token}"
    return merged


def _redact_query(params: dict[str, list[str]]) -> dict[str, list[str]]:
    sensitive_names = {"token", "api_token", "access_token"}
    redacted: dict[str, list[str]] = {}
    for key, values in params.items():
        if key.lower() in sensitive_names:
            redacted[key] = ["<redacted>"]
        else:
            redacted[key] = values
    return redacted


def _request_summary(path: str, params: dict[str, list[str]], route_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary: dict[str, Any] = {"path": path, "query": _redact_query(params)}
    if route_summary:
        summary["route_policy"] = route_summary
    return summary


def _required(params: dict[str, list[str]], name: str) -> str:
    value = _param(params, name)
    if value is None:
        raise QDataValidationError(f"{name} is required")
    return value


def _list_param(params: dict[str, list[str]], name: str) -> list[str] | None:
    value = _param(params, name)
    if not value:
        return None
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _int_list_param(params: dict[str, list[str]], name: str) -> list[int] | None:
    value = _param(params, name)
    if not value:
        return None
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _bool_param(params: dict[str, list[str]], name: str, default: bool) -> bool:
    value = _param(params, name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y"}


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    payload, _ = _read_json_body_with_raw(handler)
    return payload


def _read_json_body_with_raw(handler: BaseHTTPRequestHandler) -> tuple[dict[str, Any], bytes]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}, b""
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise QDataValidationError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise QDataValidationError("request body must be a JSON object")
    return payload, raw


def _headers_dict(headers: Any) -> dict[str, str]:
    return {str(key): str(value) for key, value in headers.items()}


def _optional_body_string(body: dict[str, Any], name: str) -> str | None:
    value = body.get(name)
    if value in (None, ""):
        return None
    return str(value)


def _int_body(body: dict[str, Any], name: str, default: int) -> int:
    value = body.get(name, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise QDataValidationError(f"{name} must be an integer") from exc


def _bool_body(body: dict[str, Any], name: str, default: bool) -> bool:
    value = body.get(name, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _require_postgres_dsn(postgres_dsn: str | None) -> str:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for writable admin endpoints")
    return postgres_dsn


def _required_scope(path: str) -> str:
    if is_kappa_path(path) or path in ADMIN_WRITE_PATHS:
        return "admin"
    return "read"


def _is_signed_wecom_callback_path(path: str) -> bool:
    return path in SIGNED_WECOM_CALLBACK_PATHS


def _route_dataset_code(path: str, params: dict[str, list[str]]) -> str | None:
    if path == "/price":
        return "minute_bar" if _param(params, "frequency", "1d") == "1m" else "daily_bar"
    if path == "/matrix":
        return "daily_bar"
    if path == "/constraints":
        return "limit_price_daily"
    return None


def _api_route_request_key(path: str, params: dict[str, list[str]]) -> str:
    parts = []
    for key in sorted(params):
        if key.lower() in {"token", "api_token", "access_token"}:
            continue
        parts.append(f"{key}={','.join(params[key])}")
    return f"api:{path}:{'&'.join(parts)}"


def _to_matrix(rows: list[dict[str, Any]], symbols: list[str], field_name: str) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = by_date.setdefault(row["trade_date"], {"trade_date": row["trade_date"]})
        item[row["symbol"]] = row.get(field_name)
    return [
        {"trade_date": trade_date, **{symbol: by_date[trade_date].get(symbol) for symbol in symbols}}
        for trade_date in sorted(by_date)
    ]


def _symbols_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for row in rows:
        symbol = row.get("symbol")
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols
