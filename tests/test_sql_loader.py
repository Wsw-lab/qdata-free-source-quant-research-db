import copy
import json
from types import SimpleNamespace
import unittest

from qdata.exceptions import QDataValidationError
from qdata.ingest.models import (
    AdjustmentFactorRecord,
    DailyBarRecord,
    LimitPriceRecord,
    MinuteBarRecord,
    QualityReport,
    SuspensionRecord,
    TradableUniverseRecord,
)
from qdata.loaders.sql_loader import SqlDailyBundleLoader


class StatefulConnection:
    """Small transactional fake for loader lifecycle and revision semantics."""

    def __init__(self) -> None:
        self.executed = []
        self.commit_count = 0
        self.rollback_count = 0
        self.next_batch_id = 99
        self.next_data_version = 7001
        self.batch_status = {}
        self.version_status = {}
        self.version_batch = {}
        self.adjustment_revisions = {}
        self.fail_commit_numbers = set()
        self.fail_sql_token = None
        self.rollback_error = None
        self._committed_state = self._state()

    def cursor(self):
        return StatefulCursor(self)

    def commit(self):
        self.commit_count += 1
        if self.commit_count in self.fail_commit_numbers:
            raise RuntimeError(f"postgres commit failed #{self.commit_count}")
        self._committed_state = self._state()

    def rollback(self):
        self.rollback_count += 1
        self._restore(self._committed_state)
        if self.rollback_error:
            raise self.rollback_error

    def _state(self):
        return copy.deepcopy(
            (
                self.batch_status,
                self.version_status,
                self.version_batch,
                self.adjustment_revisions,
            )
        )

    def _restore(self, state):
        (
            self.batch_status,
            self.version_status,
            self.version_batch,
            self.adjustment_revisions,
        ) = copy.deepcopy(state)


class StatefulCursor:
    def __init__(self, connection: StatefulConnection) -> None:
        self.connection = connection
        self._one = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, params))
        normalized = " ".join(sql.lower().split())
        self._one = None
        self.rowcount = 0
        if self.connection.fail_sql_token and self.connection.fail_sql_token in normalized:
            raise RuntimeError(f"postgres write failed: {self.connection.fail_sql_token}")

        if normalized.startswith("insert into qmeta.data_batch"):
            batch_id = self.connection.next_batch_id
            self.connection.next_batch_id += 1
            self.connection.batch_status[batch_id] = "running"
            self._one = {"batch_id": batch_id, "batch_code": params[2]}
            self.rowcount = 1
        elif normalized.startswith("insert into qmeta.dataset_version"):
            data_version = self.connection.next_data_version
            self.connection.next_data_version += 1
            batch_id = params[2]
            self.connection.version_status[data_version] = "draft"
            self.connection.version_batch[data_version] = batch_id
            self._one = {"data_version": data_version, "version_code": params[1]}
            self.rowcount = 1
        elif normalized.startswith("update qmeta.data_batch"):
            status, _, _, batch_id = params
            guarded = "status = 'running'" in normalized
            if not guarded or self.connection.batch_status.get(batch_id) == "running":
                self.connection.batch_status[batch_id] = status
                self._one = {"status": status}
                self.rowcount = 1
        elif normalized.startswith("select status from qmeta.data_batch"):
            status = self.connection.batch_status.get(params[0])
            self._one = {"status": status} if status else None
            self.rowcount = int(status is not None)
        elif normalized.startswith("update qmeta.dataset_version"):
            status, data_version = params
            guarded = "status = 'draft'" in normalized
            if not guarded or self.connection.version_status.get(data_version) == "draft":
                self.connection.version_status[data_version] = status
                self._one = {"status": status}
                self.rowcount = 1
        elif normalized.startswith("select status from qmeta.dataset_version"):
            status = self.connection.version_status.get(params[0])
            self._one = {"status": status} if status else None
            self.rowcount = int(status is not None)
        elif normalized.startswith("select pg_advisory_xact_lock"):
            self._one = {"pg_advisory_xact_lock": None}
            self.rowcount = 1
        elif "coalesce(max(revision_id), 0) + 1" in normalized:
            key = (params[0], str(params[1]))
            revisions = self.connection.adjustment_revisions.get(key, [])
            self._one = {"revision_id": max((item[0] for item in revisions), default=0) + 1}
            self.rowcount = 1
        elif normalized.startswith("insert into qmeta.adjustment_factor"):
            security_id, trade_date = params[0], str(params[1])
            revision_id = params[-1] if len(params) >= 9 else 1
            key = (security_id, trade_date)
            existing = self.connection.adjustment_revisions.setdefault(key, [])
            if "on conflict" in normalized and any(item[0] == revision_id for item in existing):
                existing[:] = [item for item in existing if item[0] != revision_id]
            existing.append((revision_id, params[2], params[3]))
            self.rowcount = 1
        elif normalized.startswith("insert into qmeta.universe_definition"):
            self._one = {"universe_id": 501}
            self.rowcount = 1
        else:
            self.rowcount = 1

    def fetchone(self):
        return self._one

    def fetchall(self):
        return []


