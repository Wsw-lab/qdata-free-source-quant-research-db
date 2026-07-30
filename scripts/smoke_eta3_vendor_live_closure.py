#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.exceptions import QDataValidationError
from qdata.zeta3_vendor_onboarding import DEFAULT_DATASETS
from qdata.eta3_vendor_live_closure import run_vendor_live_closure


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Eta-3 vendor live closure.")
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--dataset-codes", default=",".join(DEFAULT_DATASETS))
    parser.add_argument("--windows", default="5,20,60")
    parser.add_argument("--canary-symbols", default="600519.SH,000001.SZ")
    parser.add_argument("--requested-by", default="eta3-smoke")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--allow-profile-write", action="store_true")
    parser.add_argument("--activate-profile", action="store_true")
    parser.add_argument("--enable-profile-datasets", action="store_true")
    parser.add_argument("--commercial-contract-ref", default=os.getenv("QDATA_VENDOR_CONTRACT_REF", ""))
    parser.add_argument("--redistribution-allowed", choices=["unknown", "true", "false"], default="unknown")
    parser.add_argument("--run-benchmarks", action="store_true")
    parser.add_argument("--full-market", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    live_env_present = bool(os.getenv("QDATA_VENDOR_BASE_URL")) and _vendor_auth_ready()
    if args.require_live and not live_env_present:
        raise SystemExit("eta3_vendor_live_closure_smoke=failed reason=missing_vendor_live_env")
    try:
        run = run_vendor_live_closure(
            args.postgres_dsn,
            dataset_codes=[item.strip() for item in args.dataset_codes.split(",") if item.strip()],
            start_date=args.start_date,
            end_date=args.end_date,
            windows=[int(item.strip()) for item in args.windows.split(",") if item.strip()],
            canary_symbols=[item.strip().upper() for item in args.canary_symbols.split(",") if item.strip()],
            requested_by=args.requested_by,
            trigger_mode="smoke",
            environment=args.environment,
            allow_live=args.allow_live and live_env_present,
            require_live=args.require_live,
            allow_profile_write=args.allow_profile_write,
            activate_profile=args.activate_profile,
            enable_profile_datasets=args.enable_profile_datasets,
            commercial_contract_ref=args.commercial_contract_ref or None,
            redistribution_allowed=_bool_choice(args.redistribution_allowed),
            require_active_profile=True,
            require_contract=True,
            run_endpoint_probes=True,
            run_onboarding=True,
            run_benchmarks=args.run_benchmarks and args.allow_live and live_env_present,
            full_market=args.full_market,
        )
    except QDataValidationError as exc:
        raise SystemExit(f"eta3_vendor_live_closure_smoke=failed reason={exc}") from exc
    mode = "live" if run.get("allow_live") else "blocked"
    if args.allow_live and live_env_present and run.get("status") not in {"success", "warning"}:
        raise SystemExit(f"eta3_vendor_live_closure_smoke=failed status={run.get('status')} error={run.get('error_message')}")
    print(
        " ".join(
            [
                "eta3_vendor_live_closure_smoke=ok",
                f"mode={mode}",
                f"status={run.get('status')}",
                f"closure_code={run.get('closure_code')}",
                f"probe_count={run.get('endpoint_probe_count')}",
                f"onboarding_status={run.get('onboarding_status')}",
                f"live_base_url_present={run.get('live_base_url_present')}",
                f"live_token_present={run.get('live_token_present')}",
            ]
        )
    )
    return 0


def _vendor_auth_ready() -> bool:
    auth_mode = os.getenv("QDATA_VENDOR_AUTH_MODE", "bearer")
    if auth_mode == "none":
        return True
    if auth_mode == "basic":
        return bool(os.getenv("QDATA_VENDOR_USERNAME") and os.getenv("QDATA_VENDOR_PASSWORD"))
    return bool(os.getenv("QDATA_VENDOR_TOKEN"))


def _bool_choice(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


if __name__ == "__main__":
    raise SystemExit(main())
