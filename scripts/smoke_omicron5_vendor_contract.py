#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.omicron5_vendor_contract import (
    list_vendor_contract_entitlements,
    list_vendor_contract_profiles,
    list_vendor_procurement_readiness,
    run_vendor_contract_readiness_review,
)


def main() -> int:
    postgres_dsn = os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata")
    rows = run_vendor_contract_readiness_review(
        postgres_dsn,
        requested_by="omicron5-smoke",
        trigger_mode="smoke",
        environment="local",
        write_db=True,
    )
    if not rows:
        raise RuntimeError("Omicron-5 vendor contract readiness review produced no snapshots")
    profiles = list_vendor_contract_profiles(postgres_dsn, {"limit": ["5"]}, 5, 0)
    entitlements = list_vendor_contract_entitlements(postgres_dsn, {"limit": ["10"]}, 10, 0)
    readiness = list_vendor_procurement_readiness(postgres_dsn, {"limit": ["5"]}, 5, 0)
    if not profiles:
        raise RuntimeError("Omicron-5 vendor contract profiles are missing")
    if not entitlements:
        raise RuntimeError("Omicron-5 vendor contract entitlements are missing")
    if not readiness:
        raise RuntimeError("Omicron-5 procurement readiness snapshots were not persisted")
    print(
        "omicron5_vendor_contract_smoke=ok "
        f"snapshots={len(rows)} ready={_count(rows, 'ready')} conditional={_count(rows, 'conditional')} "
        f"review_required={_count(rows, 'review_required')} blocked={_count(rows, 'blocked')} "
        f"no_contract={_count(rows, 'no_contract')} primary_candidate={sum(1 for row in rows if row.get('procurement_role') == 'primary_candidate')}"
    )
    return 0


def _count(rows: list[dict], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


if __name__ == "__main__":
    raise SystemExit(main())
