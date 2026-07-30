#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.iota import ensure_iota_security_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Iota tenant/project/principal/API token ACL context.")
    parser.add_argument("--tenant-code", default="demo")
    parser.add_argument("--tenant-name", default="Demo Tenant")
    parser.add_argument("--project-code", default="quant-research")
    parser.add_argument("--project-name", default="Quant Research")
    parser.add_argument("--principal-code", default="research-bot")
    parser.add_argument("--principal-name", default="Research Bot")
    parser.add_argument("--token", default=os.getenv("QDATA_IOTA_BOOTSTRAP_TOKEN", "iotatoken"))
    parser.add_argument("--token-name", default="iota-research-token")
    parser.add_argument("--datasets", default="daily_bar,limit_price_daily,tradable_universe")
    parser.add_argument("--scopes", default="read")
    parser.add_argument("--quota-per-min", type=int, default=120)
    parser.add_argument("--cost-center", default="research")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    result = ensure_iota_security_context(
        args.postgres_dsn,
        tenant_code=args.tenant_code,
        tenant_name=args.tenant_name,
        project_code=args.project_code,
        project_name=args.project_name,
        principal_code=args.principal_code,
        principal_name=args.principal_name,
        token=args.token,
        token_name=args.token_name,
        datasets=[item.strip() for item in args.datasets.split(",") if item.strip()],
        scopes=[item.strip() for item in args.scopes.split(",") if item.strip()],
        quota_per_min=args.quota_per_min,
        cost_center=args.cost_center,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"iota_security tenant={result['tenant_code']} project={result['project_code']} "
            f"principal={result['principal_code']} token_id={result['token_id']} access={result['access_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
