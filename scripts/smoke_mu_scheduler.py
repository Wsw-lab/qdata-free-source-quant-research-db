#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa import dispatch_kappa_endpoint, format_kappa_report
from qdata.mu_scheduler import force_schedule_due, format_scheduler_report, run_mu_scheduler


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Mu scheduler against PostgreSQL/Kappa state.")
    parser.add_argument("--schedule-code", default="mu_usage_rollup_5m")
    parser.add_argument("--scheduler-id", default="mu-smoke")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    due = force_schedule_due(args.postgres_dsn, args.schedule_code)
    print(f"force_due schedule_code={due['schedule_code']} next_run_at={due['next_run_at']}")
    result = run_mu_scheduler(
        args.postgres_dsn,
        scheduler_id=args.scheduler_id,
        schedule_codes=[args.schedule_code],
        once=True,
        max_ticks=1,
        dry_run=True if args.dry_run else None,
        trade_date=args.trade_date or None,
    )
    print(format_scheduler_report(result))
    if not result.tick_results or result.status == "failed":
        return 1
    _print_kappa(args.postgres_dsn, "/admin/worker-schedules", {"schedule_code": [args.schedule_code], "limit": ["5"]})
    _print_kappa(args.postgres_dsn, "/admin/worker-schedule-ticks", {"schedule_code": [args.schedule_code], "limit": ["5"]})
    _print_kappa(args.postgres_dsn, "/admin/worker-heartbeats", {"scheduler_id": [args.scheduler_id], "limit": ["5"]})
    return 0


def _print_kappa(postgres_dsn: str, path: str, params: dict[str, list[str]]) -> None:
    result = dispatch_kappa_endpoint(postgres_dsn, path, params)
    print(format_kappa_report(result))


if __name__ == "__main__":
    raise SystemExit(main())
