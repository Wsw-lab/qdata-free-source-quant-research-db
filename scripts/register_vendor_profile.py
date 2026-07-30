#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.eta import ensure_vendor_profile


def _int_env(name: str):
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return int(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Register or update an Eta vendor integration profile.")
    parser.add_argument("--source-code", default="vendor_http")
    parser.add_argument("--source-name", default="Commercial HTTP Vendor")
    parser.add_argument("--provider-name", default="vendor_http")
    parser.add_argument("--auth-mode", choices=["none", "bearer", "header", "query", "basic"], default=os.getenv("QDATA_VENDOR_AUTH_MODE", "none"))
    parser.add_argument("--endpoint-base", default=os.getenv("QDATA_VENDOR_BASE_URL", ""))
    parser.add_argument("--enabled-datasets", default="daily_bar")
    parser.add_argument("--rate-limit-per-min", type=int, default=_int_env("QDATA_VENDOR_RATE_LIMIT_PER_MIN"))
    parser.add_argument("--retry-limit", type=int, default=int(os.getenv("QDATA_VENDOR_RETRY_LIMIT", "2")))
    parser.add_argument("--timeout-ms", type=int, default=int(float(os.getenv("QDATA_VENDOR_TIMEOUT_SECONDS", "30")) * 1000))
    parser.add_argument("--license-scope", default="commercial contract required")
    parser.add_argument("--redistribution-allowed", choices=["unknown", "true", "false"], default="unknown")
    parser.add_argument("--commercial-contract-ref", default="")
    parser.add_argument("--status", choices=["testing", "active", "paused", "retired"], default="testing")
    parser.add_argument("--owner", default="qdata")
    parser.add_argument("--details-json", default="{}")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    redistribution_allowed = {
        "unknown": None,
        "true": True,
        "false": False,
    }[args.redistribution_allowed]
    profile = ensure_vendor_profile(
        args.postgres_dsn,
        source_code=args.source_code,
        source_name=args.source_name,
        provider_name=args.provider_name,
        auth_mode=args.auth_mode,
        endpoint_base=args.endpoint_base or None,
        enabled_datasets=[item.strip() for item in args.enabled_datasets.split(",") if item.strip()],
        rate_limit_per_min=args.rate_limit_per_min,
        retry_limit=args.retry_limit,
        timeout_ms=args.timeout_ms,
        license_scope=args.license_scope,
        redistribution_allowed=redistribution_allowed,
        commercial_contract_ref=args.commercial_contract_ref or None,
        status=args.status,
        owner=args.owner,
        details=json.loads(args.details_json),
    )
    print(
        f"vendor_profile source={args.source_code} provider={args.provider_name} "
        f"profile_id={profile['profile_id']} status={profile['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
