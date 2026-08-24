from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import unittest

from qdata import Client


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_DSN = os.getenv("QDATA_TEST_POSTGRES_DSN")


class SeedTimeContractTest(unittest.TestCase):
    def test_historical_adjustment_seed_pins_ingest_time(self) -> None:
        seed = (ROOT / "db" / "seed" / "postgresql_seed.sql").read_text(
            encoding="utf-8"
        )
        adjustment_insert = seed.split(
            "INSERT INTO qmeta.adjustment_factor (", 1
        )[1].split("ON CONFLICT DO NOTHING;", 1)[0]
        self.assertIn(
            "announce_time, effective_time, ingest_time, source_id",
            " ".join(adjustment_insert.split()),
        )


class _DailyBarClickHouse:
    def __init__(self) -> None:
        self.closed = False

    def fetch_all(self, sql: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        if "FROM qts.daily_bar" not in sql:
            return []
        row = {
            "security_id": 1000001,
            "trade_date": "2024-01-02",
            "open": 1679.0,
            "high": 1702.0,
            "low": 1670.0,
            "close": 1698.0,
            "volume": 12_500_000.0,
            "amount": 21_000_000_000.0,
            "data_version": 2,
            "ingest_time": datetime.fromisoformat("2024-01-02T18:00:00+08:00"),
        }
        if row["security_id"] not in set(params.get("security_ids") or []):
            return []
        if row["data_version"] not in set(params.get("allowed_data_versions") or []):
            return []
        cutoff = params.get("asof_time")
        if cutoff is not None and row["ingest_time"] > cutoff:
            return []
        return [row]

    def close(self) -> None:
        self.closed = True


@unittest.skipUnless(
    POSTGRES_DSN,
    "set QDATA_TEST_POSTGRES_DSN to a disposable database loaded with 0001, 0006, and the seed",
)
class PostgresSqlBackendIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clickhouse = _DailyBarClickHouse()
        self.client = Client(
            backend="sql",
            postgres_dsn=POSTGRES_DSN,
            clickhouse_client=self.clickhouse,
            default_format="records",
        )

    def tearDown(self) -> None:
        self.client.close()

    def test_real_array_binding_distinct_on_and_pit_selection(self) -> None:
        securities = self.client.get_security_master(
            symbols=["600519.SH", "000001.SZ"], asof_date="2024-01-02"
        )
        self.assertEqual(
            [row["symbol"] for row in securities],
            ["600519.SH", "000001.SZ"],
        )

        factors = self.client.get_adjustment_factor(
            symbols=["600519.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            factor_type="both",
        )
        self.assertEqual(len(factors), 1)
        self.assertEqual(str(factors[0]["factor_forward"]), "0.532100000000")

        fundamentals = self.client.get_fundamental_asof(
            symbols=["600519.SH"],
            fields=["roe_ttm"],
            asof_date="2021-06-30",
            period_type="ttm",
        )
        self.assertEqual(len(fundamentals), 1)
        self.assertEqual(fundamentals[0]["report_period"], "2021-03-31")

    def test_real_version_and_adjustment_selection_support_asof_and_vintage(self) -> None:
        common = {
            "symbols": ["600519.SH"],
            "start_date": "2024-01-02",
            "end_date": "2024-01-02",
            "adjust": "forward",
        }
        asof = self.client.get_price(
            **common,
            query_mode="asof",
            asof_time="2024-01-02T18:00:02+08:00",
        )
        vintage = self.client.get_price(
            **common,
            query_mode="vintage",
            data_version="daily_bar:seed-v1",
        )
        self.assertEqual(asof[0]["open"], 893.3959)
        self.assertEqual(vintage[0]["open"], 893.3959)


if __name__ == "__main__":
    unittest.main()
