#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.lambda5_free_source_recovery import run_free_source_recovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Lambda-5 free source recovery orchestration.")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--source-codes", default="")
    parser.add_argument("--dataset-codes", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-alerts", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    row = run_free_source_recovery(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        lookback_hours=args.lookback_hours,
        source_codes=_csv(args.source_codes),
        dataset_codes=_csv(args.dataset_codes),
        requested_by="lambda5_smoke",
        trigger_mode="smoke",
        environment="local",
        dry_run=args.dry_run,
        write_alerts=not args.no_alerts,
    )
    ok_statuses = {"success", "warning", "skipped"}
    status = "ok" if row.get("status") in ok_statuses else "failed"
    print(
        " ".join(
            [
                f"lambda5_free_source_recovery_smoke={status}",
                f"status={row.get('status')}",
                f"recovery_code={row.get('recovery_code')}",
                f"snapshot_count={row.get('snapshot_count', 0)}",
                f"action_count={row.get('action_count', 0)}",
                f"retry={row.get('retry_action_count', 0)}",
                f"alerts={row.get('created_alert_count', 0)}",
                f"manual_review={row.get('manual_review_action_count', 0)}",
            ]
        )
    )
    return 0 if status == "ok" else 1


def _csv(value: str) -> list[str] | None:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


if __name__ == "__main__":
    raise SystemExit(main())
