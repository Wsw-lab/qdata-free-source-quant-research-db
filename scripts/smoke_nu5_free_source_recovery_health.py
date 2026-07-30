#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.nu5_free_source_recovery_health import (
    list_free_source_recovery_health,
    run_free_source_recovery_health,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Nu-5 free source recovery health.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    snapshot = run_free_source_recovery_health(
        args.postgres_dsn,
        requested_by="nu5-smoke",
        trigger_mode="smoke",
        environment="local",
        write_db=True,
    )
    if snapshot.get("status") == "failed":
        raise RuntimeError(f"Nu-5 health failed: {snapshot.get('error_message')}")
    rows = list_free_source_recovery_health(args.postgres_dsn, {"snapshot_code": [str(snapshot["snapshot_code"])]}, 5, 0)
    if not rows:
        raise RuntimeError("Nu-5 health snapshot was not persisted")
    print(
        "nu5_free_source_recovery_health_smoke=ok "
        f"status={snapshot.get('status')} snapshot_code={snapshot.get('snapshot_code')} "
        f"backlog={snapshot.get('backlog_count')} approvals={snapshot.get('approval_pending_count')} "
        f"overdue={snapshot.get('approval_overdue_count')} failures={snapshot.get('failed_count')} "
        f"stale_schedule={snapshot.get('stale_schedule_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
