from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest

from qdata import Client
from qdata.exceptions import QDataValidationError


def aware(value: str) -> datetime:
    return datetime.fromisoformat(value)


class _ContractPostgres:
    """Deterministic SQL-boundary fixture with adversarial hidden revisions."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []

    def fetch_all(self, sql: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        self.queries.append((sql, params))
        if "FROM qmeta.security_master" in sql:
            historical = all(
                token in sql
                for token in (
                    "security_identifier_history",
                    "security_name_history",
                    "security_status_history",
                    "JOIN qmeta.data_batch",
                    "dataset_code = 'security_master'",
                    "status = 'success'",
                    "announce_time",
                    "ingest_time",
                )
            )
            return [
                {
                    "security_id": 1,
                    "symbol": "OLD001.SH" if historical else "NEW001.SH",
                    "asset_type": "stock",
                    "exchange": "SH",
                    "name": "Old Name" if historical else "New Name",
                    "list_date": "2000-01-01",
                    "delist_date": "2025-01-01",
                    "status": "active" if historical else "delisted",
                    "currency": "CNY",
                }
            ]
        if "FROM qmeta.adjustment_factor" in sql:
            protected = all(
                token in sql
                for token in (
                    "JOIN qmeta.data_batch db",
                    "db.status = 'success'",
                    "db.finished_at IS NOT NULL",
                )
            )
            return [
                {
                    "security_id": 1,
                    "trade_date": "2024-01-02",
                    "factor_forward": 0.5 if protected else 0.1,
                    "factor_backward": 2.0 if protected else 10.0,
                    "ex_right_type": "none",
                }
            ]
        if "FROM qpit.index_member_pit" in sql:
            protected = all(
                token in sql
                for token in (
                    "JOIN qmeta.data_batch db",
                    "db.status = 'success'",
                    "announce_time",
                    "ingest_time",
                    "ROW_NUMBER() OVER",
                )
            )
            return [] if protected else [
                {
                    "index_code": "000300.SH",
                    "symbol": "LATE001.SH",
                    "security_id": 9,
                    "effective_date": "2024-01-01",
                    "end_date": None,
                    "weight": 1.0,
                }
            ]
        if "FROM qpit.industry_membership_pit" in sql:
            protected = all(
                token in sql
                for token in (
                    "FROM qmeta.industry_category_history ich",
                    "dc_category.dataset_code = 'industry_membership_pit'",
                    "db_category.status = 'success'",
                    "ich.announce_time <",
                    "ich.ingest_time <",
                    "JOIN selected_categories cat_filter",
                    "cat_filter.level = %(level)s",
                    "cat_filter.level, mem.effective_date",
                )
            )
            return [
                {
                    "symbol": "OLD001.SH",
                    "security_id": 1,
                    "industry_system": "sw",
                    "level": 1 if protected else 3,
                    "industry_code": "801120" if protected else "801123",
                    "industry_name": "Food & Beverage" if protected else "Liquor",
                    "effective_date": "2021-12-13",
                    "end_date": None,
                }
            ]
        if "FROM qpit.financial_metric_pit" in sql:
            protected = (
                sql.count("JOIN qmeta.data_batch") >= 2
                and "db_metric.status = 'success'" in sql
                and "db_statement.status = 'success'" in sql
                and "ROW_NUMBER() OVER" in sql
            )
            return [
                {
                    "security_id": 1,
                    "report_period": "2023-12-31",
                    "field_name": "roe_ttm",
                    "field_value": 0.1 if protected else 0.9,
                    "announce_time": "2024-01-01T18:00:00+08:00",
                    "ingest_time": "2024-01-01T18:01:00+08:00",
                    "revision_id": 1 if protected else 2,
                    "is_restated": not protected,
                }
            ]
        if "FROM qmeta.limit_price_daily" in sql:
            protected = all(
                token in sql
                for token in (
                    "JOIN qmeta.data_batch",
                    "db_limit.status = 'success'",
                    "ROW_NUMBER() OVER",
                    "lp.ingest_time <",
                )
            )
            return [
                {
                    "security_id": 1,
                    "trade_date": "2024-01-02",
                    "limit_up": 11.0 if protected else 99.0,
                    "limit_down": 9.0,
                    "is_st": False,
                    "is_new_listing": False,
                    "is_suspended": False,
                    "is_delisting_period": False,
                    "list_days": 100,
                }
            ]
        if "FROM qpit.universe_member_pit" in sql:
            protected = all(
                token in sql
                for token in (
                    "snapshot_batch",
                    "db.status = 'success'",
                    "db.finished_at <",
                    "ROW_NUMBER() OVER",
                )
            )
            if not protected:
                return [
                    {
                        "universe": params["universe"],
                        "symbol": "A.SH",
                        "security_id": 1,
                        "asof_date": params["asof_date"],
                        "weight": 0.5,
                    },
                    {
                        "universe": params["universe"],
                        "symbol": "B.SH",
                        "security_id": 2,
                        "asof_date": params["asof_date"],
                        "weight": 0.5,
                    },
                ]
            if params["asof_date"] == "2024-01-03":
                return [
                    {
                        "universe": params["universe"],
                        "symbol": "B.SH",
                        "security_id": 2,
                        "asof_date": params["asof_date"],
                        "weight": 0.75,
                    }
                ]
            return []
        return []

    def close(self) -> None:
        return None


class _FactorClickHouse:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []

    def fetch_all(self, sql: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        self.queries.append((sql, params))
        if "FROM qts.factor_value_daily" not in sql:
            return []
        rows = [
            {
                "factor_id": 101,
                "factor_version_id": 1001,
                "security_id": 1,
                "trade_date": "2024-01-02",
                "factor_value": 0.1,
                "quality_flag": "normal",
                "data_version": 7001,
                "calc_time": aware("2024-01-02T17:00:00+08:00"),
            },
            {
                "factor_id": 101,
                "factor_version_id": 1001,
                "security_id": 1,
                "trade_date": "2024-01-02",
                "factor_value": 0.2,
                "quality_flag": "normal",
                "data_version": 7002,
                "calc_time": aware("2024-01-02T18:00:00+08:00"),
            },
        ]
        if "ROW_NUMBER() OVER" in sql and "data_version DESC" in sql:
            return [rows[-1]]
        return rows

    def close(self) -> None:
        return None


class _RangeRenamePostgres(_ContractPostgres):
    def fetch_all(self, sql: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        if "qdata_requested_identity_range" in sql:
            self.queries.append((sql, params))
            return [{"security_id": 1}]
        if "FROM qmeta.security_master" in sql:
            self.queries.append((sql, params))
            return [
                {
                    "security_id": 1,
                    "symbol": "NEW001.SH",
                    "asset_type": "stock",
                    "exchange": "SH",
                    "name": "Renamed Corp",
                    "list_date": "2000-01-01",
                    "delist_date": None,
                    "status": "active",
                    "currency": "CNY",
                }
            ]
        if "FROM qmeta.limit_price_daily" in sql:
            self.queries.append((sql, params))
            return [
                {
                    "security_id": 1,
                    "symbol": "OLD001.SH",
                    "trade_date": "2024-01-02",
                    "limit_up": 11.0,
                    "limit_down": 9.0,
                    "is_st": False,
                    "is_new_listing": False,
                    "is_suspended": False,
                    "is_delisting_period": False,
                    "list_days": 100,
                },
                {
                    "security_id": 1,
                    "symbol": "NEW001.SH",
                    "trade_date": "2024-01-03",
                    "limit_up": 12.0,
                    "limit_down": 10.0,
                    "is_st": False,
                    "is_new_listing": False,
                    "is_suspended": False,
                    "is_delisting_period": False,
                    "list_days": 101,
                },
            ]
        return super().fetch_all(sql, params)


class _SuspensionOnlyPostgres(_ContractPostgres):
    def fetch_all(self, sql: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        if "FROM qmeta.limit_price_daily" in sql:
            self.queries.append((sql, params))
            protected = all(
                token in sql
                for token in (
                    "selected_suspension_days",
                    "constraint_spine",
                    "generate_series",
                    "LEFT JOIN selected_limits",
                )
            )
            if protected:
                return [
                    {
                        "security_id": 1,
                        "symbol": "OLD001.SH",
                        "trade_date": "2024-01-02",
                        "limit_up": None,
                        "limit_down": None,
                        "is_st": False,
                        "is_new_listing": False,
                        "is_suspended": True,
                        "is_delisting_period": False,
                        "list_days": 100,
                    }
                ]
            return []
        return super().fetch_all(sql, params)


class _FactorPostgres(_ContractPostgres):
    def fetch_all(self, sql: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        if "FROM qmeta.factor_definition" in sql:
            self.queries.append((sql, params))
            return [
                {
                    "factor_id": 101,
                    "factor_code": "momentum_20d",
                    "factor_version_id": 1001,
                    "version_code": "v1",
                }
            ]
        return super().fetch_all(sql, params)


class FinalPitSemanticsTest(unittest.TestCase):
    def test_security_history_schema_carries_causal_batch_lineage(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tables = (
            "qmeta.security_identifier_history",
            "qmeta.security_name_history",
            "qmeta.security_status_history",
        )
        for ddl in (
            root / "db" / "migrations" / "0001_postgresql_init.sql",
            root / "db" / "table.sql",
        ):
            sql = ddl.read_text(encoding="utf-8")
            for table in tables:
                with self.subTest(ddl=ddl.name, table=table):
                    block = sql.split(f"CREATE TABLE IF NOT EXISTS {table}", 1)[1].split(
                        ");", 1
                    )[0]
                    self.assertIn("announce_time", block)
                    self.assertIn("ingest_time", block)
                    self.assertIn("batch_id", block)

        migration = root / "db" / "migrations" / "0059_postgresql_security_history_lineage.sql"
        self.assertTrue(migration.is_file())
        migration_sql = migration.read_text(encoding="utf-8")
        for table in tables:
            with self.subTest(migration=table):
                self.assertIn(f"ALTER TABLE {table}", migration_sql)

    def test_security_master_accepts_every_status_the_loader_emits(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for ddl in (
            root / "db" / "migrations" / "0001_postgresql_init.sql",
            root / "db" / "table.sql",
        ):
            sql = ddl.read_text(encoding="utf-8")
            sql = sql.split(
                "CREATE TABLE IF NOT EXISTS qmeta.security_master",
                1,
            )[1].split(");", 1)[0]
            with self.subTest(ddl=ddl.name):
                for status in ("'st'", "'star_st'", "'delisting_period'"):
                    self.assertIn(status, sql)
        migration_sql = (
            root / "db" / "migrations" / "0059_postgresql_security_history_lineage.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("DROP CONSTRAINT IF EXISTS", migration_sql)
        for status in ("'st'", "'star_st'", "'delisting_period'"):
            self.assertIn(status, migration_sql)

    def test_industry_labels_have_versioned_causal_history(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for ddl in (
            root / "db" / "migrations" / "0001_postgresql_init.sql",
            root / "db" / "table.sql",
        ):
            block = ddl.read_text(encoding="utf-8")
            with self.subTest(ddl=ddl.name):
                self.assertIn(
                    "CREATE TABLE IF NOT EXISTS qmeta.industry_category_history",
                    block,
                )
                for field in (
                    "announce_time",
                    "ingest_time",
                    "batch_id",
                    "revision_id",
                ):
                    self.assertIn(field, block.split(
                        "CREATE TABLE IF NOT EXISTS qmeta.industry_category_history",
                        1,
                    )[1].split(");", 1)[0])
        migration = (
            root / "db" / "migrations" / "0060_postgresql_industry_category_history.sql"
        )
        self.assertTrue(migration.is_file())
        seed = (root / "db" / "seed" / "postgresql_seed.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("INSERT INTO qmeta.industry_category_history", seed)

    def test_universe_snapshot_identity_is_durable_even_when_snapshot_is_empty(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for ddl in (
            root / "db" / "migrations" / "0001_postgresql_init.sql",
            root / "db" / "table.sql",
        ):
            with self.subTest(ddl=ddl.name):
                sql = ddl.read_text(encoding="utf-8")
                self.assertIn("CREATE TABLE IF NOT EXISTS qmeta.universe_snapshot", sql)
                self.assertIn("UNIQUE (universe_id, trade_date, batch_id)", sql)

        migration = (
            root
            / "db"
            / "migrations"
            / "0058_postgresql_universe_snapshot.sql"
        )
        self.assertTrue(migration.is_file())
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS qmeta.universe_snapshot",
            migration.read_text(encoding="utf-8"),
        )

    def test_adjustment_and_factor_reject_modes_their_signatures_cannot_express(self) -> None:
        client = Client(default_format="records")
        for method, kwargs in (
            (
                client.get_adjustment_factor,
                {
                    "symbols": ["600519.SH"],
                    "start_date": "2024-01-02",
                    "end_date": "2024-01-02",
                },
            ),
            (
                client.get_factor,
                {
                    "factors": ["momentum_20d"],
                    "symbols": ["600519.SH"],
                    "start_date": "2024-01-02",
                    "end_date": "2024-01-02",
                },
            ),
        ):
            for mode in ("asof", "vintage"):
                with self.subTest(method=method.__name__, mode=mode):
                    with self.assertRaisesRegex(
                        QDataValidationError,
                        "only supports query_mode='latest'",
                    ):
                        method(**kwargs, query_mode=mode)

    def test_factor_defaults_to_latest_and_returns_one_deterministic_revision(self) -> None:
        postgres = _FactorPostgres()
        clickhouse = _FactorClickHouse()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            clickhouse_client=clickhouse,
            default_format="records",
        )

        rows = client.get_factor(
            factors=["momentum_20d"],
            symbols=["OLD001.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
        )

        self.assertEqual([row["factor_value"] for row in rows], [0.2])
        factor_sql = clickhouse.queries[-1][0]
        self.assertIn("ROW_NUMBER() OVER", factor_sql)
        self.assertIn("data_version DESC", factor_sql)

    def test_public_adjustment_latest_excludes_failed_batch_revision(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_adjustment_factor(
            security_ids=[1],
            start_date="2024-01-02",
            end_date="2024-01-02",
            factor_type="forward",
        )

        self.assertEqual(rows[0]["factor_forward"], 0.5)

    def test_historical_security_master_uses_historical_identity_and_status(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_security_master(
            security_ids=[1],
            asof_date="2024-01-02",
            include_delisted=False,
        )

        self.assertEqual(rows[0]["symbol"], "OLD001.SH")
        self.assertEqual(rows[0]["name"], "Old Name")
        self.assertEqual(rows[0]["status"], "active")

        historical_sql = postgres.queries[-1][0]
        self.assertNotIn("sm.list_date IS NULL", historical_sql)
        self.assertNotIn("sm.delist_date IS NULL", historical_sql)
        self.assertNotIn("sm.exchange = ANY", historical_sql)
        self.assertIn("identifier.historical_list_date AS list_date", historical_sql)
        self.assertIn("status_history.status = 'delisted'", historical_sql)

    def test_index_membership_rejects_late_or_failed_revision(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_index_members_asof("000300.SH", "2024-01-02")

        self.assertEqual(rows, [])

    def test_industry_level_is_selected_before_revision_ranking(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_industry_asof(
            symbols=["OLD001.SH"],
            industry_system="sw",
            level=1,
            asof_date="2024-01-02",
        )

        self.assertEqual(rows[0]["level"], 1)
        self.assertEqual(rows[0]["industry_code"], "801120")

    def test_fundamental_selector_excludes_failed_and_late_revisions(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_fundamental_asof(
            security_ids=[1],
            fields=["roe_ttm"],
            asof_date="2024-01-02",
        )

        self.assertEqual(rows[0]["field_value"], 0.1)
        self.assertEqual(rows[0]["revision_id"], 1)

    def test_trading_constraints_exclude_failed_and_late_revisions(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_trading_constraints(
            symbols=["OLD001.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
        )

        self.assertEqual(rows[0]["limit_up"], 11.0)
        constraint_sql = postgres.queries[-1][0]
        for token in (
            "dc_status.dataset_code = 'security_master'",
            "db_status.status = 'success'",
            "st.announce_time <",
            "st.ingest_time <",
            "PARTITION BY st.security_id, st.start_date",
            "historical_identity.historical_list_date",
        ):
            with self.subTest(token=token):
                self.assertIn(token, constraint_sql)
        self.assertNotIn("sm.list_date", constraint_sql)

    def test_constraint_range_preserves_each_days_historical_symbol(self) -> None:
        postgres = _RangeRenamePostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_trading_constraints(
            symbols=["OLD001.SH"],
            start_date="2024-01-02",
            end_date="2024-01-03",
        )

        self.assertEqual(
            [row["symbol"] for row in rows],
            ["OLD001.SH", "NEW001.SH"],
        )
        constraint_sql = next(
            sql
            for sql, _ in reversed(postgres.queries)
            if "FROM qmeta.limit_price_daily" in sql
        )
        self.assertIn("sih.start_date <= spine.trade_date", constraint_sql)
        self.assertIn(
            "identifier.symbol || '.' || identifier.exchange AS symbol",
            constraint_sql,
        )

    def test_suspension_only_episode_is_a_constraint_spine_row(self) -> None:
        postgres = _SuspensionOnlyPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_trading_constraints(
            symbols=["OLD001.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_suspended"])
        self.assertFalse(rows[0]["can_buy"])
        self.assertFalse(rows[0]["can_sell"])

    def test_tradable_snapshot_removes_members_and_empty_snapshot_clears_all(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        day_two = client.get_universe("cn_a", "2024-01-03", include_weight=True)
        day_three = client.get_universe("cn_a", "2024-01-04", include_weight=True)

        self.assertEqual([row["symbol"] for row in day_two], ["B.SH"])
        self.assertEqual(day_two[0]["weight"], 0.75)
        self.assertEqual(day_three, [])

    def test_empty_tradable_snapshot_remains_empty_when_filters_are_requested(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_universe(
            "cn_a",
            "2024-01-04",
            filters={"exclude_suspended": True, "min_list_days": 30},
        )

        self.assertEqual(rows, [])

    def test_filtered_universe_fails_closed_when_constraint_row_is_missing(self) -> None:
        postgres = _ContractPostgres()
        client = Client(
            backend="sql",
            postgres_client=postgres,
            default_format="records",
        )

        rows = client.get_universe(
            "cn_a",
            "2024-01-03",
            filters={"exclude_suspended": True},
        )

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
