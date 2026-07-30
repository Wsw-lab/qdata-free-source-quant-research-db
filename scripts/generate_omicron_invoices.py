#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.omicron_billing import format_invoice_report, generate_invoices


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Omicron invoices from Xi subscriptions and Iota usage.")
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--subscription-code", default="")
    parser.add_argument("--invoice-date", default="")
    parser.add_argument("--due-days", type=int, default=15)
    parser.add_argument("--status", choices=["draft", "issued"], default="issued")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    rows = generate_invoices(
        args.postgres_dsn,
        period_start=args.period_start,
        period_end=args.period_end,
        tenant_code=args.tenant_code or None,
        project_code=args.project_code or None,
        subscription_code=args.subscription_code or None,
        invoice_date=args.invoice_date or None,
        due_days=args.due_days,
        status=args.status,
        write_db=not args.dry_run,
    )
    if args.json:
        print(json.dumps({"data": rows, "meta": {"row_count": len(rows), "dry_run": args.dry_run}}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_invoice_report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
