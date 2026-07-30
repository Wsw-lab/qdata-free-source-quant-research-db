#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.epsilon3_vendor_gate import (
    DEFAULT_DATASET_CODE,
    DEFAULT_PRIMARY_SOURCE_CODE,
    DEFAULT_SOURCE_CODE,
    DEFAULT_WINDOWS,
    format_epsilon3_rows,
    list_vendor_live_gate_runs,
    run_vendor_live_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Epsilon-3 vendor live token gate.")
    parser.add_argument("--resource", choices=["run", "runs"], default="runs")
    parser.add_argument("--dataset-code", default=DEFAULT_DATASET_CODE)
    parser.add_argument("--source-code", default=DEFAULT_SOURCE_CODE)
    parser.add_argument("--primary-source-code", default=DEFAULT_PRIMARY_SOURCE_CODE)
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--windows", default=",".join(str(item) for item in DEFAULT_WINDOWS))
    parser.add_argument("--symbols", default="")
    parser.add_argument("--fields", default="open,high,low,close,volume,amount")
    parser.add_argument("--shard-size", type=int, default=500)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--requested-by", default="epsilon3")
    parser.add_argument("--trigger-mode", default="manual")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--no-require-active-profile", action="store_true")
    parser.add_argument("--no-require-contract", action="store_true")
    parser.add_argument("--run-benchmarks", action="store_true")
    parser.add_argument("--no-db-field-mapping", action="store_true")
    parser.add_argument("--min-coverage-rate", type=float, default=0.95)
    parser.add_argument("--max-conflict-rate", type=float, default=0.005)
    parser.add_argument("--max-failure-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-latency-ms", type=float, default=5000)
    parser.add_argument("--min-rows-per-second", type=float, default=0)
    parser.add_argument("--gate-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--run-mode", default="")
    parser.add_argument("--review-code", default="")
    parser.add_argument("--recommendation", default="")
    parser.add_argument("--recommended-role", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run":
        row = run_vendor_live_gate(
            args.postgres_dsn,
            dataset_code=args.dataset_code,
            source_code=args.source_code,
            primary_source_code=args.primary_source_code,
            start_date=args.start_date,
            end_date=args.end_date,
            windows=_windows(args.windows),
            symbols=_csv(args.symbols),
            fields=_csv(args.fields),
            shard_size=args.shard_size,
            max_symbols=args.max_symbols,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            allow_live=args.allow_live,
            require_live=args.require_live,
            require_active_profile=not args.no_require_active_profile,
            require_contract=not args.no_require_contract,
            run_benchmarks=args.run_benchmarks,
            use_db_field_mapping=not args.no_db_field_mapping,
            min_coverage_rate=args.min_coverage_rate,
            max_conflict_rate=args.max_conflict_rate,
            max_failure_rate=args.max_failure_rate,
            max_p95_latency_ms=args.max_p95_latency_ms,
            min_rows_per_second=args.min_rows_per_second,
        )
        _emit({"resource": "epsilon3.vendor-live-gate", "row_count": 1, "rows": [row]}, format_epsilon3_rows("run", [row]), args.json)
        return 0

    rows = list_vendor_live_gate_runs(args.postgres_dsn, _params(args, include_run_defaults=False), args.limit, args.offset)
    _emit({"resource": "epsilon3.vendor-live-gate-runs", "row_count": len(rows), "rows": rows}, format_epsilon3_rows("runs", rows), args.json)
    return 0


def _windows(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _csv(value: str) -> list[str] | None:
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values or None


def _params(args: argparse.Namespace, *, include_run_defaults: bool = True) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "gate_code",
        "dataset_code",
        "source_code",
        "primary_source_code",
        "status",
        "run_mode",
        "requested_by",
        "trigger_mode",
        "review_code",
        "recommendation",
        "recommended_role",
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
        "dataset_code": DEFAULT_DATASET_CODE,
        "source_code": DEFAULT_SOURCE_CODE,
        "primary_source_code": DEFAULT_PRIMARY_SOURCE_CODE,
        "requested_by": "epsilon3",
        "trigger_mode": "manual",
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
