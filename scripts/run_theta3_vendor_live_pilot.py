#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.epsilon3_vendor_gate import DEFAULT_PRIMARY_SOURCE_CODE, DEFAULT_SOURCE_CODE
from qdata.theta3_vendor_live_pilot import (
    format_theta3_rows,
    list_vendor_live_pilot_results,
    list_vendor_live_pilots,
    run_vendor_live_pilot,
)
from qdata.zeta3_vendor_onboarding import DEFAULT_CANARY_SYMBOLS, DEFAULT_DATASETS, DEFAULT_WINDOWS


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Theta-3 vendor live pilot.")
    parser.add_argument("--resource", choices=["run", "runs", "results"], default="runs")
    parser.add_argument("--source-code", default=DEFAULT_SOURCE_CODE)
    parser.add_argument("--primary-source-code", default=DEFAULT_PRIMARY_SOURCE_CODE)
    parser.add_argument("--dataset-codes", default=",".join(DEFAULT_DATASETS))
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--windows", default=",".join(str(item) for item in DEFAULT_WINDOWS))
    parser.add_argument("--canary-symbols", default=",".join(DEFAULT_CANARY_SYMBOLS))
    parser.add_argument("--shard-size", type=int, default=500)
    parser.add_argument("--max-symbols", type=int, default=10)
    parser.add_argument("--requested-by", default="theta3")
    parser.add_argument("--trigger-mode", default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--pilot-scope", choices=["canary", "full_market"], default="canary")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--allow-profile-write", action="store_true")
    parser.add_argument("--activate-profile", action="store_true")
    parser.add_argument("--enable-profile-datasets", action="store_true")
    parser.add_argument("--commercial-contract-ref", default=os.getenv("QDATA_VENDOR_CONTRACT_REF", ""))
    parser.add_argument("--redistribution-allowed", choices=["unknown", "true", "false"], default="unknown")
    parser.add_argument("--rate-limit-per-min", type=int, default=_int_env("QDATA_VENDOR_RATE_LIMIT_PER_MIN"))
    parser.add_argument("--no-require-active-profile", action="store_true")
    parser.add_argument("--no-require-contract", action="store_true")
    parser.add_argument("--run-endpoint-probes", action="store_true")
    parser.add_argument("--no-endpoint-probes", action="store_true")
    parser.add_argument("--no-onboarding", action="store_true")
    parser.add_argument("--run-benchmarks", action="store_true")
    parser.add_argument("--full-market", action="store_true")
    parser.add_argument("--pilot-code", default="")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--result-code", default="")
    parser.add_argument("--closure-code", default="")
    parser.add_argument("--probe-code", default="")
    parser.add_argument("--gate-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--closure-status", default="")
    parser.add_argument("--endpoint-status", default="")
    parser.add_argument("--schema-status", default="")
    parser.add_argument("--onboarding-status", default="")
    parser.add_argument("--gate-status", default="")
    parser.add_argument("--benchmark-status", default="")
    parser.add_argument("--signoff-status", default="")
    parser.add_argument("--recommendation", default="")
    parser.add_argument("--recommended-role", default="")
    parser.add_argument("--risk-level", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        row = run_vendor_live_pilot(
            args.postgres_dsn,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            dataset_codes=_csv(args.dataset_codes),
            start_date=args.start_date,
            end_date=args.end_date,
            windows=_windows(args.windows),
            canary_symbols=_csv(args.canary_symbols),
            shard_size=args.shard_size,
            max_symbols=args.max_symbols,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            pilot_scope=args.pilot_scope,
            allow_live=args.allow_live,
            require_live=args.require_live,
            allow_profile_write=args.allow_profile_write,
            activate_profile=args.activate_profile,
            enable_profile_datasets=args.enable_profile_datasets,
            commercial_contract_ref=args.commercial_contract_ref or None,
            redistribution_allowed=_bool_choice(args.redistribution_allowed),
            rate_limit_per_min=args.rate_limit_per_min,
            require_active_profile=not args.no_require_active_profile,
            require_contract=not args.no_require_contract,
            run_endpoint_probes=args.run_endpoint_probes or not args.no_endpoint_probes,
            run_onboarding=not args.no_onboarding,
            run_benchmarks=args.run_benchmarks,
            full_market=args.full_market,
        )
        _emit({"resource": "theta3.vendor-live-pilot", "row_count": 1, "rows": [row]}, format_theta3_rows("run", [row]), args.json)
        return 0

    params = _params(args, include_run_defaults=False)
    if args.resource == "results":
        rows = list_vendor_live_pilot_results(args.postgres_dsn, params, args.limit, args.offset)
        _emit({"resource": "theta3.vendor-live-pilot-results", "row_count": len(rows), "rows": rows}, format_theta3_rows("results", rows), args.json)
        return 0
    rows = list_vendor_live_pilots(args.postgres_dsn, params, args.limit, args.offset)
    _emit({"resource": "theta3.vendor-live-pilots", "row_count": len(rows), "rows": rows}, format_theta3_rows("runs", rows), args.json)
    return 0


def _windows(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool_choice(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return int(value)


def _params(args: argparse.Namespace, *, include_run_defaults: bool = True) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "pilot_code",
        "run_code",
        "result_code",
        "closure_code",
        "probe_code",
        "gate_code",
        "dataset_code",
        "source_code",
        "primary_source_code",
        "status",
        "closure_status",
        "endpoint_status",
        "schema_status",
        "onboarding_status",
        "gate_status",
        "benchmark_status",
        "signoff_status",
        "recommendation",
        "recommended_role",
        "risk_level",
        "pilot_scope",
        "requested_by",
        "trigger_mode",
        "environment",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if not include_run_defaults and _is_run_default_filter(name, value):
            continue
        if value:
            params[name] = [value]
    return params


def _is_run_default_filter(name: str, value: str) -> bool:
    defaults = {
        "source_code": DEFAULT_SOURCE_CODE,
        "primary_source_code": DEFAULT_PRIMARY_SOURCE_CODE,
        "pilot_scope": "canary",
        "requested_by": "theta3",
        "trigger_mode": "manual",
        "environment": "local",
        "start_date": "2024-01-04",
        "end_date": "2024-01-04",
    }
    return defaults.get(name) == value


def _emit(payload: dict, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
