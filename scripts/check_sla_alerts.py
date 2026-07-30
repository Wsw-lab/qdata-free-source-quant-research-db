#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.ops.dashboard import ensure_sla_policy, evaluate_sla, write_alert_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Zeta SLA policies and optionally write alert events.")
    parser.add_argument("--policy-code", default="daily_market_csv_all_zeta_sla")
    parser.add_argument("--policy-name", default="Daily market Zeta SLA")
    parser.add_argument("--ensure-policy", action="store_true")
    parser.add_argument("--job-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--target-finish-time", default="")
    parser.add_argument("--min-completeness", type=float, default=None)
    parser.add_argument("--max-conflict-rate", type=float, default=None)
    parser.add_argument("--max-api-error-rate", type=float, default=None)
    parser.add_argument("--max-duration-ms", type=int, default=None)
    parser.add_argument("--min-vendor-score", type=float, default=None)
    parser.add_argument("--max-vendor-conflict-rate", type=float, default=None)
    parser.add_argument("--max-vendor-failure-rate", type=float, default=None)
    parser.add_argument("--max-vendor-latency-ms", type=float, default=None)
    parser.add_argument("--max-provider-error-count", type=int, default=None)
    parser.add_argument("--alert-severity", choices=["low", "medium", "high", "critical"], default="high")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    start_date, end_date = _date_window(args.trade_date, args.start_date, args.end_date)
    if args.ensure_policy:
        ensure_sla_policy(
            args.postgres_dsn,
            policy_code=args.policy_code,
            policy_name=args.policy_name,
            dataset_code=args.dataset_code or None,
            job_code=args.job_code or None,
            source_code=args.source_code or None,
            target_finish_time=args.target_finish_time or None,
            min_completeness=args.min_completeness,
            max_conflict_rate=args.max_conflict_rate,
            max_api_error_rate=args.max_api_error_rate,
            max_duration_ms=args.max_duration_ms,
            min_vendor_score=args.min_vendor_score,
            max_vendor_conflict_rate=args.max_vendor_conflict_rate,
            max_vendor_failure_rate=args.max_vendor_failure_rate,
            max_vendor_latency_ms=args.max_vendor_latency_ms,
            max_provider_error_count=args.max_provider_error_count,
            alert_severity=args.alert_severity,
            description="created by check_sla_alerts.py",
        )
    alerts = evaluate_sla(
        args.postgres_dsn,
        start_date,
        end_date,
        policy_code=args.policy_code,
        job_code=args.job_code or None,
        dataset_code=args.dataset_code or None,
    )
    written = 0 if args.dry_run else write_alert_events(args.postgres_dsn, alerts)
    if args.json:
        print(json.dumps({"alerts": alerts, "written": written, "dry_run": args.dry_run}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(f"sla_alerts policy={args.policy_code} start={start_date} end={end_date} alerts={len(alerts)} written={written} dry_run={args.dry_run}")
        for alert in alerts[:20]:
            print(
                "alert "
                f"type={alert['alert_type']} severity={alert['severity']} trade_date={alert.get('trade_date')} "
                f"metric={alert.get('metric_name')} value={alert.get('metric_value')} threshold={alert.get('threshold_value')} "
                f"message={alert['message']}"
            )
    return 0


def _date_window(trade_date: str, start_date: str, end_date: str) -> tuple[str, str]:
    if trade_date:
        return trade_date, trade_date
    if start_date and end_date:
        return start_date, end_date
    today = date.today().isoformat()
    return today, today


if __name__ == "__main__":
    raise SystemExit(main())
