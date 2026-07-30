#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa5_free_source_reliability import (
    format_kappa5_rows,
    list_free_source_reliability_snapshots,
    score_free_source_reliability,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Kappa-5 free source reliability scoring.")
    parser.add_argument("--resource", choices=("score", "snapshots"), default="score")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--source-codes", default="")
    parser.add_argument("--dataset-codes", default="")
    parser.add_argument("--requested-by", default="kappa5")
    parser.add_argument("--trigger-mode", default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--recommended-role", default="")
    parser.add_argument("--license-status", default="")
    parser.add_argument("--commercial-clearance", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "score":
        rows = score_free_source_reliability(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            lookback_hours=args.lookback_hours,
            source_codes=_csv(args.source_codes),
            dataset_codes=_csv(args.dataset_codes),
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
        )
    else:
        rows = list_free_source_reliability_snapshots(args.postgres_dsn, _params(args), args.limit, args.offset)

    if args.json:
        print(json.dumps({"resource": args.resource, "row_count": len(rows), "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_kappa5_rows(args.resource, rows))
    return 0


def _csv(value: str) -> list[str] | None:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "snapshot_code",
        "source_code",
        "dataset_code",
        "status",
        "recommended_role",
        "license_status",
        "commercial_clearance",
        "as_of_date",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [str(value)]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
