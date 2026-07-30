from __future__ import annotations

from typing import Any, Protocol

from qdata.exceptions import QDataValidationError


class QueryClient(Protocol):
    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...

    def close(self) -> None:
        ...


class PostgresClient:
    """Thin psycopg wrapper used by SqlBackend.

    The dependency is imported lazily so the SDK can still run in mock mode
    without PostgreSQL client libraries installed.
    """

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise QDataValidationError(
                "psycopg is required for backend='sql'. Install qdata[sql] or provide a custom postgres client."
            ) from exc

        self._connection = psycopg.connect(dsn, row_factory=dict_row)

    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._connection.cursor() as cursor:
            cursor.execute(sql, params or {})
            return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self._connection.close()


class ClickHouseClient:
    """Thin clickhouse-connect wrapper used by SqlBackend."""

    def __init__(self, dsn: str | None = None, **kwargs: Any) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise QDataValidationError(
                "clickhouse-connect is required for backend='sql'. Install qdata[sql] or provide a custom clickhouse client."
            ) from exc

        if dsn:
            self._client = clickhouse_connect.get_client(dsn=dsn, **kwargs)
        else:
            self._client = clickhouse_connect.get_client(**kwargs)

    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = self._client.query(sql, parameters=params or {})
        return [dict(row) for row in result.named_results()]

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            close()
