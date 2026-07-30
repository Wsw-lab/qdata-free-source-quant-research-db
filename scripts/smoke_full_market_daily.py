#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client
from qdata.database import ClickHouseClient, PostgresClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a full-market daily production run.")
    parser.add_argument("--job-code", default="daily_market_akshare_all")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--symbols", default="600519.SH,000001.SZ")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    postgres = PostgresClient(args.postgres_dsn)
    clickhouse = ClickHouseClient(args.clickhouse_dsn)
    try:
        runs = postgres.fetch_all(
            """
            SELECT r.run_id, r.trade_date, r.attempt, r.status, r.row_count,
                   r.expected_row_count, r.missing_count, r.missing_symbols,
                   r.completeness_rate, r.expected_by_exchange, r.actual_by_exchange,
                   r.missing_by_exchange, r.missing_explanations,
                   r.batch_count, r.repair_status, r.quality_passed,
                   j.source_id
            FROM qmeta.pipeline_run r
            JOIN qmeta.pipeline_job j ON j.job_id = r.job_id
            WHERE j.job_code = %(job_code)s
              AND r.trade_date = %(trade_date)s
            ORDER BY r.run_id DESC
            LIMIT 1
            """,
            {"job_code": args.job_code, "trade_date": args.trade_date},
        )
        if not runs:
            print(f"pipeline_run=missing job={args.job_code} trade_date={args.trade_date}")
            return 1
        latest = runs[0]
        ch_rows = clickhouse.fetch_all(
            """
            SELECT count() AS row_count, uniqExact(security_id) AS security_count
            FROM qts.daily_bar FINAL
            WHERE trade_date = %(trade_date)s
            """,
            {"trade_date": args.trade_date},
        )[0]
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
        with Client(
            backend="sql",
            postgres_dsn=args.postgres_dsn,
            clickhouse_dsn=args.clickhouse_dsn,
            default_format="records",
        ) as client:
            prices = client.get_price(
                symbols=symbols,
                start_date=args.trade_date,
                end_date=args.trade_date,
                adjust="forward",
            )
        health = _fetch_job_health(
            postgres=postgres,
            job_code=args.job_code,
            trade_date=args.trade_date,
            source_id=latest["source_id"],
        )
        if not health:
            health = _fetch_source_health(
                postgres=postgres,
                trade_date=args.trade_date,
                source_id=latest["source_id"],
            )
        missing_symbols = latest.get("missing_symbols") or []
        print(
            f"pipeline_status={latest['status']} run_id={latest['run_id']} "
            f"expected={latest['expected_row_count']} rows={latest['row_count']} "
            f"missing={latest['missing_count']} completeness={latest['completeness_rate']} "
            f"batches={latest['batch_count']} repair={latest['repair_status']} "
            f"quality_passed={latest['quality_passed']}"
        )
        print(
            f"exchange_expected={latest['expected_by_exchange']} "
            f"exchange_actual={latest['actual_by_exchange']} "
            f"exchange_missing={latest['missing_by_exchange']}"
        )
        print(f"clickhouse_rows={ch_rows['row_count']} clickhouse_securities={ch_rows['security_count']}")
        print(f"sample_prices_count={len(prices)} {prices}")
        print(f"health_count={len(health)} {health}")
        if missing_symbols:
            print(f"missing_symbols={','.join(missing_symbols[:100])}")
        return 0 if latest["status"] in {"success", "partial_success"} and health else 1
    finally:
        postgres.close()
        clickhouse.close()


def _fetch_job_health(postgres: PostgresClient, job_code: str, trade_date: str, source_id: int):
    return postgres.fetch_all(
        """
        SELECT
            dc.dataset_code,
            qr.check_date,
            qr.check_name,
            qr.status,
            qr.severity,
            qr.metric_value,
            qr.threshold_value,
            qr.affected_rows,
            qr.details
        FROM qmeta.data_quality_check_result qr
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = qr.dataset_id
        JOIN qmeta.data_batch b ON b.batch_id = qr.batch_id
        WHERE dc.dataset_code = 'daily_bar'
          AND qr.check_date = %(trade_date)s
          AND b.source_id = %(source_id)s
          AND qr.details->>'job_code' = %(job_code)s
        ORDER BY qr.check_date, qr.severity, qr.check_name
        """,
        {"job_code": job_code, "trade_date": trade_date, "source_id": source_id},
    )


def _fetch_source_health(postgres: PostgresClient, trade_date: str, source_id: int):
    return postgres.fetch_all(
        """
        SELECT
            dc.dataset_code,
            qr.check_date,
            qr.check_name,
            qr.status,
            qr.severity,
            qr.metric_value,
            qr.threshold_value,
            qr.affected_rows,
            qr.details
        FROM qmeta.data_quality_check_result qr
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = qr.dataset_id
        JOIN qmeta.data_batch b ON b.batch_id = qr.batch_id
        WHERE dc.dataset_code = 'daily_bar'
          AND qr.check_date = %(trade_date)s
          AND b.source_id = %(source_id)s
          AND NOT (qr.details ? 'job_code')
        ORDER BY qr.check_date, qr.severity, qr.check_name
        """,
        {"trade_date": trade_date, "source_id": source_id},
    )


if __name__ == "__main__":
    raise SystemExit(main())
