import os
from datetime import date, datetime
from pathlib import Path
import re
import unittest
from uuid import uuid4
from zoneinfo import ZoneInfo


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


def _migration_block(sql: str, table: str) -> str:
    rebuild = f"{table}__0056_rebuild"
    match = re.search(
        rf"CREATE TABLE {re.escape(rebuild)}\b.*?"
        rf"EXCHANGE TABLES {re.escape(table)} AND {re.escape(rebuild)}\s*;.*?"
        rf"SYSTEM START MERGES {re.escape(table)}\s*;",
        sql,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError(f"create-copy-exchange migration not found: {table}")
    return match.group(0)


def _migration_order_key(sql: str, table: str) -> tuple[str, ...]:
    match = re.search(r"ORDER BY\s*\(([^)]*)\)", _migration_block(sql, table))
    if not match:
        raise AssertionError(f"rebuilt ORDER BY tuple not found: {table}")
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
                block = _migration_block(sql, table)
                rebuild = f"{table}__0056_rebuild"
                self.assertIn(f"INSERT INTO {rebuild}", block)
                self.assertIn(f"FROM {table}", block)
                self.assertIn(f"SYSTEM STOP MERGES {table}", block)
                self.assertIn(f"EXCHANGE TABLES {table} AND {rebuild}", block)
                self.assertIn(f"SYSTEM STOP MERGES {rebuild}", block)
                self.assertIn(f"SYSTEM START MERGES {table}", block)
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
    def test_daily_and_minute_optimize_final_retain_vintages_and_retries(self) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            self.fail(f"clickhouse-connect is required: {exc}")

        dsn = os.getenv(
            "QDATA_CLICKHOUSE_DSN",
            "http://qdata:qdata@127.0.0.1:18123/default",
        )
        client = clickhouse_connect.get_client(dsn=dsn)
        migration = VINTAGE_MIGRATION.read_text(encoding="utf-8")
        shanghai = ZoneInfo("Asia/Shanghai")
        trade_day = date(2024, 1, 2)
        bar_at = datetime(2024, 1, 2, 9, 31, tzinfo=shanghai)
        retry_rows = [
            # Deliberately reverse/interleave versions so row order cannot make
            # a broken sorting-key migration appear correct.
            (20.0, 7002, datetime(2024, 1, 2, 18, 0, tzinfo=shanghai)),
            (10.0, 7001, datetime(2024, 1, 2, 17, 0, tzinfo=shanghai)),
            (19.0, 7002, datetime(2024, 1, 2, 17, 59, tzinfo=shanghai)),
            (11.0, 7001, datetime(2024, 1, 2, 17, 1, tzinfo=shanghai)),
        ]
        specs = {
            "qts.daily_bar": {
                "old_sorting_key": "security_id, trade_date",
                "column_names": [
                    "security_id", "trade_date", "close", "data_version", "ingest_time",
                ],
                "rows": [
                    [1, trade_day, close, version, ingest_time]
                    for close, version, ingest_time in retry_rows
                ],
                "sentinel": [
                    2, trade_day, 99.0, 9999,
                    datetime(2024, 1, 2, 19, 0, tzinfo=shanghai),
                ],
                "sorting_key": "security_id, trade_date, data_version",
            },
            "qts.minute_bar": {
                "old_sorting_key": "security_id, trade_date, bar_time",
                "column_names": [
                    "security_id", "trade_date", "bar_time", "close", "data_version",
                    "ingest_time",
                ],
                "rows": [
                    [1, trade_day, bar_at, close, version, ingest_time]
                    for close, version, ingest_time in retry_rows
                ],
                "sentinel": [
                    2, trade_day, bar_at, 99.0, 9999,
                    datetime(2024, 1, 2, 19, 0, tzinfo=shanghai),
                ],
                "sorting_key": "security_id, trade_date, bar_time, data_version",
            },
        }
        qualified_tables = []
        try:
            for source_table, spec in specs.items():
                with self.subTest(table=source_table):
                    table = f"qdata_vintage_{source_table.rsplit('.', 1)[1]}_{uuid4().hex[:10]}"
                    qualified = f"default.{table}"
                    qualified_tables.append(qualified)
                    source_ddl = _table_block(
                        INIT_DDL.read_text(encoding="utf-8"), source_table
                    )
                    old_key_ddl = source_ddl.replace(
                        f"CREATE TABLE IF NOT EXISTS {source_table}",
                        f"CREATE TABLE {qualified}",
                        1,
                    )
                    old_key_ddl = re.sub(
                        r"ORDER BY\s*\([^)]*\)",
                        f"ORDER BY ({spec['old_sorting_key']})",
                        old_key_ddl,
                        count=1,
                    )
                    client.command(old_key_ddl.rstrip(";"))
                    client.command(f"SYSTEM STOP MERGES {qualified}")
                    for row in spec["rows"]:
                        client.insert(
                            qualified,
                            [row],
                            column_names=spec["column_names"],
                        )
                    source_rows = client.query(
                        f"""
                        SELECT data_version, close, ingest_time
                        FROM {qualified}
                        WHERE security_id = 1
                        ORDER BY ingest_time
                        """
                    ).result_rows
                    self.assertEqual(
                        [(row[0], row[1]) for row in source_rows],
                        [(7001, 10.0), (7001, 11.0), (7002, 19.0), (7002, 20.0)],
                    )
                    source_engine = client.query(
                        f"""
                        SELECT engine
                        FROM system.tables
                        WHERE database = 'default' AND name = '{table}'
                        """
                    ).result_rows
                    self.assertEqual(source_engine, [("ReplacingMergeTree",)])
                    active_parts = client.query(
                        f"""
                        SELECT count()
                        FROM system.parts
                        WHERE database = 'default' AND table = '{table}' AND active
                        """
                    ).result_rows
                    self.assertEqual(active_parts, [(4,)])

                    migration_block = _migration_block(migration, source_table)
                    rendered_block = migration_block.replace(source_table, qualified)
                    rebuild_qualified = f"{qualified}__0056_rebuild"
                    qualified_tables.append(rebuild_qualified)
                    for statement in rendered_block.split(";"):
                        if statement.strip():
                            client.command(statement)

                    sorting_key_rows = client.query(
                        f"""
                        SELECT sorting_key
                        FROM system.tables
                        WHERE database = 'default' AND name = '{table}'
                        """
                    ).result_rows
                    self.assertEqual(sorting_key_rows, [(spec["sorting_key"],)])
                    show_create = client.query(
                        f"SHOW CREATE TABLE {qualified}"
                    ).result_rows[0][0]
                    self.assertIn(
                        f"ORDER BY ({spec['sorting_key']})",
                        " ".join(show_create.split()),
                    )
                    backup_rows = client.query(
                        f"""
                        SELECT data_version, close, ingest_time
                        FROM {rebuild_qualified}
                        WHERE security_id = 1
                        ORDER BY ingest_time
                        """
                    ).result_rows
                    self.assertEqual(
                        [(row[0], row[1]) for row in backup_rows],
                        [(7001, 10.0), (7001, 11.0), (7002, 19.0), (7002, 20.0)],
                    )
                    backup_sorting_key = client.query(
                        f"""
                        SELECT sorting_key
                        FROM system.tables
                        WHERE database = 'default'
                          AND name = '{table}__0056_rebuild'
                        """
                    ).result_rows
                    self.assertEqual(backup_sorting_key, [(spec["old_sorting_key"],)])
                    copied_rows = client.query(
                        f"""
                        SELECT data_version, close, ingest_time
                        FROM {qualified}
                        WHERE security_id = 1
                        ORDER BY ingest_time
                        """
                    ).result_rows
                    self.assertEqual(
                        sorted({row[0] for row in copied_rows}),
                        [7001, 7002],
                    )

                    # A second part forces OPTIMIZE FINAL to rewrite the old
                    # part under the new sorting key rather than passing due to
                    # a single already-merged part.
                    client.insert(
                        qualified,
                        [spec["sentinel"]],
                        column_names=spec["column_names"],
                    )
                    client.command(f"OPTIMIZE TABLE {qualified} FINAL")

                    retained = client.query(
                        f"""
                        SELECT data_version, close
                        FROM {qualified}
                        WHERE security_id = 1
                        ORDER BY data_version
                        """
                    ).result_rows
                    published_visible = client.query(
                        f"""
                        SELECT close FROM {qualified}
                        WHERE security_id = 1 AND trade_date = '2024-01-02'
                          AND data_version IN (7001)
                        """
                    ).result_rows
                    vintage_v1 = client.query(
                        f"""
                        SELECT close FROM {qualified}
                        WHERE security_id = 1 AND trade_date = '2024-01-02'
                          AND data_version = 7001
                        """
                    ).result_rows

                    self.assertEqual(retained, [(7001, 11.0), (7002, 20.0)])
                    self.assertEqual(published_visible, [(11.0,)])
                    self.assertEqual(vintage_v1, [(11.0,)])
        finally:
            for qualified in qualified_tables:
                client.command(f"DROP TABLE IF EXISTS {qualified} SYNC")
            client.close()


if __name__ == "__main__":
    unittest.main()
