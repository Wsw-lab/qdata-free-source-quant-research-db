#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.exceptions import QDataValidationError
from qdata.iota3_free_source_fabric import (
    DEFAULT_CANARY_SYMBOLS,
    DEFAULT_DATASETS,
    DEFAULT_SOURCE_CODES,
    run_free_source_fabric,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Iota-3 free source fabric.")
    parser.add_argument("--source-codes", default=",".join(DEFAULT_SOURCE_CODES))
    parser.add_argument("--dataset-codes", default=",".join(DEFAULT_DATASETS))
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--canary-symbols", default=",".join(DEFAULT_CANARY_SYMBOLS))
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--require-external", action="store_true")
    parser.add_argument("--require-commercial-clearance", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    try:
        row = run_free_source_fabric(
            args.postgres_dsn,
            source_codes=_csv(args.source_codes),
            dataset_codes=_csv(args.dataset_codes),
            start_date=args.start_date,
            end_date=args.end_date,
            canary_symbols=_csv(args.canary_symbols),
            requested_by="iota3",
            trigger_mode="smoke",
            environment="local",
            allow_external=args.allow_external,
            require_external=args.require_external,
            require_commercial_clearance=args.require_commercial_clearance,
        )
    except QDataValidationError as exc:
        print(f"iota3_free_source_fabric_smoke=failed reason={exc}")
        return 1
    print(
        " ".join(
            [
                "iota3_free_source_fabric_smoke=ok",
                f"status={row.get('status')}",
                f"fabric_code={row.get('fabric_code')}",
                f"dataset_count={row.get('dataset_result_count')}",
                f"source_count={row.get('source_count')}",
                f"usable_source_count={row.get('usable_source_count')}",
                f"coverage_rate={row.get('coverage_rate')}",
                f"conflict_rate_bps={row.get('conflict_rate_bps')}",
                f"allow_external={row.get('allow_external')}",
                f"require_external={row.get('require_external')}",
            ]
        )
    )
    return 0


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
