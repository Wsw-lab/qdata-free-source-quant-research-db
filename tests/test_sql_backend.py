import os
import unittest
from unittest.mock import patch

from qdata import Client


class FakePostgres:
    def __init__(self) -> None:
        self.queries = []
        self.closed = False

    def fetch_all(self, sql, params=None):
        self.queries.append((sql, params or {}))
        if "FROM qmeta.security_master" in sql:
            return [
                {
                    "security_id": 1000001,
                    "symbol": "600519.SH",
                    "asset_type": "stock",
                    "exchange": "SH",
                    "name": "贵州茅台",
                    "list_date": "2001-08-27",
                    "delist_date": None,
                    "status": "active",
                    "currency": "CNY",
                }
            ]
        if "FROM qmeta.adjustment_factor" in sql:
            return [
                {
                    "security_id": 1000001,
                    "trade_date": "2024-01-02",
                    "factor_forward": 0.5,
                    "factor_backward": 2.0,
                    "ex_right_type": "none",
                }
            ]
        if "FROM qmeta.limit_price_daily lp" in sql:
            return [
                {
                    "security_id": 1000001,
                    "trade_date": "2024-01-02",
                    "limit_up": 11.55,
                    "limit_down": 9.45,
                    "is_st": False,
                    "is_new_listing": False,
                    "is_suspended": False,
                    "is_delisting_period": False,
                    "list_days": 8163,
                }
            ]
        if "FROM qpit.financial_metric_pit" in sql:
            return [
                {
                    "security_id": 1000001,
                    "report_period": "2021-03-31",
                    "field_name": "roe_ttm",
                    "field_value": 0.283,
                    "announce_time": "2021-04-27T19:30:00+08:00",
                    "ingest_time": "2021-04-27T19:31:00+08:00",
                    "revision_id": 1,
                    "is_restated": False,
                }
            ]
        return []

    def close(self):
        self.closed = True


class FakeClickHouse:
    def __init__(self) -> None:
        self.queries = []
        self.closed = False

    def fetch_all(self, sql, params=None):
        self.queries.append((sql, params or {}))
        if "FROM qts.daily_bar" in sql:
            return [
                {
                    "security_id": 1000001,
                    "trade_date": "2024-01-02",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000.0,
                    "amount": 10500.0,
                }
            ]
        return []

    def close(self):
        self.closed = True


class SqlBackendTest(unittest.TestCase):
    def test_sql_backend_get_security_master_uses_injected_postgres(self) -> None:
        postgres = FakePostgres()
        client = Client(backend="sql", postgres_client=postgres, default_format="records")

        rows = client.get_security_master(symbols=["600519.SH"], asof_date="2024-12-31")

        self.assertEqual(rows[0]["symbol"], "600519.SH")
        self.assertTrue(postgres.queries)
        self.assertIn("sm.list_date IS NULL", postgres.queries[-1][0])

    def test_sql_backend_get_price_uses_clickhouse_and_adjustment_factor(self) -> None:
        postgres = FakePostgres()
        clickhouse = FakeClickHouse()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            clickhouse_client=clickhouse,
            default_format="records",
        )

        rows = client.get_price(
            symbols=["600519.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            adjust="forward",
        )

        self.assertEqual(rows[0]["symbol"], "600519.SH")
        self.assertEqual(rows[0]["close"], 5.25)
        self.assertTrue(clickhouse.queries)
        self.assertIn("list_date IS NULL", postgres.queries[0][0])

    def test_sql_backend_get_fundamental_asof(self) -> None:
        client = Client(backend="sql", postgres_client=FakePostgres(), default_format="records")

        rows = client.get_fundamental_asof(
            symbols=["600519.SH"],
            fields=["roe_ttm"],
            asof_date="2021-06-30",
        )

        self.assertEqual(rows[0]["report_period"], "2021-03-31")
        self.assertEqual(rows[0]["field_value"], 0.283)

    def test_sql_backend_get_tradable_universe_filters_constraints(self) -> None:
        postgres = FakePostgres()
        client = Client(backend="sql", postgres_client=postgres, default_format="records")

        rows = client.get_tradable_universe(
            asof_date="2024-01-02",
            symbols=["600519.SH"],
            min_list_days=30,
        )

        self.assertEqual(rows[0]["symbol"], "600519.SH")
        self.assertTrue(rows[0]["can_buy"])
        self.assertFalse(rows[0]["is_new_listing"])

    def test_auto_backend_without_dsn_falls_back_to_mock(self) -> None:
        with patch.dict(os.environ, {"QDATA_BACKEND": "auto"}, clear=True):
            client = Client(default_format="records")
            rows = client.get_security_master(symbols=["600519.SH"])

        self.assertEqual(rows[0]["symbol"], "600519.SH")


if __name__ == "__main__":
    unittest.main()
