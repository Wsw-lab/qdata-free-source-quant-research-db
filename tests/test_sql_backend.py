from datetime import datetime
import os
import unittest
from unittest.mock import patch

from qdata import Client
from qdata.exceptions import QDataNotFoundError, QDataValidationError


def aware(value: str) -> datetime:
    return datetime.fromisoformat(value)


class FakePostgres:
    def __init__(self, dataset_versions=None, adjustment_factors=None, factor_versions=None) -> None:
        self.queries = []
        self.closed = False
        self.dataset_versions = dataset_versions if dataset_versions is not None else [
            {
                "dataset_code": "daily_bar", "data_version": 7001,
                "version_code": "daily_bar:seed-v1", "batch_id": 2,
                "version_status": "active", "batch_status": "success",
                "valid_from": aware("2024-01-02T17:00:00+08:00"),
                "finished_at": aware("2024-01-02T17:01:00+08:00"),
            }
        ]
        self.adjustment_factors = adjustment_factors if adjustment_factors is not None else [
            {
                "security_id": 1000001, "trade_date": "2024-01-02",
                "factor_forward": 0.5, "factor_backward": 2.0,
                "revision_id": 1, "batch_id": 2,
                "dataset_code": "daily_bar", "batch_status": "success",
                "batch_finished_at": aware("2024-01-02T17:00:00+08:00"),
                "announce_time": aware("2024-01-02T16:00:00+08:00"),
                "effective_time": aware("2024-01-02T16:00:00+08:00"),
                "ingest_time": aware("2024-01-02T17:00:00+08:00"),
            }
        ]
        self.factor_versions = factor_versions if factor_versions is not None else [
            {
                "factor_id": 101, "factor_code": "momentum_20d",
                "factor_version_id": 1001, "version_code": "mom-v1",
                "status": "published",
            }
        ]

    def fetch_all(self, sql, params=None):
        params = params or {}
        self.queries.append((sql, params))
        if "FROM qmeta.security_master" in sql:
            return [{
                "security_id": 1000001, "symbol": "600519.SH", "asset_type": "stock",
                "exchange": "SH", "name": "贵州茅台", "list_date": "2001-08-27",
                "delist_date": None, "status": "active", "currency": "CNY",
            }]
        if "FROM qmeta.dataset_version" in sql:
            return self._dataset_version_rows(sql, params)
        if "FROM qmeta.adjustment_factor" in sql:
            return self._adjustment_factor_rows(sql, params)
        if "FROM qmeta.factor_definition" in sql:
            requested = set(params.get("factors") or [])
            version = params.get("factor_version")
            return [dict(row) for row in self.factor_versions
                    if row["factor_code"] in requested
                    and (version == "published" and row["status"] == "published"
                         or row["version_code"] == version)]
        if "FROM qmeta.limit_price_daily lp" in sql:
            return [{
                "security_id": 1000001, "trade_date": "2024-01-02",
                "limit_up": 11.55, "limit_down": 9.45, "is_st": False,
                "is_new_listing": False, "is_suspended": False,
                "is_delisting_period": False, "list_days": 8163,
            }]
        if "FROM qpit.financial_metric_pit" in sql:
            return [{
                "security_id": 1000001, "report_period": "2021-03-31",
                "field_name": "roe_ttm", "field_value": 0.283,
                "announce_time": "2021-04-27T19:30:00+08:00",
                "ingest_time": "2021-04-27T19:31:00+08:00",
                "revision_id": 1, "is_restated": False,
            }]
        return []

    def _dataset_version_rows(self, sql, params):
        requested = params.get("requested_data_version", params.get("data_version"))
        cutoff = params.get("asof_time")
        if isinstance(cutoff, str):
            cutoff = aware(cutoff)
        rows = []
        for item in self.dataset_versions:
            if item["dataset_code"] != params.get("dataset_code"):
                continue
            if "dv.status IN ('active', 'superseded')" in sql and item["version_status"] not in {
                "active", "superseded"
            }:
                continue
            if "db.status = 'success'" in sql and item["batch_status"] != "success":
                continue
            if (requested is not None and "requested_data_version" in sql
                    and str(requested) not in {str(item["data_version"]), item["version_code"]}):
                continue
            if cutoff is not None:
                if "dv.valid_from <= %(asof_time)s" in sql and item["valid_from"] > cutoff:
                    continue
                if "db.finished_at <= %(asof_time)s" in sql and item["finished_at"] > cutoff:
                    continue
            rows.append({
                "data_version": item["data_version"], "version_code": item["version_code"],
                "batch_id": item["batch_id"], "status": item["version_status"],
                "valid_from": item["valid_from"], "finished_at": item["finished_at"],
            })
        return rows

    def _adjustment_factor_rows(self, sql, params):
        cutoff = params.get("knowledge_cutoff", params.get("asof_time"))
        if isinstance(cutoff, str):
            cutoff = aware(cutoff)
        allowed_batches = set(params.get("allowed_batch_ids") or [])
        knowledge_datasets = set(params.get("knowledge_dataset_codes") or [])
        if params.get("batch_id") is not None:
            allowed_batches = {params["batch_id"]}
        rows = []
        for item in self.adjustment_factors:
            if item["security_id"] not in set(params.get("security_ids") or []):
                continue
            if not params["start_date"] <= item["trade_date"] <= params["end_date"]:
                continue
            if "batch_id = ANY(%(allowed_batch_ids)s)" in sql and item["batch_id"] not in allowed_batches:
                continue
            if ("dc.dataset_code = ANY(%(knowledge_dataset_codes)s)" in sql
                    and item["dataset_code"] not in knowledge_datasets):
                continue
            if "db.status = 'success'" in sql and item["batch_status"] != "success":
                continue
            if cutoff is not None:
                if ("db.finished_at IS NOT NULL" in sql
                        and item["batch_finished_at"] is None):
                    continue
                if ("db.finished_at <= %(knowledge_cutoff)s" in sql
                        and item["batch_finished_at"] > cutoff):
                    continue
                if ("af.ingest_time <= %(knowledge_cutoff)s" in sql
                        and item["ingest_time"] > cutoff):
                    continue
                if "ingest_time <= %(asof_time)s" in sql and item["ingest_time"] > cutoff:
                    continue
                if ("announce_time IS NOT NULL" in sql or "af.announce_time IS NOT NULL" in sql) \
                        and item["announce_time"] is None:
                    continue
                if ("announce_time <= %(asof_time)s" in sql and item["announce_time"] is not None
                        and item["announce_time"] > cutoff):
                    continue
                if ("af.announce_time <= %(knowledge_cutoff)s" in sql
                        and item["announce_time"] is not None
                        and item["announce_time"] > cutoff):
                    continue
                if ("effective_time IS NOT NULL" in sql or "af.effective_time IS NOT NULL" in sql) \
                        and item["effective_time"] is None:
                    continue
                if ("effective_time <= %(asof_time)s" in sql and item["effective_time"] is not None
                        and item["effective_time"] > cutoff):
                    continue
                if ("af.effective_time <= %(knowledge_cutoff)s" in sql
                        and item["effective_time"] is not None
                        and item["effective_time"] > cutoff):
                    continue
            rows.append(dict(item))
        if not any(
            marker in sql
            for marker in (
                "DISTINCT ON (security_id, trade_date)",
                "DISTINCT ON (af.security_id, af.trade_date)",
            )
        ):
            return rows
        latest = {}
        for row in rows:
            key = (row["security_id"], row["trade_date"])
            if key not in latest or (row["revision_id"], row["ingest_time"]) > (
                latest[key]["revision_id"], latest[key]["ingest_time"]
            ):
                latest[key] = row
        return list(latest.values())

    def close(self):
        self.closed = True


