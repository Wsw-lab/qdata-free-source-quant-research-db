#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.mu5_free_source_recovery_executor import (
    execute_free_source_recovery_actions,
    format_mu5_rows,
    list_free_source_recovery_executions,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mu-5 free source recovery execution loop.")
    parser.add_argument("--resource", choices=["execute", "executions"], default="execute")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--recovery-code", default="")
    parser.add_argument("--action-types", default="")
    parser.add_argument("--source-codes", default="")
    parser.add_argument("--dataset-codes", default="")
    parser.add_argument("--execution-code", default="")
    parser.add_argument("--execution-type", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke", "api"], default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-actions", type=int, default=int(os.getenv("QDATA_MU5_FREE_SOURCE_MAX_ACTIONS", "20")))
    parser.add_argument("--start-date", default=os.getenv("QDATA_MU5_FREE_SOURCE_CANARY_START_DATE", "2024-01-04"))
    parser.add_argument("--end-date", default=os.getenv("QDATA_MU5_FREE_SOURCE_CANARY_END_DATE", "2024-01-04"))
    parser.add_argument("--canary-symbols", default="")
    parser.add_argument("--no-retry-canary", action="store_true")
    parser.add_argument("--no-manual-review", action="store_true")
    parser.add_argument("--no-wecom", action="store_true")
    parser.add_argument("--allow-wecom-external", action="store_true", default=os.getenv("QDATA_MU5_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--baostock-timeout-seconds", type=float, default=float(os.getenv("QDATA_MU5_BAOSTOCK_TIMEOUT_SECONDS", "3")))
    parser.add_argument("--tushare-token", default=os.getenv("QDATA_TUSHARE_TOKEN", ""))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "execute":
        row = execute_free_source_recovery_actions(
            args.postgres_dsn,
            action_code=args.action_code or None,
            recovery_code=args.recovery_code or None,
            action_types=_csv(args.action_types),
            source_codes=_csv(args.source_codes),
            dataset_codes=_csv(args.dataset_codes),
            max_actions=args.max_actions,
            requested_by=args.requested_by or "mu5",
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            dry_run=args.dry_run,
            execute_retry_canary=not args.no_retry_canary,
            request_manual_review=not args.no_manual_review,
            notify_wecom=not args.no_wecom,
            allow_wecom_external=args.allow_wecom_external,
            start_date=args.start_date,
            end_date=args.end_date,
            canary_symbols=_csv(args.canary_symbols),
            baostock_timeout_seconds=args.baostock_timeout_seconds,
            tushare_token=args.tushare_token or None,
        )
        if args.json:
            print(json.dumps({"resource": "mu5.free-source-recovery-execute", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
        else:
            print(_format_execute(row))
        return 0 if row.get("status") not in {"failed"} else 1

    rows = list_free_source_recovery_executions(args.postgres_dsn, _params(args), args.limit, args.offset)
    if args.json:
        print(json.dumps({"resource": "mu5.free-source-recovery-executions", "row_count": len(rows), "rows": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_mu5_rows("executions", rows))
    return 0


def _format_execute(row: dict) -> str:
    lines = [
        (
            f"mu5_free_source_recovery_execute status={row.get('status')} candidates={row.get('candidate_count')} "
            f"executions={row.get('execution_count')} recovered={row.get('recovered_count')} failed={row.get('failed_count')} "
            f"suppressed={row.get('suppressed_count')} review_requested={row.get('review_requested_count')} blocked={row.get('blocked_count')}"
        )
    ]
    for item in row.get("executions") or []:
        keys = ["execution_code", "action_code", "source_code", "dataset_code", "execution_type", "status", "iota5_pool_status", "approval_code", "wecom_receipt_code", "error_message"]
        lines.append(" ".join(f"{key}={item[key]}" for key in keys if item.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "execution_code",
        "action_code",
        "recovery_code",
        "execution_type",
        "status",
        "requested_by",
        "trigger_mode",
        "environment",
        "source_code",
        "dataset_code",
    ):
        attr = "source_codes" if name == "source_code" else "dataset_codes" if name == "dataset_code" else name
        value = getattr(args, attr)
        if name == "trigger_mode" and value == "manual":
            continue
        if name == "environment" and value == "local":
            continue
        if value:
            params[name] = [value.split(",")[0].strip()]
    return params


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
