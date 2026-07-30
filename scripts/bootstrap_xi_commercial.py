#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.xi_billing import bootstrap_xi_commercial_catalog, evaluate_budget_policies, format_budget_evaluations


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Xi product catalog, pricing plan, subscription and budget.")
    parser.add_argument("--tenant-code", default=os.getenv("QDATA_XI_TENANT_CODE", "demo"))
    parser.add_argument("--tenant-name", default="Demo Tenant")
    parser.add_argument("--project-code", default=os.getenv("QDATA_XI_PROJECT_CODE", "quant-research"))
    parser.add_argument("--project-name", default="Quant Research")
    parser.add_argument("--principal-code", default="research-bot")
    parser.add_argument("--principal-name", default="Research Bot")
    parser.add_argument("--token", default="iotatoken")
    parser.add_argument("--token-name", default="Iota Demo Token")
    parser.add_argument("--cost-center", default=os.getenv("QDATA_XI_COST_CENTER", "research"))
    parser.add_argument("--budget-amount", default=os.getenv("QDATA_XI_MONTHLY_BUDGET_AMOUNT", "0.15"))
    parser.add_argument("--hard-limit", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--write-alerts", action="store_true")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    result = bootstrap_xi_commercial_catalog(
        args.postgres_dsn,
        tenant_code=args.tenant_code,
        tenant_name=args.tenant_name,
        project_code=args.project_code,
        project_name=args.project_name,
        principal_code=args.principal_code,
        principal_name=args.principal_name,
        token=args.token,
        token_name=args.token_name,
        cost_center=args.cost_center,
        budget_amount=args.budget_amount,
        hard_limit_enabled=args.hard_limit,
    )
    evaluations = []
    if args.evaluate:
        evaluations = evaluate_budget_policies(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            budget_code=f"{args.tenant_code}_{args.project_code}_monthly_budget",
            write_db=True,
            write_alerts=args.write_alerts,
        )
    if args.json:
        print(json.dumps({"bootstrap": result, "evaluations": evaluations}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            "xi_bootstrap "
            f"product={result['product']['product_code']} plan={result['plan']['plan_code']} "
            f"subscription={result['subscription']['subscription_code']} budget={result['budget']['budget_code']}"
        )
        if evaluations:
            print(format_budget_evaluations(evaluations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