class FakeClickHouse:
    def __init__(self, daily_rows=None, factor_rows=None) -> None:
        self.queries = []
        self.closed = False
        self.daily_rows = daily_rows if daily_rows is not None else [{
            "security_id": 1000001, "trade_date": "2024-01-02",
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
            "volume": 1000.0, "amount": 10500.0, "data_version": 7001,
            "ingest_time": aware("2024-01-02T17:00:00+08:00"),
        }]
        self.factor_rows = factor_rows if factor_rows is not None else [{
            "factor_id": 101, "factor_version_id": 1001, "security_id": 1000001,
            "trade_date": "2024-01-02", "factor_value": 0.75, "quality_flag": "normal",
        }]

    def fetch_all(self, sql, params=None):
        params = params or {}
        self.queries.append((sql, params))
        if "FROM qts.daily_bar" in sql:
            return self._price_rows(params)
        if "FROM qts.factor_value_daily" in sql:
            return self._factor_rows(params)
        return []

    def _price_rows(self, params):
        allowed = params.get("allowed_data_versions")
        if allowed is None and params.get("resolved_data_version") is not None:
            allowed = (params["resolved_data_version"],)
        allowed = set(allowed) if allowed is not None else None
        cutoff = params.get("asof_time")
        if isinstance(cutoff, str):
            cutoff = aware(cutoff)
        rows = []
        for row in self.daily_rows:
            if row["security_id"] not in set(params.get("security_ids") or []):
                continue
            if not params["start_date"] <= row["trade_date"] <= params["end_date"]:
                continue
            if allowed is not None and row["data_version"] not in allowed:
                continue
            if cutoff is not None and row["ingest_time"] > cutoff:
                continue
            rows.append(dict(row))
        latest = {}
        for row in rows:
            key = (row["security_id"], row["trade_date"], row.get("bar_time"))
            if key not in latest or (row["ingest_time"], row["data_version"]) > (
                latest[key]["ingest_time"], latest[key]["data_version"]
            ):
                latest[key] = row
        return list(latest.values())

    def _factor_rows(self, params):
        exact_pairs = set()
        index = 0
        while f"factor_pair_{index}_factor_id" in params:
            exact_pairs.add((params[f"factor_pair_{index}_factor_id"],
                             params[f"factor_pair_{index}_version_id"]))
            index += 1
        factor_ids = set(params.get("factor_ids") or [])
        version_ids = set(params.get("factor_version_ids") or [])
        rows = []
        for row in self.factor_rows:
            pair = (row["factor_id"], row["factor_version_id"])
            if exact_pairs and pair not in exact_pairs:
                continue
            if not exact_pairs and (pair[0] not in factor_ids or pair[1] not in version_ids):
                continue
            rows.append(dict(row))
        return rows

    def close(self):
        self.closed = True


