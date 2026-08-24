from __future__ import annotations

import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import unittest

from qdata import Client
from qdata.exceptions import QDataNotFoundError


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_DSN = os.getenv("QDATA_TEST_POSTGRES_DSN")


def _seed_rows(table: str) -> list[dict[str, str]]:
    seed = (ROOT / "db" / "seed" / "postgresql_seed.sql").read_text(
        encoding="utf-8"
    )
    insert = seed.split(f"INSERT INTO {table} (", 1)[1]
    columns_text, values_and_tail = insert.split(") VALUES", 1)
    values_text = values_and_tail.split("ON CONFLICT", 1)[0]
    columns = [column.strip() for column in columns_text.split(",")]
    tuples = re.findall(r"\(([^()]*)\)", values_text, flags=re.DOTALL)
    rows = []
    for tuple_text in tuples:
        values = next(
            csv.reader(
                [tuple_text], delimiter=",", quotechar="'", skipinitialspace=True
            )
        )
        if len(values) != len(columns):
            raise AssertionError(
                f"could not parse {table} seed row: "
                f"expected {len(columns)} fields, got {len(values)}"
            )
        rows.append(dict(zip(columns, (value.strip() for value in values))))
    return rows


def _seed_timestamp(value: str) -> datetime:
    lowered = value.lower()
    if lowered == "default" or re.search(r"\b(now|current_timestamp)\b", lowered):
        raise AssertionError(f"non-reproducible seed timestamp: {value}")
    normalized = re.sub(r"([+-]\d{2})$", r"\1:00", value.replace("Z", "+00:00"))
    parsed = datetime.fromisoformat(normalized)
    if parsed.utcoffset() is None:
        raise AssertionError(f"seed timestamp is not timezone-aware: {value}")
    return parsed


class SeedTimeContractTest(unittest.TestCase):
    def test_historical_adjustment_seed_rejects_default_now_or_future_times(
        self,
    ) -> None:
        current_time = datetime.now(timezone.utc)
        for row in _seed_rows("qmeta.adjustment_factor"):
            with self.subTest(
                security_id=row["security_id"], trade_date=row["trade_date"]
            ):
                for field in ("announce_time", "effective_time", "ingest_time"):
                    parsed = _seed_timestamp(row[field])
                    self.assertLessEqual(parsed, current_time)

    def test_every_adjustment_record_has_a_causal_dataset_batch_and_version(
        self,
    ) -> None:
        current_time = datetime.now(timezone.utc)
        adjustments = _seed_rows("qmeta.adjustment_factor")
        batches = {
            int(row["batch_id"]): row for row in _seed_rows("qmeta.data_batch")
        }
        versions_by_batch: dict[int, list[dict[str, str]]] = {}
        for version in _seed_rows("qmeta.dataset_version"):
            versions_by_batch.setdefault(int(version["batch_id"]), []).append(version)

        dates_by_batch: dict[int, set[str]] = {}
        rows_by_batch: dict[int, int] = {}
        for row in adjustments:
            batch_id = int(row["batch_id"])
            batch = batches[batch_id]
            dates_by_batch.setdefault(batch_id, set()).add(row["trade_date"])
            rows_by_batch[batch_id] = rows_by_batch.get(batch_id, 0) + 1

            with self.subTest(
                security_id=row["security_id"], trade_date=row["trade_date"]
            ):
                self.assertEqual(batch["dataset_id"], "5")
                self.assertEqual(batch["source_id"], row["source_id"])
                self.assertEqual(batch["trade_date"], row["trade_date"])
                self.assertEqual(batch["status"], "success")

                started_at = _seed_timestamp(batch["started_at"])
                finished_at = _seed_timestamp(batch["finished_at"])
                ingest_time = _seed_timestamp(row["ingest_time"])
                self.assertLessEqual(started_at, ingest_time)
                self.assertLessEqual(ingest_time, finished_at)
                self.assertLessEqual(finished_at, current_time)

                matching_versions = versions_by_batch.get(batch_id, [])
                self.assertEqual(len(matching_versions), 1)
                version = matching_versions[0]
                self.assertEqual(version["dataset_id"], "5")
                self.assertIn(version["status"], {"active", "superseded"})
                availability = max(
                    _seed_timestamp(row["announce_time"]),
                    _seed_timestamp(row["effective_time"]),
                    ingest_time,
                )
                published_at = _seed_timestamp(version["valid_from"])
                self.assertGreaterEqual(published_at, availability)
                self.assertLessEqual(published_at, current_time)

        self.assertEqual(
            len(dates_by_batch), len({row["trade_date"] for row in adjustments})
        )
        for batch_id, dates in dates_by_batch.items():
            with self.subTest(batch_id=batch_id):
                self.assertEqual(len(dates), 1)
                self.assertEqual(
                    int(batches[batch_id]["row_count"]), rows_by_batch[batch_id]
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

        revenue = self.client.get_fundamental_asof(
            symbols=["600519.SH"],
            fields=["revenue"],
            asof_date="2021-06-30",
            period_type="ttm",
        )
        self.assertEqual(len(revenue), 1)
        self.assertEqual(revenue[0]["report_period"], "2021-03-31")
        self.assertEqual(str(revenue[0]["field_value"]), "27271000000.00000000")

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
            include_meta=True,
        )
        self.assertEqual(asof[0]["open"], 893.3959)
        self.assertEqual(vintage["data"][0]["open"], 893.3959)
        self.assertEqual(vintage["meta"]["data_version"], "daily_bar:seed-v1")
        self.assertEqual(vintage["meta"]["data_versions"], ["daily_bar:seed-v1"])

    def test_real_version_selector_fails_closed_before_publication_and_for_unknown_vintage(
        self,
    ) -> None:
        common = {
            "symbols": ["600519.SH"],
            "start_date": "2024-01-02",
            "end_date": "2024-01-02",
            "adjust": "forward",
        }
        with self.assertRaisesRegex(QDataNotFoundError, "No published data versions"):
            self.client.get_price(
                **common,
                query_mode="asof",
                asof_time="2024-01-02T18:00:00+08:00",
            )

        with self.assertRaisesRegex(
            QDataNotFoundError, "Unknown or unavailable data_version"
        ):
            self.client.get_price(
                **common,
                query_mode="vintage",
                data_version="daily_bar:does-not-exist",
            )


if __name__ == "__main__":
    unittest.main()
