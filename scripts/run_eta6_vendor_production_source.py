#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.eta6_vendor_production_source import (
    format_eta6_rows,
    list_vendor_production_source_dataset_checks,
    list_vendor_production_source_decisions,
    list_vendor_production_source_runs,
    run_vendor_production_source_closure,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Eta-6 real-vendor production primary-source closure.")
    parser.add_argument("--resource", choices=["run", "runs", "dataset-checks", "decisions"], default="run")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--dataset-code", action="append", default=[])
    parser.add_argument("--requested-by", default=os.getenv("QDATA_ETA6_REQUESTED_BY", "eta6-cli"))
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api", "worker"], default="manual")
    parser.add_argument("--environment", choices=["local", "staging", "production"], default=os.getenv("QDATA_ETA6_ENVIRONMENT", "local"))
    parser.add_argument("--closure-scope", choices=["production_primary", "canary", "full_market"], default=os.getenv("QDATA_ETA6_CLOSURE_SCOPE", "production_primary"))
    parser.add_argument("--closure-mode", choices=["review_only", "dry_run", "apply"], default=os.getenv("QDATA_ETA6_CLOSURE_MODE", "review_only"))
    parser.add_argument("--require-real-vendor-env", action="store_true", default=os.getenv("QDATA_ETA6_REQUIRE_REAL_VENDOR_ENV", "true").lower() in {"1", "true", "yes"})
    parser.add_argument("--allow-missing-real-vendor-env", action="store_true")
    parser.add_argument("--external-probe-allowed", action="store_true", default=os.getenv("QDATA_ETA6_EXTERNAL_PROBE_ALLOWED", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--min-stability-score", type=float, default=float(os.getenv("QDATA_ETA6_MIN_STABILITY_SCORE", "70")))
    parser.add_argument("--allow-cost-watch", action="store_true", default=os.getenv("QDATA_ETA6_ALLOW_COST_WATCH", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--production-code", default="")
    parser.add_argument("--dataset-check-code", default="")
    parser.add_argument("--decision-code", default="")
    parser.add_argument("--decision-type", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--production-role", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.resource == "run":
        row = run_vendor_production_source_closure(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            dataset_codes=args.dataset_code or None,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            closure_scope=args.closure_scope,
            closure_mode=args.closure_mode,
            require_real_vendor_env=False if args.allow_missing_real_vendor_env else args.require_real_vendor_env,
            external_probe_allowed=args.external_probe_allowed,
            min_stability_score=args.min_stability_score,
            allow_cost_watch=args.allow_cost_watch,
            write_db=not args.dry_run,
        )
        rows: list[dict[str, object]] | dict[str, object] = row
    else:
        params = _params(args, _provided_options(sys.argv[1:]))
        if args.resource == "runs":
            rows = list_vendor_production_source_runs(args.postgres_dsn, params, args.limit, args.offset)
        elif args.resource == "dataset-checks":
            rows = list_vendor_production_source_dataset_checks(args.postgres_dsn, params, args.limit, args.offset)
        else:
            rows = list_vendor_production_source_decisions(args.postgres_dsn, params, args.limit, args.offset)
    if args.json:
        data_rows = rows if isinstance(rows, list) else [rows]
        print(json.dumps({"resource": f"eta6.{args.resource}", "row_count": len(data_rows), "rows": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_eta6_rows(args.resource, rows))
    return 0


def _params(args: argparse.Namespace, provided_options: set[str]) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for option, key, value in [
        ("--production-code", "production_code", args.production_code),
        ("--dataset-check-code", "dataset_check_code", args.dataset_check_code),
        ("--decision-code", "decision_code", args.decision_code),
        ("--decision-type", "decision_type", args.decision_type),
        ("--source-code", "source_code", args.source_code),
        ("--primary-source-code", "primary_source_code", args.primary_source_code),
        ("--status", "status", args.status),
        ("--production-role", "production_role", args.production_role),
        ("--severity", "severity", args.severity),
        ("--environment", "environment", args.environment),
        ("--closure-scope", "closure_scope", args.closure_scope),
        ("--closure-mode", "closure_mode", args.closure_mode),
    ]:
        if value and option in provided_options:
            params[key] = [str(value)]
    return params


def _provided_options(argv: list[str]) -> set[str]:
    return {item.split("=", 1)[0] for item in argv if item.startswith("--")}


if __name__ == "__main__":
    raise SystemExit(main())
