#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.omicron5_vendor_contract import (
    format_omicron5_rows,
    list_vendor_contract_entitlements,
    list_vendor_contract_profiles,
    list_vendor_procurement_readiness,
    run_vendor_contract_readiness_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Omicron-5 authorized vendor contract readiness review.")
    parser.add_argument("--resource", choices=["review", "profiles", "entitlements", "readiness"], default="review")
    parser.add_argument("--requested-by", default="omicron5-cli")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", action="append", default=[])
    parser.add_argument("--dataset-code", action="append", default=[])
    parser.add_argument("--min-sla-uptime-pct", type=float, default=float(os.getenv("QDATA_OMICRON5_MIN_SLA_UPTIME_PCT", "99.5")))
    parser.add_argument("--min-rate-limit-per-min", type=int, default=int(os.getenv("QDATA_OMICRON5_MIN_RATE_LIMIT_PER_MIN", "60")))
    parser.add_argument("--require-live-evidence", action="store_true", default=os.getenv("QDATA_OMICRON5_REQUIRE_LIVE_EVIDENCE", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--dry-run", action="store_true", help="Evaluate readiness without writing snapshots.")
    parser.add_argument("--status", default="")
    parser.add_argument("--procurement-role", default="")
    parser.add_argument("--procurement-status", default="")
    parser.add_argument("--contract-status", default="")
    parser.add_argument("--commercial-clearance", default="")
    parser.add_argument("--redistribution-allowed", default="")
    parser.add_argument("--entitlement-status", default="")
    parser.add_argument("--allowed-role", default="")
    parser.add_argument("--schema-status", default="")
    parser.add_argument("--field-mapping-status", default="")
    parser.add_argument("--contract-code", default="")
    parser.add_argument("--entitlement-code", default="")
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "review":
        rows = run_vendor_contract_readiness_review(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            source_codes=args.source_code or None,
            dataset_codes=args.dataset_code or None,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            min_sla_uptime_pct=args.min_sla_uptime_pct,
            min_rate_limit_per_min=args.min_rate_limit_per_min,
            require_live_evidence=args.require_live_evidence,
            write_db=not args.dry_run,
        )
        counts = _counts(rows)
        if args.json:
            print(json.dumps({"resource": "review", "counts": counts, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
        else:
            print(
                "omicron5_vendor_contract_readiness "
                f"snapshots={len(rows)} ready={counts['ready']} conditional={counts['conditional']} "
                f"review_required={counts['review_required']} blocked={counts['blocked']} no_contract={counts['no_contract']} "
                f"primary_candidate={counts['primary_candidate']}"
            )
        return 0

    params = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for key, value in {
        "status": args.status,
        "procurement_role": args.procurement_role,
        "procurement_status": args.procurement_status,
        "contract_status": args.contract_status,
        "commercial_clearance": args.commercial_clearance,
        "redistribution_allowed": args.redistribution_allowed,
        "entitlement_status": args.entitlement_status,
        "allowed_role": args.allowed_role,
        "schema_status": args.schema_status,
        "field_mapping_status": args.field_mapping_status,
        "contract_code": args.contract_code,
        "entitlement_code": args.entitlement_code,
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
        rows = list_vendor_contract_profiles(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "entitlements":
        rows = list_vendor_contract_entitlements(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_vendor_procurement_readiness(args.postgres_dsn, params, args.limit, args.offset)
    if args.json:
        print(json.dumps({"resource": args.resource, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_omicron5_rows(args.resource, rows))
    return 0


def _counts(rows: list[dict]) -> dict[str, int]:
    return {
        "ready": sum(1 for row in rows if row.get("status") == "ready"),
        "conditional": sum(1 for row in rows if row.get("status") == "conditional"),
        "review_required": sum(1 for row in rows if row.get("status") == "review_required"),
        "blocked": sum(1 for row in rows if row.get("status") == "blocked"),
        "no_contract": sum(1 for row in rows if row.get("status") == "no_contract"),
        "primary_candidate": sum(1 for row in rows if row.get("procurement_role") == "primary_candidate"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
