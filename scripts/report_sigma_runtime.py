#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.sigma_runtime import (
    collect_sigma_runtime,
    evaluate_capacity_alerts,
    format_capacity_alerts,
    format_runtime_collection,
    format_runtime_daily_report,
    generate_runtime_daily_report,
    record_runtime_log,
    record_runtime_metric,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect and report Sigma runtime observability data.")
    parser.add_argument(
        "--resource",
        choices=("collect", "log", "metric", "daily-report", "capacity-alerts"),
        default="collect",
    )
    parser.add_argument("--environment", default="local")
    parser.add_argument("--component", default="sigma")
    parser.add_argument("--service-name", default="")
    parser.add_argument("--severity", default="info")
    parser.add_argument("--event-type", default="runtime_event")
    parser.add_argument("--message", default="Sigma runtime event")
    parser.add_argument("--metric-name", default="")
    parser.add_argument("--metric-value", default="")
    parser.add_argument("--unit", default="count")
    parser.add_argument("--warning-threshold", default="")
    parser.add_argument("--critical-threshold", default="")
    parser.add_argument("--report-date", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    write_db = not args.dry_run
    if args.resource == "collect":
        payload = collect_sigma_runtime(
            args.postgres_dsn,
            environment=args.environment,
            report_date=args.report_date or None,
            write_db=write_db,
        )
        _emit(payload, format_runtime_collection(payload), args.json)
        return 0
    if args.resource == "log":
        payload = record_runtime_log(
            args.postgres_dsn,
            environment=args.environment,
            component=args.component,
            service_name=args.service_name or None,
            severity=args.severity,
            event_type=args.event_type,
            message=args.message,
            write_db=write_db,
        )
        _emit(payload, f"sigma_log log_code={payload.get('log_code')} severity={payload.get('severity')} message={payload.get('message')}", args.json)
        return 0
    if args.resource == "metric":
        if not args.metric_name or args.metric_value == "":
            parser.error("--metric-name and --metric-value are required for --resource metric")
        payload = record_runtime_metric(
            args.postgres_dsn,
            environment=args.environment,
            component=args.component,
            service_name=args.service_name or None,
            metric_name=args.metric_name,
            metric_value=args.metric_value,
            unit=args.unit,
            warning_threshold=args.warning_threshold or None,
            critical_threshold=args.critical_threshold or None,
            write_db=write_db,
        )
        _emit(
            payload,
            (
                f"sigma_metric metric_code={payload.get('metric_code')} component={payload.get('component')} "
                f"metric={payload.get('metric_name')} value={payload.get('metric_value')} status={payload.get('status')}"
            ),
            args.json,
        )
        return 0
    if args.resource == "daily-report":
        payload = generate_runtime_daily_report(
            args.postgres_dsn,
            environment=args.environment,
            report_date=args.report_date or None,
            write_db=write_db,
        )
        _emit(payload, format_runtime_daily_report(payload), args.json)
        return 0
    alerts = evaluate_capacity_alerts(args.postgres_dsn, environment=args.environment, write_db=write_db)
    _emit(alerts, format_capacity_alerts(alerts), args.json)
    return 0


def _emit(payload, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
