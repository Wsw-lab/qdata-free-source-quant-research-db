#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.alpha6_route_incident_control_health import (
    list_route_incident_control_health,
    run_route_incident_control_health,
)
from qdata.lambda_worker import run_lambda_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Alpha-6 route incident control health.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--skip-omega5-precondition", action="store_true")
    args = parser.parse_args()

    if not args.skip_omega5_precondition:
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().with_name("smoke_omega5_route_incident_control.py")),
                "--postgres-dsn",
                args.postgres_dsn,
            ],
            check=True,
        )
    run_lambda_worker(
        args.postgres_dsn,
        task_names=["route_incident_control"],
        trigger_mode="smoke",
        dry_run=True,
        write_db=True,
    )

    snapshot = run_route_incident_control_health(
        args.postgres_dsn,
        requested_by="alpha6-smoke",
        trigger_mode="smoke",
        environment="local",
        lookback_hours=24,
        approval_sla_hours=4,
        write_db=True,
    )
    if snapshot.get("status") in {"failed", "critical"}:
        raise RuntimeError(f"Alpha-6 route control health is critical: {snapshot}")
    if int(snapshot.get("control_count") or 0) < 1:
        raise RuntimeError("Alpha-6 smoke expected at least one Omega-5 route control")
    if not snapshot.get("latest_control_stage"):
        raise RuntimeError("Alpha-6 smoke expected latest_control_stage evidence")
    if not snapshot.get("runbook_actions"):
        raise RuntimeError("Alpha-6 smoke expected runbook actions")
    rows = list_route_incident_control_health(args.postgres_dsn, {"snapshot_code": [str(snapshot["snapshot_code"])]}, 5, 0)
    if not rows:
        raise RuntimeError("Alpha-6 route incident control health snapshot was not persisted")
    print(
        "alpha6_route_incident_control_health_smoke=ok "
        f"status={snapshot.get('status')} snapshot_code={snapshot.get('snapshot_code')} "
        f"controls={snapshot.get('control_count')} pending={snapshot.get('pending_control_count')} "
        f"blocked_receipts={snapshot.get('notification_blocked_count')} "
        f"failed_execution={snapshot.get('failed_execution_count')} stale={snapshot.get('stale_schedule_count')} "
        f"latest_stage={snapshot.get('latest_control_stage')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
