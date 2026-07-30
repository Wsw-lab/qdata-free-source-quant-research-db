#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.exceptions import QDataValidationError
from qdata.iota3_free_source_fabric import DEFAULT_CANARY_SYMBOLS
from qdata.iota5_free_source_adapter_pool import (
    DEFAULT_IOTA5_DATASETS,
    DEFAULT_IOTA5_SOURCE_CODES,
    format_iota5_pool,
    run_free_source_adapter_pool,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Iota-5 free source adapter pool.")
    parser.add_argument("--source-codes", default=",".join(DEFAULT_IOTA5_SOURCE_CODES))
    parser.add_argument("--dataset-codes", default=",".join(DEFAULT_IOTA5_DATASETS))
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--canary-symbols", default=",".join(DEFAULT_CANARY_SYMBOLS))
    parser.add_argument("--min-source-count", type=int, default=2)
    parser.add_argument("--min-external-successful", type=int, default=2)
    parser.add_argument("--min-coverage-rate", type=float, default=0.95)
    parser.add_argument("--max-conflict-rate-bps", type=float, default=100000.0)
    parser.add_argument("--baostock-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--tushare-token", default="")
    parser.add_argument("--require-commercial-clearance", action="store_true")
    parser.add_argument("--require-ok", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        row = run_free_source_adapter_pool(
            args.postgres_dsn,
            source_codes=_csv(args.source_codes),
            dataset_codes=_csv(args.dataset_codes),
            start_date=args.start_date,
            end_date=args.end_date,
            canary_symbols=_csv(args.canary_symbols),
            min_source_count=args.min_source_count,
            min_external_successful=args.min_external_successful,
            min_coverage_rate=args.min_coverage_rate,
            max_conflict_rate_bps=args.max_conflict_rate_bps,
            require_commercial_clearance=args.require_commercial_clearance,
            provider_kwargs_by_source=_provider_kwargs(args),
        )
    except QDataValidationError as exc:
        print(f"iota5_free_source_adapter_pool=failed reason={exc}")
        return 1

    if args.json:
        print(json.dumps({"resource": "iota5.free-source-adapter-pool", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_iota5_pool(row))
    if row.get("iota5_pool_status") == "ok":
        return 0
    if row.get("iota5_pool_status") == "degraded" and not args.require_ok:
        return 0
    return 1


def _provider_kwargs(args: argparse.Namespace) -> dict[str, dict]:
    kwargs: dict[str, dict] = {"baostock": {"timeout_seconds": args.baostock_timeout_seconds}}
    if args.tushare_token:
        kwargs["tushare_free"] = {"token": args.tushare_token}
    return kwargs


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
