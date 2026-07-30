#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.epsilon3_vendor_gate import run_vendor_live_gate
from qdata.exceptions import QDataValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Epsilon-3 vendor live token gate.")
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--windows", default="5,20,60")
    parser.add_argument("--symbols", default="600519.SH,000001.SZ")
    parser.add_argument("--requested-by", default="epsilon3-smoke")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--run-benchmarks", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    live_env_present = bool(os.getenv("QDATA_VENDOR_BASE_URL")) and _vendor_auth_ready()
    if args.require_live and not live_env_present:
        raise SystemExit("epsilon3_vendor_live_gate_smoke=failed reason=missing_vendor_live_env")
    try:
        gate = run_vendor_live_gate(
            args.postgres_dsn,
            start_date=args.start_date,
            end_date=args.end_date,
            windows=[int(item.strip()) for item in args.windows.split(",") if item.strip()],
            symbols=[item.strip().upper() for item in args.symbols.split(",") if item.strip()],
            requested_by=args.requested_by,
            trigger_mode="smoke",
            allow_live=args.allow_live and live_env_present,
            require_live=args.require_live,
            require_active_profile=False if not live_env_present else True,
            require_contract=False if not live_env_present else True,
            run_benchmarks=args.run_benchmarks and args.allow_live and live_env_present,
        )
    except QDataValidationError as exc:
        raise SystemExit(f"epsilon3_vendor_live_gate_smoke=failed reason={exc}") from exc
    mode = "live" if gate.get("run_mode") == "live" else "blocked"
    if args.allow_live and live_env_present and gate.get("status") not in {"success", "warning"}:
        raise SystemExit(f"epsilon3_vendor_live_gate_smoke=failed status={gate.get('status')} error={gate.get('error_message')}")
    print(
        " ".join(
            [
                "epsilon3_vendor_live_gate_smoke=ok",
                f"mode={mode}",
                f"status={gate.get('status')}",
                f"gate_code={gate.get('gate_code')}",
                f"live_base_url_present={gate.get('live_base_url_present')}",
                f"live_token_present={gate.get('live_token_present')}",
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
