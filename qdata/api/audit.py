from __future__ import annotations

from datetime import datetime
import json
from typing import Any


def write_api_audit(
    postgres_dsn: str | None,
    *,
    token_id: int | None,
    tenant_id: int | None = None,
    project_id: int | None = None,
    principal_id: int | None = None,
    api_name: str,
    request_id: str | None,
    request_summary: dict[str, Any],
    response_format: str,
    status: str,
    row_count: int | None,
    error_message: str | None,
    started_at: datetime,
    finished_at: datetime,
    client_ip: str | None,
    user_agent: str | None,
) -> None:
    if not postgres_dsn:
        return
    try:
        import psycopg
    except ImportError:
        return
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    cost_units = (row_count or 0) / 1000 + 1
    try:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.api_request_audit (
                        token_id, tenant_id, project_id, principal_id,
                        api_name, request_id, request_summary, response_format,
                        status, row_count, error_message, started_at, finished_at,
                        duration_ms, client_ip, user_agent, cost_units
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::inet, %s, %s)
                    """,
                    (
                        token_id,
                        tenant_id,
                        project_id,
                        principal_id,
                        api_name,
                        request_id,
                        json.dumps(request_summary, ensure_ascii=False, sort_keys=True),
                        response_format,
                        status,
                        row_count,
                        error_message,
                        started_at,
                        finished_at,
                        duration_ms,
                        client_ip,
                        user_agent,
                        cost_units,
                    ),
                )
    except Exception:
        return
