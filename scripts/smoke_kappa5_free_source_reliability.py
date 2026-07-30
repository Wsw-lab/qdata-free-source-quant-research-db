#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa5_free_source_reliability import score_free_source_reliability


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Kappa-5 free source reliability scoring.")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--source-codes", default="")
    parser.add_argument("--dataset-codes", default="")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    rows = score_free_source_reliability(
        args.postgres_dsn,
        as_of_date=args.as_of_date or None,
        lookback_hours=args.lookback_hours,
        source_codes=_csv(args.source_codes),
        dataset_codes=_csv(args.dataset_codes),
        requested_by="kappa5_smoke",
        trigger_mode="smoke",
        environment="local",
    )
    counts = _counts(rows)
    scores = [float(row.get("reliability_score") or 0) for row in rows]
    status = "ok" if rows else "failed"
    print(
        " ".join(
            [
                f"kappa5_free_source_reliability_smoke={status}",
                f"snapshot_count={len(rows)}",
                f"ready={counts.get('ready', 0)}",
                f"watch={counts.get('watch', 0)}",
                f"degraded={counts.get('degraded', 0)}",
                f"rejected={counts.get('rejected', 0)}",
                f"no_data={counts.get('no_data', 0)}",
                f"min_score={min(scores) if scores else 0:.4f}",
                f"max_score={max(scores) if scores else 0:.4f}",
            ]
        )
    )
    return 0 if rows else 1


def _csv(value: str) -> list[str] | None:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
