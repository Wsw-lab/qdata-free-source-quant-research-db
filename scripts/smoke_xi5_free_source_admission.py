#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.xi5_free_source_admission import (
    list_free_source_admission_profiles,
    list_free_source_admission_snapshots,
    run_free_source_admission_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Xi-5 free source admission matrix.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    rows = run_free_source_admission_review(
        args.postgres_dsn,
        requested_by="xi5-smoke",
        trigger_mode="smoke",
        environment="local",
        write_db=True,
    )
    if not rows:
        raise RuntimeError("Xi-5 admission review produced no snapshots")
    latest = list_free_source_admission_snapshots(args.postgres_dsn, {"limit": ["5"]}, 5, 0)
    profiles = list_free_source_admission_profiles(args.postgres_dsn, {"limit": ["5"]}, 5, 0)
    if not latest:
        raise RuntimeError("Xi-5 admission snapshots were not persisted")
    if not profiles:
        raise RuntimeError("Xi-5 admission profiles are missing")
    print(
        "xi5_free_source_admission_smoke=ok "
        f"snapshots={len(rows)} approved={_count(rows, 'approved')} conditional={_count(rows, 'conditional')} "
        f"review_required={_count(rows, 'review_required')} blocked={_count(rows, 'blocked')} "
        f"no_data={_count(rows, 'no_data')} primary_candidate={sum(1 for row in rows if row.get('admission_role') == 'primary_candidate')}"
    )
    return 0


def _count(rows: list[dict], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


if __name__ == "__main__":
    raise SystemExit(main())
