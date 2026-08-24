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
        normalized_symbols = None
        if symbols:
            symbol_parts = [self._split_symbol(symbol) for symbol in symbols]
            normalized_symbols = [f"{code}.{exchange}" for code, exchange in symbol_parts]
            params["symbols"] = normalized_symbols
        if security_ids:
            where.append("sm.security_id = ANY(%(security_ids)s)")
            params["security_ids"] = security_ids
        if asset_types:
            where.append("sm.asset_type = ANY(%(asset_types)s)")
            params["asset_types"] = asset_types
        if exchanges:
            params["exchanges"] = exchanges
        if asof_date:
            parse_date(asof_date, "asof_date")
            params["asof_date"] = asof_date
            if normalized_symbols:
                where.append("(identifier.symbol || '.' || identifier.exchange) = ANY(%(symbols)s)")
            if exchanges:
                where.append("identifier.exchange = ANY(%(exchanges)s)")
            if not include_delisted:
                where.append("status_history.status <> 'delisted'")
            sql = f"""
                SELECT
                    sm.security_id,
                    identifier.symbol || '.' || identifier.exchange AS symbol,
                    sm.asset_type,
                    identifier.exchange,
                    name_history.name,
                    identifier.historical_list_date AS list_date,
                    CASE
                        WHEN status_history.status = 'delisted'
                        THEN status_history.start_date
                        ELSE NULL
                    END AS delist_date,
                    status_history.status,
                    sm.currency
                FROM qmeta.security_master sm
                JOIN LATERAL (
                    SELECT identifier_revision.symbol, identifier_revision.exchange,
                           identifier_revision.historical_list_date
                    FROM (
                        SELECT sih.*,
                            MIN(sih.start_date) OVER (
                                PARTITION BY sih.security_id
                            ) AS historical_list_date,
                            ROW_NUMBER() OVER (
                                PARTITION BY sih.security_id, sih.identifier_type,
                                             sih.start_date
                                ORDER BY sih.revision_id DESC, sih.ingest_time DESC,
                                         sih.batch_id DESC, sih.symbol DESC
                            ) AS revision_rank
                        FROM qmeta.security_identifier_history sih
                        JOIN qmeta.data_batch db_identifier
                          ON db_identifier.batch_id = sih.batch_id
                        JOIN qmeta.dataset_catalog dc_identifier
                          ON dc_identifier.dataset_id = db_identifier.dataset_id
                        WHERE sih.security_id = sm.security_id
                          AND sih.identifier_type = 'trade_symbol'
                          AND sih.start_date <= %(asof_date)s
                          AND dc_identifier.dataset_code = 'security_master'
                          AND db_identifier.status = 'success'
                          AND db_identifier.finished_at IS NOT NULL
                          AND db_identifier.finished_at <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND sih.announce_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND sih.ingest_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                    ) identifier_revision
                    WHERE identifier_revision.revision_rank = 1
                      AND (identifier_revision.end_date IS NULL
                           OR identifier_revision.end_date >= %(asof_date)s)
                    ORDER BY identifier_revision.start_date DESC,
                             identifier_revision.revision_id DESC,
                             identifier_revision.ingest_time DESC,
                             identifier_revision.batch_id DESC,
                             identifier_revision.symbol DESC
                    LIMIT 1
                ) identifier ON TRUE
                JOIN LATERAL (
                    SELECT name_revision.name
                    FROM (
                        SELECT snh.*,
                            ROW_NUMBER() OVER (
                                PARTITION BY snh.security_id, snh.start_date
                                ORDER BY snh.revision_id DESC, snh.ingest_time DESC,
                                         snh.batch_id DESC, snh.name DESC
                            ) AS revision_rank
                        FROM qmeta.security_name_history snh
                        JOIN qmeta.data_batch db_name
                          ON db_name.batch_id = snh.batch_id
                        JOIN qmeta.dataset_catalog dc_name
                          ON dc_name.dataset_id = db_name.dataset_id
                        WHERE snh.security_id = sm.security_id
                          AND snh.start_date <= %(asof_date)s
                          AND dc_name.dataset_code = 'security_master'
                          AND db_name.status = 'success'
                          AND db_name.finished_at IS NOT NULL
                          AND db_name.finished_at <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND snh.announce_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND snh.ingest_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                    ) name_revision
                    WHERE name_revision.revision_rank = 1
                      AND (name_revision.end_date IS NULL
                           OR name_revision.end_date >= %(asof_date)s)
                    ORDER BY name_revision.start_date DESC,
                             name_revision.revision_id DESC,
                             name_revision.ingest_time DESC,
                             name_revision.batch_id DESC,
                             name_revision.name DESC
                    LIMIT 1
                ) name_history ON TRUE
                JOIN LATERAL (
                    SELECT status_revision.status, status_revision.start_date
                    FROM (
                        SELECT ssh.*,
                            ROW_NUMBER() OVER (
                                PARTITION BY ssh.security_id, ssh.start_date
                                ORDER BY ssh.revision_id DESC, ssh.ingest_time DESC,
                                         ssh.batch_id DESC, ssh.status DESC
                            ) AS revision_rank
                        FROM qmeta.security_status_history ssh
                        JOIN qmeta.data_batch db_status
                          ON db_status.batch_id = ssh.batch_id
                        JOIN qmeta.dataset_catalog dc_status
                          ON dc_status.dataset_id = db_status.dataset_id
                        WHERE ssh.security_id = sm.security_id
                          AND ssh.start_date <= %(asof_date)s
                          AND dc_status.dataset_code = 'security_master'
                          AND db_status.status = 'success'
                          AND db_status.finished_at IS NOT NULL
                          AND db_status.finished_at <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND ssh.announce_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND ssh.ingest_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                    ) status_revision
                    WHERE status_revision.revision_rank = 1
                      AND (status_revision.end_date IS NULL
                           OR status_revision.end_date >= %(asof_date)s)
                    ORDER BY status_revision.start_date DESC,
                             status_revision.revision_id DESC,
                             status_revision.ingest_time DESC,
                             status_revision.batch_id DESC,
                             status_revision.status DESC
                    LIMIT 1
                ) status_history ON TRUE
                {self._where(where)}
                ORDER BY identifier.exchange, identifier.symbol
            """
        else:
            if normalized_symbols:
                where.append("(sm.current_symbol || '.' || sm.exchange) = ANY(%(symbols)s)")
            if exchanges:
                where.append("sm.exchange = ANY(%(exchanges)s)")
            if not include_delisted:
                where.append("sm.current_status <> 'delisted'")
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
        if frequency == "1m" and adjust != "none":
            raise QDataValidationError(
                "minute-bar adjustment is not supported; use adjust='none'"
            )
        cutoff = self._validate_price_mode(query_mode, asof_time, data_version)

        security_map = self._resolve_security_map(symbols, security_ids, universe, asof_date=end_date)
        requested_fields = fields or ["open", "high", "low", "close", "volume", "amount"]
        allowed_fields = self.PRICE_FIELDS if frequency == "1d" else self.MINUTE_FIELDS
        self._validate_fields(requested_fields, allowed_fields, "fields")

        table = "qts.daily_bar" if frequency == "1d" else "qts.minute_bar"
        dataset_code = "daily_bar" if frequency == "1d" else "minute_bar"
        allowed_versions = self._resolve_allowed_dataset_versions(
            dataset_code,
            query_mode=query_mode,
            asof_time=cutoff,
            requested_version=data_version,
        )
        base_fields = ["security_id", "trade_date"]
        if frequency == "1m":
            base_fields.append("bar_time")
        select_fields = base_fields + requested_fields
        order_fields = "security_id, trade_date" + (", bar_time" if frequency == "1m" else "")
        where = [
            "security_id IN %(security_ids)s",
            "trade_date BETWEEN %(start_date)s AND %(end_date)s",
            "data_version IN %(allowed_data_versions)s",
        ]
        params: dict[str, Any] = {
            "security_ids": tuple(security_map),
            "start_date": start_date,
            "end_date": end_date,
            "allowed_data_versions": tuple(row["data_version"] for row in allowed_versions),
        }
        if cutoff is not None:
            where.append("ingest_time <= %(asof_time)s")
            params["asof_time"] = cutoff
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
            knowledge_cutoff = cutoff
            if query_mode == "vintage":
                publication_time = allowed_versions[0].get("finished_at")
                if publication_time is None:
                    raise QDataNotFoundError(
                        "Selected daily-bar data version has no publication time"
                    )
                knowledge_cutoff = self._parse_aware_datetime(publication_time)
            factors = self._get_adjustment_factor_map(
                list(security_map),
                start_date,
                end_date,
                knowledge_cutoff=knowledge_cutoff,
            )
            normalized = [self._apply_adjustment(row, adjust, factors) for row in normalized]
        for row in normalized:
            row["symbol"] = security_map.get(row["security_id"])
        projected = project(normalized, ["symbol"] + select_fields)
        resolved_version_code = allowed_versions[0]["version_code"] if query_mode == "vintage" else None
        return response(
            projected,
            [row["version_code"] for row in allowed_versions],
            query_mode,
            cutoff.isoformat() if cutoff is not None else None,
            resolved_version_code,
        )

    def get_adjustment_factor(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        start_date: str | None,
        end_date: str | None,
        factor_type: str,
        query_mode: str,
    ) -> dict[str, Any]:
        if query_mode != "latest":
            raise QDataValidationError(
                "get_adjustment_factor only supports query_mode='latest'; its public "
                "signature does not expose a knowledge cutoff or immutable data version"
            )
        start_date, end_date = ensure_required_dates(start_date, end_date)
        validate_enum(factor_type, {"forward", "backward", "both"}, "factor_type")
        validate_enum(query_mode, {"latest", "asof", "vintage"}, "query_mode")
        security_map = self._resolve_security_map(symbols, security_ids, None, asof_date=end_date)

        fields = ["security_id", "trade_date", "ex_right_type"]
        if factor_type in {"forward", "both"}:
            fields.append("factor_forward")
        if factor_type in {"backward", "both"}:
            fields.append("factor_backward")
        selected_fields = ", ".join(f"af.{field} AS {field}" for field in fields)

        rows = self.postgres.fetch_all(
            f"""
            SELECT DISTINCT ON (af.security_id, af.trade_date) {selected_fields}
            FROM qmeta.adjustment_factor af
            JOIN qmeta.data_batch db ON db.batch_id = af.batch_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
            WHERE af.security_id = ANY(%(security_ids)s)
              AND af.trade_date BETWEEN %(start_date)s AND %(end_date)s
              AND dc.dataset_code IN ('daily_bar', 'adjustment_factor')
              AND db.status = 'success'
              AND db.finished_at IS NOT NULL
            ORDER BY af.security_id, af.trade_date, af.revision_id DESC, af.ingest_time DESC,
                     af.batch_id DESC
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
        if symbols and start_date != end_date:
            security_ids = self._resolve_security_ids_over_range(
                symbols,
                start_date,
                end_date,
            )
            security_map: dict[int, str] = {}
        else:
            security_map = self._resolve_security_map(
                symbols,
                None,
                universe,
                asof_date=end_date,
            )
            security_ids = list(security_map)
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
            WITH visible_limits AS (
                SELECT
                    lp.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY lp.security_id, lp.trade_date
                        ORDER BY lp.revision_id DESC, lp.ingest_time DESC,
                                 lp.batch_id DESC
                    ) AS revision_rank
                FROM qmeta.limit_price_daily lp
                JOIN qmeta.data_batch db_limit ON db_limit.batch_id = lp.batch_id
                JOIN qmeta.dataset_catalog dc_limit
                  ON dc_limit.dataset_id = db_limit.dataset_id
                WHERE lp.security_id = ANY(%(security_ids)s)
                  AND lp.trade_date BETWEEN %(start_date)s AND %(end_date)s
                  AND dc_limit.dataset_code IN ('limit_price_daily', 'daily_bar')
                  AND db_limit.status = 'success'
                  AND db_limit.finished_at IS NOT NULL
                  AND db_limit.finished_at < (lp.trade_date + INTERVAL '1 day')
                  AND lp.ingest_time < (lp.trade_date + INTERVAL '1 day')
            ),
            selected_limits AS (
                SELECT * FROM visible_limits WHERE revision_rank = 1
            ),
            visible_suspension_day_revisions AS (
                SELECT
                    sh.*,
                    generated.trade_date::date AS trade_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY sh.security_id, sh.start_time,
                                     generated.trade_date::date
                        ORDER BY sh.revision_id DESC, sh.ingest_time DESC,
                                 sh.batch_id DESC
                    ) AS revision_rank
                FROM qmeta.suspension_history sh
                JOIN qmeta.data_batch db_suspension
                  ON db_suspension.batch_id = sh.batch_id
                JOIN qmeta.dataset_catalog dc_suspension
                  ON dc_suspension.dataset_id = db_suspension.dataset_id
                CROSS JOIN LATERAL generate_series(
                    GREATEST(sh.start_time::date, %(start_date)s::date),
                    %(end_date)s::date,
                    INTERVAL '1 day'
                ) AS generated(trade_date)
                WHERE sh.security_id = ANY(%(security_ids)s)
                  AND sh.start_time::date <= %(end_date)s
                  AND dc_suspension.dataset_code IN (
                      'suspension_history', 'daily_bar'
                  )
                  AND db_suspension.status = 'success'
                  AND db_suspension.finished_at IS NOT NULL
                  AND db_suspension.finished_at <
                      (generated.trade_date::date + INTERVAL '1 day')
                  AND sh.announce_time IS NOT NULL
                  AND sh.announce_time <
                      (generated.trade_date::date + INTERVAL '1 day')
                  AND sh.ingest_time <
                      (generated.trade_date::date + INTERVAL '1 day')
            ),
            selected_suspension_days AS (
                SELECT * FROM visible_suspension_day_revisions
                WHERE revision_rank = 1
                  AND start_time::date <= trade_date
                  AND (end_time IS NULL OR end_time::date >= trade_date)
            ),
            constraint_spine AS (
                SELECT security_id, trade_date FROM selected_limits
                UNION
                SELECT security_id, trade_date FROM selected_suspension_days
            )
            SELECT
                sm.security_id,
                identifier.symbol || '.' || identifier.exchange AS symbol,
                spine.trade_date,
                COALESCE(lp.limit_up, NULL) AS limit_up,
                COALESCE(lp.limit_down, NULL) AS limit_down,
                COALESCE(lp.is_st, FALSE) AS is_st,
                COALESCE(lp.is_new_listing, FALSE) AS is_new_listing,
                EXISTS (
                    SELECT 1
                    FROM selected_suspension_days suspension_day
                    WHERE suspension_day.security_id = spine.security_id
                      AND suspension_day.trade_date = spine.trade_date
                ) AS is_suspended,
                COALESCE(st.status = 'delisting_period', FALSE) AS is_delisting_period,
                GREATEST(
                    (
                        spine.trade_date
                        - COALESCE(
                            historical_identity.historical_list_date,
                            spine.trade_date
                        )
                    ),
                    0
                ) AS list_days
            FROM constraint_spine spine
            LEFT JOIN selected_limits lp
              ON lp.security_id = spine.security_id
             AND lp.trade_date = spine.trade_date
            JOIN qmeta.security_master sm ON sm.security_id = spine.security_id
            JOIN LATERAL (
                SELECT identifier_revision.symbol, identifier_revision.exchange
                FROM (
                    SELECT sih.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY sih.security_id, sih.identifier_type,
                                         sih.start_date
                            ORDER BY sih.revision_id DESC, sih.ingest_time DESC,
                                     sih.batch_id DESC, sih.symbol DESC
                        ) AS revision_rank
                    FROM qmeta.security_identifier_history sih
                    JOIN qmeta.data_batch db_identifier_symbol
                      ON db_identifier_symbol.batch_id = sih.batch_id
                    JOIN qmeta.dataset_catalog dc_identifier_symbol
                      ON dc_identifier_symbol.dataset_id = db_identifier_symbol.dataset_id
                    WHERE sih.security_id = spine.security_id
                      AND sih.identifier_type = 'trade_symbol'
                      AND sih.start_date <= spine.trade_date
                      AND dc_identifier_symbol.dataset_code = 'security_master'
                      AND db_identifier_symbol.status = 'success'
                      AND db_identifier_symbol.finished_at IS NOT NULL
                      AND db_identifier_symbol.finished_at <
                          (spine.trade_date + INTERVAL '1 day')
                      AND sih.announce_time <
                          (spine.trade_date + INTERVAL '1 day')
                      AND sih.ingest_time <
                          (spine.trade_date + INTERVAL '1 day')
                ) identifier_revision
                WHERE identifier_revision.revision_rank = 1
                  AND (identifier_revision.end_date IS NULL
                       OR identifier_revision.end_date >= spine.trade_date)
                ORDER BY identifier_revision.start_date DESC,
                         identifier_revision.revision_id DESC,
                         identifier_revision.ingest_time DESC,
                         identifier_revision.batch_id DESC,
                         identifier_revision.symbol DESC
                LIMIT 1
            ) identifier ON TRUE
            LEFT JOIN LATERAL (
                SELECT MIN(identifier_revision.start_date) AS historical_list_date
                FROM (
                    SELECT sih.start_date,
                        ROW_NUMBER() OVER (
                            PARTITION BY sih.security_id, sih.identifier_type,
                                         sih.start_date
                            ORDER BY sih.revision_id DESC, sih.ingest_time DESC,
                                     sih.batch_id DESC, sih.symbol DESC
                        ) AS revision_rank
                    FROM qmeta.security_identifier_history sih
                    JOIN qmeta.data_batch db_identifier
                      ON db_identifier.batch_id = sih.batch_id
                    JOIN qmeta.dataset_catalog dc_identifier
                      ON dc_identifier.dataset_id = db_identifier.dataset_id
                    WHERE sih.security_id = spine.security_id
                      AND sih.identifier_type = 'trade_symbol'
                      AND sih.start_date <= spine.trade_date
                      AND dc_identifier.dataset_code = 'security_master'
                      AND db_identifier.status = 'success'
                      AND db_identifier.finished_at IS NOT NULL
                      AND db_identifier.finished_at <
                          (spine.trade_date + INTERVAL '1 day')
                      AND sih.announce_time <
                          (spine.trade_date + INTERVAL '1 day')
                      AND sih.ingest_time <
                          (spine.trade_date + INTERVAL '1 day')
                ) identifier_revision
                WHERE identifier_revision.revision_rank = 1
            ) historical_identity ON TRUE
            LEFT JOIN LATERAL (
                SELECT status_revision.status
                FROM (
                    SELECT st.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY st.security_id, st.start_date
                            ORDER BY st.revision_id DESC, st.ingest_time DESC,
                                     st.batch_id DESC, st.status DESC
                        ) AS revision_rank
                    FROM qmeta.security_status_history st
                    JOIN qmeta.data_batch db_status
                      ON db_status.batch_id = st.batch_id
                    JOIN qmeta.dataset_catalog dc_status
                      ON dc_status.dataset_id = db_status.dataset_id
                    WHERE st.security_id = spine.security_id
                      AND st.start_date <= spine.trade_date
                      AND dc_status.dataset_code = 'security_master'
                      AND db_status.status = 'success'
                      AND db_status.finished_at IS NOT NULL
                      AND db_status.finished_at <
                          (spine.trade_date + INTERVAL '1 day')
                      AND st.announce_time <
                          (spine.trade_date + INTERVAL '1 day')
                      AND st.ingest_time <
                          (spine.trade_date + INTERVAL '1 day')
                ) status_revision
                WHERE status_revision.revision_rank = 1
                  AND (status_revision.end_date IS NULL
                       OR status_revision.end_date >= spine.trade_date)
                ORDER BY status_revision.start_date DESC,
                         status_revision.revision_id DESC,
                         status_revision.ingest_time DESC,
                         status_revision.batch_id DESC,
                         status_revision.status DESC
                LIMIT 1
            ) st ON TRUE
            ORDER BY spine.security_id, spine.trade_date
            """,
            {
                "security_ids": security_ids,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        normalized = normalize_rows(rows)
        for row in normalized:
            if not row.get("symbol"):
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
                    'metric'::text AS source_kind,
                    fm.security_id,
                    fm.report_period,
                    fm.metric_scope AS natural_scope,
                    fm.metric_name AS field_name,
                    fm.metric_value AS field_value,
                    fm.announce_time,
                    fm.effective_time,
                    fm.ingest_time,
                    fm.batch_id,
                    fm.revision_id,
                    fm.is_restated
                FROM qpit.financial_metric_pit fm
                JOIN qmeta.data_batch db_metric
                  ON db_metric.batch_id = fm.batch_id
                JOIN qmeta.dataset_catalog dc_metric
                  ON dc_metric.dataset_id = db_metric.dataset_id
                WHERE fm.security_id = ANY(%(security_ids)s)
                  AND fm.metric_name = ANY(%(fields)s)
                  AND fm.metric_scope = %(period_type)s
                  AND dc_metric.dataset_code = 'financial_metric_pit'
                  AND db_metric.status = 'success'
                  AND db_metric.finished_at IS NOT NULL
                  AND db_metric.finished_at < (%(asof_date)s::date + INTERVAL '1 day')
                  AND fm.announce_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND fm.effective_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND fm.ingest_time < (%(asof_date)s::date + INTERVAL '1 day')
                  {report_filter}

                UNION ALL

                SELECT
                    'statement:' || fs.statement_type AS source_kind,
                    fs.security_id,
                    fs.report_period,
                    fs.period_type AS natural_scope,
                    fs.field_name,
                    fs.field_value,
                    fs.announce_time,
                    fs.effective_time,
                    fs.ingest_time,
                    fs.batch_id,
                    fs.revision_id,
                    fs.is_restated
                FROM qpit.financial_statement_pit fs
                JOIN qmeta.data_batch db_statement
                  ON db_statement.batch_id = fs.batch_id
                JOIN qmeta.dataset_catalog dc_statement
                  ON dc_statement.dataset_id = db_statement.dataset_id
                WHERE fs.security_id = ANY(%(security_ids)s)
                  AND fs.field_name = ANY(%(fields)s)
                  AND fs.period_type = %(period_type)s
                  AND dc_statement.dataset_code = 'financial_statement_pit'
                  AND db_statement.status = 'success'
                  AND db_statement.finished_at IS NOT NULL
                  AND db_statement.finished_at < (%(asof_date)s::date + INTERVAL '1 day')
                  AND fs.announce_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND fs.effective_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND fs.ingest_time < (%(asof_date)s::date + INTERVAL '1 day')
                  {report_filter}
            ),
            revision_ranked AS (
                SELECT source_rows.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_kind, security_id, report_period,
                                     natural_scope, field_name
                        ORDER BY revision_id DESC, ingest_time DESC, batch_id DESC
                    ) AS revision_rank
                FROM source_rows
            ),
            visible_revisions AS (
                SELECT * FROM revision_ranked WHERE revision_rank = 1
            ),
            ranked AS (
                SELECT visible_revisions.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY security_id, field_name
                        ORDER BY report_period DESC, announce_time DESC,
                                 ingest_time DESC, revision_id DESC, source_kind DESC
                    ) AS rn
                FROM visible_revisions
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
            WITH known_revisions AS (
                SELECT
                    mp.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY mp.index_id, mp.security_id, mp.effective_date
                        ORDER BY mp.revision_id DESC, mp.ingest_time DESC,
                                 mp.batch_id DESC
                    ) AS revision_rank
                FROM qpit.index_member_pit mp
                JOIN qmeta.index_master im_filter ON im_filter.index_id = mp.index_id
                JOIN qmeta.data_batch db ON db.batch_id = mp.batch_id
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
                WHERE im_filter.index_code = %(index_code)s
                  AND dc.dataset_code = 'index_member_pit'
                  AND db.status = 'success'
                  AND db.finished_at IS NOT NULL
                  AND db.finished_at < (%(asof_date)s::date + INTERVAL '1 day')
                  AND mp.announce_time IS NOT NULL
                  AND mp.announce_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND mp.ingest_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND mp.effective_date <= %(asof_date)s
            ),
            selected_members AS (
                SELECT *
                FROM known_revisions
                WHERE revision_rank = 1
                  AND (end_date IS NULL OR end_date >= %(asof_date)s)
            )
            SELECT
                im.index_code,
                identifier.symbol || '.' || identifier.exchange AS symbol,
                sm.security_id,
                mp.effective_date,
                mp.end_date,
                mp.weight
            FROM selected_members mp
            JOIN qmeta.index_master im ON im.index_id = mp.index_id
            JOIN qmeta.security_master sm ON sm.security_id = mp.security_id
            JOIN LATERAL (
                SELECT identifier_revision.symbol, identifier_revision.exchange
                FROM (
                    SELECT sih.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY sih.security_id, sih.identifier_type,
                                         sih.start_date
                            ORDER BY sih.revision_id DESC, sih.ingest_time DESC,
                                     sih.batch_id DESC, sih.symbol DESC
                        ) AS revision_rank
                    FROM qmeta.security_identifier_history sih
                    JOIN qmeta.data_batch db_identifier
                      ON db_identifier.batch_id = sih.batch_id
                    JOIN qmeta.dataset_catalog dc_identifier
                      ON dc_identifier.dataset_id = db_identifier.dataset_id
                    WHERE sih.security_id = sm.security_id
                      AND sih.identifier_type = 'trade_symbol'
                      AND sih.start_date <= %(asof_date)s
                      AND dc_identifier.dataset_code = 'security_master'
                      AND db_identifier.status = 'success'
                      AND db_identifier.finished_at IS NOT NULL
                      AND db_identifier.finished_at <
                          (%(asof_date)s::date + INTERVAL '1 day')
                      AND sih.announce_time <
                          (%(asof_date)s::date + INTERVAL '1 day')
                      AND sih.ingest_time <
                          (%(asof_date)s::date + INTERVAL '1 day')
                ) identifier_revision
                WHERE identifier_revision.revision_rank = 1
                  AND (identifier_revision.end_date IS NULL
                       OR identifier_revision.end_date >= %(asof_date)s)
                ORDER BY identifier_revision.start_date DESC,
                         identifier_revision.revision_id DESC,
                         identifier_revision.ingest_time DESC,
                         identifier_revision.batch_id DESC,
                         identifier_revision.symbol DESC
                LIMIT 1
            ) identifier ON TRUE
            ORDER BY mp.weight DESC NULLS LAST, identifier.exchange, identifier.symbol
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
            WITH category_revisions AS (
                SELECT
                    ich.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY ich.industry_id, ich.start_date
                        ORDER BY ich.revision_id DESC, ich.ingest_time DESC,
                                 ich.batch_id DESC, ich.industry_code DESC,
                                 ich.industry_name DESC
                    ) AS revision_rank
                FROM qmeta.industry_category_history ich
                JOIN qmeta.industry_system sys_category
                  ON sys_category.industry_system_id = ich.industry_system_id
                JOIN qmeta.data_batch db_category
                  ON db_category.batch_id = ich.batch_id
                JOIN qmeta.dataset_catalog dc_category
                  ON dc_category.dataset_id = db_category.dataset_id
                WHERE sys_category.system_code = %(industry_system)s
                  AND ich.level = %(level)s
                  AND ich.start_date <= %(asof_date)s
                  AND dc_category.dataset_code = 'industry_membership_pit'
                  AND db_category.status = 'success'
                  AND db_category.finished_at IS NOT NULL
                  AND db_category.finished_at <
                      (%(asof_date)s::date + INTERVAL '1 day')
                  AND ich.announce_time <
                      (%(asof_date)s::date + INTERVAL '1 day')
                  AND ich.ingest_time <
                      (%(asof_date)s::date + INTERVAL '1 day')
            ),
            visible_category_episodes AS (
                SELECT * FROM category_revisions
                WHERE revision_rank = 1
                  AND (end_date IS NULL OR end_date >= %(asof_date)s)
            ),
            selected_categories AS (
                SELECT
                    visible_category_episodes.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY industry_id
                        ORDER BY start_date DESC, revision_id DESC,
                                 ingest_time DESC, batch_id DESC,
                                 industry_code DESC, industry_name DESC
                    ) AS category_rank
                FROM visible_category_episodes
            ),
            known_revisions AS (
                SELECT
                    mem.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY mem.security_id, mem.industry_system_id,
                                     cat_filter.level, mem.effective_date
                        ORDER BY mem.revision_id DESC, mem.ingest_time DESC,
                                 mem.batch_id DESC, mem.industry_id DESC
                    ) AS revision_rank
                FROM qpit.industry_membership_pit mem
                JOIN qmeta.industry_system sys_filter
                  ON sys_filter.industry_system_id = mem.industry_system_id
                JOIN selected_categories cat_filter
                  ON cat_filter.industry_id = mem.industry_id
                 AND cat_filter.industry_system_id = mem.industry_system_id
                 AND cat_filter.category_rank = 1
                JOIN qmeta.data_batch db ON db.batch_id = mem.batch_id
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
                WHERE mem.security_id = ANY(%(security_ids)s)
                  AND sys_filter.system_code = %(industry_system)s
                  AND cat_filter.level = %(level)s
                  AND dc.dataset_code = 'industry_membership_pit'
                  AND db.status = 'success'
                  AND db.finished_at IS NOT NULL
                  AND db.finished_at < (%(asof_date)s::date + INTERVAL '1 day')
                  AND mem.announce_time IS NOT NULL
                  AND mem.announce_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND mem.ingest_time < (%(asof_date)s::date + INTERVAL '1 day')
                  AND mem.effective_date <= %(asof_date)s
            ),
            selected_members AS (
                SELECT * FROM known_revisions
                WHERE revision_rank = 1
                  AND (end_date IS NULL OR end_date >= %(asof_date)s)
            )
            SELECT
                identifier.symbol || '.' || identifier.exchange AS symbol,
                sm.security_id,
                sys.system_code AS industry_system,
                cat.level,
                cat.industry_code,
                cat.industry_name,
                mem.effective_date,
                mem.end_date
            FROM selected_members mem
            JOIN qmeta.security_master sm ON sm.security_id = mem.security_id
            JOIN qmeta.industry_system sys ON sys.industry_system_id = mem.industry_system_id
            JOIN selected_categories cat
              ON cat.industry_id = mem.industry_id
             AND cat.category_rank = 1
            JOIN LATERAL (
                SELECT identifier_revision.symbol, identifier_revision.exchange
                FROM (
                    SELECT sih.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY sih.security_id, sih.identifier_type,
                                         sih.start_date
                            ORDER BY sih.revision_id DESC, sih.ingest_time DESC,
                                     sih.batch_id DESC, sih.symbol DESC
                        ) AS revision_rank
                    FROM qmeta.security_identifier_history sih
                    JOIN qmeta.data_batch db_identifier
                      ON db_identifier.batch_id = sih.batch_id
                    JOIN qmeta.dataset_catalog dc_identifier
                      ON dc_identifier.dataset_id = db_identifier.dataset_id
                    WHERE sih.security_id = sm.security_id
                      AND sih.identifier_type = 'trade_symbol'
                      AND sih.start_date <= %(asof_date)s
                      AND dc_identifier.dataset_code = 'security_master'
                      AND db_identifier.status = 'success'
                      AND db_identifier.finished_at IS NOT NULL
                      AND db_identifier.finished_at <
                          (%(asof_date)s::date + INTERVAL '1 day')
                      AND sih.announce_time <
                          (%(asof_date)s::date + INTERVAL '1 day')
                      AND sih.ingest_time <
                          (%(asof_date)s::date + INTERVAL '1 day')
                ) identifier_revision
                WHERE identifier_revision.revision_rank = 1
                  AND (identifier_revision.end_date IS NULL
                       OR identifier_revision.end_date >= %(asof_date)s)
                ORDER BY identifier_revision.start_date DESC,
                         identifier_revision.revision_id DESC,
                         identifier_revision.ingest_time DESC,
                         identifier_revision.batch_id DESC,
                         identifier_revision.symbol DESC
                LIMIT 1
            ) identifier ON TRUE
            WHERE cat.level = %(level)s
            ORDER BY identifier.exchange, identifier.symbol
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
                WITH definition AS (
                    SELECT universe_id, universe_code, universe_type
                    FROM qmeta.universe_definition
                    WHERE universe_code = %(universe)s
                ),
                snapshot_batch AS (
                    SELECT db.batch_id
                    FROM qmeta.universe_snapshot us
                    JOIN definition ud ON ud.universe_id = us.universe_id
                    JOIN qmeta.data_batch db ON db.batch_id = us.batch_id
                    JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
                    WHERE dc.dataset_code = 'tradable_universe'
                      AND us.trade_date = %(asof_date)s
                      AND db.status = 'success'
                      AND db.finished_at IS NOT NULL
                      AND db.finished_at < (%(asof_date)s::date + INTERVAL '1 day')
                    ORDER BY db.finished_at DESC, db.batch_id DESC
                    LIMIT 1
                ),
                known_revisions AS (
                    SELECT
                        um.*,
                        ud.universe_code,
                        ud.universe_type,
                        ROW_NUMBER() OVER (
                            PARTITION BY um.universe_id, um.security_id,
                                         um.effective_date
                            ORDER BY um.revision_id DESC, um.ingest_time DESC,
                                     um.batch_id DESC
                        ) AS revision_rank
                    FROM qpit.universe_member_pit um
                    JOIN definition ud ON ud.universe_id = um.universe_id
                    JOIN qmeta.data_batch db ON db.batch_id = um.batch_id
                    JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
                    WHERE db.status = 'success'
                      AND db.finished_at IS NOT NULL
                      AND db.finished_at < (%(asof_date)s::date + INTERVAL '1 day')
                      AND um.announce_time IS NOT NULL
                      AND um.announce_time < (%(asof_date)s::date + INTERVAL '1 day')
                      AND um.ingest_time < (%(asof_date)s::date + INTERVAL '1 day')
                      AND (
                          (
                              ud.universe_type = 'rule_based'
                              AND dc.dataset_code = 'tradable_universe'
                              AND um.batch_id = (SELECT batch_id FROM snapshot_batch)
                              AND um.effective_date = %(asof_date)s
                          )
                          OR (
                              ud.universe_type <> 'rule_based'
                              AND dc.dataset_code = 'universe_member_pit'
                              AND um.effective_date <= %(asof_date)s
                          )
                      )
                ),
                selected_members AS (
                    SELECT * FROM known_revisions
                    WHERE revision_rank = 1
                      AND (end_date IS NULL OR end_date >= %(asof_date)s)
                )
                SELECT
                    um.universe_code AS universe,
                    identifier.symbol || '.' || identifier.exchange AS symbol,
                    sm.security_id,
                    %(asof_date)s::date AS asof_date,
                    um.weight
                FROM selected_members um
                JOIN qmeta.security_master sm ON sm.security_id = um.security_id
                JOIN LATERAL (
                    SELECT identifier_revision.symbol, identifier_revision.exchange
                    FROM (
                        SELECT sih.*,
                            ROW_NUMBER() OVER (
                                PARTITION BY sih.security_id, sih.identifier_type,
                                             sih.start_date
                                ORDER BY sih.revision_id DESC, sih.ingest_time DESC,
                                         sih.batch_id DESC, sih.symbol DESC
                            ) AS revision_rank
                        FROM qmeta.security_identifier_history sih
                        JOIN qmeta.data_batch db_identifier
                          ON db_identifier.batch_id = sih.batch_id
                        JOIN qmeta.dataset_catalog dc_identifier
                          ON dc_identifier.dataset_id = db_identifier.dataset_id
                        WHERE sih.security_id = sm.security_id
                          AND sih.identifier_type = 'trade_symbol'
                          AND sih.start_date <= %(asof_date)s
                          AND dc_identifier.dataset_code = 'security_master'
                          AND db_identifier.status = 'success'
                          AND db_identifier.finished_at IS NOT NULL
                          AND db_identifier.finished_at <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND sih.announce_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                          AND sih.ingest_time <
                              (%(asof_date)s::date + INTERVAL '1 day')
                    ) identifier_revision
                    WHERE identifier_revision.revision_rank = 1
                      AND (identifier_revision.end_date IS NULL
                           OR identifier_revision.end_date >= %(asof_date)s)
                    ORDER BY identifier_revision.start_date DESC,
                             identifier_revision.revision_id DESC,
                             identifier_revision.ingest_time DESC,
                             identifier_revision.batch_id DESC,
                             identifier_revision.symbol DESC
                    LIMIT 1
                ) identifier ON TRUE
                ORDER BY identifier.exchange, identifier.symbol
                """,
                {"universe": universe, "asof_date": asof_date},
            )
            rows = normalize_rows(rows)
        if filters and rows:
            symbols = [row["symbol"] for row in rows]
            constraints = {
                row["symbol"]: row
                for row in self.get_trading_constraints(symbols, None, asof_date, asof_date, None)["data"]
            }
            filtered = []
            for row in rows:
                constraint = constraints.get(row["symbol"])
                if constraint is None:
                    # A filtered universe is a trading decision surface. Missing
                    # constraint evidence must exclude the member, not silently
                    # treat every risk flag as false.
                    continue
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
        if query_mode != "latest":
            raise QDataValidationError(
                "get_factor only supports query_mode='latest'; its public signature "
                "does not expose a knowledge cutoff or immutable data version"
            )
        if self.clickhouse is None:
            raise QDataValidationError("clickhouse_dsn or clickhouse client is required for factor queries")
        start_date, end_date = ensure_required_dates(start_date, end_date)
        validate_enum(format, {"long", "wide"}, "format")
        validate_enum(query_mode, {"latest", "asof", "vintage"}, "query_mode")
        security_map = self._resolve_security_map(symbols, None, universe, asof_date=end_date)
        factor_map = self._resolve_factor_map(factors, factor_version)
        factor_pair_clauses = []
        params: dict[str, Any] = {
            "security_ids": tuple(security_map),
            "start_date": start_date,
            "end_date": end_date,
        }
        for index, (factor_id, factor) in enumerate(sorted(factor_map.items())):
            factor_id_param = f"factor_pair_{index}_factor_id"
            version_id_param = f"factor_pair_{index}_version_id"
            factor_pair_clauses.append(
                f"(factor_id = %({factor_id_param})s "
                f"AND factor_version_id = %({version_id_param})s)"
            )
            params[factor_id_param] = factor_id
            params[version_id_param] = factor["factor_version_id"]
        rows = self.clickhouse.fetch_all(
            f"""
            SELECT factor_id, factor_version_id, security_id, trade_date,
                   factor_value, quality_flag, data_version, calc_time
            FROM (
                SELECT
                    factor_id,
                    factor_version_id,
                    security_id,
                    trade_date,
                    factor_value,
                    quality_flag,
                    data_version,
                    calc_time,
                    ROW_NUMBER() OVER (
                        PARTITION BY factor_id, factor_version_id, security_id, trade_date
                        ORDER BY data_version DESC, calc_time DESC
                    ) AS _qdata_revision_rank
                FROM qts.factor_value_daily FINAL
                WHERE ({" OR ".join(factor_pair_clauses)})
                  AND security_id IN %(security_ids)s
                  AND trade_date BETWEEN %(start_date)s AND %(end_date)s
            )
            WHERE _qdata_revision_rank = 1
            ORDER BY trade_date, security_id, factor_id
            """,
            params,
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

        if asof_date:
            rows = self.get_security_master(
                symbols=symbols,
                security_ids=security_ids,
                asset_types=None,
                exchanges=None,
                asof_date=asof_date,
                include_delisted=True,
                fields=["security_id", "symbol"],
            )["data"]
            result = {row["security_id"]: row["symbol"] for row in rows}
            if not result:
                raise QDataNotFoundError("No securities matched the request")
            return result

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

    def _resolve_security_ids_over_range(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> list[int]:
        rows = self.postgres.fetch_all(
            """
            WITH qdata_requested_identity_range AS (
                SELECT
                    sih.security_id,
                    sih.symbol,
                    sih.exchange,
                    sih.end_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY sih.security_id, sih.identifier_type,
                                     sih.start_date
                        ORDER BY sih.revision_id DESC, sih.ingest_time DESC,
                                 sih.batch_id DESC, sih.symbol DESC
                    ) AS revision_rank
                FROM qmeta.security_identifier_history sih
                JOIN qmeta.data_batch db ON db.batch_id = sih.batch_id
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
                WHERE sih.identifier_type = 'trade_symbol'
                  AND sih.start_date <= %(end_date)s
                  AND dc.dataset_code = 'security_master'
                  AND db.status = 'success'
                  AND db.finished_at IS NOT NULL
                  AND db.finished_at < (%(end_date)s::date + INTERVAL '1 day')
                  AND sih.announce_time <
                      (%(end_date)s::date + INTERVAL '1 day')
                  AND sih.ingest_time <
                      (%(end_date)s::date + INTERVAL '1 day')
            )
            SELECT DISTINCT security_id
            FROM qdata_requested_identity_range
            WHERE revision_rank = 1
              AND (end_date IS NULL OR end_date >= %(start_date)s)
              AND symbol || '.' || exchange = ANY(%(symbols)s)
            ORDER BY security_id
            """,
            {
                "symbols": symbols,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        security_ids = [int(row["security_id"]) for row in normalize_rows(rows)]
        if not security_ids:
            raise QDataNotFoundError("No securities matched the requested date range")
        return security_ids

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

    def _resolve_allowed_dataset_versions(
        self,
        dataset_code: str,
        query_mode: str,
        asof_time: datetime | None,
        requested_version: str | None,
    ) -> list[dict[str, Any]]:
        where = [
            "dc.dataset_code = %(dataset_code)s",
            "db.status = 'success'",
            "dv.status IN ('active', 'superseded')",
        ]
        params: dict[str, Any] = {"dataset_code": dataset_code}
        if query_mode == "asof":
            where.extend(
                [
                    "dv.valid_from <= %(asof_time)s",
                    "db.finished_at IS NOT NULL",
                    "db.finished_at <= %(asof_time)s",
                ]
            )
            params["asof_time"] = asof_time
        elif query_mode == "vintage":
            where.extend(
                [
                    "db.finished_at IS NOT NULL",
                    "(dv.version_code = %(requested_data_version)s "
                    "OR CAST(dv.data_version AS TEXT) = %(requested_data_version)s)",
                ]
            )
            params["requested_data_version"] = str(requested_version)

        rows = normalize_rows(
            self.postgres.fetch_all(
                f"""
                SELECT
                    dv.data_version,
                    dv.version_code,
                    dv.batch_id,
                    dv.status,
                    dv.valid_from,
                    db.finished_at
                FROM qmeta.dataset_version dv
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = dv.dataset_id
                JOIN qmeta.data_batch db ON db.batch_id = dv.batch_id
                {self._where(where)}
                ORDER BY dv.valid_from, dv.data_version
                """,
                params,
            )
        )
        if not rows:
            if query_mode == "vintage":
                raise QDataNotFoundError(
                    f"Unknown or unavailable data_version for {dataset_code}: {requested_version}"
                )
            raise QDataNotFoundError(
                f"No published data versions are available for {dataset_code} in {query_mode} mode"
            )
        if query_mode == "vintage" and len(rows) != 1:
            raise QDataValidationError(
                f"data_version selection is ambiguous for {dataset_code}: {requested_version}"
            )
        return rows

    def _get_adjustment_factor_map(
        self,
        security_ids: list[int],
        start_date: str,
        end_date: str,
        knowledge_cutoff: datetime | None = None,
    ) -> dict[tuple[int, str], dict[str, Any]]:
        where = [
            "af.security_id = ANY(%(security_ids)s)",
            "af.trade_date BETWEEN %(start_date)s AND %(end_date)s",
            "dc.dataset_code = ANY(%(knowledge_dataset_codes)s)",
            "db.status = 'success'",
            "db.finished_at IS NOT NULL",
        ]
        params: dict[str, Any] = {
            "security_ids": security_ids,
            "start_date": start_date,
            "end_date": end_date,
            "knowledge_dataset_codes": ["daily_bar", "adjustment_factor"],
        }
        if knowledge_cutoff is not None:
            where.extend(
                [
                    "db.finished_at <= %(knowledge_cutoff)s",
                    "af.ingest_time <= %(knowledge_cutoff)s",
                    "af.announce_time IS NOT NULL",
                    "af.announce_time <= %(knowledge_cutoff)s",
                    "af.effective_time IS NOT NULL",
                    "af.effective_time <= %(knowledge_cutoff)s",
                ]
            )
            params["knowledge_cutoff"] = knowledge_cutoff
        rows = self.postgres.fetch_all(
            f"""
            SELECT DISTINCT ON (security_id, trade_date)
                af.security_id, af.trade_date, af.factor_forward, af.factor_backward
            FROM qmeta.adjustment_factor af
            JOIN qmeta.data_batch db ON db.batch_id = af.batch_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
            {self._where(where)}
            ORDER BY af.security_id, af.trade_date, af.revision_id DESC, af.ingest_time DESC
            """,
            params,
        )
        normalized = normalize_rows(rows)
        return {(row["security_id"], row["trade_date"]): row for row in normalized}

    @staticmethod
    def _validate_price_mode(
        query_mode: str,
        asof_time: str | None,
        data_version: str | None,
    ) -> datetime | None:
        if query_mode == "latest":
            if asof_time is not None or data_version is not None:
                raise QDataValidationError(
                    "query_mode='latest' only accepts neither asof_time nor data_version"
                )
            return None
        if query_mode == "asof":
            if data_version is not None:
                raise QDataValidationError(
                    "query_mode='asof' only accepts asof_time, not data_version"
                )
            if asof_time is None:
                raise QDataValidationError("asof_time is required when query_mode='asof'")
            return SqlBackend._parse_aware_datetime(asof_time)
        if asof_time is not None:
            raise QDataValidationError(
                "query_mode='vintage' only accepts data_version, not asof_time"
            )
        if data_version is None:
            raise QDataValidationError("data_version is required when query_mode='vintage'")
        return None

    @staticmethod
    def _parse_aware_datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise QDataValidationError(
                "asof_time must be a timezone-aware ISO-8601 datetime"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise QDataValidationError(
                "asof_time must be a timezone-aware ISO-8601 datetime"
            )
        return parsed

    def _apply_adjustment(
        self,
        row: dict[str, Any],
        adjust: str,
        factors: dict[tuple[int, str], dict[str, Any]],
    ) -> dict[str, Any]:
        adjusted = dict(row)
        factor_row = factors.get((row["security_id"], row["trade_date"]))
        if not factor_row:
            raise QDataNotFoundError(
                "Missing point-in-time adjustment factor for "
                f"security_id={row['security_id']}, trade_date={row['trade_date']}"
            )
        factor = factor_row["factor_forward"] if adjust == "forward" else factor_row["factor_backward"]
        if factor is None:
            raise QDataNotFoundError(
                "Missing point-in-time adjustment factor value for "
                f"security_id={row['security_id']}, trade_date={row['trade_date']}, adjust={adjust}"
            )
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
