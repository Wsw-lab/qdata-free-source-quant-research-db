#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.theta import ensure_default_field_mappings, load_active_field_mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Register default Theta vendor field mappings.")
    parser.add_argument("--source-code", default="vendor_http")
    parser.add_argument("--dataset-code", default="daily_bar")
    parser.add_argument("--print-mapping", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    count = ensure_default_field_mappings(args.postgres_dsn, args.source_code, args.dataset_code)
    print(f"vendor_field_mapping source={args.source_code} dataset={args.dataset_code} rows={count}")
    if args.print_mapping:
        field_mapping, field_transforms = load_active_field_mapping(args.postgres_dsn, args.source_code, args.dataset_code)
        print(f"mapping={field_mapping}")
        print(f"transforms={field_transforms}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
