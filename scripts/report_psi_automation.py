#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.psi_automation import (
    format_psi_report,
    format_psi_rows,
    list_automation_actions,
    list_automation_runs,
    list_route_incident_actions,
    run_psi_automation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan and execute Psi automation actions from Phi/Chi decisions.")
    parser.add_argument("--resource", choices=["run", "runs", "actions", "route-actions"], default="run")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--trigger-mode", default="")
    parser.add_argument("--execution-mode", choices=["", "dry_run", "execute"], default="")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--source-run-code", default="")
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--source-type", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--action-type", default="")
    parser.add_argument("--safety-level", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--principal-code", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--no-phi", action="store_true")
    parser.add_argument("--no-chi", action="store_true")
    parser.add_argument("--include-route", action="store_true")
    parser.add_argument("--route-lookback-hours", type=int, default=24)
    parser.add_argument("--route-max-actions", type=int, default=50)
    parser.add_argument("--route-owner", default="platform-ops")
    parser.add_argument("--route-no-recovered", action="store_true")
    parser.add_argument("--no-write-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        payload = run_psi_automation(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            environment=args.environment or "local",
            trigger_mode=args.trigger_mode or "manual",
            execution_mode=args.execution_mode or "dry_run",
            approve=args.approve,
            approved_by=args.approved_by or None,
            source_run_code=args.source_run_code or None,
            tenant_code=args.tenant_code or None,
            project_code=args.project_code or None,
            include_phi=not args.no_phi,
            include_chi=not args.no_chi,
            include_route=args.include_route,
            route_lookback_hours=args.route_lookback_hours,
            route_max_actions=args.route_max_actions,
            route_owner=args.route_owner,
            route_include_recovered=not args.route_no_recovered,
            run_code=args.run_code or None,
            write_db=not args.no_write_db,
        )
        _emit(payload, format_psi_report(payload), args.json)
        return 0

    params = _params(args)
    if args.resource == "runs":
        rows = list_automation_runs(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "actions":
        rows = list_automation_actions(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_route_incident_actions(args.postgres_dsn, params, args.limit, args.offset)
    payload = {"resource": f"psi.{args.resource}", "row_count": len(rows), "rows": rows}
    _emit(payload, format_psi_rows(args.resource, rows), args.json)
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "run_code",
        "environment",
        "trigger_mode",
        "execution_mode",
        "status",
        "action_code",
        "source_type",
        "source_code",
        "action_type",
        "safety_level",
        "owner",
        "tenant_code",
        "project_code",
        "principal_code",
        "dataset_code",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


def _emit(payload: dict, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
