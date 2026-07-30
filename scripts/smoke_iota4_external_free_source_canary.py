#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.exceptions import QDataValidationError
from qdata.iota4_external_free_source_canary import (
    DEFAULT_IOTA4_DATASETS,
    default_min_source_count,
    default_source_codes,
    format_iota4_canary,
    run_external_free_source_canary,
)
from qdata.iota3_free_source_fabric import DEFAULT_CANARY_SYMBOLS


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Iota-4 external free source canary.")
    parser.add_argument("--mode", choices=["live-only", "compare-local"], default="live-only")
    parser.add_argument("--source-codes", default="")
    parser.add_argument("--dataset-codes", default=",".join(DEFAULT_IOTA4_DATASETS))
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--canary-symbols", default=",".join(DEFAULT_CANARY_SYMBOLS))
    parser.add_argument("--min-source-count", type=int, default=None)
    parser.add_argument("--min-coverage-rate", type=float, default=0.95)
    parser.add_argument("--max-conflict-rate-bps", type=float, default=100000.0)
    parser.add_argument("--require-commercial-clearance", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    source_codes = _csv(args.source_codes) if args.source_codes else default_source_codes(args.mode)
    min_source_count = args.min_source_count if args.min_source_count is not None else default_min_source_count(args.mode)
    try:
        row = run_external_free_source_canary(
            args.postgres_dsn,
            mode=args.mode,
            source_codes=source_codes,
            dataset_codes=_csv(args.dataset_codes),
            start_date=args.start_date,
            end_date=args.end_date,
            canary_symbols=_csv(args.canary_symbols),
            min_source_count=min_source_count,
            min_coverage_rate=args.min_coverage_rate,
            max_conflict_rate_bps=args.max_conflict_rate_bps,
            require_commercial_clearance=args.require_commercial_clearance,
        )
    except (QDataValidationError, ValueError) as exc:
        print(f"iota4_external_free_source_canary=failed reason={exc}")
        return 1

    if args.json:
        print(json.dumps({"resource": "iota4.external-free-source-canary", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_iota4_canary(row))
    return 0 if row.get("iota4_canary_status") == "ok" else 1


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
