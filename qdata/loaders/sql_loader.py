from __future__ import annotations

from datetime import datetime
from typing import Any

from qdata.exceptions import QDataValidationError
from qdata.ingest.models import (
    AdjustmentFactorRecord,
    CalendarRecord,
    DailyBarRecord,
    LimitPriceRecord,
    MinuteBarRecord,
    QualityReport,
    SecurityRecord,
    SuspensionRecord,
    TradableUniverseRecord,
)


class SqlDailyBundleLoader:
    """Load normalized daily data into PostgreSQL and ClickHouse."""

    DATASETS = {
        "security_master": ("证券主数据", "stock", None, "postgresql", False),
        "trading_calendar": ("交易日历", None, "1d", "postgresql", False),
        "daily_bar": ("日线行情", "stock", "1d", "clickhouse", False),
        "minute_bar": ("分钟行情", "stock", "1m", "clickhouse", False),
        "adjustment_factor": ("复权因子", "stock", "1d", "postgresql", False),
        "limit_price_daily": ("涨跌停和交易约束", "stock", "1d", "postgresql", False),
        "suspension_history": ("停复牌历史", "stock", "event", "postgresql", False),
        "tradable_universe": ("每日可交易股票池", "stock", "1d", "postgresql", False),
        "data_quality": ("数据质量检查", None, "1d", "postgresql", False),
    }
    SOURCES = {
        "csv": ("本地 CSV 导入", "internal", "local ingest only"),
        "local_csv": ("本地 CSV 导入", "internal", "local ingest only"),
        "csv_mirror": ("本地 CSV 备份源", "internal", "local deterministic fallback"),
        "akshare": ("AkShare 开源数据接口", "vendor", "check upstream license before production use"),
        "vendor_http": ("商业 HTTP 数据源", "vendor", "commercial contract required"),
        "commercial_http": ("商业 HTTP 数据源", "vendor", "commercial contract required"),
        "qdata": ("QData 规则计算", "internal", "derived data"),
        "qdata_api": ("QData REST 服务", "internal", "served by qdata API"),
    }

    def __init__(self, postgres_dsn: str, clickhouse_dsn: str, source_code: str = "local_csv") -> None:
        self.postgres_dsn = postgres_dsn
        self.clickhouse_dsn = clickhouse_dsn
        self.source_code = source_code
        self._postgres = None
        self._clickhouse = None

    def __enter__(self) -> "SqlDailyBundleLoader":
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def open(self) -> None:
        if self._postgres is None:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise QDataValidationError("psycopg is required for SQL ingestion") from exc
            self._postgres = psycopg.connect(self.postgres_dsn, row_factory=dict_row)
        if self._clickhouse is None:
            try:
                import clickhouse_connect
            except ImportError as exc:
                raise QDataValidationError("clickhouse-connect is required for SQL ingestion") from exc
            self._clickhouse = clickhouse_connect.get_client(dsn=self.clickhouse_dsn)
        self.ensure_metadata()

    def close(self) -> None:
        if self._postgres is not None:
            self._postgres.close()
            self._postgres = None
        if self._clickhouse is not None:
            close = getattr(self._clickhouse, "close", None)
            if close:
                close()
            self._clickhouse = None

    def load_security_master(self, records: list[SecurityRecord]) -> None:
        self.open()
        source_id = self._source_id()
        with self._postgres.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_master AS sm (
                        asset_type, exchange, current_symbol, current_name, currency,
                        list_date, delist_date, current_status, primary_source_id
                    ) VALUES (
                        %(asset_type)s, %(exchange)s, %(current_symbol)s, %(current_name)s, %(currency)s,
                        %(list_date)s, %(delist_date)s, %(current_status)s, %(source_id)s
                    )
                    ON CONFLICT (asset_type, exchange, current_symbol) DO UPDATE SET
                        current_name = COALESCE(
                            NULLIF(EXCLUDED.current_name, EXCLUDED.current_symbol || '.' || EXCLUDED.exchange),
                            sm.current_name
                        ),
                        currency = COALESCE(EXCLUDED.currency, sm.currency),
                        list_date = COALESCE(EXCLUDED.list_date, sm.list_date),
                        delist_date = COALESCE(EXCLUDED.delist_date, sm.delist_date),
                        current_status = COALESCE(EXCLUDED.current_status, sm.current_status),
                        primary_source_id = EXCLUDED.primary_source_id,
                        updated_at = now()
                    RETURNING security_id
                    """,
                    {
                        "asset_type": record.asset_type,
                        "exchange": record.exchange,
                        "current_symbol": record.code,
                        "current_name": record.name,
                        "currency": record.currency,
                        "list_date": record.list_date,
                        "delist_date": record.delist_date,
                        "current_status": record.status,
                        "source_id": source_id,
                    },
                )
                security_id = cursor.fetchone()["security_id"]
                start_date = record.list_date or "1900-01-01"
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_identifier_history (
                        security_id, symbol, exchange, identifier_type, start_date, end_date, source_id, revision_id
                    ) VALUES (%s, %s, %s, 'trade_symbol', %s, %s, %s, 1)
                    ON CONFLICT DO NOTHING
                    """,
                    (security_id, record.code, record.exchange, start_date, record.delist_date, source_id),
                )
                if record.name != record.symbol:
                    cursor.execute(
                        """
                        INSERT INTO qmeta.security_name_history (
                            security_id, name, start_date, end_date, source_id, revision_id
                        ) VALUES (%s, %s, %s, %s, %s, 1)
                        ON CONFLICT DO NOTHING
                        """,
                        (security_id, record.name, start_date, record.delist_date, source_id),
                    )
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_status_history (
                        security_id, status, start_date, end_date, reason, source_id, revision_id
                    ) VALUES (%s, %s, %s, %s, 'csv ingest', %s, 1)
                    ON CONFLICT DO NOTHING
                    """,
                    (security_id, record.status, start_date, record.delist_date, source_id),
                )
        self._postgres.commit()

    def load_trading_calendar(self, records: list[CalendarRecord]) -> None:
        self.open()
        source_id = self._source_id()
        with self._postgres.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO qmeta.trading_calendar (
                        exchange, trade_date, is_open, session_type, pretrade_date, next_trade_date,
                        open_time, close_time, source_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (exchange, trade_date) DO UPDATE SET
                        is_open = EXCLUDED.is_open,
                        session_type = EXCLUDED.session_type,
                        pretrade_date = EXCLUDED.pretrade_date,
                        next_trade_date = EXCLUDED.next_trade_date,
                        open_time = EXCLUDED.open_time,
                        close_time = EXCLUDED.close_time,
                        source_id = EXCLUDED.source_id,
                        updated_at = now()
                    """,
                    (
                        record.exchange,
                        record.trade_date,
                        record.is_open,
                        record.session_type,
                        record.pretrade_date,
                        record.next_trade_date,
                        record.open_time,
                        record.close_time,
                        source_id,
                    ),
                )
        self._postgres.commit()

    def load_daily_bars(self, records: list[DailyBarRecord]) -> None:
        self.open()
        if not records:
            return
        source_id = self._source_id()
        security_map = self._security_id_map([record.symbol for record in records])
        trade_date = records[0].trade_date
        batch_id = self._create_batch("daily_bar", source_id, trade_date, len(records))
        ingest_time = datetime.now()

        with self._postgres.cursor() as cursor:
            for record in records:
                security_id = security_map[record.symbol]
                cursor.execute(
                    """
                    INSERT INTO qmeta.adjustment_factor (
                        security_id, trade_date, factor_forward, factor_backward, ex_right_type,
                        announce_time, effective_time, source_id, batch_id, revision_id
                    ) VALUES (%s, %s, %s, %s, %s, now(), now(), %s, %s, 1)
                    ON CONFLICT (security_id, trade_date, revision_id) DO UPDATE SET
                        factor_forward = EXCLUDED.factor_forward,
                        factor_backward = EXCLUDED.factor_backward,
                        ex_right_type = EXCLUDED.ex_right_type,
                        announce_time = EXCLUDED.announce_time,
                        effective_time = EXCLUDED.effective_time,
                        ingest_time = now(),
                        source_id = EXCLUDED.source_id,
                        batch_id = EXCLUDED.batch_id
                    """,
                    (
                        security_id,
                        record.trade_date,
                        record.factor_forward,
                        record.factor_backward,
                        record.ex_right_type,
                        source_id,
                        batch_id,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.limit_price_daily (
                        security_id, trade_date, limit_up, limit_down, limit_rule, is_st,
                        is_new_listing, source_id, batch_id, revision_id
                    ) VALUES (%s, %s, %s, %s, %s, FALSE, FALSE, %s, %s, 1)
                    ON CONFLICT (security_id, trade_date, revision_id) DO UPDATE SET
                        limit_up = EXCLUDED.limit_up,
                        limit_down = EXCLUDED.limit_down,
                        limit_rule = EXCLUDED.limit_rule,
                        is_st = EXCLUDED.is_st,
                        is_new_listing = EXCLUDED.is_new_listing,
                        ingest_time = now(),
                        source_id = EXCLUDED.source_id,
                        batch_id = EXCLUDED.batch_id
                    """,
                    (
                        security_id,
                        record.trade_date,
                        record.limit_up,
                        record.limit_down,
                        "csv",
                        source_id,
                        batch_id,
                    ),
                )
                if record.is_suspended:
                    cursor.execute(
                        """
                        INSERT INTO qmeta.suspension_history (
                            security_id, start_time, end_time, suspension_type, reason,
                            announce_time, source_id, batch_id, revision_id
                        ) VALUES (%s, %s::date + TIME '09:30', %s::date + TIME '15:00', 'full_day', 'csv ingest', now(), %s, %s, 1)
                        ON CONFLICT DO NOTHING
                        """,
                        (security_id, record.trade_date, record.trade_date, source_id, batch_id),
                    )
        self._postgres.commit()

        rows = []
        for record in records:
            security_id = security_map[record.symbol]
            ch_trade_date = datetime.strptime(record.trade_date, "%Y-%m-%d").date()
            rows.append(
                [
                    security_id,
                    ch_trade_date,
                    record.open,
                    record.high,
                    record.low,
                    record.close,
                    record.pre_close,
                    record.volume,
                    record.amount,
                    record.vwap,
                    record.turnover_rate,
                    record.limit_up,
                    record.limit_down,
                    1 if record.is_suspended else 0,
                    source_id,
                    batch_id,
                    batch_id,
                    ingest_time,
                    "normal",
                ]
            )
        self._clickhouse.insert(
            "qts.daily_bar",
            rows,
            column_names=[
                "security_id",
                "trade_date",
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
                "source_id",
                "batch_id",
                "data_version",
                "ingest_time",
                "quality_flag",
            ],
        )

    def load_market_constraints(
        self,
        adjustment_factors: list[AdjustmentFactorRecord],
        limit_prices: list[LimitPriceRecord],
        suspensions: list[SuspensionRecord],
    ) -> None:
        self.open()
        symbols = [record.symbol for record in adjustment_factors]
        symbols.extend(record.symbol for record in limit_prices)
        symbols.extend(record.symbol for record in suspensions)
        if not symbols:
            return
        source_id = self._source_id()
        security_map = self._security_id_map(symbols)
        factor_batch_id = self._create_batch("adjustment_factor", source_id, _first_trade_date(adjustment_factors), len(adjustment_factors)) if adjustment_factors else None
        limit_batch_id = self._create_batch("limit_price_daily", source_id, _first_trade_date(limit_prices), len(limit_prices)) if limit_prices else None
        suspension_batch_id = self._create_batch("suspension_history", source_id, _first_suspension_date(suspensions), len(suspensions)) if suspensions else None
        with self._postgres.cursor() as cursor:
            for record in adjustment_factors:
                cursor.execute(
                    """
                    INSERT INTO qmeta.adjustment_factor (
                        security_id, trade_date, factor_forward, factor_backward, ex_right_type,
                        announce_time, effective_time, source_id, batch_id, revision_id
                    ) VALUES (%s, %s, %s, %s, %s, now(), %s::date + TIME '00:00', %s, %s, 1)
                    ON CONFLICT (security_id, trade_date, revision_id) DO UPDATE SET
                        factor_forward = EXCLUDED.factor_forward,
                        factor_backward = EXCLUDED.factor_backward,
                        ex_right_type = EXCLUDED.ex_right_type,
                        announce_time = EXCLUDED.announce_time,
                        effective_time = EXCLUDED.effective_time,
                        ingest_time = now(),
                        source_id = EXCLUDED.source_id,
                        batch_id = EXCLUDED.batch_id
                    """,
                    (
                        security_map[record.symbol],
                        record.trade_date,
                        record.factor_forward,
                        record.factor_backward,
                        record.ex_right_type,
                        record.trade_date,
                        source_id,
                        factor_batch_id,
                    ),
                )
            for record in limit_prices:
                cursor.execute(
                    """
                    INSERT INTO qmeta.limit_price_daily (
                        security_id, trade_date, limit_up, limit_down, limit_rule, is_st,
                        is_new_listing, source_id, batch_id, revision_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    ON CONFLICT (security_id, trade_date, revision_id) DO UPDATE SET
                        limit_up = EXCLUDED.limit_up,
                        limit_down = EXCLUDED.limit_down,
                        limit_rule = EXCLUDED.limit_rule,
                        is_st = EXCLUDED.is_st,
                        is_new_listing = EXCLUDED.is_new_listing,
                        ingest_time = now(),
                        source_id = EXCLUDED.source_id,
                        batch_id = EXCLUDED.batch_id
                    """,
                    (
                        security_map[record.symbol],
                        record.trade_date,
                        record.limit_up,
                        record.limit_down,
                        record.limit_rule,
                        record.is_st,
                        record.is_new_listing,
                        source_id,
                        limit_batch_id,
                    ),
                )
            for record in suspensions:
                cursor.execute(
                    """
                    INSERT INTO qmeta.suspension_history (
                        security_id, start_time, end_time, suspension_type, reason,
                        announce_time, source_id, batch_id, revision_id
                    ) VALUES (%s, %s, %s, %s, %s, now(), %s, %s, 1)
                    ON CONFLICT (security_id, start_time, revision_id) DO UPDATE SET
                        end_time = EXCLUDED.end_time,
                        suspension_type = EXCLUDED.suspension_type,
                        reason = EXCLUDED.reason,
                        announce_time = EXCLUDED.announce_time,
                        ingest_time = now(),
                        source_id = EXCLUDED.source_id,
                        batch_id = EXCLUDED.batch_id
                    """,
                    (
                        security_map[record.symbol],
                        record.start_time,
                        record.end_time,
                        record.suspension_type,
                        record.reason,
                        source_id,
                        suspension_batch_id,
                    ),
                )
        self._postgres.commit()

    def load_minute_bars(self, records: list[MinuteBarRecord]) -> None:
        self.open()
        if not records:
            return
        source_id = self._source_id()
        security_map = self._security_id_map([record.symbol for record in records])
        trade_date = records[0].trade_date
        batch_id = self._create_batch("minute_bar", source_id, trade_date, len(records))
        ingest_time = datetime.now()
        rows = []
        for record in records:
            rows.append(
                [
                    security_map[record.symbol],
                    datetime.strptime(record.trade_date, "%Y-%m-%d").date(),
                    datetime.fromisoformat(record.bar_time.replace(" ", "T")),
                    record.open,
                    record.high,
                    record.low,
                    record.close,
                    record.volume,
                    record.amount,
                    record.vwap,
                    source_id,
                    batch_id,
                    batch_id,
                    ingest_time,
                    "normal",
                ]
            )
        self._clickhouse.insert(
            "qts.minute_bar",
            rows,
            column_names=[
                "security_id",
                "trade_date",
                "bar_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "vwap",
                "source_id",
                "batch_id",
                "data_version",
                "ingest_time",
                "quality_flag",
            ],
        )

    def load_tradable_universe(
        self,
        universe_code: str,
        universe_name: str,
        trade_date: str,
        records: list[TradableUniverseRecord],
    ) -> None:
        self.open()
        source_id = self._source_id()
        batch_id = self._create_batch("tradable_universe", source_id, trade_date, len(records))
        security_map = self._security_id_map([record.symbol for record in records]) if records else {}
        with self._postgres.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.universe_definition (
                    universe_code, universe_name, universe_type, description, owner
                ) VALUES (%s, %s, 'rule_based', 'generated tradable universe', 'qdata')
                ON CONFLICT (universe_code) DO UPDATE SET
                    universe_name = EXCLUDED.universe_name,
                    universe_type = EXCLUDED.universe_type,
                    description = EXCLUDED.description,
                    owner = EXCLUDED.owner,
                    updated_at = now()
                RETURNING universe_id
                """,
                (universe_code, universe_name),
            )
            universe_id = cursor.fetchone()["universe_id"]
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO qpit.universe_member_pit (
                        universe_id, security_id, effective_date, end_date, weight,
                        announce_time, source_id, batch_id, revision_id
                    ) VALUES (%s, %s, %s, NULL, %s, now(), %s, %s, 1)
                    ON CONFLICT (universe_id, security_id, effective_date, revision_id) DO UPDATE SET
                        end_date = EXCLUDED.end_date,
                        weight = EXCLUDED.weight,
                        announce_time = EXCLUDED.announce_time,
                        ingest_time = now(),
                        source_id = EXCLUDED.source_id,
                        batch_id = EXCLUDED.batch_id
                    """,
                    (
                        universe_id,
                        security_map[record.symbol],
                        trade_date,
                        record.weight,
                        source_id,
                        batch_id,
                    ),
                )
        self._postgres.commit()

    def write_quality_report(
        self,
        report: QualityReport,
        check_date: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.open()
        source_id = self._source_id()
        batch_id = self._create_batch("data_quality", source_id, check_date, len(report.issues))
        context = self._quality_context(context)
        job_code = context.get("job_code")
        with self._postgres.cursor() as cursor:
            if check_date:
                cursor.execute(
                    """
                    DELETE FROM qmeta.data_quality_check_result
                    WHERE check_date = %s
                      AND check_type IN ('bundle', 'ingest_quality')
                      AND dataset_id IN (
                          SELECT dataset_id
                          FROM qmeta.dataset_catalog
                          WHERE dataset_code = ANY(%s)
                      )
                      AND batch_id IN (
                          SELECT batch_id
                          FROM qmeta.data_batch
                          WHERE source_id = %s
                      )
                      AND (
                          (%s::text IS NULL AND NOT (details ? 'job_code'))
                          OR (%s::text IS NOT NULL AND details->>'job_code' = %s)
                      )
                    """,
                    (check_date, list(self.DATASETS), source_id, job_code, job_code, job_code),
                )
            if not report.issues:
                dataset_id = self._dataset_id("daily_bar")
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_quality_check_result (
                        dataset_id, batch_id, check_date, check_name, check_type, status, severity,
                        metric_value, threshold_value, affected_rows, details
                    ) VALUES (%s, %s, %s, 'daily_bundle_quality', 'bundle', 'pass', 'info', 1, 1, 0, %s::jsonb)
                    """,
                    (dataset_id, batch_id, check_date, self._json_details(context)),
                )
            for issue in report.issues:
                dataset_id = self._dataset_id(issue.dataset_code)
                status = "failed" if issue.severity in {"high", "critical"} else "warning"
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_quality_check_result (
                        dataset_id, batch_id, check_date, check_name, check_type, status, severity,
                        metric_value, threshold_value, affected_rows, details
                    ) VALUES (%s, %s, %s, %s, 'ingest_quality', %s, %s, NULL, NULL, 1, %s::jsonb)
                    """,
                    (
                        dataset_id,
                        batch_id,
                        check_date or issue.trade_date,
                        issue.check_name,
                        status,
                        issue.severity,
                        self._issue_details(issue, context),
                    ),
                )
        self._postgres.commit()

    def ensure_metadata(self) -> None:
        source_id = None
        source_name, source_type, license_scope = self.SOURCES.get(
            self.source_code,
            (self.source_code, "vendor", "unknown"),
        )
        with self._postgres.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_system (
                    source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner
                ) VALUES (%s, %s, %s, %s, 'daily', 'L4', 'qdata')
                ON CONFLICT (source_code) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    source_type = EXCLUDED.source_type,
                    license_scope = EXCLUDED.license_scope,
                    update_frequency = EXCLUDED.update_frequency,
                    latency_level = EXCLUDED.latency_level,
                    owner = EXCLUDED.owner,
                    updated_at = now()
                RETURNING source_id
                """,
                (self.source_code, source_name, source_type, license_scope),
            )
            source_id = cursor.fetchone()["source_id"]
            for dataset_code, (name, asset_type, frequency, storage_layer, pit_required) in self.DATASETS.items():
                cursor.execute(
                    """
                    INSERT INTO qmeta.dataset_catalog (
                        dataset_code, dataset_name, asset_type, frequency, storage_layer,
                        primary_source_id, pit_required, description
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'created by csv ingest')
                    ON CONFLICT (dataset_code) DO UPDATE SET
                        dataset_name = EXCLUDED.dataset_name,
                        asset_type = EXCLUDED.asset_type,
                        frequency = EXCLUDED.frequency,
                        storage_layer = EXCLUDED.storage_layer,
                        primary_source_id = EXCLUDED.primary_source_id,
                        pit_required = EXCLUDED.pit_required,
                        updated_at = now()
                    """,
                    (dataset_code, name, asset_type, frequency, storage_layer, source_id, pit_required),
                )
        self._postgres.commit()

    def _source_id(self) -> int:
        with self._postgres.cursor() as cursor:
            cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = %s", (self.source_code,))
            row = cursor.fetchone()
        if not row:
            raise QDataValidationError(f"source system not found: {self.source_code}")
        return row["source_id"]

    def _dataset_id(self, dataset_code: str) -> int:
        with self._postgres.cursor() as cursor:
            cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = %s", (dataset_code,))
            row = cursor.fetchone()
        if not row:
            raise QDataValidationError(f"dataset not found: {dataset_code}")
        return row["dataset_id"]

    def _create_batch(self, dataset_code: str, source_id: int, trade_date: str | None, row_count: int) -> int:
        dataset_id = self._dataset_id(dataset_code)
        batch_code = f"{self.source_code}-{dataset_code}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        with self._postgres.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.data_batch (
                    dataset_id, source_id, batch_code, trade_date, natural_date,
                    started_at, finished_at, status, raw_uri, row_count
                ) VALUES (%s, %s, %s, %s, CURRENT_DATE, now(), now(), 'success', %s, %s)
                RETURNING batch_id
                """,
                (dataset_id, source_id, batch_code, trade_date, f"raw://{self.source_code}", row_count),
            )
            batch_id = cursor.fetchone()["batch_id"]
        self._postgres.commit()
        return batch_id

    def _security_id_map(self, symbols: list[str]) -> dict[str, int]:
        unique_symbols = sorted(set(symbols))
        with self._postgres.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_symbol || '.' || exchange AS symbol, security_id
                FROM qmeta.security_master
                WHERE current_symbol || '.' || exchange = ANY(%s)
                """,
                (unique_symbols,),
            )
            rows = cursor.fetchall()
        result = {row["symbol"]: row["security_id"] for row in rows}
        missing = sorted(set(unique_symbols) - set(result))
        if missing:
            raise QDataValidationError(f"daily bar contains unknown symbols: {missing}")
        return result

    @staticmethod
    def _quality_context(context: dict[str, Any] | None) -> dict[str, Any]:
        return {key: value for key, value in (context or {}).items() if value is not None}

    @classmethod
    def _issue_details(cls, issue, context: dict[str, Any] | None = None) -> str:
        return cls._json_details(
            {
                **(context or {}),
                "message": issue.message,
                "symbol": issue.symbol,
                "trade_date": issue.trade_date,
                "field_name": issue.field_name,
            }
        )

    @staticmethod
    def _json_details(payload: dict[str, Any] | None = None) -> str:
        import json

        return json.dumps(
            payload or {},
            ensure_ascii=False,
        )


def _first_trade_date(records) -> str | None:
    return records[0].trade_date if records else None


def _first_suspension_date(records: list[SuspensionRecord]) -> str | None:
    return records[0].start_time[:10] if records else None
