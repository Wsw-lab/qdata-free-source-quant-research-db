#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa import dispatch_kappa_endpoint, format_kappa_report
from qdata.xi_billing import evaluate_budget_policies, format_budget_evaluations


RESOURCE_PATHS = {
    "products": "/admin/data-products",
    "pricing-plans": "/admin/pricing-plans",
    "pricing-rules": "/admin/pricing-rules",
    "subscriptions": "/admin/product-subscriptions",
    "budget-policies": "/admin/budget-policies",
    "budget-usage": "/admin/budget-usage",
    "budget-alerts": "/admin/budget-alerts",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Xi product catalog, pricing and budget resources.")
    parser.add_argument("--resource", choices=sorted([*RESOURCE_PATHS, "evaluate-budgets"]), default="products")
    parser.add_argument("--product-code", default="")
    parser.add_argument("--plan-code", default="")
    parser.add_argument("--subscription-code", default="")
    parser.add_argument("--budget-code", default="")
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--principal-code", default="")
    parser.add_argument("--cost-center", default="")
    parser.add_argument("--api-name", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--write-alerts", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "evaluate-budgets":
        rows = evaluate_budget_policies(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            budget_code=args.budget_code or None,
            write_db=args.write_db,
            write_alerts=args.write_alerts,
        )
        if args.json:
            print(json.dumps({"resource": "xi.budget-evaluation", "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
        else:
            print(format_budget_evaluations(rows))
        return 0

    params = _params(args)
    result = dispatch_kappa_endpoint(args.postgres_dsn, RESOURCE_PATHS[args.resource], params)
    if args.json:
        print(json.dumps({"resource": result.resource, "meta": result.meta, "data": result.rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_kappa_report(result))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "product_code",
        "plan_code",
        "subscription_code",
        "budget_code",
        "tenant_code",
        "project_code",
        "principal_code",
        "cost_center",
        "api_name",
        "status",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
