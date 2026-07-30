#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.nu_deploy import NU_CHECKS, format_nu_health_report, report_to_dict, run_nu_health_check


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Nu deployment health checks.")
    parser.add_argument("--check", choices=NU_CHECKS, action="append", default=[])
    parser.add_argument("--environment", default=os.getenv("QDATA_NU_ENVIRONMENT", "local"))
    parser.add_argument("--release-code", default=os.getenv("QDATA_NU_RELEASE_CODE", ""))
    parser.add_argument("--version-label", default=os.getenv("QDATA_NU_VERSION_LABEL", ""))
    parser.add_argument("--git-ref", default=os.getenv("QDATA_NU_GIT_REF", ""))
    parser.add_argument("--api-base-url", default=os.getenv("QDATA_API_BASE_URL", ""))
    parser.add_argument("--api-token", default=os.getenv("QDATA_API_TOKEN", ""))
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--require-live-scheduler", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    report = run_nu_health_check(
        args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn or None,
        api_base_url=args.api_base_url or None,
        api_token=args.api_token or None,
        environment=args.environment,
        release_code=args.release_code or None,
        version_label=args.version_label or None,
        git_ref=args.git_ref or None,
        write_db=args.write_db,
        require_live_scheduler=args.require_live_scheduler,
        check_names=args.check or None,
    )
    if args.json:
        print(json.dumps(report_to_dict(report), ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_nu_health_report(report))
    if report.status == "failed":
        return 1
    if args.fail_on_warning and report.status == "warning":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
