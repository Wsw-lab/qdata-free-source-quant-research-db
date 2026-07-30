#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.delta2_wecom import (
    DEFAULT_PROFILE_CODE,
    format_delta2_rows,
    list_automation_live_receipts,
    run_delta2_wecom_live_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Delta-2 WeCom live validation and receipt reporting.")
    parser.add_argument("--resource", choices=["validate", "receipts"], default="receipts")
    parser.add_argument("--profile-code", default=DEFAULT_PROFILE_CODE)
    parser.add_argument("--channel-code", default="")
    parser.add_argument("--provider-code", default="wecom")
    parser.add_argument("--environment", default="")
    parser.add_argument("--receipt-code", default="")
    parser.add_argument("--validation-code", default="")
    parser.add_argument("--message-type", choices=["text", "markdown"], default="markdown")
    parser.add_argument("--status", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--endpoint-secret-ref", default="")
    parser.add_argument("--provider-errcode", default="")
    parser.add_argument("--trigger-mode", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--message", default="")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "validate":
        payload = run_delta2_wecom_live_validation(
            args.postgres_dsn,
            profile_code=args.profile_code,
            requested_by=args.requested_by or "delta2",
            title=args.title or "QData Delta-2 企业微信 live validation",
            message=args.message or "企业微信 live validation smoke",
            action_code=args.action_code or None,
            trigger_mode=args.trigger_mode or "manual",
            message_type=args.message_type,
            allow_external=args.allow_external,
            force=args.force,
        )
        _emit(payload, format_delta2_rows("receipts", [payload]), args.json)
        return 0

    rows = list_automation_live_receipts(args.postgres_dsn, _params(args), args.limit, args.offset)
    payload = {"resource": "delta2.receipts", "row_count": len(rows), "rows": rows}
    _emit(payload, format_delta2_rows("receipts", rows), args.json)
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "profile_code",
        "channel_code",
        "provider_code",
        "environment",
        "receipt_code",
        "validation_code",
        "message_type",
        "status",
        "requested_by",
        "endpoint_secret_ref",
        "provider_errcode",
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