class SqlBackendTest(unittest.TestCase):
    def test_sql_backend_get_security_master_uses_injected_postgres(self) -> None:
        postgres = FakePostgres()
        client = Client(backend="sql", postgres_client=postgres, default_format="records")
        rows = client.get_security_master(symbols=["600519.SH"], asof_date="2024-12-31")
        self.assertEqual(rows[0]["symbol"], "600519.SH")
        sql = postgres.queries[-1][0]
        self.assertNotIn("sm.list_date IS NULL", sql)
        self.assertIn("identifier.historical_list_date AS list_date", sql)
        self.assertIn("db_identifier.status = 'success'", sql)

    def test_latest_price_excludes_failed_and_running_versions_before_ranking(self) -> None:
        versions = [
            self._version(7001, 2, "success", "active", "17:00"),
            self._version(7002, 3, "failed", "active", "18:00"),
            self._version(7003, 4, "running", "superseded", "19:00"),
            self._version(7004, 5, "success", "draft", "20:00"),
        ]
        rows = [self._price(7001, 10.0, "17:00"), self._price(7002, 20.0, "18:00"),
                self._price(7003, 30.0, "19:00"), self._price(7004, 40.0, "20:00")]
        postgres, clickhouse = FakePostgres(dataset_versions=versions), FakeClickHouse(daily_rows=rows)
        result = self._client(postgres, clickhouse).get_price(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02")
        self.assertEqual(result[0]["close"], 10.0)
        sql, params = clickhouse.queries[-1]
        self.assertIn("data_version IN %(allowed_data_versions)s", sql)
        self.assertEqual(params["allowed_data_versions"], (7001,))
        version_sql = next(sql for sql, _ in postgres.queries if "FROM qmeta.dataset_version" in sql)
        self.assertIn("db.status = 'success'", version_sql)
        self.assertIn("dv.status IN ('active', 'superseded')", version_sql)

    def test_latest_price_fails_closed_when_no_published_version_is_allowed(self) -> None:
        postgres = FakePostgres(dataset_versions=[self._version(7002, 3, "failed", "recalled", "18:00")])
        client = self._client(postgres, FakeClickHouse(daily_rows=[self._price(7002, 20.0, "18:00")]))
        with self.assertRaisesRegex(QDataNotFoundError, "No published data versions"):
            client.get_price(symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02")

    def test_asof_resolves_versions_and_revisions_before_cutoff(self) -> None:
        versions = [self._version(7001, 2, "success", "superseded", "17:00"),
                    self._version(7002, 3, "success", "active", "19:00")]
        postgres = FakePostgres(dataset_versions=versions)
        clickhouse = FakeClickHouse(daily_rows=[self._price(7001, 10.0, "17:00"),
                                                self._price(7002, 20.0, "19:00")])
        payload = self._client(postgres, clickhouse).get_price(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
            query_mode="asof", asof_time="2024-01-02T18:00:00+08:00", include_meta=True)
        self.assertEqual(payload["data"][0]["close"], 10.0)
        self.assertEqual(payload["meta"]["asof_time"], "2024-01-02T18:00:00+08:00")
        sql, params = clickhouse.queries[-1]
        self.assertIn("data_version IN %(allowed_data_versions)s", sql)
        self.assertEqual(params["allowed_data_versions"], (7001,))
        self.assertIsInstance(params["asof_time"], datetime)
        self.assertIsNotNone(params["asof_time"].utcoffset())
        version_sql = next(sql for sql, _ in postgres.queries if "FROM qmeta.dataset_version" in sql)
        self.assertIn("db.status = 'success'", version_sql)
        self.assertIn("dv.valid_from <= %(asof_time)s", version_sql)
        self.assertIn("db.finished_at <= %(asof_time)s", version_sql)

    def test_vintage_uses_real_version_not_batch_id(self) -> None:
        postgres, clickhouse = FakePostgres(), FakeClickHouse()
        payload = self._client(postgres, clickhouse).get_price(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
            query_mode="vintage", data_version="daily_bar:seed-v1", include_meta=True)
        _, params = clickhouse.queries[-1]
        self.assertEqual(params["allowed_data_versions"], (7001,))
        self.assertNotEqual(params["allowed_data_versions"][0], 2)
        self.assertEqual(payload["meta"]["data_version"], "daily_bar:seed-v1")
        version_sql = next(sql for sql, _ in postgres.queries if "FROM qmeta.dataset_version" in sql)
        self.assertIn("dv.version_code = %(requested_data_version)s", version_sql)

    def test_vintage_rejects_unknown_or_unpublished_version(self) -> None:
        client = self._client(FakePostgres(), FakeClickHouse())

        with self.assertRaisesRegex(QDataNotFoundError, "Unknown or unavailable data_version"):
            client.get_price(
                symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
                query_mode="vintage", data_version="daily_bar:not-published",
            )

    def test_price_modes_are_strictly_mutually_exclusive(self) -> None:
        client = self._client(FakePostgres(), FakeClickHouse())
        kwargs = {"symbols": ["600519.SH"], "start_date": "2024-01-02", "end_date": "2024-01-02"}
        invalid = [
            {"query_mode": "latest", "asof_time": "2024-01-02T18:00:00+08:00"},
            {"query_mode": "latest", "data_version": "daily_bar:seed-v1"},
            {"query_mode": "asof", "asof_time": "2024-01-02T18:00:00+08:00", "data_version": "daily_bar:seed-v1"},
            {"query_mode": "vintage", "data_version": "daily_bar:seed-v1", "asof_time": "2024-01-02T18:00:00+08:00"},
        ]
        for mode_kwargs in invalid:
            with self.subTest(mode_kwargs=mode_kwargs):
                with self.assertRaisesRegex(QDataValidationError, "only accepts"):
                    client.get_price(**kwargs, **mode_kwargs)

    def test_asof_requires_timezone_aware_datetime_not_date_or_naive_time(self) -> None:
        client = self._client(FakePostgres(), FakeClickHouse())
        kwargs = {"symbols": ["600519.SH"], "start_date": "2024-01-02",
                  "end_date": "2024-01-02", "query_mode": "asof"}
        for cutoff in ("2024-01-02", "2024-01-02T18:00:00", "not-a-timestamp"):
            with self.subTest(cutoff=cutoff):
                with self.assertRaisesRegex(QDataValidationError, "timezone-aware ISO-8601"):
                    client.get_price(**kwargs, asof_time=cutoff)

    def test_adjustment_factor_uses_old_revision_at_old_asof(self) -> None:
        factors = [self._factor_revision(1, 2, 0.5, "17:00"),
                   self._factor_revision(2, 3, 0.25, "19:00")]
        versions = [self._version(7001, 2, "success", "superseded", "17:00"),
                    self._version(7002, 3, "success", "active", "19:00")]
        postgres = FakePostgres(dataset_versions=versions, adjustment_factors=factors)
        rows = self._client(postgres, FakeClickHouse(daily_rows=[self._price(7001, 10.0, "17:00")])).get_price(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
            adjust="forward", query_mode="asof", asof_time="2024-01-02T18:00:00+08:00")
        self.assertEqual(rows[0]["close"], 5.0)
        factor_sql, factor_params = next((sql, params) for sql, params in postgres.queries
                                         if "FROM qmeta.adjustment_factor" in sql)
        self.assertIn("af.announce_time <= %(knowledge_cutoff)s", factor_sql)
        self.assertIn("af.effective_time <= %(knowledge_cutoff)s", factor_sql)
        self.assertEqual(factor_params["knowledge_cutoff"], aware("2024-01-02T18:00:00+08:00"))

    def test_latest_adjustment_uses_only_successful_independent_correction(self) -> None:
        factors = [
            self._factor_revision(1, 2, 0.5, "17:00"),
            self._factor_revision(
                2, 3, 0.25, "17:30", dataset_code="adjustment_factor",
                batch_finished_at=aware("2024-01-02T19:00:00+08:00"),
            ),
            self._factor_revision(
                3, 4, 0.1, "20:00", dataset_code="adjustment_factor", batch_status="failed"
            ),
            self._factor_revision(
                4, 5, 0.05, "21:00", dataset_code="adjustment_factor", batch_status="running"
            ),
        ]
        postgres = FakePostgres(adjustment_factors=factors)

        rows = self._client(postgres, FakeClickHouse()).get_price(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
            adjust="forward",
        )

        self.assertEqual(rows[0]["close"], 2.625)
        factor_sql, factor_params = next((sql, params) for sql, params in postgres.queries
                                         if "FROM qmeta.adjustment_factor" in sql)
        self.assertIn("JOIN qmeta.data_batch db", factor_sql)
        self.assertIn("db.status = 'success'", factor_sql)
        self.assertEqual(set(factor_params["knowledge_dataset_codes"]),
                         {"daily_bar", "adjustment_factor"})

    def test_asof_adjustment_switches_only_after_correction_is_published(self) -> None:
        factors = [
            self._factor_revision(1, 2, 0.5, "17:00"),
            self._factor_revision(
                2, 3, 0.25, "17:30", dataset_code="adjustment_factor",
                batch_finished_at=aware("2024-01-02T19:00:00+08:00"),
            ),
        ]
        for cutoff, expected_close in (
            ("2024-01-02T18:00:00+08:00", 5.25),
            ("2024-01-02T20:00:00+08:00", 2.625),
        ):
            with self.subTest(cutoff=cutoff):
                postgres = FakePostgres(adjustment_factors=factors)
                rows = self._client(postgres, FakeClickHouse()).get_price(
                    symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
                    adjust="forward", query_mode="asof", asof_time=cutoff,
                )
                self.assertEqual(rows[0]["close"], expected_close)
                factor_sql = next(sql for sql, _ in postgres.queries
                                  if "FROM qmeta.adjustment_factor" in sql)
                self.assertIn("db.finished_at <= %(knowledge_cutoff)s", factor_sql)

    def test_public_adjustment_factor_latest_returns_only_latest_revision(self) -> None:
        factors = [self._factor_revision(1, 2, 0.5, "17:00"),
                   self._factor_revision(2, 3, 0.25, "19:00")]
        postgres = FakePostgres(adjustment_factors=factors)

        rows = self._client(postgres, FakeClickHouse()).get_adjustment_factor(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
            factor_type="forward")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["factor_forward"], 0.25)

    def test_asof_excludes_adjustment_revision_with_unknown_availability(self) -> None:
        visible = self._factor_revision(1, 2, 0.5, "17:00")
        unavailable = self._factor_revision(2, 2, 0.25, "17:30")
        unavailable["announce_time"] = None
        postgres = FakePostgres(adjustment_factors=[visible, unavailable])

        rows = self._client(postgres, FakeClickHouse()).get_price(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
            adjust="forward", query_mode="asof", asof_time="2024-01-02T18:00:00+08:00")

        self.assertEqual(rows[0]["close"], 5.25)

    def test_vintage_adjustment_is_frozen_at_daily_version_publication(self) -> None:
        daily = self._factor_revision(1, 2, 0.5, "16:00")
        correction_before_publication = self._factor_revision(
            2, 3, 0.25, "16:30", dataset_code="adjustment_factor"
        )
        correction_after_publication = self._factor_revision(
            3, 4, 0.1, "16:45", dataset_code="adjustment_factor",
            batch_finished_at=aware("2024-01-02T19:00:00+08:00"),
        )
        postgres = FakePostgres(adjustment_factors=[
            daily, correction_before_publication, correction_after_publication,
        ])

        rows = self._client(postgres, FakeClickHouse()).get_price(
            symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
            adjust="forward", query_mode="vintage", data_version="daily_bar:seed-v1")

        self.assertEqual(rows[0]["close"], 2.625)
        _, factor_params = next((sql, params) for sql, params in postgres.queries
                                if "FROM qmeta.adjustment_factor" in sql)
        self.assertEqual(factor_params["knowledge_cutoff"], aware("2024-01-02T17:01:00+08:00"))

    def test_adjusted_price_fails_closed_when_exact_factor_is_missing(self) -> None:
        client = self._client(FakePostgres(adjustment_factors=[]), FakeClickHouse())
        with self.assertRaisesRegex(QDataNotFoundError, "Missing point-in-time adjustment factor"):
            client.get_price(symbols=["600519.SH"], start_date="2024-01-02",
                             end_date="2024-01-02", adjust="forward")

    def test_minute_adjustment_is_explicitly_unsupported_not_silently_unadjusted(self) -> None:
        client = self._client(FakePostgres(), FakeClickHouse())

        with self.assertRaisesRegex(QDataValidationError, "minute-bar adjustment is not supported"):
            client.get_price(
                symbols=["600519.SH"], start_date="2024-01-02", end_date="2024-01-02",
                frequency="1m", adjust="forward",
            )

    def test_factor_query_uses_exact_bound_pairs_not_cross_product(self) -> None:
        factor_versions = [
            {"factor_id": 101, "factor_code": "momentum_20d", "factor_version_id": 1001,
             "version_code": "published-v1", "status": "published"},
            {"factor_id": 102, "factor_code": "quality_roe", "factor_version_id": 2002,
             "version_code": "published-v1", "status": "published"},
        ]
        factor_rows = [self._factor_value(101, 1001, 1.0), self._factor_value(102, 2002, 2.0),
                       self._factor_value(101, 2002, 99.0), self._factor_value(102, 1001, 88.0)]
        postgres, clickhouse = FakePostgres(factor_versions=factor_versions), FakeClickHouse(factor_rows=factor_rows)
        rows = self._client(postgres, clickhouse).get_factor(
            factors=["momentum_20d", "quality_roe"], symbols=["600519.SH"],
            start_date="2024-01-02", end_date="2024-01-02", factor_version="published")
        self.assertEqual({row["factor_value"] for row in rows}, {1.0, 2.0})
        sql, params = clickhouse.queries[-1]
        self.assertIn("factor_pair_0_factor_id", params)
        self.assertIn("factor_pair_1_factor_id", params)
        self.assertIn("factor_id = %(factor_pair_0_factor_id)s", sql)

    def test_sql_backend_get_fundamental_asof(self) -> None:
        client = Client(backend="sql", postgres_client=FakePostgres(), default_format="records")
        rows = client.get_fundamental_asof(symbols=["600519.SH"], fields=["roe_ttm"], asof_date="2021-06-30")
        self.assertEqual(rows[0]["report_period"], "2021-03-31")
        self.assertEqual(rows[0]["field_value"], 0.283)

    def test_sql_backend_get_tradable_universe_filters_constraints(self) -> None:
        client = Client(backend="sql", postgres_client=FakePostgres(), default_format="records")
        rows = client.get_tradable_universe(asof_date="2024-01-02", symbols=["600519.SH"], min_list_days=30)
        self.assertTrue(rows[0]["can_buy"])
        self.assertFalse(rows[0]["is_new_listing"])

    def test_auto_backend_without_dsn_falls_back_to_mock(self) -> None:
        with patch.dict(os.environ, {"QDATA_BACKEND": "auto"}, clear=True):
            rows = Client(default_format="records").get_security_master(symbols=["600519.SH"])
        self.assertEqual(rows[0]["symbol"], "600519.SH")

    @staticmethod
    def _client(postgres, clickhouse):
        return Client(backend="sql", postgres_client=postgres, clickhouse_client=clickhouse,
                      default_format="records")

    @staticmethod
    def _version(data_version, batch_id, batch_status, version_status, time_text):
        timestamp = aware(f"2024-01-02T{time_text}:00+08:00")
        return {"dataset_code": "daily_bar", "data_version": data_version,
                "version_code": f"daily_bar:v{data_version}", "batch_id": batch_id,
                "batch_status": batch_status, "version_status": version_status,
                "valid_from": timestamp, "finished_at": timestamp}

    @staticmethod
    def _price(data_version, close, time_text):
        return {"security_id": 1000001, "trade_date": "2024-01-02", "open": close,
                "high": close, "low": close, "close": close, "volume": 1000.0,
                "amount": close * 1000, "data_version": data_version,
                "ingest_time": aware(f"2024-01-02T{time_text}:00+08:00")}

    @staticmethod
    def _factor_revision(
        revision_id, batch_id, factor_forward, time_text,
        dataset_code="daily_bar", batch_status="success", batch_finished_at=None,
    ):
        timestamp = aware(f"2024-01-02T{time_text}:00+08:00")
        return {"security_id": 1000001, "trade_date": "2024-01-02",
                "factor_forward": factor_forward, "factor_backward": 1 / factor_forward,
                "revision_id": revision_id, "batch_id": batch_id,
                "dataset_code": dataset_code, "batch_status": batch_status,
                "batch_finished_at": batch_finished_at or timestamp,
                "announce_time": timestamp, "effective_time": timestamp, "ingest_time": timestamp}

    @staticmethod
    def _factor_value(factor_id, factor_version_id, value):
        return {"factor_id": factor_id, "factor_version_id": factor_version_id,
                "security_id": 1000001, "trade_date": "2024-01-02",
                "factor_value": value, "quality_flag": "normal"}


if __name__ == "__main__":
    unittest.main()
