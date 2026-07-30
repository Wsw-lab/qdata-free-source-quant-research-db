#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.sources.sync import sync_daily_market


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Phi-5 active route policy runtime selection and audit.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    parser.add_argument("--trade-date", default="2024-01-04")
    parser.add_argument("--raw-root", default="/tmp/qdata-phi5-smoke-raw")
    args = parser.parse_args()

    policy_code = _insert_smoke_policy(args.postgres_dsn, effective_date=date.fromisoformat(args.trade_date))
    try:
        csv_kwargs = {
            "security_master_path": "raw/samples/security_master.csv",
            "trading_calendar_path": "raw/samples/trading_calendar.csv",
            "daily_bar_path": "raw/samples/daily_bar.csv",
        }
        result = sync_daily_market(
            provider_name="csv",
            trade_date=args.trade_date,
            symbols=["600519.SH"],
            postgres_dsn=args.postgres_dsn,
            clickhouse_dsn=args.clickhouse_dsn,
            raw_root=args.raw_root,
            dry_run=True,
            provider_kwargs=csv_kwargs,
            route_provider_kwargs={
                "csv": csv_kwargs,
                "csv_mirror": {**csv_kwargs, "provider_name": "csv_mirror"},
            },
            use_route_policy=True,
        )
        route = result.get("route_decision") or {}
        audits = _count_recent_decisions(args.postgres_dsn, policy_code)
        if route.get("selected_source_code") != "csv_mirror" or route.get("final_source_code") != "csv_mirror":
            raise SystemExit(f"phi5_route_policy_smoke=failed reason=unexpected_route route={route}")
        if audits <= 0:
            raise SystemExit("phi5_route_policy_smoke=failed reason=audit_missing")
        print(
            "phi5_route_policy_smoke=ok "
            f"policy_code={policy_code} selected={route.get('selected_source_code')} "
            f"final={route.get('final_source_code')} fallback={route.get('fallback_applied')} audits={audits}"
        )
    finally:
        _supersede_smoke_policy(args.postgres_dsn, policy_code)
    return 0


def _insert_smoke_policy(postgres_dsn: str, *, effective_date: date) -> str:
    import psycopg
    from psycopg.rows import dict_row

    policy_code = f"phi5-smoke-policy-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = 'daily_bar'")
            dataset_id = cursor.fetchone()["dataset_id"]
            cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = 'csv_mirror'")
            source_id = cursor.fetchone()["source_id"]
            cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = 'csv'")
            backup_source_id = cursor.fetchone()["source_id"]
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_weight_policy (
                    policy_code, source_id, dataset_id,
                    backup_source_id, effective_date,
                    policy_status, execution_mode,
                    primary_weight_pct, backup_weight_pct,
                    free_source_weight_pct, created_by,
                    evidence, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    'active', 'apply',
                    100, 0,
                    0, 'phi5_smoke',
                    '{"purpose":"phi5 smoke temporary active policy"}'::jsonb, now()
                )
                """,
                (policy_code, source_id, dataset_id, backup_source_id, effective_date),
            )
    return policy_code


def _count_recent_decisions(postgres_dsn: str, policy_code: str) -> int:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM qmeta.source_route_decision_audit srda
                JOIN qmeta.source_route_weight_policy srwp ON srwp.policy_id = srda.policy_id
                WHERE srwp.policy_code = %s
                """,
                (policy_code,),
            )
            return int(cursor.fetchone()["count"])


def _supersede_smoke_policy(postgres_dsn: str, policy_code: str) -> None:
    import psycopg

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.source_route_weight_policy
                SET policy_status = 'superseded',
                    end_date = current_date,
                    updated_at = now()
                WHERE policy_code = %s
                """,
                (policy_code,),
            )


if __name__ == "__main__":
    raise SystemExit(main())
