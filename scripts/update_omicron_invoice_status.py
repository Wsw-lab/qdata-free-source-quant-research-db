#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.omicron_billing import mark_invoice_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Update an Omicron invoice payment or lifecycle status.")
    parser.add_argument("--invoice-code", required=True)
    parser.add_argument("--status", choices=["draft", "issued", "partially_paid", "paid", "overdue", "void"], required=True)
    parser.add_argument("--paid-amount", default=None)
    parser.add_argument("--message", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    row = mark_invoice_status(
        args.postgres_dsn,
        invoice_code=args.invoice_code,
        status=args.status,
        paid_amount=args.paid_amount,
        event_message=args.message or None,
    )
    if args.json:
        print(json.dumps({"data": row}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            " ".join(
                [
                    f"invoice={row.get('invoice_code')}",
                    f"status={row.get('status')}",
                    f"total={row.get('total_amount')}",
                    f"paid={row.get('paid_amount')}",
                    f"outstanding={row.get('outstanding_amount')}",
                ]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
