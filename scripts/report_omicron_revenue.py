#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa import dispatch_kappa_endpoint, format_kappa_report


RESOURCE_PATHS = {
    "invoices": "/admin/invoices",
    "invoice-lines": "/admin/invoice-lines",
    "invoice-events": "/admin/invoice-events",
    "revenue-summary": "/admin/revenue-summary",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Omicron invoices and revenue through Kappa read-only endpoints.")
    parser.add_argument("--resource", choices=sorted(RESOURCE_PATHS), default="invoices")
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--product-code", default="")
    parser.add_argument("--plan-code", default="")
    parser.add_argument("--subscription-code", default="")
    parser.add_argument("--invoice-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--metric-name", default="")
    parser.add_argument("--api-name", default="")
    parser.add_argument("--event-type", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

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
        "tenant_code",
        "project_code",
        "product_code",
        "plan_code",
        "subscription_code",
        "invoice_code",
        "status",
        "metric_name",
        "api_name",
        "event_type",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
