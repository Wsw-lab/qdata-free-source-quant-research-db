import os
from pathlib import Path
import re
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
INIT_DDL = ROOT / "db" / "migrations" / "0002_clickhouse_init.sql"
COMBINED_DDL = ROOT / "db" / "table.sql"
VINTAGE_MIGRATION = ROOT / "db" / "migrations" / "0056_clickhouse_durable_vintage.sql"


def _table_block(sql: str, table: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\b.*?;",
        sql,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError(f"CREATE TABLE block not found: {table}")
    return match.group(0)


def _order_key(sql_block: str) -> tuple[str, ...]:
    match = re.search(r"ORDER BY\s*\(([^)]*)\)", sql_block)
    if not match:
        raise AssertionError("ORDER BY tuple not found")
    return tuple(part.strip() for part in match.group(1).split(","))


def _migration_order_key(sql: str, table: str) -> tuple[str, ...]:
    match = re.search(
        rf"ALTER TABLE {re.escape(table)}\b.*?MODIFY ORDER BY\s*\(([^)]*)\)\s*;",
        sql,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError(f"version-preserving ALTER not found: {table}")
    return tuple(part.strip() for part in match.group(1).split(","))


def _merged_rows(rows: list[dict], key: tuple[str, ...]) -> list[dict]:
    """Model ReplacingMergeTree: one max-ingest row per ORDER BY key."""
    winners = {}
    for row in rows:
        values = tuple(
            row["data_version"] if field == "version_key" else row[field]
            for field in key
        )
        if values not in winners or row["ingest_time"] > winners[values]["ingest_time"]:
            winners[values] = row
    return list(winners.values())


class ClickHouseVintageSchemaContractTest(unittest.TestCase):
    def test_fresh_daily_and_minute_schemas_retain_each_data_version_after_merge(self) -> None:
        fixtures = {
            "qts.daily_bar": [
                {"security_id": 1, "trade_date": "2024-01-02", "data_version": 7001,
                 "ingest_time": "2024-01-02T17:00:00", "close": 10.0},
                {"security_id": 1, "trade_date": "2024-01-02", "data_version": 7002,
                 "ingest_time": "2024-01-02T18:00:00", "close": 20.0},
            ],
            "qts.minute_bar": [
                {"security_id": 1, "trade_date": "2024-01-02",
                 "bar_time": "2024-01-02T09:31:00", "data_version": 7001,
                 "ingest_time": "2024-01-02T17:00:00", "close": 10.0},
                {"security_id": 1, "trade_date": "2024-01-02",
                 "bar_time": "2024-01-02T09:31:00", "data_version": 7002,
                 "ingest_time": "2024-01-02T18:00:00", "close": 20.0},
            ],
        }
        for ddl_path in (INIT_DDL, COMBINED_DDL):
            sql = ddl_path.read_text(encoding="utf-8")
            for table, rows in fixtures.items():
                with self.subTest(ddl=ddl_path.name, table=table):
                    key = _order_key(_table_block(sql, table))
                    merged = _merged_rows(rows, key)
                    self.assertEqual(
                        sorted(row["data_version"] for row in merged),
                        [7001, 7002],
                    )

    def test_existing_table_migration_retains_versions_and_replaces_only_retries(self) -> None:
        self.assertTrue(
            VINTAGE_MIGRATION.is_file(),
            "an executable existing-table ClickHouse migration is required",
        )
        sql = VINTAGE_MIGRATION.read_text(encoding="utf-8")
        fixtures = {
            "qts.daily_bar": [
                {"security_id": 1, "trade_date": "2024-01-02", "data_version": 7001,
                 "ingest_time": "2024-01-02T17:00:00", "close": 10.0},
                {"security_id": 1, "trade_date": "2024-01-02", "data_version": 7001,
                 "ingest_time": "2024-01-02T17:01:00", "close": 11.0},
                {"security_id": 1, "trade_date": "2024-01-02", "data_version": 7002,
                 "ingest_time": "2024-01-02T18:00:00", "close": 20.0},
            ],
            "qts.minute_bar": [
                {"security_id": 1, "trade_date": "2024-01-02",
                 "bar_time": "2024-01-02T09:31:00", "data_version": 7001,
                 "ingest_time": "2024-01-02T17:00:00", "close": 10.0},
                {"security_id": 1, "trade_date": "2024-01-02",
                 "bar_time": "2024-01-02T09:31:00", "data_version": 7001,
                 "ingest_time": "2024-01-02T17:01:00", "close": 11.0},
                {"security_id": 1, "trade_date": "2024-01-02",
                 "bar_time": "2024-01-02T09:31:00", "data_version": 7002,
                 "ingest_time": "2024-01-02T18:00:00", "close": 20.0},
            ],
        }

        for table, rows in fixtures.items():
            with self.subTest(table=table):
                key = _migration_order_key(sql, table)
                merged = sorted(_merged_rows(rows, key), key=lambda row: row["data_version"])
                self.assertEqual(
                    [(row["data_version"], row["close"]) for row in merged],
                    [(7001, 11.0), (7002, 20.0)],
                )


@unittest.skipUnless(
    os.getenv("QDATA_RUN_CLICKHOUSE_INTEGRATION") == "1",
    "set QDATA_RUN_CLICKHOUSE_INTEGRATION=1 to run ClickHouse 24.8 migration test",
)
class ClickHouseVintageMigrationIntegrationTest(unittest.TestCase):
    def test_optimize_final_retains_vintage_and_publication_gate(self) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            self.fail(f"clickhouse-connect is required: {exc}")

        dsn = os.getenv(
            "QDATA_CLICKHOUSE_DSN",
            "http://qdata:qdata@127.0.0.1:18123/default",
        )
        client = clickhouse_connect.get_client(dsn=dsn)
        table = f"qdata_vintage_migration_{uuid4().hex[:12]}"
        qualified = f"default.{table}"
        try:
            client.command(
                f"""
                CREATE TABLE {qualified} (
                    security_id UInt64,
                    trade_date Date,
                    close Nullable(Float64),
                    data_version UInt64,
                    ingest_time DateTime64(3, 'Asia/Shanghai')
                )
                ENGINE = ReplacingMergeTree(ingest_time)
                PARTITION BY toYYYYMM(trade_date)
                ORDER BY (security_id, trade_date)
                """
            )
            client.insert(
                qualified,
                [
                    [1, "2024-01-02", 10.0, 7001, "2024-01-02 17:00:00"],
                    [1, "2024-01-02", 11.0, 7001, "2024-01-02 17:01:00"],
                    [1, "2024-01-02", 20.0, 7002, "2024-01-02 18:00:00"],
                ],
                column_names=[
                    "security_id", "trade_date", "close", "data_version", "ingest_time",
                ],
            )
            migration = VINTAGE_MIGRATION.read_text(encoding="utf-8")
            statement = re.search(
                r"ALTER TABLE qts\.daily_bar\b.*?;",
                migration,
                flags=re.DOTALL,
            )
            self.assertIsNotNone(statement)
            client.command(
                statement.group(0).replace("qts.daily_bar", qualified).rstrip(";")
            )
            client.command(f"OPTIMIZE TABLE {qualified} FINAL")

            retained = client.query(
                f"SELECT data_version, close FROM {qualified} FINAL ORDER BY data_version"
            ).result_rows
            latest_visible = client.query(
                f"""
                SELECT close FROM {qualified} FINAL
                WHERE security_id = 1 AND trade_date = '2024-01-02'
                  AND data_version IN (7001)
                """
            ).result_rows
            vintage_v1 = client.query(
                f"""
                SELECT close FROM {qualified} FINAL
                WHERE security_id = 1 AND trade_date = '2024-01-02'
                  AND data_version = 7001
                """
            ).result_rows

            self.assertEqual(retained, [(7001, 11.0), (7002, 20.0)])
            self.assertEqual(latest_visible, [(11.0,)])
            self.assertEqual(vintage_v1, [(11.0,)])
        finally:
            client.command(f"DROP TABLE IF EXISTS {qualified} SYNC")
            client.close()


if __name__ == "__main__":
    unittest.main()
