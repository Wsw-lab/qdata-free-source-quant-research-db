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
    list_route_incident_actions,
    run_psi_automation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Psi-5 source-route incident automation from Chi-5 signals.")
    parser.add_argument("--resource", choices=["run", "route-actions"], default="run")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "api", "smoke", "demo"], default="manual")
    parser.add_argument("--execution-mode", choices=["dry_run", "execute"], default=os.getenv("QDATA_PSI5_ROUTE_EXECUTION_MODE", "execute"))
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--route-lookback-hours", type=int, default=int(os.getenv("QDATA_PSI5_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--route-max-actions", type=int, default=int(os.getenv("QDATA_PSI5_ROUTE_MAX_ACTIONS", "50")))
    parser.add_argument("--route-owner", default=os.getenv("QDATA_PSI5_ROUTE_OWNER", "platform-ops"))
    parser.add_argument("--route-no-recovered", action="store_true")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--incident-action-code", default="")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--source-signal-type", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--action-type", default="")
    parser.add_argument("--safety-level", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--no-write-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        payload = run_psi_automation(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            environment=args.environment,
            trigger_mode=args.trigger_mode,
            execution_mode=args.execution_mode,
            approve=args.approve,
            approved_by=args.approved_by or None,
            include_phi=False,
            include_chi=False,
            include_route=True,
            route_lookback_hours=args.route_lookback_hours,
            route_max_actions=args.route_max_actions,
            route_owner=args.route_owner,
            route_include_recovered=not args.route_no_recovered,
            run_code=args.run_code or None,
            write_db=not args.no_write_db,
        )
        _emit(payload, format_psi_report(payload), args.json)
        return 0

    rows = list_route_incident_actions(args.postgres_dsn, _params(args), args.limit, args.offset)
    payload = {"resource": "psi5.route-actions", "row_count": len(rows), "rows": rows}
    _emit(payload, format_psi_rows("route-actions", rows), args.json)
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "incident_action_code",
        "run_code",
        "action_code",
        "source_signal_type",
        "dataset_code",
        "source_code",
        "action_type",
        "safety_level",
        "status",
        "owner",
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
