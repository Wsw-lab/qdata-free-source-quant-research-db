#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.upsilon5_route_weight_execution import (
    format_upsilon5_rows,
    list_source_route_weight_policies,
    list_vendor_route_weight_execution_datasets,
    list_vendor_route_weight_executions,
    list_vendor_route_weight_rollout_stages,
    run_vendor_route_weight_execution,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Upsilon-5 route-weight execution, rollout stages and source route policies.")
    parser.add_argument("--resource", choices=["run", "executions", "datasets", "stages", "policies"], default="run")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--dataset-code", action="append", default=[])
    parser.add_argument("--requested-by", default="upsilon5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default=os.getenv("QDATA_ENVIRONMENT", "local"))
    parser.add_argument("--execution-scope", choices=["primary_source", "all_datasets", "full_market"], default=os.getenv("QDATA_UPSILON5_EXECUTION_SCOPE", "primary_source"))
    parser.add_argument("--execution-mode", choices=["review_only", "dry_run", "apply"], default=os.getenv("QDATA_UPSILON5_EXECUTION_MODE", "review_only"))
    parser.add_argument("--approval-policy", choices=["manual_required", "auto_if_optimized"], default=os.getenv("QDATA_UPSILON5_APPROVAL_POLICY", "manual_required"))
    parser.add_argument("--approval-status", choices=["not_required", "pending", "approved", "rejected", "blocked"], default=os.getenv("QDATA_UPSILON5_APPROVAL_STATUS", "pending"))
    parser.add_argument("--rollout-policy", choices=["review_only", "canary", "gradual", "full"], default=os.getenv("QDATA_UPSILON5_ROLLOUT_POLICY", "gradual"))
    parser.add_argument("--rollout-stage", type=float, action="append", default=[])
    parser.add_argument("--current-stage-sequence", type=int, default=int(os.getenv("QDATA_UPSILON5_CURRENT_STAGE_SEQUENCE", "1")))
    parser.add_argument("--max-initial-primary-weight-pct", type=float, default=float(os.getenv("QDATA_UPSILON5_MAX_INITIAL_PRIMARY_WEIGHT_PCT", "10")))
    parser.add_argument("--allow-over-budget", action="store_true", default=os.getenv("QDATA_UPSILON5_ALLOW_OVER_BUDGET", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--allow-quota-risk", action="store_true", default=os.getenv("QDATA_UPSILON5_ALLOW_QUOTA_RISK", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--rollback-requested", action="store_true", default=os.getenv("QDATA_UPSILON5_ROLLBACK_REQUESTED", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--execution-code", default="")
    parser.add_argument("--execution-dataset-code", default="")
    parser.add_argument("--stage-code", default="")
    parser.add_argument("--policy-code", default="")
    parser.add_argument("--optimization-code", default="")
    parser.add_argument("--plan-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--policy-status", default="")
    parser.add_argument("--stage-sequence", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        rows = run_vendor_route_weight_execution(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            dataset_codes=args.dataset_code or None,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            execution_scope=args.execution_scope,
            execution_mode=args.execution_mode,
            approval_policy=args.approval_policy,
            approval_status=args.approval_status,
            rollout_policy=args.rollout_policy,
            rollout_stages=args.rollout_stage or None,
            current_stage_sequence=args.current_stage_sequence,
            max_initial_primary_weight_pct=args.max_initial_primary_weight_pct,
            allow_over_budget=args.allow_over_budget,
            allow_quota_risk=args.allow_quota_risk,
            rollback_requested=args.rollback_requested,
            write_db=not args.dry_run,
        )
    else:
        provided_options = _provided_options(sys.argv[1:])
        params: dict[str, list[str]] = {}
        for option, key, value in [
            ("--execution-code", "execution_code", args.execution_code),
            ("--execution-dataset-code", "execution_dataset_code", args.execution_dataset_code),
            ("--stage-code", "stage_code", args.stage_code),
            ("--policy-code", "policy_code", args.policy_code),
            ("--optimization-code", "optimization_code", args.optimization_code),
            ("--plan-code", "plan_code", args.plan_code),
            ("--source-code", "source_code", args.source_code),
            ("--primary-source-code", "primary_source_code", args.primary_source_code),
            ("--status", "status", args.status),
            ("--approval-status", "approval_status", args.approval_status),
            ("--execution-mode", "execution_mode", args.execution_mode),
            ("--execution-scope", "execution_scope", args.execution_scope),
            ("--rollout-policy", "rollout_policy", args.rollout_policy),
            ("--policy-status", "policy_status", args.policy_status),
            ("--stage-sequence", "stage_sequence", args.stage_sequence),
        ]:
            if value and option in provided_options:
                params[key] = [value]
        if args.resource == "executions":
            rows = list_vendor_route_weight_executions(args.postgres_dsn, params, args.limit, args.offset)
        elif args.resource == "datasets":
            rows = list_vendor_route_weight_execution_datasets(args.postgres_dsn, params, args.limit, args.offset)
        elif args.resource == "stages":
            rows = list_vendor_route_weight_rollout_stages(args.postgres_dsn, params, args.limit, args.offset)
        else:
            rows = list_source_route_weight_policies(args.postgres_dsn, params, args.limit, args.offset)
    output_rows = (
        rows.get("datasets")
        if isinstance(rows, dict) and args.resource == "datasets"
        else rows.get("stages")
        if isinstance(rows, dict) and args.resource == "stages"
        else rows.get("policies")
        if isinstance(rows, dict) and args.resource == "policies"
        else rows
    )
    row_count = len(output_rows) if isinstance(output_rows, list) else 1
    if args.json:
        print(json.dumps({"resource": f"upsilon5.{args.resource}", "row_count": row_count, "rows": output_rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_upsilon5_rows(args.resource, rows))
    return 0


def _provided_options(argv: list[str]) -> set[str]:
    return {item.split("=", 1)[0] for item in argv if item.startswith("--")}


if __name__ == "__main__":
    raise SystemExit(main())
