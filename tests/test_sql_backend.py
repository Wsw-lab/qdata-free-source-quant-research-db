import os
import unittest
from unittest.mock import patch

from qdata import Client
from qdata.exceptions import QDataNotFoundError, QDataValidationError


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
        if "FROM qmeta.dataset_version" in sql:
            if str((params or {}).get("data_version")) in {"2", "daily_bar:seed-v1"}:
                return [
                    {
                        "data_version": 2,
                        "version_code": "daily_bar:seed-v1",
                        "batch_id": 2,
                        "status": "active",
                    }
                ]
            return []
        if "FROM qmeta.factor_definition" in sql:
            if (params or {}).get("factor_version") in {"published", "mom-v1"}:
                return [
                    {
                        "factor_id": 101,
                        "factor_code": "momentum_20d",
                        "factor_version_id": 1001,
                        "version_code": "mom-v1",
                    }
                ]
            return []
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
        if "FROM qts.factor_value_daily" in sql:
            return [
                {
                    "factor_id": 101,
                    "factor_version_id": 1001,
                    "security_id": 1000001,
                    "trade_date": "2024-01-02",
                    "factor_value": 0.75,
                    "quality_flag": "normal",
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

    def test_sql_backend_get_price_applies_asof_before_revision_ranking(self) -> None:
        clickhouse = FakeClickHouse()
        client = Client(
            backend="sql",
            postgres_client=FakePostgres(),
            clickhouse_client=clickhouse,
            default_format="records",
        )

        client.get_price(
            symbols=["600519.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            query_mode="asof",
            asof_time="2024-01-02T18:00:00+08:00",
        )

        sql, params = clickhouse.queries[-1]
        self.assertIn("ingest_time <= %(asof_time)s", sql)
        self.assertIn("row_number() OVER", sql)
        self.assertNotIn("FROM qts.daily_bar FINAL", sql)
        self.assertEqual(params["asof_time"], "2024-01-02T18:00:00+08:00")

    def test_sql_backend_get_price_resolves_and_filters_vintage(self) -> None:
        postgres = FakePostgres()
        clickhouse = FakeClickHouse()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            clickhouse_client=clickhouse,
            default_format="records",
        )

        payload = client.get_price(
            symbols=["600519.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            query_mode="vintage",
            data_version="daily_bar:seed-v1",
            include_meta=True,
        )

        sql, params = clickhouse.queries[-1]
        self.assertIn("data_version = %(resolved_data_version)s", sql)
        self.assertEqual(params["resolved_data_version"], 2)
        self.assertEqual(payload["meta"]["data_version"], "daily_bar:seed-v1")
        version_queries = [query for query in postgres.queries if "FROM qmeta.dataset_version" in query[0]]
        self.assertEqual(len(version_queries), 1)

    def test_sql_backend_price_modes_fail_closed_when_cutoff_or_version_is_missing(self) -> None:
        client = Client(
            backend="sql",
            postgres_client=FakePostgres(),
            clickhouse_client=FakeClickHouse(),
            default_format="records",
        )
        kwargs = {
            "symbols": ["600519.SH"],
            "start_date": "2024-01-02",
            "end_date": "2024-01-02",
        }

        with self.assertRaisesRegex(QDataValidationError, "asof_time is required"):
            client.get_price(**kwargs, query_mode="asof")
        with self.assertRaisesRegex(QDataValidationError, "data_version is required"):
            client.get_price(**kwargs, query_mode="vintage")
        with self.assertRaisesRegex(QDataNotFoundError, "Unknown or unavailable data_version"):
            client.get_price(**kwargs, query_mode="vintage", data_version="does-not-exist")
        with self.assertRaisesRegex(QDataValidationError, "ISO-8601"):
            client.get_price(**kwargs, query_mode="asof", asof_time="not-a-timestamp")

    def test_sql_backend_get_factor_filters_exact_resolved_version(self) -> None:
        clickhouse = FakeClickHouse()
        client = Client(
            backend="sql",
            postgres_client=FakePostgres(),
            clickhouse_client=clickhouse,
            default_format="records",
        )

        rows = client.get_factor(
            factors=["momentum_20d"],
            symbols=["600519.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            factor_version="mom-v1",
        )

        sql, params = clickhouse.queries[-1]
        self.assertIn("factor_version_id IN %(factor_version_ids)s", sql)
        self.assertEqual(params["factor_version_ids"], (1001,))
        self.assertEqual(rows[0]["factor_version"], "mom-v1")

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
