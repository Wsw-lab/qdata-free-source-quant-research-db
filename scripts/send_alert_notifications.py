#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.iota import dispatch_alert_notifications


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch Iota alert notifications.")
    parser.add_argument("--channel-code", default="")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    deliveries = dispatch_alert_notifications(
        args.postgres_dsn,
        channel_code=args.channel_code or None,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(deliveries, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"alert_notifications deliveries={len(deliveries)} dry_run={args.dry_run}")
        for item in deliveries[:20]:
            print(
                f"delivery alert_id={item['alert_id']} channel={item['channel_code']} "
                f"type={item['alert_type']} severity={item['severity']} status={item['status']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
