#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.exceptions import QDataValidationError
from qdata.zeta3_vendor_onboarding import DEFAULT_DATASETS, run_vendor_onboarding


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Zeta-3 vendor onboarding.")
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--dataset-codes", default=",".join(DEFAULT_DATASETS))
    parser.add_argument("--windows", default="5,20,60")
    parser.add_argument("--canary-symbols", default="600519.SH,000001.SZ")
    parser.add_argument("--requested-by", default="zeta3-smoke")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--run-benchmarks", action="store_true")
    parser.add_argument("--full-market", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    live_env_present = bool(os.getenv("QDATA_VENDOR_BASE_URL")) and _vendor_auth_ready()
    if args.require_live and not live_env_present:
        raise SystemExit("zeta3_vendor_onboarding_smoke=failed reason=missing_vendor_live_env")
    try:
        run = run_vendor_onboarding(
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
            require_active_profile=False if not live_env_present else True,
            require_contract=False if not live_env_present else True,
            run_benchmarks=args.run_benchmarks and args.allow_live and live_env_present,
            full_market=args.full_market,
        )
    except QDataValidationError as exc:
        raise SystemExit(f"zeta3_vendor_onboarding_smoke=failed reason={exc}") from exc
    mode = "live" if run.get("allow_live") else "blocked"
    if args.allow_live and live_env_present and run.get("status") not in {"success", "warning"}:
        raise SystemExit(f"zeta3_vendor_onboarding_smoke=failed status={run.get('status')} error={run.get('error_message')}")
    print(
        " ".join(
            [
                "zeta3_vendor_onboarding_smoke=ok",
                f"mode={mode}",
                f"status={run.get('status')}",
                f"run_code={run.get('run_code')}",
                f"dataset_count={len(run.get('dataset_codes') or [])}",
                f"gate_count={len(run.get('gate_codes') or [])}",
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


if __name__ == "__main__":
    raise SystemExit(main())
