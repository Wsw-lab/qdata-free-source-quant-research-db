#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.zeta3_vendor_onboarding import (
    DEFAULT_CANARY_SYMBOLS,
    DEFAULT_DATASETS,
    DEFAULT_PRIMARY_SOURCE_CODE,
    DEFAULT_SOURCE_CODE,
    DEFAULT_WINDOWS,
    format_zeta3_rows,
    list_vendor_onboarding_results,
    list_vendor_onboarding_runs,
    run_vendor_onboarding,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Zeta-3 vendor onboarding.")
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
    parser.add_argument("--requested-by", default="zeta3")
    parser.add_argument("--trigger-mode", default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--no-require-active-profile", action="store_true")
    parser.add_argument("--no-require-contract", action="store_true")
    parser.add_argument("--no-canary", action="store_true")
    parser.add_argument("--no-gates", action="store_true")
    parser.add_argument("--run-benchmarks", action="store_true")
    parser.add_argument("--full-market", action="store_true")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--onboarding-code", default="")
    parser.add_argument("--gate-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--preflight-status", default="")
    parser.add_argument("--canary-status", default="")
    parser.add_argument("--gate-status", default="")
    parser.add_argument("--recommendation", default="")
    parser.add_argument("--recommended-role", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        row = run_vendor_onboarding(
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
            allow_live=args.allow_live,
            require_live=args.require_live,
            require_active_profile=not args.no_require_active_profile,
            require_contract=not args.no_require_contract,
            run_canary=not args.no_canary,
            run_gates=not args.no_gates,
            run_benchmarks=args.run_benchmarks,
            full_market=args.full_market,
        )
        _emit({"resource": "zeta3.vendor-onboarding", "row_count": 1, "rows": [row]}, format_zeta3_rows("run", [row]), args.json)
        return 0

    params = _params(args, include_run_defaults=False)
    if args.resource == "results":
        rows = list_vendor_onboarding_results(args.postgres_dsn, params, args.limit, args.offset)
        _emit({"resource": "zeta3.vendor-onboarding-results", "row_count": len(rows), "rows": rows}, format_zeta3_rows("results", rows), args.json)
        return 0
    rows = list_vendor_onboarding_runs(args.postgres_dsn, params, args.limit, args.offset)
    _emit({"resource": "zeta3.vendor-onboarding-runs", "row_count": len(rows), "rows": rows}, format_zeta3_rows("runs", rows), args.json)
    return 0


def _windows(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _params(args: argparse.Namespace, *, include_run_defaults: bool = True) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "run_code",
        "onboarding_code",
        "gate_code",
        "dataset_code",
        "source_code",
        "primary_source_code",
        "status",
        "preflight_status",
        "canary_status",
        "gate_status",
        "recommendation",
        "recommended_role",
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
        "requested_by": "zeta3",
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
