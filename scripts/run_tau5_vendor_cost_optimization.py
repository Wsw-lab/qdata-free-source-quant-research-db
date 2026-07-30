#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.tau5_vendor_cost_optimization import (
    format_tau5_rows,
    list_vendor_budget_stress_snapshots,
    list_vendor_cost_optimizations,
    list_vendor_route_weight_plans,
    run_vendor_cost_optimizer,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Tau-5 vendor cost optimization, route weight and budget stress snapshots.")
    parser.add_argument("--resource", choices=["run", "optimizations", "plans", "stress"], default="run")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--dataset-code", action="append", default=[])
    parser.add_argument("--requested-by", default="tau5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default=os.getenv("QDATA_ENVIRONMENT", "local"))
    parser.add_argument("--optimization-scope", choices=["primary_source", "all_datasets", "full_market"], default=os.getenv("QDATA_TAU5_OPTIMIZATION_SCOPE", "primary_source"))
    parser.add_argument("--lookback-hours", type=int, default=int(os.getenv("QDATA_TAU5_LOOKBACK_HOURS", "24")))
    parser.add_argument("--forecast-window-days", type=int, default=int(os.getenv("QDATA_TAU5_FORECAST_WINDOW_DAYS", "30")))
    parser.add_argument("--monthly-budget-amount", type=float, default=float(os.getenv("QDATA_TAU5_MONTHLY_BUDGET_AMOUNT", "10000")))
    parser.add_argument("--max-budget-usage-pct", type=float, default=float(os.getenv("QDATA_TAU5_MAX_BUDGET_USAGE_PCT", "0.85")))
    parser.add_argument("--max-daily-quota-usage-pct", type=float, default=float(os.getenv("QDATA_TAU5_MAX_DAILY_QUOTA_USAGE_PCT", "0.85")))
    parser.add_argument("--max-monthly-quota-usage-pct", type=float, default=float(os.getenv("QDATA_TAU5_MAX_MONTHLY_QUOTA_USAGE_PCT", "0.85")))
    parser.add_argument("--min-stability-score", type=float, default=float(os.getenv("QDATA_TAU5_MIN_STABILITY_SCORE", "70")))
    parser.add_argument("--cost-safety-margin-pct", type=float, default=float(os.getenv("QDATA_TAU5_COST_SAFETY_MARGIN_PCT", "0.15")))
    parser.add_argument("--default-unit-cost", type=float, default=float(os.getenv("QDATA_TAU5_DEFAULT_UNIT_COST", "0.01")))
    parser.add_argument("--stress-multiplier", type=float, action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--optimization-code", default="")
    parser.add_argument("--plan-code", default="")
    parser.add_argument("--stress-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--optimization-role", default="")
    parser.add_argument("--plan-role", default="")
    parser.add_argument("--recommended-action", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        row = run_vendor_cost_optimizer(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            dataset_codes=args.dataset_code or None,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            optimization_scope=args.optimization_scope,
            lookback_hours=args.lookback_hours,
            forecast_window_days=args.forecast_window_days,
            monthly_budget_amount=args.monthly_budget_amount,
            max_budget_usage_pct=args.max_budget_usage_pct,
            max_daily_quota_usage_pct=args.max_daily_quota_usage_pct,
            max_monthly_quota_usage_pct=args.max_monthly_quota_usage_pct,
            min_stability_score=args.min_stability_score,
            cost_safety_margin_pct=args.cost_safety_margin_pct,
            default_unit_cost=args.default_unit_cost,
            stress_multipliers=args.stress_multiplier or None,
            write_db=not args.dry_run,
        )
        rows = row
    else:
        params: dict[str, list[str]] = {}
        for key, value in [
            ("optimization_code", args.optimization_code),
            ("plan_code", args.plan_code),
            ("stress_code", args.stress_code),
            ("source_code", args.source_code),
            ("primary_source_code", args.primary_source_code),
            ("status", args.status),
            ("optimization_role", args.optimization_role),
            ("plan_role", args.plan_role),
            ("optimization_scope", args.optimization_scope),
            ("recommended_action", args.recommended_action),
        ]:
            if value:
                params[key] = [value]
        if args.resource == "optimizations":
            rows = list_vendor_cost_optimizations(args.postgres_dsn, params, args.limit, args.offset)
        elif args.resource == "plans":
            rows = list_vendor_route_weight_plans(args.postgres_dsn, params, args.limit, args.offset)
        else:
            rows = list_vendor_budget_stress_snapshots(args.postgres_dsn, params, args.limit, args.offset)
    output_rows = rows.get("route_plans") if isinstance(rows, dict) and args.resource == "plans" else rows.get("stress_snapshots") if isinstance(rows, dict) and args.resource == "stress" else rows
    row_count = len(output_rows) if isinstance(output_rows, list) else 1
    if args.json:
        print(json.dumps({"resource": f"tau5.{args.resource}", "row_count": row_count, "rows": output_rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_tau5_rows(args.resource, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
