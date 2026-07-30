import json
import unittest

from qdata.ingest.models import AdjustmentFactorRecord, LimitPriceRecord, QualityReport, SuspensionRecord
from qdata.loaders.sql_loader import SqlDailyBundleLoader


class FakeConnection:
    def __init__(self) -> None:
        self.executed = []
        self.commit_count = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commit_count += 1


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, params))


class SqlDailyBundleLoaderTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
