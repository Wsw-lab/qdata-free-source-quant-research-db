from __future__ import annotations

from datetime import datetime
from typing import Any

from qdata.backend_utils import (
    date_range,
    ensure_required_dates,
    normalize_rows,
    parse_date,
    project,
    response,
    validate_enum,
)
from qdata.database import ClickHouseClient, PostgresClient, QueryClient
from qdata.exceptions import QDataNotFoundError, QDataValidationError


class SqlBackend:
    """PostgreSQL + ClickHouse backend for real data environments."""

    PRICE_FIELDS = {
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "volume",
        "amount",
        "vwap",
        "turnover_rate",
        "limit_up",
        "limit_down",
        "is_suspended",
    }
    MINUTE_FIELDS = {"open", "high", "low", "close", "volume", "amount", "vwap"}
    SECURITY_FIELDS = {
        "security_id",
        "symbol",
        "asset_type",
        "exchange",
        "name",
        "list_date",
        "delist_date",
        "status",
        "currency",
    }
    CONSTRAINT_FIELDS = {
        "is_suspended",
        "is_st",
        "limit_up",
        "limit_down",
        "can_buy",
        "can_sell",
        "list_days",
        "is_new_listing",
        "is_delisting_period",
    }

    def __init__(
        self,
        postgres_dsn: str | None = None,
        clickhouse_dsn: str | None = None,
        postgres: QueryClient | None = None,
        clickhouse: QueryClient | None = None,
    ) -> None:
        self.postgres = postgres or (PostgresClient(postgres_dsn) if postgres_dsn else None)
        self.clickhouse = clickhouse or (ClickHouseClient(clickhouse_dsn) if clickhouse_dsn else None)
        if self.postgres is None:
            raise QDataValidationError("postgres_dsn or postgres client is required for backend='sql'")

    def close(self) -> None:
        self.postgres.close()
        if self.clickhouse is not None:
            self.clickhouse.close()

    def get_security_master(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        asset_types: list[str] | None,
        exchanges: list[str] | None,
        asof_date: str | None,
        include_delisted: bool,
        fields: list[str] | None,
    ) -> dict[str, Any]:
        requested_fields = fields or [
            "security_id",
            "symbol",
            "asset_type",
            "exchange",
            "name",
            "list_date",
            "delist_date",
            "status",
        ]
        self._validate_fields(requested_fields, self.SECURITY_FIELDS, "fields")
        where = []
        params: dict[str, Any] = {}
        if symbols:
            symbol_parts = [self._split_symbol(symbol) for symbol in symbols]
            where.append("(sm.current_symbol || '.' || sm.exchange) = ANY(%(symbols)s)")
            params["symbols"] = [f"{code}.{exchange}" for code, exchange in symbol_parts]
        if security_ids:
            where.append("sm.security_id = ANY(%(security_ids)s)")
            params["security_ids"] = security_ids
        if asset_types:
            where.append("sm.asset_type = ANY(%(asset_types)s)")
            params["asset_types"] = asset_types
        if exchanges:
            where.append("sm.exchange = ANY(%(exchanges)s)")
            params["exchanges"] = exchanges
        if not include_delisted:
            where.append("sm.current_status <> 'delisted'")
        if asof_date:
            parse_date(asof_date, "asof_date")
            where.append("(sm.list_date IS NULL OR sm.list_date <= %(asof_date)s)")
            where.append("(sm.delist_date IS NULL OR sm.delist_date >= %(asof_date)s)")
            params["asof_date"] = asof_date

        sql = f"""
            SELECT
                sm.security_id,
                sm.current_symbol || '.' || sm.exchange AS symbol,
                sm.asset_type,
                sm.exchange,
                sm.current_name AS name,
                sm.list_date,
                sm.delist_date,
                sm.current_status AS status,
                sm.currency
            FROM qmeta.security_master sm
            {self._where(where)}
            ORDER BY sm.exchange, sm.current_symbol
        """
        rows = normalize_rows(self.postgres.fetch_all(sql, params))
        return response(project(rows, requested_fields), ["security_master:sql"], "asof" if asof_date else "latest")

    def get_trading_calendar(
        self,
        exchange: str,
        start_date: str,
        end_date: str,
        open_only: bool,
    ) -> dict[str, Any]:
        date_range(start_date, end_date)
        where = ["exchange = %(exchange)s", "trade_date BETWEEN %(start_date)s AND %(end_date)s"]
        if open_only:
            where.append("is_open = TRUE")
        rows = self.postgres.fetch_all(
            f"""
            SELECT exchange, trade_date, is_open, session_type, pretrade_date, next_trade_date
            FROM qmeta.trading_calendar
            {self._where(where)}
            ORDER BY trade_date
            """,
            {"exchange": exchange, "start_date": start_date, "end_date": end_date},
        )
        return response(normalize_rows(rows), ["trading_calendar:sql"], "latest")

    def get_price(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        universe: str | None,
        start_date: str | None,
        end_date: str | None,
        frequency: str,
        adjust: str,
        fields: list[str] | None,
        query_mode: str,
        asof_time: str | None,
        data_version: str | None,
    ) -> dict[str, Any]:
        if self.clickhouse is None:
            raise QDataValidationError("clickhouse_dsn or clickhouse client is required for market data queries")
        start_date, end_date = ensure_required_dates(start_date, end_date)
        validate_enum(frequency, {"1d", "1m"}, "frequency")
        validate_enum(adjust, {"none", "forward", "backward"}, "adjust")
        validate_enum(query_mode, {"latest", "asof", "vintage"}, "query_mode")

        if query_mode == "asof" and not asof_time:
            raise QDataValidationError("asof_time is required when query_mode='asof'")
        if query_mode == "vintage" and not data_version:
            raise QDataValidationError("data_version is required when query_mode='vintage'")
        if asof_time:
            self._validate_asof_time(asof_time)

        security_map = self._resolve_security_map(symbols, security_ids, universe, asof_date=end_date)
        requested_fields = fields or ["open", "high", "low", "close", "volume", "amount"]
        allowed_fields = self.PRICE_FIELDS if frequency == "1d" else self.MINUTE_FIELDS
        self._validate_fields(requested_fields, allowed_fields, "fields")

        table = "qts.daily_bar" if frequency == "1d" else "qts.minute_bar"
        dataset_code = "daily_bar" if frequency == "1d" else "minute_bar"
        resolved_version = self._resolve_dataset_version(dataset_code, data_version) if data_version else None
        base_fields = ["security_id", "trade_date"]
        if frequency == "1m":
            base_fields.append("bar_time")
        select_fields = base_fields + requested_fields
        order_fields = "security_id, trade_date" + (", bar_time" if frequency == "1m" else "")
        where = [
            "security_id IN %(security_ids)s",
            "trade_date BETWEEN %(start_date)s AND %(end_date)s",
        ]
        params: dict[str, Any] = {
            "security_ids": tuple(security_map),
            "start_date": start_date,
            "end_date": end_date,
        }
        if asof_time:
            where.append("ingest_time <= %(asof_time)s")
            params["asof_time"] = asof_time
        if resolved_version:
            where.append("data_version = %(resolved_data_version)s")
            params["resolved_data_version"] = resolved_version["data_version"]
        rows = self.clickhouse.fetch_all(
            f"""
            SELECT {", ".join(select_fields)}
            FROM (
                SELECT
                    {", ".join(select_fields)},
                    row_number() OVER (
                        PARTITION BY {order_fields}
                        ORDER BY ingest_time DESC, data_version DESC
                    ) AS _qdata_revision_rank
                FROM {table}
                {self._where(where)}
            )
            WHERE _qdata_revision_rank = 1
            ORDER BY {order_fields}
            """,
            params,
        )
        normalized = normalize_rows(rows)
        if adjust != "none" and frequency == "1d":
            factors = self._get_adjustment_factor_map(
                list(security_map),
                start_date,
                end_date,
                asof_time=asof_time,
                batch_id=resolved_version.get("batch_id") if resolved_version else None,
            )
            normalized = [self._apply_adjustment(row, adjust, factors) for row in normalized]
        for row in normalized:
            row["symbol"] = security_map.get(row["security_id"])
        projected = project(normalized, ["symbol"] + select_fields)
        resolved_version_code = resolved_version["version_code"] if resolved_version else None
        return response(projected, [f"{frequency}_bar:sql"], query_mode, asof_time, resolved_version_code)

    def get_adjustment_factor(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        start_date: str | None,
        end_date: str | None,
        factor_type: str,
        query_mode: str,
    ) -> dict[str, Any]:
        start_date, end_date = ensure_required_dates(start_date, end_date)
        validate_enum(factor_type, {"forward", "backward", "both"}, "factor_type")
        validate_enum(query_mode, {"latest", "asof", "vintage"}, "query_mode")
        security_map = self._resolve_security_map(symbols, security_ids, None, asof_date=end_date)

        fields = ["security_id", "trade_date", "ex_right_type"]
        if factor_type in {"forward", "both"}:
            fields.append("factor_forward")
        if factor_type in {"backward", "both"}:
            fields.append("factor_backward")

        rows = self.postgres.fetch_all(
            f"""
            SELECT {", ".join(fields)}
            FROM qmeta.adjustment_factor
            WHERE security_id = ANY(%(security_ids)s)
              AND trade_date BETWEEN %(start_date)s AND %(end_date)s
            ORDER BY security_id, trade_date, revision_id
            """,
            {"security_ids": list(security_map), "start_date": start_date, "end_date": end_date},
        )
        normalized = normalize_rows(rows)
        for row in normalized:
            row["symbol"] = security_map.get(row["security_id"])
        return response(project(normalized, ["symbol"] + fields), ["adjustment_factor:sql"], query_mode)

    def get_trading_constraints(
        self,
        symbols: list[str] | None,
        universe: str | None,
        start_date: str | None,
        end_date: str | None,
        fields: list[str] | None,
    ) -> dict[str, Any]:
        start_date, end_date = ensure_required_dates(start_date, end_date)
        security_map = self._resolve_security_map(symbols, None, universe, asof_date=end_date)
        requested_fields = fields or [
            "is_suspended",
            "is_st",
            "limit_up",
            "limit_down",
            "can_buy",
            "can_sell",
            "list_days",
            "is_new_listing",
            "is_delisting_period",
        ]
        self._validate_fields(requested_fields, self.CONSTRAINT_FIELDS, "fields")
        rows = self.postgres.fetch_all(
            """
            SELECT
                sm.security_id,
                lp.trade_date,
                COALESCE(lp.limit_up, NULL) AS limit_up,
                COALESCE(lp.limit_down, NULL) AS limit_down,
                COALESCE(lp.is_st, FALSE) AS is_st,
                COALESCE(lp.is_new_listing, FALSE) AS is_new_listing,
                EXISTS (
                    SELECT 1
                    FROM qmeta.suspension_history sh
                    WHERE sh.security_id = lp.security_id
                      AND sh.start_time::date <= lp.trade_date
                      AND (sh.end_time IS NULL OR sh.end_time::date >= lp.trade_date)
                ) AS is_suspended,
                COALESCE(st.status = 'delisting_period', FALSE) AS is_delisting_period,
                GREATEST((lp.trade_date - COALESCE(sm.list_date, lp.trade_date)), 0) AS list_days
            FROM qmeta.limit_price_daily lp
            JOIN qmeta.security_master sm ON sm.security_id = lp.security_id
            LEFT JOIN LATERAL (
                SELECT status
                FROM qmeta.security_status_history st
                WHERE st.security_id = lp.security_id
                  AND st.start_date <= lp.trade_date
                  AND (st.end_date IS NULL OR st.end_date >= lp.trade_date)
                ORDER BY st.start_date DESC, st.revision_id DESC, st.created_at DESC
                LIMIT 1
            ) st ON TRUE
            WHERE lp.security_id = ANY(%(security_ids)s)
              AND lp.trade_date BETWEEN %(start_date)s AND %(end_date)s
            ORDER BY lp.security_id, lp.trade_date
            """,
            {"security_ids": list(security_map), "start_date": start_date, "end_date": end_date},
        )
        normalized = normalize_rows(rows)
        for row in normalized:
            row["symbol"] = security_map.get(row["security_id"])
            blocked = row.get("is_suspended", False) or row.get("is_delisting_period", False)
            row["can_buy"] = not blocked
            row["can_sell"] = not blocked
        return response(project(normalized, ["symbol", "security_id", "trade_date"] + requested_fields), ["trading_constraints:sql"], "latest")

    def get_tradable_universe(
        self,
        asof_date: str,
        symbols: list[str] | None,
        universe: str | None,
        exclude_st: bool,
        exclude_suspended: bool,
        exclude_new_listing: bool,
        exclude_delisting_period: bool,
        min_list_days: int,
    ) -> dict[str, Any]:
        parse_date(asof_date, "asof_date")
        if min_list_days < 0:
            raise QDataValidationError("min_list_days must be greater than or equal to 0")
        if symbols:
            base_rows = self.get_security_master(
                symbols=symbols,
                security_ids=None,
                asset_types=["stock"],
                exchanges=None,
                asof_date=asof_date,
                include_delisted=False,
                fields=None,
            )["data"]
        elif universe:
            base_rows = self.get_universe(universe, asof_date, {}, False)["data"]
        else:
            base_rows = self.get_security_master(
                symbols=None,
                security_ids=None,
                asset_types=["stock"],
                exchanges=None,
                asof_date=asof_date,
                include_delisted=False,
                fields=None,
            )["data"]
        base_symbols = [row["symbol"] for row in base_rows]
        if not base_symbols:
            return response([], ["tradable_universe:sql"], "asof")
        constraints = {
            row["symbol"]: row
            for row in self.get_trading_constraints(base_symbols, None, asof_date, asof_date, None)["data"]
        }
        rows = []
        for row in base_rows:
            constraint = constraints.get(row["symbol"])
            if not constraint:
                continue
            if exclude_suspended and constraint.get("is_suspended"):
                continue
            if exclude_st and constraint.get("is_st"):
                continue
            if exclude_new_listing and constraint.get("is_new_listing"):
                continue
            if exclude_delisting_period and constraint.get("is_delisting_period"):
                continue
            if int(constraint.get("list_days") or 0) < min_list_days:
                continue
            rows.append(
                {
                    "symbol": row["symbol"],
                    "security_id": row["security_id"],
                    "asof_date": asof_date,
                    "can_buy": constraint.get("can_buy"),
                    "can_sell": constraint.get("can_sell"),
                    "list_days": constraint.get("list_days"),
                    "is_st": constraint.get("is_st"),
                    "is_suspended": constraint.get("is_suspended"),
                    "is_new_listing": constraint.get("is_new_listing"),
                    "is_delisting_period": constraint.get("is_delisting_period"),
                }
            )
        return response(rows, ["tradable_universe:sql"], "asof")

    def get_fundamental_asof(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        fields: list[str] | None,
        asof_date: str | None,
        report_period: str | None,
        period_type: str,
        include_revision_info: bool,
    ) -> dict[str, Any]:
        if not asof_date:
            raise QDataValidationError("asof_date is required")
        if not fields:
            raise QDataValidationError("fields are required")
        parse_date(asof_date, "asof_date")
        security_map = self._resolve_security_map(symbols, security_ids, None, asof_date=asof_date)
        params: dict[str, Any] = {
            "security_ids": list(security_map),
            "fields": fields,
            "asof_date": asof_date,
            "period_type": period_type,
        }
        report_filter = ""
        if report_period:
            parse_date(report_period, "report_period")
            report_filter = "AND report_period = %(report_period)s"
            params["report_period"] = report_period
        rows = self.postgres.fetch_all(
            f"""
            WITH source_rows AS (
                SELECT
                    security_id,
                    report_period,
                    metric_name AS field_name,
                    metric_value AS field_value,
                    announce_time,
                    ingest_time,
                    revision_id,
                    is_restated
                FROM qpit.financial_metric_pit
                WHERE security_id = ANY(%(security_ids)s)
                  AND metric_name = ANY(%(fields)s)
                  AND metric_scope = %(period_type)s
                  AND announce_time <= (%(asof_date)s::date + INTERVAL '1 day' - INTERVAL '1 second')
                  AND ingest_time <= (%(asof_date)s::date + INTERVAL '1 day' - INTERVAL '1 second')
                  {report_filter}

                UNION ALL

                SELECT
                    security_id,
                    report_period,
                    field_name,
                    field_value,
                    announce_time,
                    ingest_time,
                    revision_id,
                    is_restated
                FROM qpit.financial_statement_pit
                WHERE security_id = ANY(%(security_ids)s)
                  AND field_name = ANY(%(fields)s)
                  AND period_type = %(period_type)s
                  AND announce_time <= (%(asof_date)s::date + INTERVAL '1 day' - INTERVAL '1 second')
                  AND ingest_time <= (%(asof_date)s::date + INTERVAL '1 day' - INTERVAL '1 second')
                  {report_filter}
            ),
            ranked AS (
                SELECT
                    security_id,
                    report_period,
                    field_name,
                    field_value,
                    announce_time,
                    ingest_time,
                    revision_id,
                    is_restated,
                    ROW_NUMBER() OVER (
                        PARTITION BY security_id, field_name
                        ORDER BY report_period DESC, announce_time DESC, revision_id DESC
                    ) AS rn
                FROM source_rows
            )
            SELECT *
            FROM ranked
            WHERE rn = 1
            ORDER BY security_id, field_name
            """,
            params,
        )
        normalized = normalize_rows(rows)
        result = []
        for row in normalized:
            item = {
                "symbol": security_map.get(row["security_id"]),
                "security_id": row["security_id"],
                "asof_date": asof_date,
                "report_period": row["report_period"],
                "field_name": row["field_name"],
                "field_value": row["field_value"],
            }
            if include_revision_info:
                item.update(
                    {
                        "announce_time": row["announce_time"],
                        "ingest_time": row["ingest_time"],
                        "revision_id": row["revision_id"],
                        "is_restated": row["is_restated"],
                    }
                )
            result.append(item)
        return response(result, ["financial_metric_pit:sql"], "asof")

    def get_index_members_asof(
        self,
        index_code: str,
        asof_date: str,
        fields: list[str] | None,
        include_weight: bool,
    ) -> dict[str, Any]:
        parse_date(asof_date, "asof_date")
        default_fields = ["index_code", "symbol", "security_id", "effective_date", "end_date"]
        if include_weight:
            default_fields.append("weight")
        rows = self.postgres.fetch_all(
            """
            SELECT
                im.index_code,
                sm.current_symbol || '.' || sm.exchange AS symbol,
                sm.security_id,
                mp.effective_date,
                mp.end_date,
                mp.weight
            FROM qpit.index_member_pit mp
            JOIN qmeta.index_master im ON im.index_id = mp.index_id
            JOIN qmeta.security_master sm ON sm.security_id = mp.security_id
            WHERE im.index_code = %(index_code)s
              AND mp.effective_date <= %(asof_date)s
              AND (mp.end_date IS NULL OR mp.end_date >= %(asof_date)s)
            ORDER BY mp.weight DESC NULLS LAST, sm.exchange, sm.current_symbol
            """,
            {"index_code": index_code, "asof_date": asof_date},
        )
        return response(project(normalize_rows(rows), fields or default_fields), ["index_member_pit:sql"], "asof")

    def get_industry_asof(
        self,
        symbols: list[str] | None,
        universe: str | None,
        industry_system: str,
        level: int,
        asof_date: str | None,
    ) -> dict[str, Any]:
        if not asof_date:
            raise QDataValidationError("asof_date is required")
        parse_date(asof_date, "asof_date")
        security_map = self._resolve_security_map(symbols, None, universe, asof_date=asof_date)
        rows = self.postgres.fetch_all(
            """
            SELECT
                sm.current_symbol || '.' || sm.exchange AS symbol,
                sm.security_id,
                sys.system_code AS industry_system,
                cat.level,
                cat.industry_code,
                cat.industry_name,
                mem.effective_date,
                mem.end_date
            FROM qpit.industry_membership_pit mem
            JOIN qmeta.security_master sm ON sm.security_id = mem.security_id
            JOIN qmeta.industry_system sys ON sys.industry_system_id = mem.industry_system_id
            JOIN qmeta.industry_category cat ON cat.industry_id = mem.industry_id
            WHERE mem.security_id = ANY(%(security_ids)s)
              AND sys.system_code = %(industry_system)s
              AND cat.level = %(level)s
              AND mem.effective_date <= %(asof_date)s
              AND (mem.end_date IS NULL OR mem.end_date >= %(asof_date)s)
            ORDER BY sm.exchange, sm.current_symbol
            """,
            {
                "security_ids": list(security_map),
                "industry_system": industry_system,
                "level": level,
                "asof_date": asof_date,
            },
        )
        return response(normalize_rows(rows), ["industry_membership_pit:sql"], "asof")

    def get_universe(
        self,
        universe: str,
        asof_date: str,
        filters: dict[str, Any],
        include_weight: bool,
    ) -> dict[str, Any]:
        parse_date(asof_date, "asof_date")
        if universe in {"hs300", "000300.SH", "zz500", "000905.SH", "zz1000", "000852.SH"}:
            index_code = {"hs300": "000300.SH", "zz500": "000905.SH", "zz1000": "000852.SH"}.get(universe, universe)
            rows = [
                {
                    "universe": universe,
                    "symbol": row["symbol"],
                    "security_id": row["security_id"],
                    "asof_date": asof_date,
                    "weight": row.get("weight"),
                }
                for row in self.get_index_members_asof(index_code, asof_date, None, True)["data"]
            ]
        else:
            rows = self.postgres.fetch_all(
                """
                SELECT
                    ud.universe_code AS universe,
                    sm.current_symbol || '.' || sm.exchange AS symbol,
                    sm.security_id,
                    %(asof_date)s::date AS asof_date,
                    um.weight
                FROM qpit.universe_member_pit um
                JOIN qmeta.universe_definition ud ON ud.universe_id = um.universe_id
                JOIN qmeta.security_master sm ON sm.security_id = um.security_id
                WHERE ud.universe_code = %(universe)s
                  AND um.effective_date <= %(asof_date)s
                  AND (um.end_date IS NULL OR um.end_date >= %(asof_date)s)
                ORDER BY sm.exchange, sm.current_symbol
                """,
                {"universe": universe, "asof_date": asof_date},
            )
            rows = normalize_rows(rows)
        if filters:
            symbols = [row["symbol"] for row in rows]
            constraints = {
                row["symbol"]: row
                for row in self.get_trading_constraints(symbols, None, asof_date, asof_date, None)["data"]
            }
            filtered = []
            for row in rows:
                constraint = constraints.get(row["symbol"], {})
                if filters.get("exclude_st") and constraint.get("is_st"):
                    continue
                if filters.get("exclude_suspended") and constraint.get("is_suspended"):
                    continue
                if filters.get("exclude_delisting_period") and constraint.get("is_delisting_period"):
                    continue
                if filters.get("exclude_new_listing") and constraint.get("is_new_listing"):
                    continue
                if constraint.get("list_days", 10_000) < filters.get("min_list_days", 0):
                    continue
                filtered.append(row)
            rows = filtered
        if not include_weight:
            rows = [{key: value for key, value in row.items() if key != "weight"} for row in rows]
        return response(rows, ["universe:sql"], "asof")

    def get_factor(
        self,
        factors: list[str],
        symbols: list[str] | None,
        universe: str | None,
        start_date: str | None,
        end_date: str | None,
        factor_version: str,
        query_mode: str,
        format: str,
    ) -> dict[str, Any]:
        if self.clickhouse is None:
            raise QDataValidationError("clickhouse_dsn or clickhouse client is required for factor queries")
        start_date, end_date = ensure_required_dates(start_date, end_date)
        validate_enum(format, {"long", "wide"}, "format")
        validate_enum(query_mode, {"latest", "asof", "vintage"}, "query_mode")
        security_map = self._resolve_security_map(symbols, None, universe, asof_date=end_date)
        factor_map = self._resolve_factor_map(factors, factor_version)
        rows = self.clickhouse.fetch_all(
            """
            SELECT
                factor_id,
                factor_version_id,
                security_id,
                trade_date,
                factor_value,
                quality_flag
            FROM qts.factor_value_daily FINAL
            WHERE factor_id IN %(factor_ids)s
              AND factor_version_id IN %(factor_version_ids)s
              AND security_id IN %(security_ids)s
              AND trade_date BETWEEN %(start_date)s AND %(end_date)s
            ORDER BY trade_date, security_id, factor_id
            """,
            {
                "factor_ids": tuple(factor_map),
                "factor_version_ids": tuple(factor["factor_version_id"] for factor in factor_map.values()),
                "security_ids": tuple(security_map),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        normalized = normalize_rows(rows)
        factor_code_by_id = {factor_id: factor["factor_code"] for factor_id, factor in factor_map.items()}
        version_code_by_id = {
            factor["factor_version_id"]: factor["version_code"]
            for factor in factor_map.values()
        }
        for row in normalized:
            row["symbol"] = security_map.get(row["security_id"])
            row["factor_code"] = factor_code_by_id.get(row["factor_id"])
            row["factor_version"] = version_code_by_id.get(row["factor_version_id"])
        if format == "wide":
            normalized = self._factor_rows_to_wide(normalized, factors)
        else:
            normalized = project(
                normalized,
                ["symbol", "security_id", "trade_date", "factor_code", "factor_value", "factor_version", "quality_flag"],
            )
        return response(normalized, ["factor_value_daily:sql"], query_mode)

    def get_dataset_health(
        self,
        dataset_code: str,
        start_date: str,
        end_date: str,
        severity: str | None,
    ) -> dict[str, Any]:
        date_range(start_date, end_date)
        where = [
            "dc.dataset_code = %(dataset_code)s",
            "qr.check_date BETWEEN %(start_date)s AND %(end_date)s",
        ]
        params: dict[str, Any] = {"dataset_code": dataset_code, "start_date": start_date, "end_date": end_date}
        if severity:
            where.append("qr.severity = %(severity)s")
            params["severity"] = severity
        rows = self.postgres.fetch_all(
            f"""
            SELECT
                dc.dataset_code,
                qr.check_date,
                qr.check_name,
                qr.status,
                qr.severity,
                qr.metric_value,
                qr.threshold_value,
                qr.affected_rows,
                qr.details
            FROM qmeta.data_quality_check_result qr
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = qr.dataset_id
            {self._where(where)}
            ORDER BY qr.check_date, qr.severity, qr.check_name
            """,
            params,
        )
        return response(normalize_rows(rows), [f"{dataset_code}:quality:sql"], "latest")

    def _resolve_security_map(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        universe: str | None,
        asof_date: str | None,
    ) -> dict[int, str]:
        if universe and not symbols and not security_ids:
            rows = self.get_universe(universe, asof_date or "9999-12-31", {}, False)["data"]
            return {row["security_id"]: row["symbol"] for row in rows}
        if not symbols and not security_ids:
            raise QDataValidationError("symbols, security_ids, or universe is required")

        where = []
        params: dict[str, Any] = {}
        if symbols:
            where.append("(current_symbol || '.' || exchange) = ANY(%(symbols)s)")
            params["symbols"] = symbols
        if security_ids:
            where.append("security_id = ANY(%(security_ids)s)")
            params["security_ids"] = security_ids
        if asof_date:
            where.append("(list_date IS NULL OR list_date <= %(asof_date)s)")
            where.append("(delist_date IS NULL OR delist_date >= %(asof_date)s)")
            params["asof_date"] = asof_date
        rows = self.postgres.fetch_all(
            f"""
            SELECT security_id, current_symbol || '.' || exchange AS symbol
            FROM qmeta.security_master
            {self._where(where)}
            """,
            params,
        )
        result = {row["security_id"]: row["symbol"] for row in normalize_rows(rows)}
        if not result:
            raise QDataNotFoundError("No securities matched the request")
        return result

    def _resolve_factor_map(self, factors: list[str], factor_version: str) -> dict[int, dict[str, Any]]:
        rows = self.postgres.fetch_all(
            """
            SELECT
                fd.factor_id,
                fd.factor_code,
                fv.factor_version_id,
                fv.version_code
            FROM qmeta.factor_definition fd
            JOIN qmeta.factor_version fv ON fv.factor_id = fd.factor_id
            WHERE fd.factor_code = ANY(%(factors)s)
              AND (%(factor_version)s = 'published' AND fv.status = 'published'
                   OR fv.version_code = %(factor_version)s)
            """,
            {"factors": factors, "factor_version": factor_version},
        )
        normalized = normalize_rows(rows)
        rows_by_code: dict[str, list[dict[str, Any]]] = {}
        for row in normalized:
            rows_by_code.setdefault(row["factor_code"], []).append(row)
        missing = sorted(set(factors) - set(rows_by_code))
        if missing:
            raise QDataNotFoundError(f"No factor version matched: {missing}")
        ambiguous = sorted(code for code, matches in rows_by_code.items() if len(matches) != 1)
        if ambiguous:
            raise QDataValidationError(f"Factor version selection is ambiguous: {ambiguous}")
        return {matches[0]["factor_id"]: matches[0] for matches in rows_by_code.values()}

    def _resolve_dataset_version(self, dataset_code: str, requested_version: str) -> dict[str, Any]:
        rows = normalize_rows(
            self.postgres.fetch_all(
                """
                SELECT
                    dv.data_version,
                    dv.version_code,
                    dv.batch_id,
                    dv.status
                FROM qmeta.dataset_version dv
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = dv.dataset_id
                WHERE dc.dataset_code = %(dataset_code)s
                  AND (dv.version_code = %(data_version)s OR CAST(dv.data_version AS TEXT) = %(data_version)s)
                  AND dv.status IN ('active', 'superseded')
                """,
                {"dataset_code": dataset_code, "data_version": str(requested_version)},
            )
        )
        if not rows:
            raise QDataNotFoundError(
                f"Unknown or unavailable data_version for {dataset_code}: {requested_version}"
            )
        if len(rows) != 1:
            raise QDataValidationError(
                f"data_version selection is ambiguous for {dataset_code}: {requested_version}"
            )
        return rows[0]

    def _get_adjustment_factor_map(
        self,
        security_ids: list[int],
        start_date: str,
        end_date: str,
        asof_time: str | None = None,
        batch_id: int | None = None,
    ) -> dict[tuple[int, str], dict[str, Any]]:
        where = [
            "security_id = ANY(%(security_ids)s)",
            "trade_date BETWEEN %(start_date)s AND %(end_date)s",
        ]
        params: dict[str, Any] = {
            "security_ids": security_ids,
            "start_date": start_date,
            "end_date": end_date,
        }
        if asof_time:
            where.append("ingest_time <= %(asof_time)s")
            params["asof_time"] = asof_time
        if batch_id is not None:
            where.append("batch_id = %(batch_id)s")
            params["batch_id"] = batch_id
        rows = self.postgres.fetch_all(
            f"""
            SELECT DISTINCT ON (security_id, trade_date)
                security_id, trade_date, factor_forward, factor_backward
            FROM qmeta.adjustment_factor
            {self._where(where)}
            ORDER BY security_id, trade_date, revision_id DESC, ingest_time DESC
            """,
            params,
        )
        normalized = normalize_rows(rows)
        return {(row["security_id"], row["trade_date"]): row for row in normalized}

    @staticmethod
    def _validate_asof_time(value: str) -> None:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise QDataValidationError("asof_time must use ISO-8601 date/time format") from exc

    def _apply_adjustment(
        self,
        row: dict[str, Any],
        adjust: str,
        factors: dict[tuple[int, str], dict[str, Any]],
    ) -> dict[str, Any]:
        adjusted = dict(row)
        factor_row = factors.get((row["security_id"], row["trade_date"]))
        if not factor_row:
            return adjusted
        factor = factor_row["factor_forward"] if adjust == "forward" else factor_row["factor_backward"]
        if factor is None:
            return adjusted
        for field in ("open", "high", "low", "close", "pre_close", "vwap", "limit_up", "limit_down"):
            if field in adjusted and adjusted[field] is not None:
                adjusted[field] = round(float(adjusted[field]) * float(factor), 6)
        return adjusted

    def _factor_rows_to_wide(self, rows: list[dict[str, Any]], factors: list[str]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["symbol"], row["trade_date"])
            item = grouped.setdefault(
                key,
                {
                    "symbol": row["symbol"],
                    "security_id": row["security_id"],
                    "trade_date": row["trade_date"],
                },
            )
            item[row["factor_code"]] = row["factor_value"]
        for item in grouped.values():
            for factor in factors:
                item.setdefault(factor, None)
        return list(grouped.values())

    @staticmethod
    def _where(clauses: list[str]) -> str:
        return "WHERE " + " AND ".join(f"({clause})" for clause in clauses) if clauses else ""

    @staticmethod
    def _validate_fields(fields: list[str], allowed_fields: set[str], field_name: str) -> None:
        invalid = sorted(set(fields) - allowed_fields)
        if invalid:
            raise QDataValidationError(f"Unsupported {field_name}: {invalid}")

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        parts = symbol.split(".")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise QDataValidationError(f"Invalid symbol format: {symbol}")
        return parts[0], parts[1]
