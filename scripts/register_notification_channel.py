#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.iota import ensure_notification_channel


def main() -> int:
    parser = argparse.ArgumentParser(description="Register Iota alert notification channel.")
    parser.add_argument("--channel-code", default="stdout-high")
    parser.add_argument("--channel-name", default="Stdout High Alerts")
    parser.add_argument("--channel-type", choices=["stdout", "webhook", "email", "feishu"], default="stdout")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--min-severity", choices=["low", "medium", "high", "critical"], default="high")
    parser.add_argument("--inactive", action="store_true")
    parser.add_argument("--config-json", default="{}")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    result = ensure_notification_channel(
        args.postgres_dsn,
        channel_code=args.channel_code,
        channel_name=args.channel_name,
        channel_type=args.channel_type,
        endpoint=args.endpoint or None,
        min_severity=args.min_severity,
        is_active=not args.inactive,
        config=json.loads(args.config_json),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"notification_channel code={result['channel_code']} type={result['channel_type']} "
            f"active={result['is_active']} min_severity={result['min_severity']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