class FakeClickHouse:
    def __init__(self, error=None, accept_before_error: bool = False) -> None:
        self.error = error
        self.accept_before_error = accept_before_error
        self.inserts = []

    def insert(self, table, rows, column_names):
        if not self.error or self.accept_before_error:
            self.inserts.append((table, rows, column_names))
        if self.error:
            raise self.error


class SqlDailyBundleLoaderTest(unittest.TestCase):
    def test_create_versioned_batch_creates_distinct_draft_version(self) -> None:
        connection = StatefulConnection()
        loader = self._loader(connection, FakeClickHouse())

        handle = loader._create_versioned_batch("daily_bar", 11, "2024-01-04", 1)

        self.assertEqual(handle.batch_id, 99)
        self.assertEqual(handle.data_version, 7001)
        self.assertNotEqual(handle.batch_id, handle.data_version)
        self.assertEqual(connection.batch_status[99], "running")
        self.assertEqual(connection.version_status[7001], "draft")
        version_sql, version_params = next(
            (sql, params) for sql, params in connection.executed
            if "INSERT INTO qmeta.dataset_version" in sql
        )
        self.assertIn("daily_bar", version_params[1])
        self.assertIn("draft", version_sql)

    def test_daily_success_writes_real_version_and_atomically_publishes(self) -> None:
        connection = StatefulConnection()
        clickhouse = FakeClickHouse()
        loader = self._loader(connection, clickhouse)

        loader.load_daily_bars([self._daily_bar()])

        _, rows, columns = clickhouse.inserts[0]
        self.assertEqual(rows[0][columns.index("batch_id")], 99)
        self.assertEqual(rows[0][columns.index("data_version")], 7001)
        self.assertNotEqual(
            rows[0][columns.index("batch_id")],
            rows[0][columns.index("data_version")],
        )
        self.assertEqual(connection.batch_status[99], "success")
        self.assertEqual(connection.version_status[7001], "active")
        self.assertEqual(connection.commit_count, 2)

    def test_minute_success_writes_real_version_and_atomically_publishes(self) -> None:
        connection = StatefulConnection()
        clickhouse = FakeClickHouse()
        loader = self._loader(connection, clickhouse)

        loader.load_minute_bars([self._minute_bar()])

        _, rows, columns = clickhouse.inserts[0]
        self.assertEqual(rows[0][columns.index("batch_id")], 99)
        self.assertEqual(rows[0][columns.index("data_version")], 7001)
        self.assertEqual(connection.batch_status[99], "success")
        self.assertEqual(connection.version_status[7001], "active")

    def test_minute_write_error_is_failed_and_recalled(self) -> None:
        connection = StatefulConnection()
        loader = self._loader(
            connection,
            FakeClickHouse(error=RuntimeError("minute clickhouse failed")),
        )

        with self.assertRaisesRegex(RuntimeError, "minute clickhouse failed"):
            loader.load_minute_bars([self._minute_bar()])

        self.assertEqual(connection.batch_status[99], "failed")
        self.assertEqual(connection.version_status[7001], "recalled")

    def test_clickhouse_accept_then_error_is_failed_and_recalled(self) -> None:
        connection = StatefulConnection()
        original = RuntimeError("clickhouse acknowledgement lost")
        loader = self._loader(connection, FakeClickHouse(error=original, accept_before_error=True))

        with self.assertRaises(RuntimeError) as caught:
            loader.load_daily_bars([self._daily_bar()])

        self.assertIs(caught.exception, original)
        self.assertEqual(connection.batch_status[99], "failed")
        self.assertEqual(connection.version_status[7001], "recalled")

    def test_publish_commit_failure_is_failed_and_recalled(self) -> None:
        connection = StatefulConnection()
        connection.fail_commit_numbers = {2}
        loader = self._loader(connection, FakeClickHouse())

        with self.assertRaisesRegex(RuntimeError, "postgres commit failed #2"):
            loader.load_daily_bars([self._daily_bar()])

        self.assertEqual(connection.batch_status[99], "failed")
        self.assertEqual(connection.version_status[7001], "recalled")
        self.assertEqual(connection.rollback_count, 1)

    def test_secondary_lifecycle_errors_do_not_mask_primary_error(self) -> None:
        connection = StatefulConnection()
        connection.rollback_error = RuntimeError("rollback secondary")
        original = RuntimeError("clickhouse primary")
        loader = self._loader(connection, FakeClickHouse(error=original))
        loader._create_versioned_batch = lambda *args: SimpleNamespace(
            batch_id=99,
            data_version=7001,
            version_code="daily_bar:test",
        )

        def fail_terminal(*args, **kwargs):
            raise RuntimeError("terminal secondary")

        loader._finish_versioned_batch = fail_terminal
        with self.assertRaises(RuntimeError) as caught:
            loader.load_daily_bars([self._daily_bar()])

        self.assertIs(caught.exception, original)
        self.assertEqual(len(caught.exception.qdata_lifecycle_errors), 2)

    def test_finish_batch_is_idempotent_but_rejects_terminal_overwrite(self) -> None:
        connection = StatefulConnection()
        connection.batch_status[99] = "running"
        connection._committed_state = connection._state()
        loader = self._loader(connection, FakeClickHouse())

        loader._finish_batches([99], "success")
        loader._finish_batches([99], "success")
        with self.assertRaisesRegex(QDataValidationError, "cannot transition"):
            loader._finish_batches([99], "failed", "late failure")

        self.assertEqual(connection.batch_status[99], "success")

    def test_adjustment_factor_corrections_append_monotonic_revisions(self) -> None:
        connection = StatefulConnection()
        loader = self._loader(connection, FakeClickHouse())
        loader._write_daily_bar_metadata([self._daily_bar(1.0)], {"600519.SH": 1000001}, 11, 91)
        loader._write_daily_bar_metadata([self._daily_bar(1.1)], {"600519.SH": 1000001}, 11, 92)

        revisions = connection.adjustment_revisions[(1000001, "2024-01-04")]
        self.assertEqual([item[0] for item in revisions], [1, 2])
        self.assertEqual([item[1] for item in revisions], [1.0, 1.1])
        factor_sql = "\n".join(
            sql for sql, _ in connection.executed if "INSERT INTO qmeta.adjustment_factor" in sql
        )
        self.assertNotIn("ON CONFLICT", factor_sql)

    def test_market_constraints_failure_marks_every_started_batch_failed(self) -> None:
        connection = StatefulConnection()
        connection.fail_sql_token = "insert into qmeta.limit_price_daily"
        loader = self._loader(connection, FakeClickHouse())
        terminal = []
        ids = iter([91, 92])
        loader._create_batch = lambda *args: next(ids)
        loader._finish_batches = lambda batch_ids, status, error_message=None: terminal.append(
            (tuple(batch_ids), status, error_message)
        )

        with self.assertRaisesRegex(RuntimeError, "limit_price_daily"):
            loader.load_market_constraints(
                [AdjustmentFactorRecord("600519.SH", "2024-01-04", 0.5, 2.0)],
                [LimitPriceRecord("600519.SH", "2024-01-04", 100.0, 80.0)],
                [],
            )

        self.assertEqual(terminal[-1][0:2], ((91, 92), "failed"))
        self.assertEqual(connection.rollback_count, 1)

    def test_market_constraints_write_all_supported_record_types(self) -> None:
        connection = StatefulConnection()
        loader = self._loader(connection, FakeClickHouse())
        ids = iter([91, 92, 93])
        terminal = []
        loader._create_batch = lambda *args: next(ids)
        loader._finish_batches = lambda batch_ids, status, error_message=None: terminal.append(
            (tuple(batch_ids), status)
        )

        loader.load_market_constraints(
            [AdjustmentFactorRecord("600519.SH", "2024-01-04", 0.5, 2.0)],
            [LimitPriceRecord("600519.SH", "2024-01-04", 100.0, 80.0)],
            [SuspensionRecord(
                "600519.SH", "2024-01-04 09:30:00", "2024-01-04 15:00:00",
                "full_day", "test",
            )],
        )

        sql_text = "\n".join(sql for sql, _ in connection.executed)
        self.assertIn("INSERT INTO qmeta.adjustment_factor", sql_text)
        self.assertIn("INSERT INTO qmeta.limit_price_daily", sql_text)
        self.assertIn("INSERT INTO qmeta.suspension_history", sql_text)
        self.assertEqual(terminal, [((91, 92, 93), "success")])

    def test_universe_failure_marks_started_batch_failed(self) -> None:
        connection = StatefulConnection()
        connection.fail_sql_token = "insert into qpit.universe_member_pit"
        loader = self._loader(connection, FakeClickHouse())
        terminal = []
        loader._create_batch = lambda *args: 93
        loader._finish_batches = lambda batch_ids, status, error_message=None: terminal.append(
            (tuple(batch_ids), status, error_message)
        )

        with self.assertRaisesRegex(RuntimeError, "universe_member_pit"):
            loader.load_tradable_universe(
                "cn_a",
                "A shares",
                "2024-01-04",
                [TradableUniverseRecord("600519.SH", "2024-01-04")],
            )

        self.assertEqual(terminal[-1][0:2], ((93,), "failed"))
        self.assertEqual(connection.rollback_count, 1)

    def test_quality_failure_marks_started_batch_failed(self) -> None:
        connection = StatefulConnection()
        connection.fail_sql_token = "insert into qmeta.data_quality_check_result"
        loader = self._loader(connection, FakeClickHouse())
        terminal = []
        loader._create_batch = lambda *args: 94
        loader._finish_batches = lambda batch_ids, status, error_message=None: terminal.append(
            (tuple(batch_ids), status, error_message)
        )

        with self.assertRaisesRegex(RuntimeError, "data_quality_check_result"):
            loader.write_quality_report(QualityReport(), "2024-01-04")

        self.assertEqual(terminal[-1][0:2], ((94,), "failed"))
        self.assertEqual(connection.rollback_count, 1)

    def test_quality_report_cleanup_is_scoped_to_source_and_job(self) -> None:
        connection = StatefulConnection()
        loader = self._loader(connection, FakeClickHouse())
        terminal = []
        loader._create_batch = lambda *args: 99
        loader._finish_batches = lambda batch_ids, status, error_message=None: terminal.append(status)

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
        self.assertEqual(terminal, ["success"])

    @staticmethod
    def _loader(connection, clickhouse):
        loader = SqlDailyBundleLoader(
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            source_code="csv",
        )
        loader._postgres = connection
        loader._clickhouse = clickhouse
        loader.open = lambda: None
        loader._source_id = lambda: 11
        loader._dataset_id = lambda dataset_code: 7
        loader._security_id_map = lambda symbols: {"600519.SH": 1000001}
        return loader

    @staticmethod
    def _daily_bar(factor_forward=1.0):
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
            factor_forward=factor_forward,
        )

    @staticmethod
    def _minute_bar():
        return MinuteBarRecord(
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


if __name__ == "__main__":
    unittest.main()
