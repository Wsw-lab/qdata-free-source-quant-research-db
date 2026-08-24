import json
import unittest

from qdata.ingest.models import (
    AdjustmentFactorRecord,
    DailyBarRecord,
    LimitPriceRecord,
    MinuteBarRecord,
    QualityReport,
    SuspensionRecord,
)
from qdata.loaders.sql_loader import SqlDailyBundleLoader


class FakeConnection:
    def __init__(self) -> None:
        self.executed = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fetchone_results = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, params))

    def fetchone(self):
        if self.connection.fetchone_results:
            return self.connection.fetchone_results.pop(0)
        return None


class FakeClickHouse:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.inserts = []

    def insert(self, table, rows, column_names):
        self.inserts.append((table, rows, column_names))
        if self.fail:
            raise RuntimeError("clickhouse write failed")


class SqlDailyBundleLoaderTest(unittest.TestCase):
    def test_create_batch_starts_running_without_finished_timestamp(self) -> None:
        connection = FakeConnection()
        connection.fetchone_results.append({"batch_id": 99})
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="csv",
        )
        loader._postgres = connection
        loader._dataset_id = lambda dataset_code: 7

        batch_id = loader._create_batch("daily_bar", 11, "2024-01-04", 1)

        sql, params = connection.executed[0]
        self.assertEqual(batch_id, 99)
        self.assertIn("NULL, 'running'", sql)
        self.assertNotIn("'success'", sql)
        self.assertEqual(params[-1], 1)

    def test_quality_report_cleanup_is_scoped_to_source_and_job(self) -> None:
        connection = FakeConnection()
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="csv",
        )
        loader._postgres = connection
        loader.open = lambda: None
        loader._source_id = lambda: 11
        loader._create_batch = lambda dataset_code, source_id, trade_date, row_count: 99
        loader._dataset_id = lambda dataset_code: 7

        loader.write_quality_report(
            QualityReport(),
            check_date="2024-01-04",
            context={"job_code": "daily_market_csv_all", "run_id": 42},
        )

        delete_sql, delete_params = connection.executed[0]
        self.assertIn("FROM qmeta.data_batch", delete_sql)
        self.assertIn("source_id = %s", delete_sql)
        self.assertIn("details ? 'job_code'", delete_sql)
        self.assertEqual(
            delete_params,
            (
                "2024-01-04",
                list(SqlDailyBundleLoader.DATASETS),
                11,
                "daily_market_csv_all",
                "daily_market_csv_all",
                "daily_market_csv_all",
            ),
        )

        _, insert_params = connection.executed[1]
        details = json.loads(insert_params[3])
        self.assertEqual(details["job_code"], "daily_market_csv_all")
        self.assertEqual(details["run_id"], 42)

    def test_load_market_constraints_upserts_factor_limit_and_suspension(self) -> None:
        connection = FakeConnection()
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="csv",
        )
        loader._postgres = connection
        loader.open = lambda: None
        loader._source_id = lambda: 11
        loader._security_id_map = lambda symbols: {"600519.SH": 1000001}
        loader._create_batch = lambda dataset_code, source_id, trade_date, row_count: {
            "adjustment_factor": 91,
            "limit_price_daily": 92,
            "suspension_history": 93,
        }[dataset_code]

        loader.load_market_constraints(
            adjustment_factors=[
                AdjustmentFactorRecord("600519.SH", "2024-01-04", 0.5, 2.0, "cash_dividend")
            ],
            limit_prices=[
                LimitPriceRecord("600519.SH", "2024-01-04", 100.0, 80.0, "main_10pct")
            ],
            suspensions=[
                SuspensionRecord("600519.SH", "2024-01-04 09:30:00", "2024-01-04 15:00:00", "full_day", "test")
            ],
        )

        sql_text = "\n".join(sql for sql, _ in connection.executed)
        self.assertIn("INSERT INTO qmeta.adjustment_factor", sql_text)
        self.assertIn("INSERT INTO qmeta.limit_price_daily", sql_text)
        self.assertIn("INSERT INTO qmeta.suspension_history", sql_text)

    def test_daily_bar_batch_is_marked_success_only_after_clickhouse_write(self) -> None:
        connection = FakeConnection()
        clickhouse = FakeClickHouse()
        loader = self._daily_loader(connection, clickhouse)

        loader.load_daily_bars([self._daily_bar()])

        self.assertEqual(clickhouse.inserts[0][0], "qts.daily_bar")
        status_updates = [
            params
            for sql, params in connection.executed
            if "UPDATE qmeta.data_batch" in sql
        ]
        self.assertEqual(status_updates, [("success", 0, None, 99)])

    def test_daily_bar_batch_is_marked_failed_and_postgres_is_rolled_back(self) -> None:
        connection = FakeConnection()
        loader = self._daily_loader(connection, FakeClickHouse(fail=True))

        with self.assertRaisesRegex(RuntimeError, "clickhouse write failed"):
            loader.load_daily_bars([self._daily_bar()])

        self.assertEqual(connection.rollback_count, 1)
        status_updates = [
            params
            for sql, params in connection.executed
            if "UPDATE qmeta.data_batch" in sql
        ]
        self.assertEqual(status_updates, [("failed", 1, "clickhouse write failed", 99)])

    def test_minute_bar_batch_is_marked_failed_when_clickhouse_write_fails(self) -> None:
        connection = FakeConnection()
        loader = self._daily_loader(connection, FakeClickHouse(fail=True))
        minute = MinuteBarRecord(
            symbol="600519.SH",
            trade_date="2024-01-04",
            bar_time="2024-01-04 09:31:00",
            open=10.0,
            high=10.1,
            low=9.9,
            close=10.0,
            volume=100.0,
            amount=1000.0,
        )

        with self.assertRaisesRegex(RuntimeError, "clickhouse write failed"):
            loader.load_minute_bars([minute])

        status_updates = [
            params
            for sql, params in connection.executed
            if "UPDATE qmeta.data_batch" in sql
        ]
        self.assertEqual(status_updates, [("failed", 1, "clickhouse write failed", 99)])

    @staticmethod
    def _daily_loader(connection, clickhouse):
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="csv",
        )
        loader._postgres = connection
        loader._clickhouse = clickhouse
        loader.open = lambda: None
        loader._source_id = lambda: 11
        loader._security_id_map = lambda symbols: {"600519.SH": 1000001}
        loader._create_batch = lambda dataset_code, source_id, trade_date, row_count: 99
        return loader

    @staticmethod
    def _daily_bar():
        return DailyBarRecord(
            symbol="600519.SH",
            trade_date="2024-01-04",
            open=10.0,
            high=11.0,
            low=9.0,
            close=10.5,
            pre_close=10.0,
            volume=1000.0,
            amount=10500.0,
        )


if __name__ == "__main__":
    unittest.main()
