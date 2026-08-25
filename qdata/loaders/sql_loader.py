from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
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


@dataclass(frozen=True)
class VersionedBatch:
    batch_id: int
    data_version: int
    version_code: str


class SqlDailyBundleLoader:
    """Load normalized daily data into PostgreSQL and ClickHouse."""

    DATASETS = {
        "security_master": ("证券主数据", "stock", None, "postgresql", True),
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
        if not records:
            return
        # An explicit security_id is a stable identity assertion.  Validate the
        # complete input and any current target-symbol owner before creating an
        # audit batch or mutating master/history state.  In particular, a
        # symbol-only placeholder may already own the target ticker; silently
        # re-keying that row would orphan PostgreSQL/ClickHouse facts because
        # there is no cross-store transaction that can prove such a merge safe.
        self._preflight_security_master_records(records)
        source_id = self._source_id()
        batch_id = self._create_batch("security_master", source_id, None, len(records))
        try:
            with self._postgres.cursor() as cursor:
                for record in records:
                    is_partial_placeholder = (
                        record.name.strip().upper() == record.symbol.upper()
                        and record.list_date is None
                        and record.delist_date is None
                    )
                    normalized_status = self._normalize_security_status(
                        record.status,
                        record.delist_date,
                    )
                    incoming_status = (
                        None
                        if is_partial_placeholder or record.status is None
                        else normalized_status
                    )
                    resolved = self._upsert_security_master(
                        cursor,
                        record=record,
                        incoming_status=incoming_status,
                        source_id=source_id,
                    )
                    security_id = resolved["security_id"]
                    if is_partial_placeholder:
                        # A symbol-only record is sufficient to allocate/reuse a
                        # current security_id for market data, but it is not an
                        # authoritative identity, name, or status event. Keeping
                        # it out of PIT history prevents a later real record with
                        # an earlier list date from being shadowed forever.
                        continue
                    knowledge_date = date.today().isoformat()
                    start_date = self._date_string(
                        resolved.get("list_date") or knowledge_date
                    )
                    delist_date = self._optional_date_string(
                        resolved.get("delist_date")
                    )
                    resolved_name = resolved.get("current_name") or record.symbol
                    resolved_status = self._normalize_security_status(
                        resolved.get("current_status"),
                        delist_date,
                    )
                    previous_status = self._latest_security_status(
                        cursor,
                        security_id=security_id,
                    )
                    previous_identifier = self._latest_security_identifier(
                        cursor,
                        security_id=security_id,
                    )
                    previous_name = self._latest_security_name(
                        cursor,
                        security_id=security_id,
                    )
                    self._append_identifier_transition(
                        cursor,
                        record=record,
                        security_id=security_id,
                        initial_start_date=start_date,
                        knowledge_date=knowledge_date,
                        previous=previous_identifier,
                        source_id=source_id,
                        batch_id=batch_id,
                    )
                    self._append_name_transition(
                        cursor,
                        record=record,
                        security_id=security_id,
                        name=resolved_name,
                        initial_start_date=start_date,
                        knowledge_date=knowledge_date,
                        previous=previous_name,
                        source_id=source_id,
                        batch_id=batch_id,
                    )
                    if (
                        previous_status is None
                        and resolved_status == "delisted"
                        and delist_date is not None
                    ):
                        delist_day = datetime.strptime(
                            delist_date, "%Y-%m-%d"
                        ).date()
                        list_day = datetime.strptime(start_date, "%Y-%m-%d").date()
                        if list_day < delist_day:
                            self._append_security_status(
                                cursor,
                                security_id=security_id,
                                status="active",
                                start_date=start_date,
                                end_date=(delist_day - timedelta(days=1)).isoformat(),
                                source_id=source_id,
                                batch_id=batch_id,
                            )
                        self._append_security_status(
                            cursor,
                            security_id=security_id,
                            status="delisted",
                            start_date=delist_date,
                            end_date=None,
                            source_id=source_id,
                            batch_id=batch_id,
                        )
                    elif incoming_status is None and previous_status is not None:
                        # Partial daily providers do not carry an authoritative
                        # status event. Preserve the existing episode instead of
                        # inventing a transition from the current-master label.
                        continue
                    else:
                        status_start_date = self._security_status_effective_date(
                            record=record,
                            status=resolved_status,
                            list_date=start_date,
                            knowledge_date=knowledge_date,
                            previous_status=previous_status,
                        )
                        if previous_status is not None:
                            previous_start = self._date_string(
                                previous_status["start_date"]
                            )
                            previous_end = self._optional_date_string(
                                previous_status.get("end_date")
                            )
                            transition_day = datetime.strptime(
                                status_start_date,
                                "%Y-%m-%d",
                            ).date()
                            previous_start_day = datetime.strptime(
                                previous_start,
                                "%Y-%m-%d",
                            ).date()
                            is_transition = (
                                previous_status["status"] != resolved_status
                                or previous_start != status_start_date
                            )
                            if (
                                is_transition
                                and previous_start_day < transition_day
                                and (
                                    previous_end is None
                                    or datetime.strptime(
                                        previous_end,
                                        "%Y-%m-%d",
                                    ).date()
                                    >= transition_day
                                )
                            ):
                                self._append_security_status(
                                    cursor,
                                    security_id=security_id,
                                    status=previous_status["status"],
                                    start_date=previous_start,
                                    end_date=(transition_day - timedelta(days=1)).isoformat(),
                                    source_id=source_id,
                                    batch_id=batch_id,
                                )
                        self._append_security_status(
                            cursor,
                            security_id=security_id,
                            status=resolved_status,
                            start_date=status_start_date,
                            end_date=None,
                            source_id=source_id,
                            batch_id=batch_id,
                        )
            self._finish_batches([batch_id], "success")
        except Exception as exc:
            self._record_lifecycle_failure(exc, batch_ids=[batch_id])
            raise

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
        versioned_batch = self._create_versioned_batch(
            "daily_bar", source_id, trade_date, len(records)
        )
        ingest_time = datetime.now()
        try:
            self._write_daily_bar_metadata(
                records, security_map, source_id, versioned_batch.batch_id
            )
            rows = self._daily_bar_clickhouse_rows(
                records,
                security_map,
                source_id,
                versioned_batch.batch_id,
                versioned_batch.data_version,
                ingest_time,
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
            self._finish_versioned_batch(versioned_batch, "success")
        except Exception as exc:
            self._record_lifecycle_failure(exc, versioned_batch=versioned_batch)
            raise

    def _write_daily_bar_metadata(
        self,
        records: list[DailyBarRecord],
        security_map: dict[str, int],
        source_id: int,
        batch_id: int,
    ) -> None:
        with self._postgres.cursor() as cursor:
            for record in records:
                security_id = security_map[record.symbol]
                self._append_adjustment_factor(
                    cursor,
                    security_id=security_id,
                    trade_date=record.trade_date,
                    factor_forward=record.factor_forward,
                    factor_backward=record.factor_backward,
                    ex_right_type=record.ex_right_type,
                    source_id=source_id,
                    batch_id=batch_id,
                )
                self._append_limit_price(
                    cursor,
                    security_id=security_id,
                    trade_date=record.trade_date,
                    limit_up=record.limit_up,
                    limit_down=record.limit_down,
                    limit_rule="csv",
                    is_st=False,
                    is_new_listing=False,
                    source_id=source_id,
                    batch_id=batch_id,
                )
                if record.is_suspended:
                    self._append_suspension(
                        cursor,
                        security_id=security_id,
                        start_time=f"{record.trade_date} 09:30:00",
                        end_time=f"{record.trade_date} 15:00:00",
                        suspension_type="full_day",
                        reason="csv ingest",
                        source_id=source_id,
                        batch_id=batch_id,
                    )

    @staticmethod
    def _daily_bar_clickhouse_rows(
        records: list[DailyBarRecord],
        security_map: dict[str, int],
        source_id: int,
        batch_id: int,
        data_version: int,
        ingest_time: datetime,
    ) -> list[list[Any]]:
        rows = []
        for record in records:
            rows.append(
                [
                    security_map[record.symbol],
                    datetime.strptime(record.trade_date, "%Y-%m-%d").date(),
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
                    data_version,
                    ingest_time,
                    "normal",
                ]
            )
        return rows

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
        factor_batch_id = None
        factor_versioned_batch: VersionedBatch | None = None
        limit_batch_id = None
        suspension_batch_id = None
        batch_ids: list[int] = []
        try:
            if adjustment_factors:
                factor_versioned_batch = self._create_versioned_batch(
                    "adjustment_factor",
                    source_id,
                    _first_trade_date(adjustment_factors),
                    len(adjustment_factors),
                )
                factor_batch_id = factor_versioned_batch.batch_id
            if limit_prices:
                limit_batch_id = self._create_batch(
                    "limit_price_daily",
                    source_id,
                    _first_trade_date(limit_prices),
                    len(limit_prices),
                )
                batch_ids.append(limit_batch_id)
            if suspensions:
                suspension_batch_id = self._create_batch(
                    "suspension_history",
                    source_id,
                    _first_suspension_date(suspensions),
                    len(suspensions),
                )
                batch_ids.append(suspension_batch_id)

            with self._postgres.cursor() as cursor:
                for record in adjustment_factors:
                    self._append_adjustment_factor(
                        cursor,
                        security_id=security_map[record.symbol],
                        trade_date=record.trade_date,
                        factor_forward=record.factor_forward,
                        factor_backward=record.factor_backward,
                        ex_right_type=record.ex_right_type,
                        source_id=source_id,
                        batch_id=factor_batch_id,
                    )
                for record in limit_prices:
                    self._append_limit_price(
                        cursor,
                        security_id=security_map[record.symbol],
                        trade_date=record.trade_date,
                        limit_up=record.limit_up,
                        limit_down=record.limit_down,
                        limit_rule=record.limit_rule,
                        is_st=record.is_st,
                        is_new_listing=record.is_new_listing,
                        source_id=source_id,
                        batch_id=limit_batch_id,
                    )
                for record in suspensions:
                    self._append_suspension(
                        cursor,
                        security_id=security_map[record.symbol],
                        start_time=record.start_time,
                        end_time=record.end_time,
                        suspension_type=record.suspension_type,
                        reason=record.reason,
                        source_id=source_id,
                        batch_id=suspension_batch_id,
                    )
            self._finish_market_constraint_batches(
                factor_versioned_batch,
                batch_ids,
                "success",
            )
        except Exception as exc:
            self._record_market_constraint_failure(
                exc,
                factor_versioned_batch,
                batch_ids,
            )
            raise

    def load_minute_bars(self, records: list[MinuteBarRecord]) -> None:
        self.open()
        if not records:
            return
        source_id = self._source_id()
        security_map = self._security_id_map([record.symbol for record in records])
        trade_date = records[0].trade_date
        versioned_batch = self._create_versioned_batch(
            "minute_bar", source_id, trade_date, len(records)
        )
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
                    versioned_batch.batch_id,
                    versioned_batch.data_version,
                    ingest_time,
                    "normal",
                ]
            )
        try:
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
            self._finish_versioned_batch(versioned_batch, "success")
        except Exception as exc:
            self._record_lifecycle_failure(exc, versioned_batch=versioned_batch)
            raise

    def load_tradable_universe(
        self,
        universe_code: str,
        universe_name: str,
        trade_date: str,
        records: list[TradableUniverseRecord],
    ) -> None:
        self.open()
        source_id = self._source_id()
        security_map = self._security_id_map([record.symbol for record in records]) if records else {}
        batch_id = self._create_batch("tradable_universe", source_id, trade_date, len(records))
        try:
            with self._postgres.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.universe_definition AS ud (
                        universe_code, universe_name, universe_type, description, owner
                    ) VALUES (%s, %s, 'rule_based', 'generated tradable universe', 'qdata')
                    ON CONFLICT (universe_code) DO UPDATE SET
                        universe_name = EXCLUDED.universe_name,
                        description = EXCLUDED.description,
                        owner = EXCLUDED.owner,
                        updated_at = now()
                    WHERE ud.universe_type = 'rule_based'
                    RETURNING universe_id
                    """,
                    (universe_code, universe_name),
                )
                universe_row = cursor.fetchone()
                if not universe_row:
                    raise QDataValidationError(
                        "existing universe is not rule_based; refusing to reinterpret "
                        f"historical membership for {universe_code}"
                    )
                universe_id = universe_row["universe_id"]
                cursor.execute(
                    """
                    INSERT INTO qmeta.universe_snapshot (
                        universe_id, trade_date, batch_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (universe_id, trade_date, batch_id),
                )
                for record in records:
                    self._append_universe_member(
                        cursor,
                        universe_id=universe_id,
                        security_id=security_map[record.symbol],
                        trade_date=trade_date,
                        weight=record.weight,
                        source_id=source_id,
                        batch_id=batch_id,
                    )
            self._finish_batches([batch_id], "success")
        except Exception as exc:
            self._record_lifecycle_failure(exc, batch_ids=[batch_id])
            raise

    def write_quality_report(
        self,
        report: QualityReport,
        check_date: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.open()
        source_id = self._source_id()
        context = self._quality_context(context)
        job_code = context.get("job_code")
        batch_id = self._create_batch("data_quality", source_id, check_date, len(report.issues))
        try:
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
            self._finish_batches([batch_id], "success")
        except Exception as exc:
            self._record_lifecycle_failure(exc, batch_ids=[batch_id])
            raise

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

    def _preflight_security_master_records(
        self,
        records: list[SecurityRecord],
    ) -> None:
        target_owner: dict[tuple[str, str, str], int] = {}
        id_target: dict[int, tuple[str, str, str]] = {}
        for record in records:
            if record.security_id is None:
                continue
            target = (record.asset_type, record.exchange, record.code)
            previous_id = target_owner.get(target)
            if previous_id is not None and previous_id != record.security_id:
                raise QDataValidationError(
                    "security-master batch maps one target symbol to multiple "
                    f"security_ids: {record.symbol}"
                )
            previous_target = id_target.get(record.security_id)
            if previous_target is not None and previous_target != target:
                raise QDataValidationError(
                    "security-master batch maps one security_id to multiple "
                    f"target symbols: {record.security_id}"
                )
            target_owner[target] = record.security_id
            id_target[record.security_id] = target

        if not target_owner:
            return
        with self._postgres.cursor() as cursor:
            for (asset_type, exchange, symbol), security_id in sorted(
                target_owner.items()
            ):
                cursor.execute(
                    """
                    SELECT security_id AS target_security_id
                    FROM qmeta.security_master
                    WHERE asset_type = %s
                      AND exchange = %s
                      AND current_symbol = %s
                    FOR KEY SHARE
                    """,
                    (asset_type, exchange, symbol),
                )
                row = cursor.fetchone()
                if row is None:
                    continue
                owner_id = int(row["target_security_id"])
                if owner_id != int(security_id):
                    raise QDataValidationError(
                        f"target symbol {symbol}.{exchange} is already owned by "
                        f"security_id {owner_id}; refusing unsafe cross-identity "
                        "merge/re-key"
                    )

    @staticmethod
    def _upsert_security_master(
        cursor: Any,
        *,
        record: SecurityRecord,
        incoming_status: str | None,
        source_id: int,
    ) -> dict[str, Any]:
        params = {
            "security_id": record.security_id,
            "asset_type": record.asset_type,
            "exchange": record.exchange,
            "current_symbol": record.code,
            "current_name": record.name,
            "currency": record.currency,
            "list_date": record.list_date,
            "delist_date": record.delist_date,
            "current_status": incoming_status,
            "source_id": source_id,
        }
        if record.security_id is not None:
            cursor.execute(
                """
                INSERT INTO qmeta.security_master AS sm (
                    security_id, asset_type, exchange, current_symbol,
                    current_name, currency, list_date, delist_date,
                    current_status, primary_source_id
                ) VALUES (
                    %(security_id)s, %(asset_type)s, %(exchange)s,
                    %(current_symbol)s, %(current_name)s, %(currency)s,
                    %(list_date)s, %(delist_date)s,
                    COALESCE(%(current_status)s, 'unknown'), %(source_id)s
                )
                ON CONFLICT (security_id) DO UPDATE SET
                    asset_type = EXCLUDED.asset_type,
                    exchange = EXCLUDED.exchange,
                    current_symbol = EXCLUDED.current_symbol,
                    current_name = COALESCE(
                        NULLIF(
                            EXCLUDED.current_name,
                            EXCLUDED.current_symbol || '.' || EXCLUDED.exchange
                        ),
                        sm.current_name
                    ),
                    currency = COALESCE(EXCLUDED.currency, sm.currency),
                    list_date = COALESCE(EXCLUDED.list_date, sm.list_date),
                    delist_date = COALESCE(EXCLUDED.delist_date, sm.delist_date),
                    current_status = COALESCE(%(current_status)s, sm.current_status),
                    primary_source_id = EXCLUDED.primary_source_id,
                    updated_at = now()
                RETURNING security_id, list_date, delist_date,
                          current_name, current_status
                """,
                params,
            )
        else:
            cursor.execute(
                """
                INSERT INTO qmeta.security_master AS sm (
                    asset_type, exchange, current_symbol, current_name, currency,
                    list_date, delist_date, current_status, primary_source_id
                ) VALUES (
                    %(asset_type)s, %(exchange)s, %(current_symbol)s,
                    %(current_name)s, %(currency)s, %(list_date)s,
                    %(delist_date)s, COALESCE(%(current_status)s, 'unknown'),
                    %(source_id)s
                )
                ON CONFLICT (asset_type, exchange, current_symbol) DO UPDATE SET
                    current_name = COALESCE(
                        NULLIF(
                            EXCLUDED.current_name,
                            EXCLUDED.current_symbol || '.' || EXCLUDED.exchange
                        ),
                        sm.current_name
                    ),
                    currency = COALESCE(EXCLUDED.currency, sm.currency),
                    list_date = COALESCE(EXCLUDED.list_date, sm.list_date),
                    delist_date = COALESCE(EXCLUDED.delist_date, sm.delist_date),
                    current_status = COALESCE(%(current_status)s, sm.current_status),
                    primary_source_id = EXCLUDED.primary_source_id,
                    updated_at = now()
                RETURNING security_id, list_date, delist_date,
                          current_name, current_status
                """,
                params,
            )
        row = cursor.fetchone()
        if not row:
            raise QDataValidationError("security master upsert returned no row")
        return row

    @staticmethod
    def _latest_security_identifier(
        cursor: Any,
        *,
        security_id: int,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT sih.symbol, sih.exchange, sih.start_date, sih.end_date
            FROM qmeta.security_identifier_history sih
            JOIN qmeta.data_batch db ON db.batch_id = sih.batch_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
            WHERE sih.security_id = %s
              AND sih.identifier_type = 'trade_symbol'
              AND dc.dataset_code = 'security_master'
              AND db.status = 'success'
              AND db.finished_at IS NOT NULL
            ORDER BY sih.start_date DESC, sih.revision_id DESC,
                     sih.ingest_time DESC, sih.batch_id DESC, sih.symbol DESC
            LIMIT 1
            """,
            (security_id,),
        )
        return cursor.fetchone()

    @staticmethod
    def _latest_security_name(
        cursor: Any,
        *,
        security_id: int,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT snh.name, snh.start_date, snh.end_date
            FROM qmeta.security_name_history snh
            JOIN qmeta.data_batch db ON db.batch_id = snh.batch_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
            WHERE snh.security_id = %s
              AND dc.dataset_code = 'security_master'
              AND db.status = 'success'
              AND db.finished_at IS NOT NULL
            ORDER BY snh.start_date DESC, snh.revision_id DESC,
                     snh.ingest_time DESC, snh.batch_id DESC, snh.name DESC
            LIMIT 1
            """,
            (security_id,),
        )
        return cursor.fetchone()

    @classmethod
    def _append_identifier_transition(
        cls,
        cursor: Any,
        *,
        record: SecurityRecord,
        security_id: int,
        initial_start_date: str,
        knowledge_date: str,
        previous: dict[str, Any] | None,
        source_id: int,
        batch_id: int,
    ) -> None:
        same_open_episode = bool(
            previous
            and previous["symbol"] == record.code
            and previous["exchange"] == record.exchange
            and previous.get("end_date") is None
        )
        start_date = cls._history_transition_start(
            explicit_date=record.identifier_effective_date,
            initial_start_date=initial_start_date,
            knowledge_date=knowledge_date,
            previous=previous,
            same_open_episode=same_open_episode,
        )
        cls._close_previous_identifier_if_needed(
            cursor,
            previous=previous,
            next_start_date=start_date,
            next_symbol=record.code,
            next_exchange=record.exchange,
            security_id=security_id,
            source_id=source_id,
            batch_id=batch_id,
        )
        cls._append_security_identifier(
            cursor,
            security_id=security_id,
            symbol=record.code,
            exchange=record.exchange,
            start_date=start_date,
            end_date=None,
            source_id=source_id,
            batch_id=batch_id,
        )

    @classmethod
    def _append_name_transition(
        cls,
        cursor: Any,
        *,
        record: SecurityRecord,
        security_id: int,
        name: str,
        initial_start_date: str,
        knowledge_date: str,
        previous: dict[str, Any] | None,
        source_id: int,
        batch_id: int,
    ) -> None:
        same_open_episode = bool(
            previous
            and previous["name"] == name
            and previous.get("end_date") is None
        )
        start_date = cls._history_transition_start(
            explicit_date=record.name_effective_date,
            initial_start_date=initial_start_date,
            knowledge_date=knowledge_date,
            previous=previous,
            same_open_episode=same_open_episode,
        )
        if previous is not None and (
            previous["name"] != name
            or cls._date_string(previous["start_date"]) != start_date
        ):
            cls._append_closed_name_revision(
                cursor,
                previous=previous,
                next_start_date=start_date,
                security_id=security_id,
                source_id=source_id,
                batch_id=batch_id,
            )
        cls._append_security_name(
            cursor,
            security_id=security_id,
            name=name,
            start_date=start_date,
            end_date=None,
            source_id=source_id,
            batch_id=batch_id,
        )

    @classmethod
    def _history_transition_start(
        cls,
        *,
        explicit_date: str | None,
        initial_start_date: str,
        knowledge_date: str,
        previous: dict[str, Any] | None,
        same_open_episode: bool,
    ) -> str:
        if explicit_date is not None:
            return cls._date_string(explicit_date)
        if same_open_episode and previous is not None:
            return cls._date_string(previous["start_date"])
        if previous is None:
            return initial_start_date
        return knowledge_date

    @classmethod
    def _close_previous_identifier_if_needed(
        cls,
        cursor: Any,
        *,
        previous: dict[str, Any] | None,
        next_start_date: str,
        next_symbol: str,
        next_exchange: str,
        security_id: int,
        source_id: int,
        batch_id: int,
    ) -> None:
        if previous is None:
            return
        changed = (
            previous["symbol"] != next_symbol
            or previous["exchange"] != next_exchange
            or cls._date_string(previous["start_date"]) != next_start_date
        )
        if not changed:
            return
        closed_end = cls._transition_end_date(previous, next_start_date)
        if closed_end is None:
            return
        cls._append_security_identifier(
            cursor,
            security_id=security_id,
            symbol=previous["symbol"],
            exchange=previous["exchange"],
            start_date=cls._date_string(previous["start_date"]),
            end_date=closed_end,
            source_id=source_id,
            batch_id=batch_id,
        )

    @classmethod
    def _append_closed_name_revision(
        cls,
        cursor: Any,
        *,
        previous: dict[str, Any],
        next_start_date: str,
        security_id: int,
        source_id: int,
        batch_id: int,
    ) -> None:
        closed_end = cls._transition_end_date(previous, next_start_date)
        if closed_end is None:
            return
        cls._append_security_name(
            cursor,
            security_id=security_id,
            name=previous["name"],
            start_date=cls._date_string(previous["start_date"]),
            end_date=closed_end,
            source_id=source_id,
            batch_id=batch_id,
        )

    @classmethod
    def _transition_end_date(
        cls,
        previous: dict[str, Any],
        next_start_date: str,
    ) -> str | None:
        previous_start = datetime.strptime(
            cls._date_string(previous["start_date"]),
            "%Y-%m-%d",
        ).date()
        next_start = datetime.strptime(next_start_date, "%Y-%m-%d").date()
        if next_start < previous_start:
            raise QDataValidationError(
                "history transition effective date cannot precede the current episode"
            )
        if next_start == previous_start:
            return None
        previous_end = cls._optional_date_string(previous.get("end_date"))
        if previous_end is not None and datetime.strptime(
            previous_end,
            "%Y-%m-%d",
        ).date() < next_start:
            return None
        return (next_start - timedelta(days=1)).isoformat()

    @staticmethod
    def _date_string(value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    @classmethod
    def _optional_date_string(cls, value: Any) -> str | None:
        return None if value is None else cls._date_string(value)

    @staticmethod
    def _normalize_security_status(
        status: str | None,
        delist_date: str | None,
    ) -> str:
        normalized = str(status or "unknown").strip().lower()
        if normalized in {"inactive", "terminated"}:
            return "delisted" if delist_date else "unknown"
        allowed = {
            "prelisted",
            "active",
            "suspended",
            "st",
            "star_st",
            "delisting_period",
            "delisted",
            "unknown",
        }
        return normalized if normalized in allowed else "unknown"

    @classmethod
    def _security_status_effective_date(
        cls,
        *,
        record: SecurityRecord,
        status: str,
        list_date: str,
        knowledge_date: str,
        previous_status: dict[str, Any] | None,
    ) -> str:
        if record.status_effective_date is not None:
            return cls._date_string(record.status_effective_date)
        if previous_status is not None and previous_status["status"] == status:
            return cls._date_string(previous_status["start_date"])
        if status == "delisted" and record.delist_date is not None:
            return cls._date_string(record.delist_date)
        if previous_status is None and status == "active":
            return list_date
        return knowledge_date

    @staticmethod
    def _latest_security_status(
        cursor: Any,
        *,
        security_id: int,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT st.status, st.start_date, st.end_date
            FROM qmeta.security_status_history st
            JOIN qmeta.data_batch db ON db.batch_id = st.batch_id
            JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
            WHERE st.security_id = %s
              AND dc.dataset_code = 'security_master'
              AND db.status = 'success'
              AND db.finished_at IS NOT NULL
            ORDER BY st.start_date DESC, st.revision_id DESC,
                     st.ingest_time DESC, st.batch_id DESC, st.status DESC
            LIMIT 1
            """,
            (security_id,),
        )
        return cursor.fetchone()

    @staticmethod
    def _allocate_revision(
        cursor: Any,
        *,
        lock_key: str,
        table: str,
        natural_key_sql: str,
        natural_key_params: tuple[Any, ...],
        label: str,
    ) -> int:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        cursor.execute(
            f"""
            SELECT COALESCE(MAX(revision_id), 0) + 1 AS revision_id
            FROM {table}
            WHERE {natural_key_sql}
            """,
            natural_key_params,
        )
        revision_row = cursor.fetchone()
        if not revision_row or revision_row.get("revision_id") is None:
            raise QDataValidationError(f"could not allocate {label} revision")
        return revision_row["revision_id"]

    @classmethod
    def _append_security_identifier(
        cls,
        cursor: Any,
        *,
        security_id: int,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str | None,
        source_id: int,
        batch_id: int,
    ) -> None:
        revision_id = cls._allocate_revision(
            cursor,
            lock_key=(
                f"qmeta.security_identifier_history:{security_id}:trade_symbol:"
                f"{start_date}"
            ),
            table="qmeta.security_identifier_history",
            natural_key_sql=(
                "security_id = %s AND identifier_type = 'trade_symbol' "
                "AND start_date = %s"
            ),
            natural_key_params=(security_id, start_date),
            label="security-identifier",
        )
        cursor.execute(
            """
            INSERT INTO qmeta.security_identifier_history (
                security_id, symbol, exchange, identifier_type, start_date,
                end_date, announce_time, ingest_time, source_id, batch_id,
                revision_id
            ) VALUES (
                %s, %s, %s, 'trade_symbol', %s, %s, now(), now(), %s, %s, %s
            )
            """,
            (
                security_id,
                symbol,
                exchange,
                start_date,
                end_date,
                source_id,
                batch_id,
                revision_id,
            ),
        )

    @classmethod
    def _append_security_name(
        cls,
        cursor: Any,
        *,
        security_id: int,
        name: str,
        start_date: str,
        end_date: str | None,
        source_id: int,
        batch_id: int,
    ) -> None:
        revision_id = cls._allocate_revision(
            cursor,
            lock_key=f"qmeta.security_name_history:{security_id}:{start_date}",
            table="qmeta.security_name_history",
            natural_key_sql="security_id = %s AND start_date = %s",
            natural_key_params=(security_id, start_date),
            label="security-name",
        )
        cursor.execute(
            """
            INSERT INTO qmeta.security_name_history (
                security_id, name, start_date, end_date, announce_time,
                ingest_time, source_id, batch_id, revision_id
            ) VALUES (%s, %s, %s, %s, now(), now(), %s, %s, %s)
            """,
            (
                security_id,
                name,
                start_date,
                end_date,
                source_id,
                batch_id,
                revision_id,
            ),
        )

    @classmethod
    def _append_security_status(
        cls,
        cursor: Any,
        *,
        security_id: int,
        status: str,
        start_date: str,
        end_date: str | None,
        source_id: int,
        batch_id: int,
    ) -> None:
        revision_id = cls._allocate_revision(
            cursor,
            lock_key=f"qmeta.security_status_history:{security_id}:{start_date}",
            table="qmeta.security_status_history",
            natural_key_sql="security_id = %s AND start_date = %s",
            natural_key_params=(security_id, start_date),
            label="security-status",
        )
        cursor.execute(
            """
            INSERT INTO qmeta.security_status_history (
                security_id, status, start_date, end_date, reason,
                announce_time, ingest_time, source_id, batch_id, revision_id
            ) VALUES (%s, %s, %s, %s, 'security-master ingest', now(), now(), %s, %s, %s)
            """,
            (
                security_id,
                status,
                start_date,
                end_date,
                source_id,
                batch_id,
                revision_id,
            ),
        )

    @staticmethod
    def _append_adjustment_factor(
        cursor: Any,
        security_id: int,
        trade_date: str,
        factor_forward: float | None,
        factor_backward: float | None,
        ex_right_type: str,
        source_id: int,
        batch_id: int,
    ) -> None:
        revision_lock_key = f"qmeta.adjustment_factor:{security_id}:{trade_date}"
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (revision_lock_key,),
        )
        cursor.execute(
            """
            SELECT COALESCE(MAX(revision_id), 0) + 1 AS revision_id
            FROM qmeta.adjustment_factor
            WHERE security_id = %s AND trade_date = %s
            """,
            (security_id, trade_date),
        )
        revision_row = cursor.fetchone()
        if not revision_row or revision_row.get("revision_id") is None:
            raise QDataValidationError("could not allocate adjustment-factor revision")
        cursor.execute(
            """
            INSERT INTO qmeta.adjustment_factor (
                security_id, trade_date, factor_forward, factor_backward, ex_right_type,
                announce_time, effective_time, source_id, batch_id, revision_id
            ) VALUES (%s, %s, %s, %s, %s, now(), %s::date + TIME '00:00', %s, %s, %s)
            """,
            (
                security_id,
                trade_date,
                factor_forward,
                factor_backward,
                ex_right_type,
                trade_date,
                source_id,
                batch_id,
                revision_row["revision_id"],
            ),
        )

    @staticmethod
    def _append_limit_price(
        cursor: Any,
        *,
        security_id: int,
        trade_date: str,
        limit_up: float | None,
        limit_down: float | None,
        limit_rule: str,
        is_st: bool,
        is_new_listing: bool,
        source_id: int,
        batch_id: int,
    ) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"qmeta.limit_price_daily:{security_id}:{trade_date}",),
        )
        cursor.execute(
            """
            SELECT COALESCE(MAX(revision_id), 0) + 1 AS revision_id
            FROM qmeta.limit_price_daily
            WHERE security_id = %s AND trade_date = %s
            """,
            (security_id, trade_date),
        )
        revision_row = cursor.fetchone()
        if not revision_row or revision_row.get("revision_id") is None:
            raise QDataValidationError("could not allocate limit-price revision")
        cursor.execute(
            """
            INSERT INTO qmeta.limit_price_daily (
                security_id, trade_date, limit_up, limit_down, limit_rule, is_st,
                is_new_listing, source_id, batch_id, revision_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                security_id,
                trade_date,
                limit_up,
                limit_down,
                limit_rule,
                is_st,
                is_new_listing,
                source_id,
                batch_id,
                revision_row["revision_id"],
            ),
        )

    @staticmethod
    def _append_suspension(
        cursor: Any,
        *,
        security_id: int,
        start_time: str,
        end_time: str | None,
        suspension_type: str,
        reason: str | None,
        source_id: int,
        batch_id: int,
    ) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"qmeta.suspension_history:{security_id}:{start_time}",),
        )
        cursor.execute(
            """
            SELECT COALESCE(MAX(revision_id), 0) + 1 AS revision_id
            FROM qmeta.suspension_history
            WHERE security_id = %s AND start_time = %s
            """,
            (security_id, start_time),
        )
        revision_row = cursor.fetchone()
        if not revision_row or revision_row.get("revision_id") is None:
            raise QDataValidationError("could not allocate suspension revision")
        cursor.execute(
            """
            INSERT INTO qmeta.suspension_history (
                security_id, start_time, end_time, suspension_type, reason,
                announce_time, source_id, batch_id, revision_id
            ) VALUES (%s, %s, %s, %s, %s, now(), %s, %s, %s)
            """,
            (
                security_id,
                start_time,
                end_time,
                suspension_type,
                reason,
                source_id,
                batch_id,
                revision_row["revision_id"],
            ),
        )

    @staticmethod
    def _append_universe_member(
        cursor: Any,
        *,
        universe_id: int,
        security_id: int,
        trade_date: str,
        weight: float | None,
        source_id: int,
        batch_id: int,
    ) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (
                f"qpit.universe_member_pit:{universe_id}:{security_id}:"
                f"{trade_date}",
            ),
        )
        cursor.execute(
            """
            SELECT COALESCE(MAX(revision_id), 0) + 1 AS revision_id
            FROM qpit.universe_member_pit
            WHERE universe_id = %s
              AND security_id = %s
              AND effective_date = %s
            """,
            (universe_id, security_id, trade_date),
        )
        revision_row = cursor.fetchone()
        if not revision_row or revision_row.get("revision_id") is None:
            raise QDataValidationError("could not allocate universe-member revision")
        cursor.execute(
            """
            INSERT INTO qpit.universe_member_pit (
                universe_id, security_id, effective_date, end_date, weight,
                announce_time, source_id, batch_id, revision_id
            ) VALUES (%s, %s, %s, %s, %s, now(), %s, %s, %s)
            """,
            (
                universe_id,
                security_id,
                trade_date,
                trade_date,
                weight,
                source_id,
                batch_id,
                revision_row["revision_id"],
            ),
        )

    def _create_batch(
        self,
        dataset_code: str,
        source_id: int,
        trade_date: str | None,
        row_count: int,
    ) -> int:
        dataset_id = self._dataset_id(dataset_code)
        batch_code = self._new_batch_code(dataset_code)
        try:
            with self._postgres.cursor() as cursor:
                batch_id = self._insert_running_batch(
                    cursor,
                    dataset_id,
                    source_id,
                    batch_code,
                    trade_date,
                    row_count,
                )
            self._postgres.commit()
        except Exception as exc:
            self._rollback_preserving(exc)
            raise
        return batch_id

    def _create_versioned_batch(
        self,
        dataset_code: str,
        source_id: int,
        trade_date: str | None,
        row_count: int,
    ) -> VersionedBatch:
        dataset_id = self._dataset_id(dataset_code)
        batch_code = self._new_batch_code(dataset_code)
        version_code = f"{dataset_code}:{batch_code}"
        try:
            with self._postgres.cursor() as cursor:
                batch_id = self._insert_running_batch(
                    cursor,
                    dataset_id,
                    source_id,
                    batch_code,
                    trade_date,
                    row_count,
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.dataset_version (
                        dataset_id, version_code, batch_id, valid_from, status, description
                    ) VALUES (%s, %s, %s, now(), 'draft', %s)
                    RETURNING data_version, version_code
                    """,
                    (
                        dataset_id,
                        version_code,
                        batch_id,
                        f"{dataset_code} ingest batch {batch_code}",
                    ),
                )
                version_row = cursor.fetchone()
                if not version_row:
                    raise QDataValidationError(
                        f"dataset version was not created for batch {batch_id}"
                    )
            self._postgres.commit()
        except Exception as exc:
            self._rollback_preserving(exc)
            raise
        return VersionedBatch(
            batch_id=batch_id,
            data_version=version_row["data_version"],
            version_code=version_row["version_code"],
        )

    def _new_batch_code(self, dataset_code: str) -> str:
        return (
            f"{self.source_code}-{dataset_code}-"
            f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        )

    def _insert_running_batch(
        self,
        cursor: Any,
        dataset_id: int,
        source_id: int,
        batch_code: str,
        trade_date: str | None,
        row_count: int,
    ) -> int:
        cursor.execute(
            """
            INSERT INTO qmeta.data_batch (
                dataset_id, source_id, batch_code, trade_date, natural_date,
                started_at, finished_at, status, raw_uri, row_count
            ) VALUES (%s, %s, %s, %s, CURRENT_DATE, now(), NULL, 'running', %s, %s)
            RETURNING batch_id
            """,
            (
                dataset_id,
                source_id,
                batch_code,
                trade_date,
                f"raw://{self.source_code}",
                row_count,
            ),
        )
        row = cursor.fetchone()
        if not row:
            raise QDataValidationError(f"data batch was not created: {batch_code}")
        return row["batch_id"]

    def _finish_batches(
        self,
        batch_ids: list[int],
        status: str,
        error_message: str | None = None,
    ) -> None:
        if not batch_ids:
            return
        if status not in {"success", "failed"}:
            raise QDataValidationError("batch terminal status must be success or failed")
        with self._postgres.cursor() as cursor:
            for batch_id in batch_ids:
                self._transition_batch(cursor, batch_id, status, error_message)
        self._postgres.commit()

    def _finish_versioned_batch(
        self,
        versioned_batch: VersionedBatch,
        status: str,
        error_message: str | None = None,
    ) -> None:
        if status not in {"success", "failed"}:
            raise QDataValidationError("batch terminal status must be success or failed")
        version_status = "active" if status == "success" else "recalled"
        with self._postgres.cursor() as cursor:
            self._transition_batch(
                cursor,
                versioned_batch.batch_id,
                status,
                error_message,
            )
            self._transition_dataset_version(
                cursor,
                versioned_batch.data_version,
                version_status,
            )
        self._postgres.commit()

    def _finish_market_constraint_batches(
        self,
        factor_versioned_batch: VersionedBatch | None,
        batch_ids: list[int],
        status: str,
        error_message: str | None = None,
    ) -> None:
        if status not in {"success", "failed"}:
            raise QDataValidationError("batch terminal status must be success or failed")
        if factor_versioned_batch is None and not batch_ids:
            return
        version_status = "active" if status == "success" else "recalled"
        with self._postgres.cursor() as cursor:
            if factor_versioned_batch is not None:
                self._transition_batch(
                    cursor,
                    factor_versioned_batch.batch_id,
                    status,
                    error_message,
                )
                self._transition_dataset_version(
                    cursor,
                    factor_versioned_batch.data_version,
                    version_status,
                )
            for batch_id in batch_ids:
                self._transition_batch(cursor, batch_id, status, error_message)
        self._postgres.commit()

    @staticmethod
    def _transition_batch(
        cursor: Any,
        batch_id: int,
        status: str,
        error_message: str | None,
    ) -> None:
        error_count = 1 if status == "failed" else 0
        cursor.execute(
            """
            UPDATE qmeta.data_batch
            SET status = %s,
                finished_at = now(),
                error_count = %s,
                error_message = %s
            WHERE batch_id = %s AND status = 'running'
            RETURNING status
            """,
            (status, error_count, error_message, batch_id),
        )
        if cursor.rowcount not in {0, 1}:
            raise QDataValidationError(
                f"batch {batch_id} transition updated {cursor.rowcount} rows"
            )
        row = cursor.fetchone()
        if row and row.get("status") == status:
            return
        cursor.execute(
            "SELECT status FROM qmeta.data_batch WHERE batch_id = %s",
            (batch_id,),
        )
        current = cursor.fetchone()
        current_status = current.get("status") if current else "missing"
        if current_status == status:
            return
        raise QDataValidationError(
            f"batch {batch_id} cannot transition from {current_status} to {status}"
        )

    @staticmethod
    def _transition_dataset_version(
        cursor: Any,
        data_version: int,
        status: str,
    ) -> None:
        cursor.execute(
            """
            UPDATE qmeta.dataset_version
            SET status = %s
            WHERE data_version = %s AND status = 'draft'
            RETURNING status
            """,
            (status, data_version),
        )
        if cursor.rowcount not in {0, 1}:
            raise QDataValidationError(
                f"dataset version {data_version} transition updated {cursor.rowcount} rows"
            )
        row = cursor.fetchone()
        if row and row.get("status") == status:
            return
        cursor.execute(
            "SELECT status FROM qmeta.dataset_version WHERE data_version = %s",
            (data_version,),
        )
        current = cursor.fetchone()
        current_status = current.get("status") if current else "missing"
        if current_status == status:
            return
        raise QDataValidationError(
            f"dataset version {data_version} cannot transition from "
            f"{current_status} to {status}"
        )

    def _record_lifecycle_failure(
        self,
        primary_error: Exception,
        batch_ids: list[int] | None = None,
        versioned_batch: VersionedBatch | None = None,
    ) -> None:
        secondary_errors: list[Exception] = []
        try:
            self._postgres.rollback()
        except Exception as exc:
            secondary_errors.append(exc)
        try:
            if versioned_batch is not None:
                self._finish_versioned_batch(
                    versioned_batch,
                    "failed",
                    str(primary_error),
                )
            elif batch_ids:
                self._finish_batches(batch_ids, "failed", str(primary_error))
        except Exception as exc:
            secondary_errors.append(exc)
        if secondary_errors:
            self._attach_lifecycle_errors(primary_error, secondary_errors)

    def _record_market_constraint_failure(
        self,
        primary_error: Exception,
        factor_versioned_batch: VersionedBatch | None,
        batch_ids: list[int],
    ) -> None:
        secondary_errors: list[Exception] = []
        try:
            self._postgres.rollback()
        except Exception as exc:
            secondary_errors.append(exc)
        try:
            self._finish_market_constraint_batches(
                factor_versioned_batch,
                batch_ids,
                "failed",
                str(primary_error),
            )
        except Exception as exc:
            secondary_errors.append(exc)
        if secondary_errors:
            self._attach_lifecycle_errors(primary_error, secondary_errors)

    def _rollback_preserving(self, primary_error: Exception) -> None:
        try:
            self._postgres.rollback()
        except Exception as exc:
            self._attach_lifecycle_errors(primary_error, [exc])

    @staticmethod
    def _attach_lifecycle_errors(
        primary_error: Exception,
        secondary_errors: list[Exception],
    ) -> None:
        existing = tuple(getattr(primary_error, "qdata_lifecycle_errors", ()))
        try:
            primary_error.qdata_lifecycle_errors = existing + tuple(secondary_errors)
        except (AttributeError, TypeError):
            pass

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
