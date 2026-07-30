#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa import dispatch_kappa_endpoint, format_kappa_report
from qdata.rho_revenue import (
    format_ar_aging_report,
    format_customer_health_report,
    format_reconciliation_report,
    generate_ar_aging_snapshots,
    generate_customer_health_snapshots,
    reconcile_revenue,
)


RESOURCE_PATHS = {
    "reconciliation": "/admin/revenue-reconciliation",
    "reconciliation-lines": "/admin/revenue-reconciliation-lines",
    "ar-aging": "/admin/ar-aging",
    "customer-health": "/admin/customer-health",
}


GENERATE_RESOURCES = {"generate-reconciliation", "generate-ar-aging", "generate-customer-health", "generate-all"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and report Rho revenue reconciliation resources.")
    parser.add_argument(
        "--resource",
        choices=sorted(set(RESOURCE_PATHS) | GENERATE_RESOURCES),
        default="generate-all",
    )
    parser.add_argument("--period-start", default="")
    parser.add_argument("--period-end", default="")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--reconciliation-date", default="")
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--product-code", default="")
    parser.add_argument("--plan-code", default="")
    parser.add_argument("--subscription-code", default="")
    parser.add_argument("--reconciliation-code", default="")
    parser.add_argument("--invoice-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--tolerance-amount", default="0.00000001")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource in GENERATE_RESOURCES:
        payload = _generate(args)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
        else:
            print(_format_generated(payload))
        return 0

    result = dispatch_kappa_endpoint(args.postgres_dsn, RESOURCE_PATHS[args.resource], _params(args))
    if args.json:
        print(json.dumps({"resource": result.resource, "meta": result.meta, "data": result.rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_kappa_report(result))
    return 0


def _generate(args: argparse.Namespace) -> dict[str, object]:
    write_db = not args.dry_run
    payload: dict[str, object] = {"meta": {"dry_run": args.dry_run}, "data": {}}
    if args.resource in {"generate-reconciliation", "generate-all"}:
        if not args.period_start or not args.period_end:
            raise SystemExit("--period-start and --period-end are required for reconciliation")
        rows = reconcile_revenue(
            args.postgres_dsn,
            period_start=args.period_start,
            period_end=args.period_end,
            tenant_code=args.tenant_code or None,
            project_code=args.project_code or None,
            subscription_code=args.subscription_code or None,
            reconciliation_date=args.reconciliation_date or args.as_of_date or None,
            tolerance_amount=args.tolerance_amount,
            write_db=write_db,
        )
        payload["data"]["reconciliation"] = rows
    if args.resource in {"generate-ar-aging", "generate-all"}:
        if not args.as_of_date:
            raise SystemExit("--as-of-date is required for AR aging")
        rows = generate_ar_aging_snapshots(
            args.postgres_dsn,
            as_of_date=args.as_of_date,
            tenant_code=args.tenant_code or None,
            project_code=args.project_code or None,
            product_code=args.product_code or None,
            plan_code=args.plan_code or None,
            start_date=args.period_start or None,
            end_date=args.period_end or None,
            write_db=write_db,
        )
        payload["data"]["ar_aging"] = rows
    if args.resource in {"generate-customer-health", "generate-all"}:
        if not args.as_of_date:
            raise SystemExit("--as-of-date is required for customer health")
        rows = generate_customer_health_snapshots(
            args.postgres_dsn,
            as_of_date=args.as_of_date,
            tenant_code=args.tenant_code or None,
            project_code=args.project_code or None,
            product_code=args.product_code or None,
            subscription_code=args.subscription_code or None,
            write_db=write_db,
        )
        payload["data"]["customer_health"] = rows
    payload["meta"]["row_count"] = sum(len(rows) for rows in payload["data"].values())
    return payload


def _format_generated(payload: dict[str, object]) -> str:
    data = payload.get("data") or {}
    sections: list[str] = []
    if data.get("reconciliation") is not None:
        sections.append(format_reconciliation_report(data["reconciliation"]))
    if data.get("ar_aging") is not None:
        sections.append(format_ar_aging_report(data["ar_aging"]))
    if data.get("customer_health") is not None:
        sections.append(format_customer_health_report(data["customer_health"]))
    return "\n".join(sections)


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "tenant_code",
        "project_code",
        "product_code",
        "plan_code",
        "subscription_code",
        "reconciliation_code",
        "invoice_code",
        "status",
        "period_start",
        "period_end",
        "as_of_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
