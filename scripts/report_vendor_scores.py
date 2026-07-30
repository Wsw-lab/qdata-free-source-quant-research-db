#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Print latest Eta vendor quality scores.")
    parser.add_argument("--dataset-code", default="daily_bar")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise SystemExit("psycopg is required for report_vendor_scores.py") from exc

    with psycopg.connect(args.postgres_dsn, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    ss.source_code, dc.dataset_code, vq.score_date,
                    vq.coverage_rate, vq.conflict_rate, vq.failure_rate,
                    vq.latency_ms, vq.total_score, vq.rating
                FROM qmeta.vendor_quality_score_daily vq
                JOIN qmeta.source_system ss ON ss.source_id = vq.source_id
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vq.dataset_id
                WHERE dc.dataset_code = %s
                ORDER BY vq.score_date DESC, vq.total_score DESC
                LIMIT %s
                """,
                (args.dataset_code, args.limit),
            )
            rows = cursor.fetchall()
    print(f"vendor_scores dataset={args.dataset_code} rows={len(rows)}")
    for row in rows:
        print(
            f"vendor source={row['source_code']} date={row['score_date']} score={row['total_score']} "
            f"rating={row['rating']} coverage={row['coverage_rate']} conflict={row['conflict_rate']} "
            f"failure={row['failure_rate']} latency_ms={row['latency_ms']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
