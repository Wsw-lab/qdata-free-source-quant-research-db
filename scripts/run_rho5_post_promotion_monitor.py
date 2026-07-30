#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.rho5_post_promotion_monitor import (
    format_rho5_rows,
    list_vendor_post_promotion_monitors,
    list_vendor_post_promotion_results,
    run_post_promotion_monitor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Rho-5 post-promotion monitoring and rollback guardrail.")
    parser.add_argument("--resource", choices=["run", "runs", "results"], default="run")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default="csv")
    parser.add_argument("--dataset-code", action="append", dest="dataset_codes")
    parser.add_argument("--requested-by", default="rho5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--promotion-scope", choices=["canary", "full_market"], default="full_market")
    parser.add_argument("--monitor-scope", choices=["shadow", "post_promotion", "rollback_drill"], default=os.getenv("QDATA_RHO5_MONITOR_SCOPE", "post_promotion"))
    parser.add_argument("--no-applied-promotion-required", action="store_true", default=os.getenv("QDATA_RHO5_REQUIRE_APPLIED_PROMOTION", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--apply-rollback", action="store_true", default=os.getenv("QDATA_RHO5_APPLY_ROLLBACK", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--rollback-dry-run", action="store_true")
    parser.add_argument("--shadow-window-hours", type=int, default=int(os.getenv("QDATA_RHO5_SHADOW_WINDOW_HOURS", "24")))
    parser.add_argument("--max-conflict-rate-bps", type=float, default=float(os.getenv("QDATA_RHO5_MAX_CONFLICT_RATE_BPS", "5")))
    parser.add_argument("--max-failure-rate", type=float, default=float(os.getenv("QDATA_RHO5_MAX_FAILURE_RATE", "0.01")))
    parser.add_argument("--max-stale-minutes", type=int, default=int(os.getenv("QDATA_RHO5_MAX_STALE_MINUTES", "90")))
    parser.add_argument("--status", action="append")
    parser.add_argument("--monitor-code", action="append")
    parser.add_argument("--promotion-code", action="append")
    parser.add_argument("--result-code", action="append")
    parser.add_argument("--shadow-status", action="append")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        rows = run_post_promotion_monitor(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            dataset_codes=args.dataset_codes,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            promotion_scope=args.promotion_scope,
            monitor_scope=args.monitor_scope,
            require_applied_promotion=not args.no_applied_promotion_required,
            apply_rollback=args.apply_rollback,
            rollback_dry_run=args.rollback_dry_run,
            shadow_window_hours=args.shadow_window_hours,
            max_conflict_rate_bps=args.max_conflict_rate_bps,
            max_failure_rate=args.max_failure_rate,
            max_stale_minutes=args.max_stale_minutes,
        )
        resource = "run"
    else:
        params = _params(args)
        if args.resource == "runs":
            rows = list_vendor_post_promotion_monitors(args.postgres_dsn, params, args.limit, args.offset)
        else:
            rows = list_vendor_post_promotion_results(args.postgres_dsn, params, args.limit, args.offset)
        resource = args.resource

    if args.json:
        output_rows = rows if isinstance(rows, list) else [rows]
        print(json.dumps({"resource": f"rho5.{resource}", "row_count": len(output_rows), "rows": output_rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_rho5_rows(resource, rows))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for name in ("status", "monitor_code", "promotion_code", "result_code", "shadow_status"):
        values = getattr(args, name)
        if values:
            params[name] = values
    if args.source_code:
        params["source_code"] = [args.source_code]
    if args.primary_source_code:
        params["primary_source_code"] = [args.primary_source_code]
    if args.monitor_scope:
        params["monitor_scope"] = [args.monitor_scope]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
