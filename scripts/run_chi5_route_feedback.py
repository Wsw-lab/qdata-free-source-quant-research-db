#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.chi5_route_feedback import (
    format_chi5_rows,
    list_source_route_circuit_breakers,
    list_source_route_health_snapshots,
    list_source_route_recovery_probes,
    run_source_route_feedback_monitor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Chi-5 source route feedback monitor.")
    parser.add_argument("--resource", choices=["check", "health", "circuits", "probes"], default="check")
    parser.add_argument("--requested-by", default="chi5-cli")
    parser.add_argument("--trigger-mode", choices=["", "manual", "scheduled", "once", "smoke", "api"], default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--lookback-hours", type=int, default=int(os.getenv("QDATA_CHI5_LOOKBACK_HOURS", "24")))
    parser.add_argument("--min-request-count", type=int, default=int(os.getenv("QDATA_CHI5_MIN_REQUEST_COUNT", "1")))
    parser.add_argument("--min-success-rate", type=float, default=float(os.getenv("QDATA_CHI5_MIN_SUCCESS_RATE", "0.95")))
    parser.add_argument("--max-failure-rate", type=float, default=float(os.getenv("QDATA_CHI5_MAX_FAILURE_RATE", "0.1")))
    parser.add_argument("--max-fallback-rate", type=float, default=float(os.getenv("QDATA_CHI5_MAX_FALLBACK_RATE", "0.2")))
    parser.add_argument("--max-empty-rate", type=float, default=float(os.getenv("QDATA_CHI5_MAX_EMPTY_RATE", "0.2")))
    parser.add_argument("--max-latency-p95-ms", type=float, default=float(os.getenv("QDATA_CHI5_MAX_LATENCY_P95_MS", "2000")))
    parser.add_argument("--circuit-open-minutes", type=int, default=int(os.getenv("QDATA_CHI5_CIRCUIT_OPEN_MINUTES", "30")))
    parser.add_argument("--recovery-probe-min-success-rate", type=float, default=float(os.getenv("QDATA_CHI5_RECOVERY_PROBE_MIN_SUCCESS_RATE", "1.0")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--circuit-status", default="")
    parser.add_argument("--circuit-action", default="")
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--breaker-code", default="")
    parser.add_argument("--probe-code", default="")
    parser.add_argument("--decision-summary", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "check":
        result = run_source_route_feedback_monitor(
            args.postgres_dsn,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode or "manual",
            environment=args.environment or "local",
            lookback_hours=args.lookback_hours,
            min_request_count=args.min_request_count,
            min_success_rate=args.min_success_rate,
            max_failure_rate=args.max_failure_rate,
            max_fallback_rate=args.max_fallback_rate,
            max_empty_rate=args.max_empty_rate,
            max_latency_p95_ms=args.max_latency_p95_ms,
            circuit_open_minutes=args.circuit_open_minutes,
            recovery_probe_min_success_rate=args.recovery_probe_min_success_rate,
            write_db=not args.dry_run,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, default=str, indent=2, sort_keys=True))
        else:
            print(
                "chi5_route_feedback "
                f"status={result.get('status')} snapshots={result.get('snapshot_count')} "
                f"healthy={result.get('healthy_count')} degraded={result.get('degraded_count')} "
                f"open_circuits={result.get('circuit_open_count')} probes={result.get('recovery_probe_count')} "
                f"recovered={result.get('recovered_probe_count')}"
            )
        return 0

    params = _params(args)
    if args.resource == "health":
        rows = list_source_route_health_snapshots(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "circuits":
        rows = list_source_route_circuit_breakers(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_source_route_recovery_probes(args.postgres_dsn, params, args.limit, args.offset)
    if args.json:
        print(json.dumps({"resource": args.resource, "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_chi5_rows(args.resource, rows))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for key in (
        "dataset_code",
        "source_code",
        "status",
        "circuit_status",
        "circuit_action",
        "snapshot_code",
        "breaker_code",
        "probe_code",
        "decision_summary",
        "start_date",
        "end_date",
        "trigger_mode",
        "environment",
    ):
        value = getattr(args, key)
        if value:
            params[key] = [str(value)]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
