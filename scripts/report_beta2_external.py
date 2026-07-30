#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.beta2_external import (
    format_beta2_rows,
    list_automation_channels,
    list_automation_dispatches,
    list_automation_runbooks,
    recover_beta2_dispatch,
    run_beta2_dispatch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Beta-2 external notification/approval dispatch and recovery drills.")
    parser.add_argument(
        "--resource",
        choices=["dispatch", "recover", "channels", "dispatches", "runbooks"],
        default="dispatch",
    )
    parser.add_argument("--action-code", default="")
    parser.add_argument("--channel-code", default="")
    parser.add_argument("--channel-type", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--dispatch-code", default="")
    parser.add_argument("--dispatch-type", choices=["notification", "approval_request", "manual_review"], default="")
    parser.add_argument("--trigger-mode", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--recovered-by", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--runbook-code", default="")
    parser.add_argument("--failure-class", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "dispatch":
        payload = run_beta2_dispatch(
            args.postgres_dsn,
            action_code=args.action_code,
            channel_code=args.channel_code,
            requested_by=args.requested_by or "beta2",
            trigger_mode=args.trigger_mode or "manual",
            dispatch_type=args.dispatch_type or None,
            allow_external=args.allow_external,
            force=args.force,
        )
        _emit(payload, format_beta2_rows("dispatches", [payload]), args.json)
        return 0
    if args.resource == "recover":
        payload = recover_beta2_dispatch(
            args.postgres_dsn,
            dispatch_code=args.dispatch_code,
            recovered_by=args.recovered_by or args.requested_by or "beta2",
            reason=args.reason or "Beta-2 manual recovery",
            runbook_code=args.runbook_code or None,
        )
        _emit(payload, format_beta2_rows("dispatches", [payload]), args.json)
        return 0

    params = _params(args)
    if args.resource == "channels":
        rows = list_automation_channels(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "dispatches":
        rows = list_automation_dispatches(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_automation_runbooks(args.postgres_dsn, params, args.limit, args.offset)
    payload = {"resource": f"beta2.{args.resource}", "row_count": len(rows), "rows": rows}
    _emit(payload, format_beta2_rows(args.resource, rows), args.json)
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "action_code",
        "channel_code",
        "channel_type",
        "environment",
        "dispatch_code",
        "dispatch_type",
        "trigger_mode",
        "status",
        "requested_by",
        "recovered_by",
        "runbook_code",
        "failure_class",
        "severity",
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
