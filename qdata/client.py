from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any

from qdata.database import QueryClient
from qdata.exceptions import QDataValidationError
from qdata.mock_backend import MockBackend
from qdata.sql_backend import SqlBackend


class Client:
    """Python SDK client for the quantitative data platform.

    The MVP uses a local mock backend by default so the SDK can be exercised
    before the REST service and databases are deployed.
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
        default_format: str = "dataframe",
        backend: str | None = None,
        postgres_dsn: str | None = None,
        clickhouse_dsn: str | None = None,
        postgres_client: QueryClient | None = None,
        clickhouse_client: QueryClient | None = None,
    ) -> None:
        self.token = token
        self.base_url = base_url
        self.timeout = timeout
        self.default_format = default_format
        selected_backend = backend or os.getenv("QDATA_BACKEND", "mock")
        postgres_dsn = postgres_dsn or os.getenv("QDATA_POSTGRES_DSN")
        clickhouse_dsn = clickhouse_dsn or os.getenv("QDATA_CLICKHOUSE_DSN")

        if selected_backend == "auto":
            selected_backend = "sql" if postgres_dsn or postgres_client else "mock"

        if selected_backend == "mock":
            self._backend = MockBackend()
        elif selected_backend == "sql":
            self._backend = SqlBackend(
                postgres_dsn=postgres_dsn,
                clickhouse_dsn=clickhouse_dsn,
                postgres=postgres_client,
                clickhouse=clickhouse_client,
            )
        else:
            raise QDataValidationError("backend must be one of: mock, sql, auto")

    def get_security_master(
        self,
        symbols: list[str] | None = None,
        security_ids: list[int] | None = None,
        asset_types: list[str] | None = None,
        exchanges: list[str] | None = None,
        asof_date: str | None = None,
        include_delisted: bool = False,
        fields: list[str] | None = None,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_security_master(
            symbols=symbols,
            security_ids=security_ids,
            asset_types=asset_types,
            exchanges=exchanges,
            asof_date=asof_date,
            include_delisted=include_delisted,
            fields=fields,
        )
        return self._format(payload, output_format, include_meta)

    def get_trading_calendar(
        self,
        exchange: str,
        start_date: str,
        end_date: str,
        open_only: bool = True,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_trading_calendar(
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            open_only=open_only,
        )
        return self._format(payload, output_format, include_meta)

    def get_price(
        self,
        symbols: list[str] | None = None,
        security_ids: list[int] | None = None,
        universe: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        frequency: str = "1d",
        adjust: str = "none",
        fields: list[str] | None = None,
        query_mode: str = "latest",
        asof_time: str | None = None,
        data_version: str | None = None,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_price(
            symbols=symbols,
            security_ids=security_ids,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjust=adjust,
            fields=fields,
            query_mode=query_mode,
            asof_time=asof_time,
            data_version=data_version,
        )
        return self._format(payload, output_format, include_meta)

    def get_adjustment_factor(
        self,
        symbols: list[str] | None = None,
        security_ids: list[int] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        factor_type: str = "both",
        query_mode: str = "latest",
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_adjustment_factor(
            symbols=symbols,
            security_ids=security_ids,
            start_date=start_date,
            end_date=end_date,
            factor_type=factor_type,
            query_mode=query_mode,
        )
        return self._format(payload, output_format, include_meta)

    def get_trading_constraints(
        self,
        symbols: list[str] | None = None,
        universe: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        fields: list[str] | None = None,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_trading_constraints(
            symbols=symbols,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            fields=fields,
        )
        return self._format(payload, output_format, include_meta)

    def get_fundamental_asof(
        self,
        symbols: list[str] | None = None,
        security_ids: list[int] | None = None,
        fields: list[str] | None = None,
        asof_date: str | None = None,
        report_period: str | None = None,
        period_type: str = "ttm",
        include_revision_info: bool = True,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_fundamental_asof(
            symbols=symbols,
            security_ids=security_ids,
            fields=fields,
            asof_date=asof_date,
            report_period=report_period,
            period_type=period_type,
            include_revision_info=include_revision_info,
        )
        return self._format(payload, output_format, include_meta)

    def get_index_members_asof(
        self,
        index_code: str,
        asof_date: str,
        fields: list[str] | None = None,
        include_weight: bool = True,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_index_members_asof(
            index_code=index_code,
            asof_date=asof_date,
            fields=fields,
            include_weight=include_weight,
        )
        return self._format(payload, output_format, include_meta)

    def get_industry_asof(
        self,
        symbols: list[str] | None = None,
        universe: str | None = None,
        industry_system: str = "sw",
        level: int = 1,
        asof_date: str | None = None,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_industry_asof(
            symbols=symbols,
            universe=universe,
            industry_system=industry_system,
            level=level,
            asof_date=asof_date,
        )
        return self._format(payload, output_format, include_meta)

    def get_universe(
        self,
        universe: str,
        asof_date: str,
        filters: Mapping[str, Any] | None = None,
        include_weight: bool = False,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_universe(
            universe=universe,
            asof_date=asof_date,
            filters=dict(filters or {}),
            include_weight=include_weight,
        )
        return self._format(payload, output_format, include_meta)

    def get_tradable_universe(
        self,
        asof_date: str,
        symbols: list[str] | None = None,
        universe: str | None = None,
        exclude_st: bool = True,
        exclude_suspended: bool = True,
        exclude_new_listing: bool = True,
        exclude_delisting_period: bool = True,
        min_list_days: int = 30,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_tradable_universe(
            asof_date=asof_date,
            symbols=symbols,
            universe=universe,
            exclude_st=exclude_st,
            exclude_suspended=exclude_suspended,
            exclude_new_listing=exclude_new_listing,
            exclude_delisting_period=exclude_delisting_period,
            min_list_days=min_list_days,
        )
        return self._format(payload, output_format, include_meta)

    def get_factor(
        self,
        factors: list[str],
        symbols: list[str] | None = None,
        universe: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        factor_version: str = "published",
        query_mode: str = "asof",
        format: str = "long",
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_factor(
            factors=factors,
            symbols=symbols,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            factor_version=factor_version,
            query_mode=query_mode,
            format=format,
        )
        return self._format(payload, output_format, include_meta)

    def get_dataset_health(
        self,
        dataset_code: str,
        start_date: str,
        end_date: str,
        severity: str | None = None,
        output_format: str | None = None,
        include_meta: bool = False,
    ) -> Any:
        payload = self._backend.get_dataset_health(
            dataset_code=dataset_code,
            start_date=start_date,
            end_date=end_date,
            severity=severity,
        )
        return self._format(payload, output_format, include_meta)

    def close(self) -> None:
        close = getattr(self._backend, "close", None)
        if close:
            close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _format(self, payload: dict[str, Any], output_format: str | None, include_meta: bool) -> Any:
        rows = payload["data"]
        selected_format = output_format or self.default_format

        if selected_format == "records":
            data: Any = rows
        elif selected_format == "dataframe":
            data = self._to_dataframe(rows)
        elif selected_format == "json":
            data = payload
        else:
            raise QDataValidationError(f"Unsupported output_format: {selected_format}")

        if include_meta and selected_format != "json":
            return {"data": data, "meta": payload["meta"], "request_id": payload["request_id"]}
        return data

    @staticmethod
    def _to_dataframe(rows: list[dict[str, Any]]) -> Any:
        try:
            import pandas as pd
        except ImportError as exc:
            raise QDataValidationError(
                "pandas is required for output_format='dataframe'. "
                "Use output_format='records' or install qdata[dataframe]."
            ) from exc
        return pd.DataFrame(rows)
