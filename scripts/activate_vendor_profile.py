#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.theta import update_vendor_profile_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch an Eta/Theta vendor integration profile status.")
    parser.add_argument("--source-code", default="vendor_http")
    parser.add_argument("--provider-name", default="vendor_http")
    parser.add_argument("--status", choices=["testing", "active", "paused", "retired"], required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    result = update_vendor_profile_status(args.postgres_dsn, args.source_code, args.provider_name, args.status)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"vendor_profile source={result['source_code']} provider={result['provider_name']} "
            f"profile_id={result['profile_id']} status={result['status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
