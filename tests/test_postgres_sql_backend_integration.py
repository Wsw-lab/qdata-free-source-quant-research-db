from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
import unittest

from qdata import Client
from qdata.exceptions import QDataNotFoundError, QDataValidationError
from qdata.ingest.models import (
    AdjustmentFactorRecord,
    LimitPriceRecord,
    SecurityRecord,
    SuspensionRecord,
    TradableUniverseRecord,
)
from qdata.loaders.sql_loader import SqlDailyBundleLoader


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_DSN = os.getenv("QDATA_TEST_POSTGRES_DSN")
CLICKHOUSE_DSN = os.getenv("QDATA_TEST_CLICKHOUSE_DSN")


def _seed_rows(
    table: str,
    seed_path: Path | None = None,
) -> list[dict[str, str]]:
    seed = (seed_path or ROOT / "db" / "seed" / "postgresql_seed.sql").read_text(
        encoding="utf-8"
    )
    insert = seed.split(f"INSERT INTO {table} (", 1)[1]
    columns_text, values_and_tail = insert.split(") VALUES", 1)
    values_text = values_and_tail.split("ON CONFLICT", 1)[0].split(";", 1)[0]
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
    def test_every_public_pit_seed_row_has_explicit_causal_batch_and_version(self) -> None:
        dataset_ids = {
            "qmeta.security_identifier_history": "1",
            "qmeta.security_name_history": "1",
            "qmeta.security_status_history": "1",
            "qpit.financial_metric_pit": "7",
            "qpit.financial_statement_pit": "8",
            "qpit.index_member_pit": "9",
            "qmeta.industry_category_history": "10",
            "qpit.industry_membership_pit": "10",
            "qpit.universe_member_pit": "12",
            "qmeta.limit_price_daily": "6",
        }
        batches = {
            int(row["batch_id"]): row for row in _seed_rows("qmeta.data_batch")
        }
        versions_by_batch: dict[int, list[dict[str, str]]] = {}
        for version in _seed_rows("qmeta.dataset_version"):
            versions_by_batch.setdefault(int(version["batch_id"]), []).append(version)

        for table, expected_dataset_id in dataset_ids.items():
            rows = _seed_rows(table)
            self.assertTrue(rows, table)
            for row in rows:
                with self.subTest(table=table, row=row):
                    self.assertIn("ingest_time", row)
                    ingest_time = _seed_timestamp(row["ingest_time"])
                    batch = batches[int(row["batch_id"])]
                    self.assertEqual(batch["dataset_id"], expected_dataset_id)
                    self.assertEqual(batch["status"], "success")
                    self.assertEqual(batch["source_id"], row["source_id"])
                    started_at = _seed_timestamp(batch["started_at"])
                    finished_at = _seed_timestamp(batch["finished_at"])
                    self.assertLessEqual(started_at, ingest_time)
                    self.assertLessEqual(ingest_time, finished_at)
                    if "announce_time" in row:
                        self.assertLessEqual(
                            _seed_timestamp(row["announce_time"]),
                            finished_at,
                        )
                    if "effective_time" in row:
                        self.assertLessEqual(
                            _seed_timestamp(row["effective_time"]),
                            finished_at,
                        )
                    versions = versions_by_batch.get(int(row["batch_id"]), [])
                    self.assertEqual(len(versions), 1)
                    self.assertEqual(versions[0]["dataset_id"], expected_dataset_id)
                    self.assertIn(versions[0]["status"], {"active", "superseded"})
                    availability = [ingest_time]
                    for field in ("announce_time", "effective_time"):
                        if field in row:
                            availability.append(_seed_timestamp(row[field]))
                    self.assertGreaterEqual(
                        _seed_timestamp(versions[0]["valid_from"]),
                        max(availability),
                    )

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

    def test_every_clickhouse_factor_data_version_is_published_by_factor_dataset(self) -> None:
        clickhouse_rows = _seed_rows(
            "qts.factor_value_daily",
            ROOT / "db" / "seed" / "clickhouse_seed.sql",
        )
        versions = {
            int(row["data_version"]): row
            for row in _seed_rows("qmeta.dataset_version")
            if row["dataset_id"] == "11"
        }
        batches = {
            int(row["batch_id"]): row for row in _seed_rows("qmeta.data_batch")
        }

        self.assertTrue(clickhouse_rows)
        for row in clickhouse_rows:
            data_version = int(row["data_version"])
            with self.subTest(data_version=data_version):
                self.assertIn(data_version, versions)
                version = versions[data_version]
                self.assertIn(version["status"], {"active", "superseded"})
                batch = batches[int(version["batch_id"])]
                self.assertEqual(batch["dataset_id"], "11")
                self.assertEqual(batch["status"], "success")
                self.assertNotEqual(batch["finished_at"].upper(), "NULL")


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

    def test_real_membership_universe_and_constraint_selectors(self) -> None:
        index_rows = self.client.get_index_members_asof(
            "000300.SH",
            "2024-01-02",
        )
        self.assertEqual(
            [row["symbol"] for row in index_rows],
            ["600519.SH", "000001.SZ"],
        )

        industry_rows = self.client.get_industry_asof(
            symbols=["600519.SH"],
            industry_system="sw",
            level=1,
            asof_date="2024-01-02",
        )
        self.assertEqual(industry_rows[0]["industry_code"], "801120")

        universe_rows = self.client.get_universe(
            "zz800",
            "2024-01-02",
            include_weight=True,
        )
        self.assertEqual(
            [row["symbol"] for row in universe_rows],
            ["600519.SH", "000001.SZ"],
        )

        constraints = self.client.get_trading_constraints(
            symbols=["600519.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
        )
        self.assertEqual(str(constraints[0]["limit_up"]), "1842.500000")

    def test_utc_session_cannot_leak_next_shanghai_day_revisions(self) -> None:
        connection = self.client._backend.postgres._connection
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL TIME ZONE 'UTC'")
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_batch (
                        dataset_id, source_id, batch_code, trade_date, natural_date,
                        started_at, finished_at, status, row_count
                    ) VALUES (
                        1, 2, 'test-utc-late-security', '2024-01-02', '2024-01-02',
                        '2024-01-03 00:29:00+08', '2024-01-03 00:30:00+08',
                        'success', 1
                    ) RETURNING batch_id
                    """
                )
                security_batch = cursor.fetchone()["batch_id"]
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_identifier_history (
                        security_id, symbol, exchange, identifier_type, start_date,
                        end_date, announce_time, ingest_time, source_id, batch_id,
                        revision_id
                    ) VALUES (
                        1000001, 'TZLEAK', 'SH', 'trade_symbol', '2001-08-27',
                        NULL, '2024-01-03 00:30:00+08',
                        '2024-01-03 00:30:00+08', 2, %s, 999
                    )
                    """,
                    (security_batch,),
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_batch (
                        dataset_id, source_id, batch_code, trade_date, natural_date,
                        started_at, finished_at, status, row_count
                    ) VALUES (
                        6, 2, 'test-utc-late-limit', '2024-01-02', '2024-01-02',
                        '2024-01-03 00:29:00+08', '2024-01-03 00:30:00+08',
                        'success', 1
                    ) RETURNING batch_id
                    """
                )
                limit_batch = cursor.fetchone()["batch_id"]
                cursor.execute(
                    """
                    INSERT INTO qmeta.limit_price_daily (
                        security_id, trade_date, limit_up, limit_down, limit_rule,
                        is_st, is_new_listing, ingest_time, source_id, batch_id,
                        revision_id
                    ) VALUES (
                        1000001, '2024-01-02', 9999, 1, 'timezone leak',
                        FALSE, FALSE, '2024-01-03 00:30:00+08', 2, %s, 999
                    )
                    """,
                    (limit_batch,),
                )

            securities = self.client.get_security_master(
                security_ids=[1000001],
                asof_date="2024-01-02",
            )
            constraints = self.client.get_trading_constraints(
                symbols=["600519.SH"],
                start_date="2024-01-02",
                end_date="2024-01-02",
            )

            self.assertEqual(securities[0]["symbol"], "600519.SH")
            self.assertEqual(str(constraints[0]["limit_up"]), "1842.500000")
        finally:
            connection.rollback()

    def test_real_overlapping_membership_episodes_select_latest_effective_episode(self) -> None:
        connection = self.client._backend.postgres._connection
        suffix = datetime.now().strftime("%H%M%S%f")
        index_code = f"I{suffix}.SH"
        universe_code = f"overlap_{suffix}"
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.index_master (
                        index_code, exchange, index_name, provider, currency,
                        base_date, launch_date
                    ) VALUES (%s, 'SH', 'Overlap index', 'test', 'CNY',
                              '2024-01-01', '2024-01-01')
                    RETURNING index_id
                    """,
                    (index_code,),
                )
                index_id = cursor.fetchone()["index_id"]
                cursor.execute(
                    """
                    INSERT INTO qmeta.universe_definition (
                        universe_code, universe_name, universe_type, description, owner
                    ) VALUES (%s, 'Overlap universe', 'manual', 'test', 'test')
                    RETURNING universe_id
                    """,
                    (universe_code,),
                )
                universe_id = cursor.fetchone()["universe_id"]
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_batch (
                        dataset_id, source_id, batch_code, trade_date, natural_date,
                        started_at, finished_at, status, row_count
                    ) VALUES
                        (9, 3, %s, '2024-01-02', '2024-01-02',
                         '2024-01-02 18:00:00+08', '2024-01-02 18:01:00+08',
                         'success', 2),
                        (10, 2, %s, '2024-01-02', '2024-01-02',
                         '2024-01-02 18:00:00+08', '2024-01-02 18:01:00+08',
                         'success', 2),
                        (12, 2, %s, '2024-01-02', '2024-01-02',
                         '2024-01-02 18:00:00+08', '2024-01-02 18:01:00+08',
                         'success', 2)
                    RETURNING dataset_id, batch_id
                    """,
                    (
                        f"test-overlap-index-{suffix}",
                        f"test-overlap-industry-{suffix}",
                        f"test-overlap-universe-{suffix}",
                    ),
                )
                batch_by_dataset = {
                    row["dataset_id"]: row["batch_id"] for row in cursor.fetchall()
                }
                cursor.execute(
                    """
                    INSERT INTO qpit.index_member_pit (
                        index_id, security_id, effective_date, end_date, weight,
                        announce_time, ingest_time, source_id, batch_id, revision_id
                    ) VALUES
                        (%s, 1000001, '2024-01-01', NULL, 0.4,
                         '2024-01-01 18:00:00+08', '2024-01-01 18:01:00+08',
                         3, %s, 1),
                        (%s, 1000001, '2024-01-02', NULL, 0.6,
                         '2024-01-02 18:00:00+08', '2024-01-02 18:01:00+08',
                         3, %s, 1)
                    """,
                    (index_id, batch_by_dataset[9], index_id, batch_by_dataset[9]),
                )
                cursor.execute(
                    """
                    INSERT INTO qpit.industry_membership_pit (
                        security_id, industry_system_id, industry_id,
                        effective_date, end_date, announce_time, ingest_time,
                        source_id, batch_id, revision_id
                    ) VALUES
                        (1000001, 1, 101, '2024-01-01', NULL,
                         '2024-01-01 18:00:00+08', '2024-01-01 18:01:00+08',
                         2, %s, 1),
                        (1000001, 1, 102, '2024-01-02', NULL,
                         '2024-01-02 18:00:00+08', '2024-01-02 18:01:00+08',
                         2, %s, 1)
                    """,
                    (batch_by_dataset[10], batch_by_dataset[10]),
                )
                cursor.execute(
                    """
                    INSERT INTO qpit.universe_member_pit (
                        universe_id, security_id, effective_date, end_date, weight,
                        announce_time, ingest_time, revision_id, source_id, batch_id
                    ) VALUES
                        (%s, 1000001, '2024-01-01', NULL, 0.4,
                         '2024-01-01 18:00:00+08', '2024-01-01 18:01:00+08',
                         1, 2, %s),
                        (%s, 1000001, '2024-01-02', NULL, 0.6,
                         '2024-01-02 18:00:00+08', '2024-01-02 18:01:00+08',
                         1, 2, %s)
                    """,
                    (
                        universe_id,
                        batch_by_dataset[12],
                        universe_id,
                        batch_by_dataset[12],
                    ),
                )

            index_rows = self.client.get_index_members_asof(index_code, "2024-01-03")
            industry_rows = self.client.get_industry_asof(
                symbols=["600519.SH"],
                industry_system="sw",
                level=1,
                asof_date="2024-01-03",
            )
            universe_rows = self.client.get_universe(
                universe_code,
                "2024-01-03",
                include_weight=True,
            )

            self.assertEqual(
                [row["effective_date"] for row in index_rows],
                ["2024-01-02"],
            )
            self.assertEqual([row["industry_code"] for row in industry_rows], ["801780"])
            self.assertEqual([str(row["weight"]) for row in universe_rows], ["0.6000000000"])
        finally:
            connection.rollback()

    def test_real_selectors_exclude_failed_and_late_revisions(self) -> None:
        connection = self.client._backend.postgres._connection
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_batch (
                        dataset_id, source_id, batch_code, trade_date, natural_date,
                        started_at, finished_at, status, row_count
                    ) VALUES
                        (5, 2, 'test-failed-adjustment', '2024-01-02', '2024-01-02',
                         '2024-01-02 19:00:00+08', '2024-01-02 19:01:00+08', 'failed', 1),
                        (7, 2, 'test-failed-fundamental', '2021-03-31', '2021-04-28',
                         '2021-04-28 00:02:00+08', '2021-04-28 00:03:00+08', 'failed', 1),
                        (6, 2, 'test-failed-limit', '2024-01-02', '2024-01-02',
                         '2024-01-02 19:00:00+08', '2024-01-02 19:01:00+08', 'failed', 1)
                    RETURNING batch_id, dataset_id
                    """
                )
                batch_by_dataset = {
                    row["dataset_id"]: row["batch_id"] for row in cursor.fetchall()
                }
                cursor.execute(
                    """
                    INSERT INTO qmeta.adjustment_factor (
                        security_id, trade_date, factor_forward, factor_backward,
                        ex_right_type, announce_time, effective_time, ingest_time,
                        source_id, batch_id, revision_id
                    ) VALUES (
                        1000001, '2024-01-02', 0.01, 100, 'failed-test',
                        '2024-01-02 19:00:00+08', '2024-01-02 19:00:00+08',
                        '2024-01-02 19:00:00+08', 2, %s, 99
                    )
                    """,
                    (batch_by_dataset[5],),
                )
                cursor.execute(
                    """
                    INSERT INTO qpit.financial_metric_pit (
                        security_id, report_period, metric_name, metric_value,
                        metric_unit, metric_scope, announce_time, effective_time,
                        ingest_time, source_id, batch_id, revision_id, is_restated
                    ) VALUES (
                        1000001, '2021-03-31', 'roe_ttm', 9.9, 'ratio', 'ttm',
                        '2021-04-27 19:30:00+08', '2021-04-28 00:00:00+08',
                        '2021-04-27 19:31:00+08', 2, %s, 99, TRUE
                    )
                    """,
                    (batch_by_dataset[7],),
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.limit_price_daily (
                        security_id, trade_date, limit_up, limit_down, limit_rule,
                        is_st, is_new_listing, source_id, batch_id, ingest_time,
                        revision_id
                    ) VALUES (
                        1000001, '2024-01-02', 999, 1, 'failed-test', FALSE,
                        FALSE, 2, %s, '2024-01-02 19:00:00+08', 99
                    )
                    """,
                    (batch_by_dataset[6],),
                )
                cursor.execute(
                    """
                    INSERT INTO qpit.index_member_pit (
                        index_id, security_id, effective_date, end_date, weight,
                        announce_time, ingest_time, source_id, batch_id, revision_id
                    ) VALUES (
                        300, 1000001, '2023-12-11', NULL, 0.99,
                        '2023-12-01 18:00:00+08', '2024-01-03 09:00:00+08',
                        3, 8, 2
                    )
                    """
                )

            adjustment = self.client.get_adjustment_factor(
                symbols=["600519.SH"],
                start_date="2024-01-02",
                end_date="2024-01-02",
                factor_type="forward",
            )
            fundamental = self.client.get_fundamental_asof(
                symbols=["600519.SH"],
                fields=["roe_ttm"],
                asof_date="2021-06-30",
            )
            constraints = self.client.get_trading_constraints(
                symbols=["600519.SH"],
                start_date="2024-01-02",
                end_date="2024-01-02",
            )
            members = self.client.get_index_members_asof(
                "000300.SH",
                "2024-01-02",
            )

            self.assertEqual(str(adjustment[0]["factor_forward"]), "0.532100000000")
            self.assertEqual(str(fundamental[0]["field_value"]), "0.28300000")
            self.assertEqual(str(constraints[0]["limit_up"]), "1842.500000")
            self.assertEqual(str(members[0]["weight"]), "0.0612000000")
        finally:
            connection.rollback()

    def test_real_historical_master_does_not_leak_current_symbol_or_status(self) -> None:
        connection = self.client._backend.postgres._connection
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_master (
                        security_id, asset_type, exchange, current_symbol,
                        current_name, currency, list_date, delist_date,
                        current_status, primary_source_id
                    ) VALUES (
                        1999001, 'stock', 'SH', 'NEW001', 'New Name', 'CNY',
                        '2020-01-01', '2025-01-02', 'delisted', 2
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_identifier_history (
                        security_id, symbol, exchange, identifier_type, start_date,
                        end_date, announce_time, ingest_time, source_id, batch_id,
                        revision_id, created_at
                    ) VALUES
                        (1999001, 'OLD001', 'SH', 'trade_symbol', '2020-01-01',
                         '2024-12-31', '2018-06-11 17:50:00+08',
                         '2018-06-11 18:00:00+08', 2, 1, 1,
                         '2018-06-11 18:00:00+08'),
                        (1999001, 'NEW001', 'SH', 'trade_symbol', '2025-01-01',
                         NULL, '2018-06-11 17:50:00+08',
                         '2018-06-11 18:00:00+08', 2, 1, 1,
                         '2018-06-11 18:00:00+08')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_name_history (
                        security_id, name, start_date, end_date, announce_time,
                        ingest_time, source_id, batch_id, revision_id, created_at
                    ) VALUES
                        (1999001, 'Old Name', '2020-01-01', '2024-12-31',
                         '2018-06-11 17:50:00+08', '2018-06-11 18:00:00+08',
                         2, 1, 1, '2018-06-11 18:00:00+08'),
                        (1999001, 'New Name', '2025-01-01', NULL,
                         '2018-06-11 17:50:00+08', '2018-06-11 18:00:00+08',
                         2, 1, 1, '2018-06-11 18:00:00+08')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.security_status_history (
                        security_id, status, start_date, end_date, reason,
                        announce_time, ingest_time, source_id, batch_id,
                        revision_id, created_at
                    ) VALUES
                        (1999001, 'active', '2020-01-01', '2024-12-31', 'old',
                         '2018-06-11 17:50:00+08', '2018-06-11 18:00:00+08',
                         2, 1, 1, '2018-06-11 18:00:00+08'),
                        (1999001, 'delisted', '2025-01-01', NULL, 'new',
                         '2018-06-11 17:50:00+08', '2018-06-11 18:00:00+08',
                         2, 1, 1, '2018-06-11 18:00:00+08')
                    """
                )

            rows = self.client.get_security_master(
                symbols=["OLD001.SH"],
                asof_date="2024-01-02",
                include_delisted=False,
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "OLD001.SH")
            self.assertEqual(rows[0]["name"], "Old Name")
            self.assertEqual(rows[0]["status"], "active")
            self.assertIsNone(rows[0]["delist_date"])
        finally:
            connection.rollback()

    def test_real_security_loader_uses_stable_id_for_ticker_rename(self) -> None:
        connection = self.client._backend.postgres._connection
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="mock_vendor",
        )
        loader._postgres = connection
        loader._clickhouse = object()
        loader.open = lambda: None
        loader.ensure_metadata()
        suffix = datetime.now().strftime("%H%M%S%f")[-10:]
        old_symbol = f"R{suffix}.SH"
        new_symbol = f"N{suffix}.SH"
        today = date.today()
        rename_day = today + timedelta(days=1)

        loader.load_security_master(
            [
                SecurityRecord(
                    old_symbol,
                    "Old Loader Name",
                    list_date="2020-01-01",
                    status="active",
                )
            ]
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT security_id
                FROM qmeta.security_master
                WHERE current_symbol = %s AND exchange = 'SH'
                """,
                (old_symbol.split(".")[0],),
            )
            security_id = cursor.fetchone()["security_id"]

        loader.load_security_master(
            [
                SecurityRecord(
                    new_symbol,
                    "New Loader Name",
                    list_date="2020-01-01",
                    status="active",
                    security_id=security_id,
                    identifier_effective_date=rename_day.isoformat(),
                    name_effective_date=rename_day.isoformat(),
                )
            ]
        )

        old_rows = self.client.get_security_master(
            symbols=[old_symbol],
            asof_date=today.isoformat(),
        )
        new_rows = self.client.get_security_master(
            symbols=[new_symbol],
            asof_date=rename_day.isoformat(),
        )
        self.assertEqual(old_rows[0]["security_id"], security_id)
        self.assertEqual(old_rows[0]["name"], "Old Loader Name")
        self.assertEqual(new_rows[0]["security_id"], security_id)
        self.assertEqual(new_rows[0]["name"], "New Loader Name")

    def test_real_stable_id_rename_rejects_preoccupied_placeholder_before_batch(self) -> None:
        connection = self.client._backend.postgres._connection
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="mock_vendor",
        )
        loader._postgres = connection
        loader._clickhouse = object()
        loader.open = lambda: None
        loader.ensure_metadata()
        suffix = datetime.now().strftime("%H%M%S%f")[-10:]
        old_symbol = f"O{suffix}.SH"
        target_symbol = f"T{suffix}.SH"

        loader.load_security_master(
            [
                SecurityRecord(
                    old_symbol,
                    "Authoritative old entity",
                    list_date="2020-01-01",
                    status="active",
                )
            ]
        )
        loader.load_security_master([SecurityRecord(target_symbol, target_symbol)])
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_symbol || '.' || exchange AS symbol, security_id
                FROM qmeta.security_master
                WHERE current_symbol || '.' || exchange = ANY(%s)
                ORDER BY symbol
                """,
                ([old_symbol, target_symbol],),
            )
            owners = {row["symbol"]: row["security_id"] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM qmeta.data_batch db
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
                WHERE dc.dataset_code = 'security_master'
                """
            )
            batch_count_before = cursor.fetchone()["count"]
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM qmeta.security_identifier_history
                WHERE security_id = ANY(%s)
                """,
                (list(owners.values()),),
            )
            history_count_before = cursor.fetchone()["count"]

        with self.assertRaisesRegex(
            QDataValidationError,
            "target symbol .* is already owned",
        ):
            loader.load_security_master(
                [
                    SecurityRecord(
                        target_symbol,
                        "Renamed authoritative entity",
                        list_date="2020-01-01",
                        status="active",
                        security_id=owners[old_symbol],
                        identifier_effective_date=date.today().isoformat(),
                        name_effective_date=date.today().isoformat(),
                    )
                ]
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_symbol || '.' || exchange AS symbol, security_id
                FROM qmeta.security_master
                WHERE current_symbol || '.' || exchange = ANY(%s)
                ORDER BY symbol
                """,
                ([old_symbol, target_symbol],),
            )
            after_owners = {row["symbol"]: row["security_id"] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM qmeta.data_batch db
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = db.dataset_id
                WHERE dc.dataset_code = 'security_master'
                """
            )
            batch_count_after = cursor.fetchone()["count"]
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM qmeta.security_identifier_history
                WHERE security_id = ANY(%s)
                """,
                (list(owners.values()),),
            )
            history_count_after = cursor.fetchone()["count"]

        self.assertEqual(after_owners, owners)
        self.assertEqual(batch_count_after, batch_count_before)
        self.assertEqual(history_count_after, history_count_before)

    def test_real_suspension_only_ingest_is_returned_by_constraints(self) -> None:
        connection = self.client._backend.postgres._connection
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="mock_vendor",
        )
        loader._postgres = connection
        loader._clickhouse = object()
        loader.open = lambda: None
        loader.ensure_metadata()
        suffix = datetime.now().strftime("%H%M%S%f")[-10:]
        symbol = f"S{suffix}.SH"
        trade_date = date.today().isoformat()

        loader.load_security_master(
            [
                SecurityRecord(
                    symbol,
                    "Suspension Only Corp",
                    list_date="2020-01-01",
                    status="star_st",
                )
            ]
        )
        loader.load_market_constraints(
            [],
            [],
            [
                SuspensionRecord(
                    symbol,
                    f"{trade_date} 09:30:00+08:00",
                    f"{trade_date} 15:00:00+08:00",
                    "full_day",
                    "suspension-only integration",
                )
            ],
        )

        rows = self.client.get_trading_constraints(
            symbols=[symbol],
            start_date=trade_date,
            end_date=trade_date,
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_suspended"])
        self.assertTrue(rows[0]["is_st"])
        self.assertIsNone(rows[0]["is_new_listing"])
        self.assertIsNone(rows[0]["limit_up"])
        self.assertFalse(rows[0]["can_buy"])

        universe_code = f"st_suspension_{suffix}"
        loader.load_tradable_universe(
            universe_code,
            "ST suspension universe",
            trade_date,
            [TradableUniverseRecord(symbol, trade_date)],
        )
        filtered = self.client.get_universe(
            universe_code,
            trade_date,
            filters={"exclude_st": True, "exclude_suspended": False},
        )
        self.assertEqual(filtered, [])

    def test_real_industry_query_does_not_leak_current_category_label(self) -> None:
        connection = self.client._backend.postgres._connection
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE qmeta.industry_category
                    SET industry_name = 'CURRENT LABEL LEAK'
                    WHERE industry_id = 101
                    """
                )

            rows = self.client.get_industry_asof(
                symbols=["600519.SH"],
                industry_system="sw",
                level=1,
                asof_date="2024-01-02",
            )

            self.assertEqual(rows[0]["industry_name"], "食品饮料")
        finally:
            connection.rollback()

    def test_real_tradable_snapshot_sequence_removes_and_clears_members(self) -> None:
        connection = self.client._backend.postgres._connection
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="mock_vendor",
        )
        loader._postgres = connection
        loader._clickhouse = object()
        loader.open = lambda: None
        loader.ensure_metadata()

        day_one = date.today()
        day_two = day_one + timedelta(days=1)
        day_three = day_one + timedelta(days=2)
        universe_code = f"pit_snapshot_{datetime.now().strftime('%H%M%S%f')}"

        loader.load_tradable_universe(
            universe_code,
            "PIT snapshot test",
            day_one.isoformat(),
            [
                TradableUniverseRecord("600519.SH", day_one.isoformat()),
                TradableUniverseRecord("000001.SZ", day_one.isoformat()),
            ],
        )
        loader.load_tradable_universe(
            universe_code,
            "PIT snapshot test",
            day_two.isoformat(),
            [TradableUniverseRecord("000001.SZ", day_two.isoformat())],
        )
        loader.load_tradable_universe(
            universe_code,
            "PIT snapshot test",
            day_three.isoformat(),
            [],
        )
        loader.load_tradable_universe(
            universe_code,
            "PIT snapshot test",
            day_two.isoformat(),
            [TradableUniverseRecord("000001.SZ", day_two.isoformat(), 0.75)],
        )

        day_two_rows = self.client.get_universe(
            universe_code,
            day_two.isoformat(),
            include_weight=True,
        )
        day_three_rows = self.client.get_universe(
            universe_code,
            day_three.isoformat(),
            include_weight=True,
        )
        self.assertEqual([row["symbol"] for row in day_two_rows], ["000001.SZ"])
        self.assertEqual(str(day_two_rows[0]["weight"]), "0.7500000000")
        self.assertEqual(day_three_rows, [])

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT array_agg(um.revision_id ORDER BY um.revision_id) AS revisions
                FROM qpit.universe_member_pit um
                JOIN qmeta.universe_definition ud
                  ON ud.universe_id = um.universe_id
                WHERE ud.universe_code = %s
                  AND um.security_id = 1000002
                  AND um.effective_date = %s
                """,
                (universe_code, day_two),
            )
            self.assertEqual(cursor.fetchone()["revisions"], [1, 2])

    def test_real_universe_type_update_is_rejected_and_original_type_survives(self) -> None:
        connection = self.client._backend.postgres._connection
        universe_code = f"immutable_{datetime.now().strftime('%H%M%S%f')}"
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.universe_definition (
                        universe_code, universe_name, universe_type, description, owner
                    ) VALUES (%s, 'Immutable universe', 'manual', 'test', 'test')
                    RETURNING universe_id
                    """,
                    (universe_code,),
                )
                universe_id = cursor.fetchone()["universe_id"]
                cursor.execute("SAVEPOINT universe_type_guard")
                with self.assertRaises(Exception):
                    cursor.execute(
                        """
                        UPDATE qmeta.universe_definition
                        SET universe_type = 'rule_based'
                        WHERE universe_id = %s
                        """,
                        (universe_id,),
                    )
                cursor.execute("ROLLBACK TO SAVEPOINT universe_type_guard")
                cursor.execute(
                    """
                    SELECT universe_type
                    FROM qmeta.universe_definition
                    WHERE universe_id = %s
                    """,
                    (universe_id,),
                )
                self.assertEqual(cursor.fetchone()["universe_type"], "manual")
        finally:
            connection.rollback()

    def test_real_recalled_adjustment_version_cannot_override_active_price_factor(self) -> None:
        connection = self.client._backend.postgres._connection
        suffix = datetime.now().strftime("%H%M%S%f")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qmeta.data_batch (
                        dataset_id, source_id, batch_code, trade_date, natural_date,
                        started_at, finished_at, status, row_count
                    ) VALUES
                        (5, 2, %s, '2024-01-02', '2024-01-02',
                         '2024-01-02 19:00:00+08', '2024-01-02 19:01:00+08',
                         'success', 1),
                        (5, 2, %s, '2024-01-02', '2024-01-02',
                         '2024-01-02 20:00:00+08', '2024-01-02 20:01:00+08',
                         'success', 1)
                    RETURNING batch_code, batch_id
                    """,
                    (f"test-active-adjustment-{suffix}", f"test-recalled-adjustment-{suffix}"),
                )
                batches = {row["batch_code"]: row["batch_id"] for row in cursor.fetchall()}
                active_batch = batches[f"test-active-adjustment-{suffix}"]
                recalled_batch = batches[f"test-recalled-adjustment-{suffix}"]
                cursor.execute(
                    """
                    INSERT INTO qmeta.dataset_version (
                        dataset_id, version_code, batch_id, valid_from, status, description
                    ) VALUES
                        (5, %s, %s, '2024-01-02 19:01:00+08', 'active', 'test'),
                        (5, %s, %s, '2024-01-02 20:01:00+08', 'recalled', 'test')
                    """,
                    (
                        f"adjustment_factor:active-{suffix}",
                        active_batch,
                        f"adjustment_factor:recalled-{suffix}",
                        recalled_batch,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO qmeta.adjustment_factor (
                        security_id, trade_date, factor_forward, factor_backward,
                        ex_right_type, announce_time, effective_time, ingest_time,
                        source_id, batch_id, revision_id
                    ) VALUES
                        (1000001, '2024-01-02', 0.4, 2.5, 'test-active',
                         '2024-01-02 19:00:00+08', '2024-01-02 19:00:00+08',
                         '2024-01-02 19:00:30+08', 2, %s, 900),
                        (1000001, '2024-01-02', 0.1, 10.0, 'test-recalled',
                         '2024-01-02 20:00:00+08', '2024-01-02 20:00:00+08',
                         '2024-01-02 20:00:30+08', 2, %s, 901)
                    """,
                    (active_batch, recalled_batch),
                )

            adjustments = self.client.get_adjustment_factor(
                symbols=["600519.SH"],
                start_date="2024-01-02",
                end_date="2024-01-02",
                factor_type="forward",
            )
            adjusted_prices = self.client.get_price(
                symbols=["600519.SH"],
                start_date="2024-01-02",
                end_date="2024-01-02",
                adjust="forward",
            )

            self.assertEqual(str(adjustments[0]["factor_forward"]), "0.400000000000")
            self.assertEqual(adjusted_prices[0]["close"], 679.2)
        finally:
            connection.rollback()

    def test_real_constraint_loader_appends_and_selector_uses_latest_success(self) -> None:
        connection = self.client._backend.postgres._connection
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="mock_vendor",
        )
        loader._postgres = connection
        loader._clickhouse = object()
        loader.open = lambda: None
        loader.ensure_metadata()
        trade_date = date.today().isoformat()
        start_time = f"{trade_date} 09:30:00+08:00"
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(revision_id), 0) AS revision_id
                FROM qmeta.limit_price_daily
                WHERE security_id = 1000001 AND trade_date = %s
                """,
                (trade_date,),
            )
            previous_limit_revision = cursor.fetchone()["revision_id"]
            cursor.execute(
                """
                SELECT COALESCE(MAX(revision_id), 0) AS revision_id
                FROM qmeta.suspension_history
                WHERE security_id = 1000001 AND start_time = %s
                """,
                (start_time,),
            )
            previous_suspension_revision = cursor.fetchone()["revision_id"]

        for limit_up, end_time in (
            (100.0, f"{trade_date} 15:00:00+08:00"),
            (101.0, f"{trade_date} 14:30:00+08:00"),
        ):
            loader.load_market_constraints(
                [],
                [LimitPriceRecord("600519.SH", trade_date, limit_up, 80.0)],
                [
                    SuspensionRecord(
                        "600519.SH",
                        start_time,
                        end_time,
                        "full_day",
                        "revision test",
                    )
                ],
            )

        rows = self.client.get_trading_constraints(
            symbols=["600519.SH"],
            start_date=trade_date,
            end_date=trade_date,
        )
        self.assertEqual(str(rows[0]["limit_up"]), "101.000000")
        self.assertTrue(rows[0]["is_suspended"])

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT array_agg(revision_id ORDER BY revision_id) AS revisions
                FROM qmeta.limit_price_daily
                WHERE security_id = 1000001 AND trade_date = %s
                """,
                (trade_date,),
            )
            self.assertEqual(
                cursor.fetchone()["revisions"][-2:],
                [previous_limit_revision + 1, previous_limit_revision + 2],
            )
            cursor.execute(
                """
                SELECT array_agg(revision_id ORDER BY revision_id) AS revisions
                FROM qmeta.suspension_history
                WHERE security_id = 1000001 AND start_time = %s
                """,
                (start_time,),
            )
            self.assertEqual(
                cursor.fetchone()["revisions"][-2:],
                [
                    previous_suspension_revision + 1,
                    previous_suspension_revision + 2,
                ],
            )

    def test_real_adjustment_loader_publishes_queryable_dataset_version(self) -> None:
        connection = self.client._backend.postgres._connection
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="mock_vendor",
        )
        loader._postgres = connection
        loader._clickhouse = object()
        loader.open = lambda: None
        loader.ensure_metadata()
        trade_date = date.today().isoformat()

        loader.load_market_constraints(
            [AdjustmentFactorRecord("600519.SH", trade_date, 0.42, 2.38)],
            [],
            [],
        )

        rows = self.client.get_adjustment_factor(
            symbols=["600519.SH"],
            start_date=trade_date,
            end_date=trade_date,
            factor_type="both",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["factor_forward"]), "0.420000000000")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT db.status AS batch_status, dv.status AS version_status
                FROM qmeta.adjustment_factor af
                JOIN qmeta.data_batch db ON db.batch_id = af.batch_id
                JOIN qmeta.dataset_version dv
                  ON dv.dataset_id = db.dataset_id
                 AND dv.batch_id = db.batch_id
                WHERE af.security_id = 1000001
                  AND af.trade_date = %s
                ORDER BY af.revision_id DESC
                LIMIT 1
                """,
                (trade_date,),
            )
            state = cursor.fetchone()
        self.assertEqual(state, {"batch_status": "success", "version_status": "active"})

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


@unittest.skipUnless(
    POSTGRES_DSN and CLICKHOUSE_DSN,
    "set both QDATA_TEST_POSTGRES_DSN and QDATA_TEST_CLICKHOUSE_DSN",
)
class CrossStoreFactorIntegrationTest(unittest.TestCase):
    def test_real_factor_latest_rejects_orphan_higher_data_version(self) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            self.fail(f"clickhouse-connect is required: {exc}")

        clickhouse = clickhouse_connect.get_client(dsn=CLICKHOUSE_DSN)
        shanghai_time = datetime.fromisoformat("2024-01-02T19:00:00+08:00")
        clickhouse.insert(
            "qts.factor_value_daily",
            [[1, 1, 1000001, date(2024, 1, 2), 0.99, 800, shanghai_time, 9999, "normal"]],
            column_names=[
                "factor_id",
                "factor_version_id",
                "security_id",
                "trade_date",
                "factor_value",
                "universe_id",
                "calc_time",
                "data_version",
                "quality_flag",
            ],
        )
        try:
            client = Client(
                backend="sql",
                postgres_dsn=POSTGRES_DSN,
                clickhouse_dsn=CLICKHOUSE_DSN,
                default_format="records",
            )
            try:
                rows = client.get_factor(
                    factors=["momentum_20d"],
                    symbols=["600519.SH"],
                    start_date="2024-01-02",
                    end_date="2024-01-02",
                )
            finally:
                client.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["factor_value"], 0.032)
        finally:
            clickhouse.command(
                "ALTER TABLE qts.factor_value_daily DELETE WHERE data_version = 9999"
            )
            clickhouse.close()

    def test_real_factor_latest_fails_closed_on_equal_version_time_conflict(self) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            self.fail(f"clickhouse-connect is required: {exc}")

        clickhouse = clickhouse_connect.get_client(dsn=CLICKHOUSE_DSN)
        conflict_time = datetime.fromisoformat("2024-01-02T20:00:00+08:00")
        clickhouse.insert(
            "qts.factor_value_daily",
            [
                [1, 1, 1000001, date(2024, 1, 2), 0.88, 800, conflict_time, 13, "normal"],
                [1, 1, 1000001, date(2024, 1, 2), 0.99, 800, conflict_time, 13, "normal"],
            ],
            column_names=[
                "factor_id",
                "factor_version_id",
                "security_id",
                "trade_date",
                "factor_value",
                "universe_id",
                "calc_time",
                "data_version",
                "quality_flag",
            ],
        )
        try:
            client = Client(
                backend="sql",
                postgres_dsn=POSTGRES_DSN,
                clickhouse_dsn=CLICKHOUSE_DSN,
                default_format="records",
            )
            try:
                with self.assertRaisesRegex(
                    QDataValidationError,
                    "conflicting factor rows",
                ):
                    client.get_factor(
                        factors=["momentum_20d"],
                        symbols=["600519.SH"],
                        start_date="2024-01-02",
                        end_date="2024-01-02",
                    )
            finally:
                client.close()
        finally:
            clickhouse.command(
                "ALTER TABLE qts.factor_value_daily DELETE WHERE "
                "data_version = 13 AND calc_time = toDateTime64("
                "'2024-01-02 20:00:00', 3, 'Asia/Shanghai')"
            )
            clickhouse.close()

    def test_real_factor_latest_collapses_identical_retry_rows(self) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            self.fail(f"clickhouse-connect is required: {exc}")

        clickhouse = clickhouse_connect.get_client(dsn=CLICKHOUSE_DSN)
        retry_time = datetime.fromisoformat("2024-01-02T20:01:00+08:00")
        retry = [
            1,
            1,
            1000001,
            date(2024, 1, 2),
            0.88,
            800,
            retry_time,
            13,
            "normal",
        ]
        clickhouse.insert(
            "qts.factor_value_daily",
            [retry, list(retry)],
            column_names=[
                "factor_id",
                "factor_version_id",
                "security_id",
                "trade_date",
                "factor_value",
                "universe_id",
                "calc_time",
                "data_version",
                "quality_flag",
            ],
        )
        try:
            client = Client(
                backend="sql",
                postgres_dsn=POSTGRES_DSN,
                clickhouse_dsn=CLICKHOUSE_DSN,
                default_format="records",
            )
            try:
                rows = client.get_factor(
                    factors=["momentum_20d"],
                    symbols=["600519.SH"],
                    start_date="2024-01-02",
                    end_date="2024-01-02",
                )
            finally:
                client.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["factor_value"], 0.88)
        finally:
            clickhouse.command(
                "ALTER TABLE qts.factor_value_daily DELETE WHERE "
                "data_version = 13 AND calc_time = toDateTime64("
                "'2024-01-02 20:01:00', 3, 'Asia/Shanghai')"
            )
            clickhouse.close()


if __name__ == "__main__":
    unittest.main()
