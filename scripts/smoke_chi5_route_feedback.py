#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.chi5_route_feedback import (
    list_source_route_circuit_breakers,
    list_source_route_health_snapshots,
    list_source_route_recovery_probes,
    run_source_route_feedback_monitor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Chi-5 source-route feedback and circuit recovery.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    failed_code = _insert_decision(args.postgres_dsn, source_code="baostock", decision_status="failed", started_at=datetime.now(timezone.utc) - timedelta(hours=2), row_count=0)
    first = run_source_route_feedback_monitor(
        args.postgres_dsn,
        requested_by="chi5-smoke",
        trigger_mode="smoke",
        lookback_hours=4,
        max_failure_rate=0.0,
        max_empty_rate=0.0,
        circuit_open_minutes=0,
        write_db=True,
    )
    circuits = list_source_route_circuit_breakers(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": ["baostock"]}, 5, 0)
    if not circuits or circuits[0].get("status") != "open":
        raise RuntimeError(f"Chi-5 circuit did not open after failed decision: {failed_code}")

    success_code = _insert_decision(args.postgres_dsn, source_code="baostock", decision_status="success", started_at=datetime.now(timezone.utc), row_count=1)
    second = run_source_route_feedback_monitor(
        args.postgres_dsn,
        requested_by="chi5-smoke",
        trigger_mode="smoke",
        lookback_hours=1,
        min_success_rate=1.0,
        max_failure_rate=0.0,
        max_empty_rate=0.0,
        circuit_open_minutes=0,
        recovery_probe_min_success_rate=1.0,
        write_db=True,
    )
    health = list_source_route_health_snapshots(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": ["baostock"]}, 5, 0)
    probes = list_source_route_recovery_probes(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": ["baostock"]}, 5, 0)
    circuits = list_source_route_circuit_breakers(args.postgres_dsn, {"dataset_code": ["daily_bar"], "source_code": ["baostock"]}, 5, 0)
    if not health:
        raise RuntimeError("Chi-5 health snapshot was not persisted")
    if not probes or probes[0].get("status") != "recovered":
        raise RuntimeError(f"Chi-5 recovery probe did not recover source after success decision: {success_code}")
    if not circuits or circuits[0].get("status") != "closed":
        raise RuntimeError("Chi-5 circuit did not close after recovered probe")
    print(
        "chi5_route_feedback_smoke=ok "
        f"first_status={first.get('status')} second_status={second.get('status')} "
        f"health={len(health)} circuit={circuits[0].get('status')} "
        f"probe={probes[0].get('status')} failed_decision={failed_code} success_decision={success_code}"
    )
    return 0


def _insert_decision(postgres_dsn: str, *, source_code: str, decision_status: str, started_at: datetime, row_count: int) -> str:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("psycopg is required for Chi-5 smoke") from exc
    digest = hashlib.sha1(f"{source_code}:{decision_status}:{started_at.isoformat()}".encode("utf-8")).hexdigest()[:12]
    decision_code = f"chi5-smoke-route-{source_code}-{decision_status}-{digest}"
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = 'daily_bar'")
            dataset = cursor.fetchone()
            cursor.execute("SELECT source_id FROM qmeta.source_system WHERE source_code = %s", (source_code,))
            source = cursor.fetchone()
            if not dataset or not source:
                raise RuntimeError("daily_bar dataset and smoke source must exist before Chi-5 smoke")
            cursor.execute(
                """
                INSERT INTO qmeta.source_route_decision_audit (
                    decision_code, dataset_id,
                    requested_source_id, selected_source_id,
                    final_source_id, primary_source_id,
                    request_key, decision_context,
                    route_mode, decision_status,
                    selected_role, effective_date,
                    selected_weight_pct, deterministic_bucket,
                    candidate_sources, attempt_sources,
                    fallback_attempted, fallback_applied,
                    row_count, duration_ms,
                    details, started_at, finished_at,
                    updated_at
                ) VALUES (
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, 'smoke',
                    'default', %s,
                    'requested', CURRENT_DATE,
                    100, 0,
                    ARRAY[%s]::text[], ARRAY[%s]::text[],
                    FALSE, FALSE,
                    %s, 5,
                    '{"owner":"chi5-smoke"}'::jsonb, %s, %s,
                    now()
                )
                ON CONFLICT (decision_code) DO NOTHING
                """,
                (
                    decision_code,
                    dataset["dataset_id"],
                    source["source_id"],
                    source["source_id"],
                    source["source_id"],
                    source["source_id"],
                    decision_code,
                    decision_status,
                    source_code,
                    source_code,
                    row_count,
                    started_at,
                    started_at + timedelta(milliseconds=5),
                ),
            )
    return decision_code


if __name__ == "__main__":
    raise SystemExit(main())
