#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.chi_governance import (
    collect_project_governance_snapshots,
    evaluate_access_boundary,
    format_chi_report,
    list_access_decisions,
    list_governance_actions,
    list_project_governance,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report and run Chi governance checks.")
    parser.add_argument("--resource", choices=["evaluate-access", "collect-snapshots", "access-audit", "project-governance", "governance-actions"], default="project-governance")
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--principal-code", default="")
    parser.add_argument("--token-name", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--api-name", default="")
    parser.add_argument("--access-level", default="read")
    parser.add_argument("--fields", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--write-audit", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--write-actions", action="store_true")
    parser.add_argument("--snapshot-date", default="")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--recommended-action", default="")
    parser.add_argument("--action-type", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "evaluate-access":
        rows = [
            evaluate_access_boundary(
                args.postgres_dsn,
                tenant_code=args.tenant_code or None,
                project_code=args.project_code or None,
                principal_code=args.principal_code or None,
                token_name=args.token_name or None,
                dataset_code=args.dataset_code or "daily_bar",
                api_name=args.api_name or "price",
                access_level=args.access_level,
                fields=[item.strip() for item in args.fields.split(",") if item.strip()] or None,
                request_id=args.request_id or None,
                write_audit=args.write_audit,
            )
        ]
        resource = "evaluate-access"
    elif args.resource == "collect-snapshots":
        rows = collect_project_governance_snapshots(
            args.postgres_dsn,
            snapshot_date=args.snapshot_date or args.as_of_date or None,
            tenant_code=args.tenant_code or None,
            project_code=args.project_code or None,
            write_db=args.write_db,
            write_actions=args.write_actions,
        )
        resource = "project-governance"
    else:
        params = _params(args)
        if args.resource == "access-audit":
            rows = list_access_decisions(args.postgres_dsn, params, args.limit, args.offset)
        elif args.resource == "project-governance":
            rows = list_project_governance(args.postgres_dsn, params, args.limit, args.offset)
        else:
            rows = list_governance_actions(args.postgres_dsn, params, args.limit, args.offset)
        resource = args.resource

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_chi_report(resource, rows))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "tenant_code",
        "project_code",
        "principal_code",
        "token_name",
        "dataset_code",
        "api_name",
        "status",
        "decision",
        "recommended_action",
        "action_type",
        "severity",
        "as_of_date",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
