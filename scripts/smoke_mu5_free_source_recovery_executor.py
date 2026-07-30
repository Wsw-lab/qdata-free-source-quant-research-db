#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.mu5_free_source_recovery_executor import execute_free_source_recovery_actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Mu-5 free source recovery execution loop.")
    parser.add_argument("--max-actions", type=int, default=1)
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--action-types", default="manual_review")
    parser.add_argument("--allow-wecom-external", action="store_true", default=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    row = execute_free_source_recovery_actions(
        args.postgres_dsn,
        action_types=_csv(args.action_types),
        max_actions=args.max_actions,
        requested_by="mu5-smoke",
        trigger_mode="smoke",
        environment="local",
        execute_retry_canary=False,
        request_manual_review=True,
        notify_wecom=True,
        allow_wecom_external=args.allow_wecom_external,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    if args.json:
        print(json.dumps({"resource": "mu5.free-source-recovery-smoke", "row_count": 1, "rows": [row]}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(
            f"mu5_free_source_recovery_smoke={'ok' if row.get('execution_count') else 'skipped'} "
            f"status={row.get('status')} candidates={row.get('candidate_count')} executions={row.get('execution_count')} "
            f"recovered={row.get('recovered_count')} failed={row.get('failed_count')} suppressed={row.get('suppressed_count')} "
            f"review_requested={row.get('review_requested_count')} blocked={row.get('blocked_count')}"
        )
    return 0 if row.get("execution_count") else 1


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
