#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.theta import format_decision_reports, generate_vendor_decision_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Theta vendor go-live decision reports.")
    parser.add_argument("--dataset-code", default="daily_bar")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    decisions = generate_vendor_decision_reports(
        args.postgres_dsn,
        args.dataset_code,
        source_code=args.source_code or None,
        write_db=args.write_db,
    )
    if args.json:
        print(json.dumps(decisions, ensure_ascii=False, default=lambda item: getattr(item, "__dict__", str(item)), indent=2, sort_keys=True))
    else:
        print(format_decision_reports(decisions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
