#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.sigma5_vendor_primary_stability import (
    format_sigma5_rows,
    list_vendor_primary_stability_datasets,
    list_vendor_primary_stability_snapshots,
    run_vendor_primary_stability_monitor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Sigma-5 primary vendor production stability snapshots.")
    parser.add_argument("--resource", choices=["run", "snapshots", "datasets"], default="run")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--dataset-code", action="append", default=[])
    parser.add_argument("--requested-by", default="sigma5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default=os.getenv("QDATA_ENVIRONMENT", "local"))
    parser.add_argument("--monitor-scope", choices=["primary_source", "all_datasets", "full_market"], default=os.getenv("QDATA_SIGMA5_MONITOR_SCOPE", "primary_source"))
    parser.add_argument("--lookback-hours", type=int, default=int(os.getenv("QDATA_SIGMA5_LOOKBACK_HOURS", "24")))
    parser.add_argument("--capacity-window-days", type=int, default=int(os.getenv("QDATA_SIGMA5_CAPACITY_WINDOW_DAYS", "7")))
    parser.add_argument("--min-success-rate", type=float, default=float(os.getenv("QDATA_SIGMA5_MIN_SUCCESS_RATE", "0.995")))
    parser.add_argument("--max-error-rate", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_ERROR_RATE", "0.005")))
    parser.add_argument("--max-latency-p95-ms", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_LATENCY_P95_MS", "2000")))
    parser.add_argument("--max-timeout-rate", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_TIMEOUT_RATE", "0.01")))
    parser.add_argument("--max-cost-units", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_COST_UNITS", "500")))
    parser.add_argument("--max-scheduler-lag-minutes", type=int, default=int(os.getenv("QDATA_SIGMA5_MAX_SCHEDULER_LAG_MINUTES", "90")))
    parser.add_argument("--max-backlog-count", type=int, default=int(os.getenv("QDATA_SIGMA5_MAX_BACKLOG_COUNT", "50")))
    parser.add_argument("--max-post-promotion-no-applied-count", type=int, default=int(os.getenv("QDATA_SIGMA5_MAX_POST_PROMOTION_NO_APPLIED_COUNT", "0")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--stability-role", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        row = run_vendor_primary_stability_monitor(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            dataset_codes=args.dataset_code or None,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            monitor_scope=args.monitor_scope,
            lookback_hours=args.lookback_hours,
            capacity_window_days=args.capacity_window_days,
            min_success_rate=args.min_success_rate,
            max_error_rate=args.max_error_rate,
            max_latency_p95_ms=args.max_latency_p95_ms,
            max_timeout_rate=args.max_timeout_rate,
            max_cost_units=args.max_cost_units,
            max_scheduler_lag_minutes=args.max_scheduler_lag_minutes,
            max_backlog_count=args.max_backlog_count,
            max_post_promotion_no_applied_count=args.max_post_promotion_no_applied_count,
            write_db=not args.dry_run,
        )
        rows = row
    else:
        params: dict[str, list[str]] = {}
        for key, value in [
            ("snapshot_code", args.snapshot_code),
            ("source_code", args.source_code),
            ("primary_source_code", args.primary_source_code),
            ("status", args.status),
            ("stability_role", args.stability_role),
            ("monitor_scope", args.monitor_scope),
        ]:
            if value:
                params[key] = [value]
        if args.resource == "snapshots":
            rows = list_vendor_primary_stability_snapshots(args.postgres_dsn, params, args.limit, args.offset)
        else:
            rows = list_vendor_primary_stability_datasets(args.postgres_dsn, params, args.limit, args.offset)
    output_rows = rows.get("results") if isinstance(rows, dict) and args.resource == "datasets" else rows
    row_count = len(output_rows) if isinstance(output_rows, list) else 1
    if args.json:
        print(json.dumps({"resource": f"sigma5.{args.resource}", "row_count": row_count, "rows": output_rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_sigma5_rows(args.resource, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
