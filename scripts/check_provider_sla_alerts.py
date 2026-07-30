#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.ops.dashboard import ensure_sla_policy, evaluate_sla, write_alert_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Theta provider SLA and write alert events.")
    parser.add_argument("--policy-code", default="daily_bar_vendor_theta_sla")
    parser.add_argument("--policy-name", default="Daily bar vendor Theta SLA")
    parser.add_argument("--source-code", default="vendor_http")
    parser.add_argument("--dataset-code", default="daily_bar")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--min-vendor-score", type=float, default=90)
    parser.add_argument("--max-vendor-conflict-rate", type=float, default=0.005)
    parser.add_argument("--max-vendor-failure-rate", type=float, default=0.01)
    parser.add_argument("--max-vendor-latency-ms", type=float, default=5000)
    parser.add_argument("--max-provider-error-count", type=int, default=0)
    parser.add_argument("--alert-severity", choices=["low", "medium", "high", "critical"], default="high")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    start_date = args.trade_date or args.start_date
    end_date = args.trade_date or args.end_date
    if not start_date or not end_date:
        raise SystemExit("--trade-date or --start-date/--end-date is required")
    ensure_sla_policy(
        args.postgres_dsn,
        policy_code=args.policy_code,
        policy_name=args.policy_name,
        dataset_code=args.dataset_code,
        source_code=args.source_code,
        min_vendor_score=args.min_vendor_score,
        max_vendor_conflict_rate=args.max_vendor_conflict_rate,
        max_vendor_failure_rate=args.max_vendor_failure_rate,
        max_vendor_latency_ms=args.max_vendor_latency_ms,
        max_provider_error_count=args.max_provider_error_count,
        alert_severity=args.alert_severity,
        description="created by check_provider_sla_alerts.py",
    )
    alerts = evaluate_sla(
        args.postgres_dsn,
        start_date,
        end_date,
        policy_code=args.policy_code,
        dataset_code=args.dataset_code,
    )
    written = 0 if args.dry_run else write_alert_events(args.postgres_dsn, alerts)
    print(f"provider_sla_alerts policy={args.policy_code} source={args.source_code} dataset={args.dataset_code} start={start_date} end={end_date} alerts={len(alerts)} written={written} dry_run={args.dry_run}")
    for alert in alerts[:20]:
        print(
            "alert "
            f"type={alert['alert_type']} severity={alert['severity']} trade_date={alert.get('trade_date')} "
            f"metric={alert.get('metric_name')} value={alert.get('metric_value')} threshold={alert.get('threshold_value')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
