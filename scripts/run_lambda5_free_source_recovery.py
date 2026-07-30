#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.lambda5_free_source_recovery import (
    format_lambda5_rows,
    list_free_source_recovery_actions,
    list_free_source_recovery_runs,
    run_free_source_recovery,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Lambda-5 free source recovery orchestration.")
    parser.add_argument("--resource", choices=("recover", "runs", "actions"), default="recover")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--source-codes", default="")
    parser.add_argument("--dataset-codes", default="")
    parser.add_argument("--requested-by", default="lambda5")
    parser.add_argument("--trigger-mode", choices=("manual", "scheduled", "once", "smoke", "api"), default="")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-actions", type=int, default=50)
    parser.add_argument("--min-retry-score", type=float, default=75.0)
    parser.add_argument("--no-alerts", action="store_true")
    parser.add_argument("--no-write-db", action="store_true")
    parser.add_argument("--recovery-code", default="")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--action-type", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--reason-code", default="")
    parser.add_argument("--recommended-role", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "recover":
        row = run_free_source_recovery(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            lookback_hours=args.lookback_hours,
            source_codes=_csv(args.source_codes),
            dataset_codes=_csv(args.dataset_codes),
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode or "manual",
            environment=args.environment,
            dry_run=args.dry_run,
            max_actions=args.max_actions,
            min_retry_score=args.min_retry_score,
            write_alerts=not args.no_alerts,
            write_db=not args.no_write_db,
        )
        rows = [row]
    elif args.resource == "runs":
        rows = list_free_source_recovery_runs(args.postgres_dsn, _params(args), args.limit, args.offset)
    else:
        rows = list_free_source_recovery_actions(args.postgres_dsn, _params(args), args.limit, args.offset)

    if args.json:
        print(json.dumps({"resource": args.resource, "row_count": len(rows), "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_lambda5_rows(args.resource, rows))
    return 0


def _csv(value: str) -> list[str] | None:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "recovery_code",
        "action_code",
        "source_code",
        "dataset_code",
        "status",
        "action_type",
        "severity",
        "reason_code",
        "recommended_role",
        "requested_by",
        "trigger_mode",
        "environment",
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
