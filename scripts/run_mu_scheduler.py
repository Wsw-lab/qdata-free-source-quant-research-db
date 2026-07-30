#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.lambda_worker import WORKER_TASKS
from qdata.mu_scheduler import format_scheduler_report, force_schedule_due, run_mu_scheduler


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mu scheduler for Lambda worker schedules.")
    parser.add_argument("--scheduler-id", default=os.getenv("QDATA_MU_SCHEDULER_ID", ""))
    parser.add_argument("--schedule-code", action="append", default=[])
    parser.add_argument("--task", choices=WORKER_TASKS, action="append", default=[])
    parser.add_argument("--once", action="store_true", help="Run one scheduler scan and exit.")
    parser.add_argument("--max-ticks", type=int, default=0, help="Maximum scheduler scans. 0 means infinite unless --once is set.")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("QDATA_MU_POLL_SECONDS", "30")))
    parser.add_argument("--due-limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="Force all due schedules to run Lambda tasks in dry-run mode.")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--force-due", action="store_true", help="Set selected schedules next_run_at to now before scanning.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.force_due:
        if not args.schedule_code:
            parser.error("--force-due requires at least one --schedule-code")
        for schedule_code in args.schedule_code:
            force_schedule_due(args.postgres_dsn, schedule_code)
    max_ticks = 1 if args.once else (args.max_ticks if args.max_ticks > 0 else None)
    result = run_mu_scheduler(
        args.postgres_dsn,
        scheduler_id=args.scheduler_id or None,
        schedule_codes=args.schedule_code or None,
        task_names=args.task or None,
        once=args.once,
        max_ticks=max_ticks,
        poll_seconds=args.poll_seconds,
        due_limit=args.due_limit,
        dry_run=True if args.dry_run else None,
        trade_date=args.trade_date or None,
        start_date=args.start_date or None,
        end_date=args.end_date or None,
    )
    if args.json:
        print(json.dumps(_result_dict(result), ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_scheduler_report(result))
    return 0


def _result_dict(result) -> dict:
    return {
        "scheduler_id": result.scheduler_id,
        "status": result.status,
        "scan_count": result.scan_count,
        "duration_ms": result.duration_ms,
        "tick_results": [
            {
                "tick_id": item.tick_id,
                "schedule_code": item.schedule_code,
                "task_name": item.task_name,
                "status": item.status,
                "worker_run_id": item.worker_run_id,
                "lock_acquired": item.lock_acquired,
                "duration_ms": item.duration_ms,
                "error_message": item.error_message,
                "details": item.details or {},
            }
            for item in result.tick_results
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
