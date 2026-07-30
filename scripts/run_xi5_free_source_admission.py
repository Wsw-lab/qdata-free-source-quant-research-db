#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.xi5_free_source_admission import (
    format_xi5_rows,
    list_free_source_admission_profiles,
    list_free_source_admission_snapshots,
    run_free_source_admission_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Xi-5 free source admission matrix review.")
    parser.add_argument("--resource", choices=["review", "snapshots", "profiles"], default="review")
    parser.add_argument("--requested-by", default="xi5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--lookback-days", type=int, default=int(os.getenv("QDATA_XI5_FREE_SOURCE_LOOKBACK_DAYS", "30")))
    parser.add_argument("--source-code", action="append", default=[])
    parser.add_argument("--dataset-code", action="append", default=[])
    parser.add_argument("--min-validator-score", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_VALIDATOR_SCORE", "55")))
    parser.add_argument("--min-backup-score", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_BACKUP_SCORE", "75")))
    parser.add_argument("--min-primary-score", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_PRIMARY_SCORE", "90")))
    parser.add_argument("--min-coverage-rate", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_COVERAGE_RATE", "0.95")))
    parser.add_argument("--max-conflict-rate-bps", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MAX_CONFLICT_RATE_BPS", "5")))
    parser.add_argument("--dry-run", action="store_true", help="Evaluate admission without writing snapshots.")
    parser.add_argument("--status", default="")
    parser.add_argument("--admission-role", default="")
    parser.add_argument("--license-status", default="")
    parser.add_argument("--commercial-clearance", default="")
    parser.add_argument("--redistribution-allowed", default="")
    parser.add_argument("--contract-status", default="")
    parser.add_argument("--terms-review-status", default="")
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "review":
        rows = run_free_source_admission_review(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            lookback_days=args.lookback_days,
            source_codes=args.source_code or None,
            dataset_codes=args.dataset_code or None,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            min_validator_score=args.min_validator_score,
            min_backup_score=args.min_backup_score,
            min_primary_score=args.min_primary_score,
            min_coverage_rate=args.min_coverage_rate,
            max_conflict_rate_bps=args.max_conflict_rate_bps,
            write_db=not args.dry_run,
        )
        counts = _counts(rows)
        if args.json:
            print(json.dumps({"resource": "review", "counts": counts, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
        else:
            print(
                "xi5_free_source_admission "
                f"snapshots={len(rows)} approved={counts['approved']} conditional={counts['conditional']} "
                f"review_required={counts['review_required']} blocked={counts['blocked']} no_data={counts['no_data']} "
                f"primary_candidate={counts['primary_candidate']}"
            )
        return 0

    params = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for key, value in {
        "status": args.status,
        "admission_role": args.admission_role,
        "license_status": args.license_status,
        "commercial_clearance": args.commercial_clearance,
        "redistribution_allowed": args.redistribution_allowed,
        "contract_status": args.contract_status,
        "terms_review_status": args.terms_review_status,
        "snapshot_code": args.snapshot_code,
        "environment": args.environment,
    }.items():
        if value:
            params[key] = [value]
    if args.source_code:
        params["source_code"] = [args.source_code[-1]]
    if args.dataset_code:
        params["dataset_code"] = [args.dataset_code[-1]]
    if args.as_of_date:
        params["as_of_date"] = [args.as_of_date]

    if args.resource == "profiles":
        rows = list_free_source_admission_profiles(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_free_source_admission_snapshots(args.postgres_dsn, params, args.limit, args.offset)
    if args.json:
        print(json.dumps({"resource": args.resource, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_xi5_rows(args.resource, rows))
    return 0


def _counts(rows: list[dict]) -> dict[str, int]:
    return {
        "approved": sum(1 for row in rows if row.get("status") == "approved"),
        "conditional": sum(1 for row in rows if row.get("status") == "conditional"),
        "review_required": sum(1 for row in rows if row.get("status") == "review_required"),
        "blocked": sum(1 for row in rows if row.get("status") == "blocked"),
        "no_data": sum(1 for row in rows if row.get("status") == "no_data"),
        "primary_candidate": sum(1 for row in rows if row.get("admission_role") == "primary_candidate"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
