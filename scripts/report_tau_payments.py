#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa import dispatch_kappa_endpoint, format_kappa_report
from qdata.tau_payments import (
    bootstrap_tau_demo,
    format_payment_import,
    format_payment_matches,
    format_tau_demo_report,
    import_payment_records,
    load_payment_csv,
    match_payments,
)


RESOURCE_PATHS = {
    "payment-batches": "/admin/payment-batches",
    "payments": "/admin/payments",
    "payment-matches": "/admin/payment-matches",
    "revenue-ledger": "/admin/revenue-ledger",
    "fx-rates": "/admin/fx-rates",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import, match and report Tau payment records.")
    parser.add_argument(
        "--resource",
        choices=sorted(["bootstrap-demo", "import-csv", "match", *RESOURCE_PATHS]),
        default="bootstrap-demo",
    )
    parser.add_argument("--csv-path", default="")
    parser.add_argument("--batch-code", default="")
    parser.add_argument("--source-type", default="manual_csv")
    parser.add_argument("--account-code", default="")
    parser.add_argument("--statement-start", default="")
    parser.add_argument("--statement-end", default="")
    parser.add_argument("--currency", default="CNY")
    parser.add_argument("--base-currency", default="CNY")
    parser.add_argument("--provider", default="manual")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--amount", default="100.00000000")
    parser.add_argument("--transaction-code", default="")
    parser.add_argument("--invoice-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--payment-channel", default="")
    parser.add_argument("--entry-type", default="")
    parser.add_argument("--from-currency", default="")
    parser.add_argument("--to-currency", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    write_db = not args.dry_run
    if args.resource == "bootstrap-demo":
        payload = bootstrap_tau_demo(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            tenant_code=args.tenant_code or "demo",
            project_code=args.project_code or "quant-research",
            amount=args.amount,
            write_db=write_db,
        )
        _emit(payload, format_tau_demo_report(payload), args.json)
        return 0
    if args.resource == "import-csv":
        if not args.csv_path or not args.batch_code:
            parser.error("--csv-path and --batch-code are required for import-csv")
        payload = import_payment_records(
            args.postgres_dsn,
            load_payment_csv(args.csv_path),
            batch_code=args.batch_code,
            source_type=args.source_type,
            account_code=args.account_code or None,
            statement_start=args.statement_start or None,
            statement_end=args.statement_end or None,
            currency=args.currency,
            base_currency=args.base_currency,
            provider=args.provider,
            write_db=write_db,
        )
        _emit(payload, format_payment_import(payload), args.json)
        return 0
    if args.resource == "match":
        rows = match_payments(
            args.postgres_dsn,
            batch_code=args.batch_code or None,
            transaction_code=args.transaction_code or None,
            write_db=write_db,
        )
        _emit(rows, format_payment_matches(rows), args.json)
        return 0

    result = dispatch_kappa_endpoint(args.postgres_dsn, RESOURCE_PATHS[args.resource], _params(args))
    if args.json:
        print(json.dumps({"resource": result.resource, "meta": result.meta, "data": result.rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_kappa_report(result))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "batch_code",
        "transaction_code",
        "invoice_code",
        "tenant_code",
        "project_code",
        "status",
        "currency",
        "payment_channel",
        "entry_type",
        "from_currency",
        "to_currency",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


def _emit(payload, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
