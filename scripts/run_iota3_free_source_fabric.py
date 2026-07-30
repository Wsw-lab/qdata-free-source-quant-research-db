#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.iota3_free_source_fabric import (
    DEFAULT_CANARY_SYMBOLS,
    DEFAULT_DATASETS,
    DEFAULT_SOURCE_CODES,
    format_iota3_rows,
    free_source_catalog,
    list_free_source_fabric_results,
    list_free_source_fabric_runs,
    run_free_source_fabric,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or report Iota-3 free source fabric.")
    parser.add_argument("--resource", choices=["run", "runs", "results", "catalog"], default="runs")
    parser.add_argument("--source-codes", default=",".join(DEFAULT_SOURCE_CODES))
    parser.add_argument("--dataset-codes", default=",".join(DEFAULT_DATASETS))
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--canary-symbols", default=",".join(DEFAULT_CANARY_SYMBOLS))
    parser.add_argument("--requested-by", default="iota3")
    parser.add_argument("--trigger-mode", default="manual")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--fabric-scope", choices=["canary", "full_market"], default="canary")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--require-external", action="store_true")
    parser.add_argument("--require-commercial-clearance", action="store_true")
    parser.add_argument("--min-source-count", type=int, default=2)
    parser.add_argument("--min-coverage-rate", type=float, default=0.95)
    parser.add_argument("--max-conflict-rate-bps", type=float, default=5.0)
    parser.add_argument("--csv-mirror-close-offset-bps", type=float, default=0.0)
    parser.add_argument("--fabric-code", default="")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--result-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--coverage-status", default="")
    parser.add_argument("--consistency-status", default="")
    parser.add_argument("--license-status", default="")
    parser.add_argument("--freshness-status", default="")
    parser.add_argument("--recommendation", default="")
    parser.add_argument("--recommended-role", default="")
    parser.add_argument("--risk-level", default="")
    parser.add_argument("--baseline-source-code", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "catalog":
        rows = free_source_catalog()
        _emit({"resource": "iota3.free-source-catalog", "row_count": len(rows), "rows": rows}, format_iota3_rows("catalog", rows), args.json)
        return 0

    if args.resource == "run":
        row = run_free_source_fabric(
            args.postgres_dsn,
            source_codes=_csv(args.source_codes),
            dataset_codes=_csv(args.dataset_codes),
            start_date=args.start_date,
            end_date=args.end_date,
            canary_symbols=_csv(args.canary_symbols),
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            environment=args.environment,
            fabric_scope=args.fabric_scope,
            allow_external=args.allow_external,
            require_external=args.require_external,
            require_commercial_clearance=args.require_commercial_clearance,
            min_source_count=args.min_source_count,
            min_coverage_rate=args.min_coverage_rate,
            max_conflict_rate_bps=args.max_conflict_rate_bps,
            provider_kwargs_by_source=_provider_kwargs(args),
        )
        _emit({"resource": "iota3.free-source-fabric", "row_count": 1, "rows": [row]}, format_iota3_rows("run", [row]), args.json)
        return 0

    params = _params(args, include_run_defaults=False)
    if args.resource == "results":
        rows = list_free_source_fabric_results(args.postgres_dsn, params, args.limit, args.offset)
        _emit({"resource": "iota3.free-source-fabric-results", "row_count": len(rows), "rows": rows}, format_iota3_rows("results", rows), args.json)
        return 0
    rows = list_free_source_fabric_runs(args.postgres_dsn, params, args.limit, args.offset)
    _emit({"resource": "iota3.free-source-fabric-runs", "row_count": len(rows), "rows": rows}, format_iota3_rows("runs", rows), args.json)
    return 0


def _provider_kwargs(args: argparse.Namespace) -> dict[str, dict]:
    kwargs: dict[str, dict] = {}
    if args.csv_mirror_close_offset_bps:
        kwargs["csv_mirror"] = {"close_offset_bps": args.csv_mirror_close_offset_bps}
    return kwargs


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _params(args: argparse.Namespace, *, include_run_defaults: bool = True) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "fabric_code",
        "run_code",
        "result_code",
        "dataset_code",
        "source_code",
        "status",
        "coverage_status",
        "consistency_status",
        "license_status",
        "freshness_status",
        "recommendation",
        "recommended_role",
        "risk_level",
        "baseline_source_code",
        "requested_by",
        "trigger_mode",
        "environment",
        "fabric_scope",
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
        "requested_by": "iota3",
        "trigger_mode": "manual",
        "environment": "local",
        "fabric_scope": "canary",
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
