#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.lambda_worker import WORKER_TASKS, format_worker_report, run_lambda_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Lambda background automation worker tasks.")
    parser.add_argument("--task", choices=WORKER_TASKS, action="append", help="Task to run. Repeat for multiple tasks; defaults to all tasks.")
    parser.add_argument("--once", action="store_true", help="Mark trigger mode as once.")
    parser.add_argument("--trigger-mode", choices=["manual", "scheduled", "once", "smoke"], default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--channel-code", default="")
    parser.add_argument("--alert-limit", type=int, default=50)
    parser.add_argument("--schedule-code", default="")
    parser.add_argument("--include-manual-schedules", action="store_true")
    parser.add_argument("--cost-per-request", type=float, default=1.0)
    parser.add_argument("--cost-per-1000-rows", type=float, default=0.1)
    parser.add_argument("--free-source-lookback-hours", type=int, default=72)
    parser.add_argument("--free-source-max-actions", type=int, default=50)
    parser.add_argument("--free-source-min-retry-score", type=float, default=75.0)
    parser.add_argument("--no-free-source-alerts", action="store_true")
    parser.add_argument("--mu5-max-actions", type=int, default=int(os.getenv("QDATA_MU5_FREE_SOURCE_MAX_ACTIONS", "20")))
    parser.add_argument("--mu5-start-date", default=os.getenv("QDATA_MU5_FREE_SOURCE_CANARY_START_DATE", "2024-01-04"))
    parser.add_argument("--mu5-end-date", default=os.getenv("QDATA_MU5_FREE_SOURCE_CANARY_END_DATE", "2024-01-04"))
    parser.add_argument("--mu5-no-retry-canary", action="store_true")
    parser.add_argument("--mu5-no-manual-review", action="store_true")
    parser.add_argument("--mu5-no-wecom", action="store_true")
    parser.add_argument("--mu5-allow-wecom-external", action="store_true", default=os.getenv("QDATA_MU5_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--mu5-baostock-timeout-seconds", type=float, default=float(os.getenv("QDATA_MU5_BAOSTOCK_TIMEOUT_SECONDS", "3")))
    parser.add_argument("--nu5-lookback-hours", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--nu5-approval-sla-hours", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_APPROVAL_SLA_HOURS", "4")))
    parser.add_argument("--nu5-max-backlog-actions", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_MAX_BACKLOG_ACTIONS", "50")))
    parser.add_argument("--nu5-max-failure-rate", type=float, default=float(os.getenv("QDATA_NU5_FREE_SOURCE_MAX_FAILURE_RATE", "0.5")))
    parser.add_argument("--nu5-max-stale-minutes", type=int, default=int(os.getenv("QDATA_NU5_FREE_SOURCE_MAX_STALE_MINUTES", "90")))
    parser.add_argument("--xi5-lookback-days", type=int, default=int(os.getenv("QDATA_XI5_FREE_SOURCE_LOOKBACK_DAYS", "30")))
    parser.add_argument("--xi5-min-validator-score", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_VALIDATOR_SCORE", "55")))
    parser.add_argument("--xi5-min-backup-score", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_BACKUP_SCORE", "75")))
    parser.add_argument("--xi5-min-primary-score", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_PRIMARY_SCORE", "90")))
    parser.add_argument("--xi5-min-coverage-rate", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MIN_COVERAGE_RATE", "0.95")))
    parser.add_argument("--xi5-max-conflict-rate-bps", type=float, default=float(os.getenv("QDATA_XI5_FREE_SOURCE_MAX_CONFLICT_RATE_BPS", "5")))
    parser.add_argument("--omicron5-min-sla-uptime-pct", type=float, default=float(os.getenv("QDATA_OMICRON5_MIN_SLA_UPTIME_PCT", "99.5")))
    parser.add_argument("--omicron5-min-rate-limit-per-min", type=int, default=int(os.getenv("QDATA_OMICRON5_MIN_RATE_LIMIT_PER_MIN", "60")))
    parser.add_argument("--omicron5-require-live-evidence", action="store_true", default=os.getenv("QDATA_OMICRON5_REQUIRE_LIVE_EVIDENCE", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--pi5-promotion-scope", choices=["canary", "full_market"], default=os.getenv("QDATA_PI5_PROMOTION_SCOPE", "full_market"))
    parser.add_argument("--pi5-no-full-market-required", action="store_true", default=os.getenv("QDATA_PI5_REQUIRE_FULL_MARKET", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--pi5-no-signoff-required", action="store_true", default=os.getenv("QDATA_PI5_REQUIRE_SIGNOFF", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--pi5-apply-routing", action="store_true", default=os.getenv("QDATA_PI5_APPLY_ROUTING", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--pi5-target-priority", type=int, default=int(os.getenv("QDATA_PI5_TARGET_PRIORITY", "0")))
    parser.add_argument("--rho5-monitor-scope", choices=["shadow", "post_promotion", "rollback_drill"], default=os.getenv("QDATA_RHO5_MONITOR_SCOPE", "post_promotion"))
    parser.add_argument("--rho5-no-applied-promotion-required", action="store_true", default=os.getenv("QDATA_RHO5_REQUIRE_APPLIED_PROMOTION", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--rho5-apply-rollback", action="store_true", default=os.getenv("QDATA_RHO5_APPLY_ROLLBACK", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--rho5-shadow-window-hours", type=int, default=int(os.getenv("QDATA_RHO5_SHADOW_WINDOW_HOURS", "24")))
    parser.add_argument("--rho5-max-conflict-rate-bps", type=float, default=float(os.getenv("QDATA_RHO5_MAX_CONFLICT_RATE_BPS", "5")))
    parser.add_argument("--rho5-max-failure-rate", type=float, default=float(os.getenv("QDATA_RHO5_MAX_FAILURE_RATE", "0.01")))
    parser.add_argument("--rho5-max-stale-minutes", type=int, default=int(os.getenv("QDATA_RHO5_MAX_STALE_MINUTES", "90")))
    parser.add_argument("--sigma5-monitor-scope", choices=["primary_source", "all_datasets", "full_market"], default=os.getenv("QDATA_SIGMA5_MONITOR_SCOPE", "primary_source"))
    parser.add_argument("--sigma5-lookback-hours", type=int, default=int(os.getenv("QDATA_SIGMA5_LOOKBACK_HOURS", "24")))
    parser.add_argument("--sigma5-capacity-window-days", type=int, default=int(os.getenv("QDATA_SIGMA5_CAPACITY_WINDOW_DAYS", "7")))
    parser.add_argument("--sigma5-min-success-rate", type=float, default=float(os.getenv("QDATA_SIGMA5_MIN_SUCCESS_RATE", "0.995")))
    parser.add_argument("--sigma5-max-error-rate", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_ERROR_RATE", "0.005")))
    parser.add_argument("--sigma5-max-latency-p95-ms", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_LATENCY_P95_MS", "2000")))
    parser.add_argument("--sigma5-max-timeout-rate", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_TIMEOUT_RATE", "0.01")))
    parser.add_argument("--sigma5-max-cost-units", type=float, default=float(os.getenv("QDATA_SIGMA5_MAX_COST_UNITS", "500")))
    parser.add_argument("--sigma5-max-scheduler-lag-minutes", type=int, default=int(os.getenv("QDATA_SIGMA5_MAX_SCHEDULER_LAG_MINUTES", "90")))
    parser.add_argument("--sigma5-max-backlog-count", type=int, default=int(os.getenv("QDATA_SIGMA5_MAX_BACKLOG_COUNT", "50")))
    parser.add_argument("--sigma5-max-post-promotion-no-applied-count", type=int, default=int(os.getenv("QDATA_SIGMA5_MAX_POST_PROMOTION_NO_APPLIED_COUNT", "0")))
    parser.add_argument("--tau5-optimization-scope", choices=["primary_source", "all_datasets", "full_market"], default=os.getenv("QDATA_TAU5_OPTIMIZATION_SCOPE", "primary_source"))
    parser.add_argument("--tau5-lookback-hours", type=int, default=int(os.getenv("QDATA_TAU5_LOOKBACK_HOURS", "24")))
    parser.add_argument("--tau5-forecast-window-days", type=int, default=int(os.getenv("QDATA_TAU5_FORECAST_WINDOW_DAYS", "30")))
    parser.add_argument("--tau5-monthly-budget-amount", type=float, default=float(os.getenv("QDATA_TAU5_MONTHLY_BUDGET_AMOUNT", "10000")))
    parser.add_argument("--tau5-max-budget-usage-pct", type=float, default=float(os.getenv("QDATA_TAU5_MAX_BUDGET_USAGE_PCT", "0.85")))
    parser.add_argument("--tau5-max-daily-quota-usage-pct", type=float, default=float(os.getenv("QDATA_TAU5_MAX_DAILY_QUOTA_USAGE_PCT", "0.85")))
    parser.add_argument("--tau5-max-monthly-quota-usage-pct", type=float, default=float(os.getenv("QDATA_TAU5_MAX_MONTHLY_QUOTA_USAGE_PCT", "0.85")))
    parser.add_argument("--tau5-min-stability-score", type=float, default=float(os.getenv("QDATA_TAU5_MIN_STABILITY_SCORE", "70")))
    parser.add_argument("--tau5-cost-safety-margin-pct", type=float, default=float(os.getenv("QDATA_TAU5_COST_SAFETY_MARGIN_PCT", "0.15")))
    parser.add_argument("--tau5-default-unit-cost", type=float, default=float(os.getenv("QDATA_TAU5_DEFAULT_UNIT_COST", "0.01")))
    parser.add_argument("--tau5-stress-multiplier", type=float, action="append", default=[])
    parser.add_argument("--upsilon5-execution-scope", choices=["primary_source", "all_datasets", "full_market"], default=os.getenv("QDATA_UPSILON5_EXECUTION_SCOPE", "primary_source"))
    parser.add_argument("--upsilon5-execution-mode", choices=["review_only", "dry_run", "apply"], default=os.getenv("QDATA_UPSILON5_EXECUTION_MODE", "review_only"))
    parser.add_argument("--upsilon5-approval-policy", choices=["manual_required", "auto_if_optimized"], default=os.getenv("QDATA_UPSILON5_APPROVAL_POLICY", "manual_required"))
    parser.add_argument("--upsilon5-approval-status", choices=["not_required", "pending", "approved", "rejected", "blocked"], default=os.getenv("QDATA_UPSILON5_APPROVAL_STATUS", "pending"))
    parser.add_argument("--upsilon5-rollout-policy", choices=["review_only", "canary", "gradual", "full"], default=os.getenv("QDATA_UPSILON5_ROLLOUT_POLICY", "gradual"))
    parser.add_argument("--upsilon5-rollout-stage", type=float, action="append", default=[])
    parser.add_argument("--upsilon5-current-stage-sequence", type=int, default=int(os.getenv("QDATA_UPSILON5_CURRENT_STAGE_SEQUENCE", "1")))
    parser.add_argument("--upsilon5-max-initial-primary-weight-pct", type=float, default=float(os.getenv("QDATA_UPSILON5_MAX_INITIAL_PRIMARY_WEIGHT_PCT", "10")))
    parser.add_argument("--upsilon5-allow-over-budget", action="store_true", default=os.getenv("QDATA_UPSILON5_ALLOW_OVER_BUDGET", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--upsilon5-allow-quota-risk", action="store_true", default=os.getenv("QDATA_UPSILON5_ALLOW_QUOTA_RISK", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--upsilon5-rollback-requested", action="store_true", default=os.getenv("QDATA_UPSILON5_ROLLBACK_REQUESTED", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--chi5-lookback-hours", type=int, default=int(os.getenv("QDATA_CHI5_LOOKBACK_HOURS", "24")))
    parser.add_argument("--chi5-min-request-count", type=int, default=int(os.getenv("QDATA_CHI5_MIN_REQUEST_COUNT", "1")))
    parser.add_argument("--chi5-min-success-rate", type=float, default=float(os.getenv("QDATA_CHI5_MIN_SUCCESS_RATE", "0.95")))
    parser.add_argument("--chi5-max-failure-rate", type=float, default=float(os.getenv("QDATA_CHI5_MAX_FAILURE_RATE", "0.1")))
    parser.add_argument("--chi5-max-fallback-rate", type=float, default=float(os.getenv("QDATA_CHI5_MAX_FALLBACK_RATE", "0.2")))
    parser.add_argument("--chi5-max-empty-rate", type=float, default=float(os.getenv("QDATA_CHI5_MAX_EMPTY_RATE", "0.2")))
    parser.add_argument("--chi5-max-latency-p95-ms", type=float, default=float(os.getenv("QDATA_CHI5_MAX_LATENCY_P95_MS", "2000")))
    parser.add_argument("--chi5-circuit-open-minutes", type=int, default=int(os.getenv("QDATA_CHI5_CIRCUIT_OPEN_MINUTES", "30")))
    parser.add_argument("--chi5-recovery-probe-min-success-rate", type=float, default=float(os.getenv("QDATA_CHI5_RECOVERY_PROBE_MIN_SUCCESS_RATE", "1.0")))
    parser.add_argument("--psi5-route-lookback-hours", type=int, default=int(os.getenv("QDATA_PSI5_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--psi5-route-max-actions", type=int, default=int(os.getenv("QDATA_PSI5_ROUTE_MAX_ACTIONS", "50")))
    parser.add_argument("--psi5-route-execution-mode", choices=["dry_run", "execute"], default=os.getenv("QDATA_PSI5_ROUTE_EXECUTION_MODE", "execute"))
    parser.add_argument("--psi5-route-approve-high-risk", action="store_true", default=os.getenv("QDATA_PSI5_ROUTE_APPROVE_HIGH_RISK", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--psi5-route-approved-by", default=os.getenv("QDATA_PSI5_ROUTE_APPROVED_BY", ""))
    parser.add_argument("--psi5-route-owner", default=os.getenv("QDATA_PSI5_ROUTE_OWNER", "platform-ops"))
    parser.add_argument("--psi5-route-no-recovered", action="store_true", default=os.getenv("QDATA_PSI5_ROUTE_INCLUDE_RECOVERED", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--omega5-route-lookback-hours", type=int, default=int(os.getenv("QDATA_OMEGA5_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--omega5-route-max-controls", type=int, default=int(os.getenv("QDATA_OMEGA5_ROUTE_MAX_CONTROLS", "50")))
    parser.add_argument("--omega5-route-execution-mode", choices=["review_only", "dry_run", "execute"], default=os.getenv("QDATA_OMEGA5_ROUTE_EXECUTION_MODE", "review_only"))
    parser.add_argument("--omega5-route-auto-approve", action="store_true", default=os.getenv("QDATA_OMEGA5_ROUTE_AUTO_APPROVE", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--omega5-route-approved-by", default=os.getenv("QDATA_OMEGA5_ROUTE_APPROVED_BY", ""))
    parser.add_argument("--omega5-route-requested-by", default=os.getenv("QDATA_OMEGA5_ROUTE_REQUESTED_BY", "omega5"))
    parser.add_argument("--omega5-route-approval-sla-hours", type=int, default=int(os.getenv("QDATA_OMEGA5_ROUTE_APPROVAL_SLA_HOURS", "4")))
    parser.add_argument("--omega5-route-no-wecom", action="store_true")
    parser.add_argument("--omega5-route-allow-wecom-external", action="store_true", default=os.getenv("QDATA_OMEGA5_ROUTE_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--omega5-route-no-rollback", action="store_true")
    parser.add_argument("--alpha6-route-lookback-hours", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--alpha6-route-approval-sla-hours", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_APPROVAL_SLA_HOURS", "4")))
    parser.add_argument("--alpha6-route-max-pending-controls", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_MAX_PENDING_CONTROLS", "50")))
    parser.add_argument("--alpha6-route-max-failed-execution-rate", type=float, default=float(os.getenv("QDATA_ALPHA6_ROUTE_MAX_FAILED_EXECUTION_RATE", "0.1")))
    parser.add_argument("--alpha6-route-max-blocked-receipt-rate", type=float, default=float(os.getenv("QDATA_ALPHA6_ROUTE_MAX_BLOCKED_RECEIPT_RATE", "0.8")))
    parser.add_argument("--alpha6-route-max-stale-minutes", type=int, default=int(os.getenv("QDATA_ALPHA6_ROUTE_MAX_STALE_MINUTES", "90")))
    parser.add_argument("--alpha6-route-requested-by", default=os.getenv("QDATA_ALPHA6_ROUTE_REQUESTED_BY", "alpha6"))
    parser.add_argument("--alpha6-route-environment", default=os.getenv("QDATA_ALPHA6_ROUTE_ENVIRONMENT", "local"))
    parser.add_argument("--alpha6-route-control-schedule-code", default=os.getenv("QDATA_ALPHA6_ROUTE_CONTROL_SCHEDULE_CODE", "omega5_route_incident_control_15m"))
    parser.add_argument("--beta6-route-lookback-hours", type=int, default=int(os.getenv("QDATA_BETA6_ROUTE_LOOKBACK_HOURS", "24")))
    parser.add_argument("--beta6-route-max-controls", type=int, default=int(os.getenv("QDATA_BETA6_ROUTE_MAX_CONTROLS", "100")))
    parser.add_argument("--beta6-route-approval-decision", choices=["approve", "reject", "hold"], default=os.getenv("QDATA_BETA6_ROUTE_APPROVAL_DECISION", "hold"))
    parser.add_argument("--beta6-route-apply-decisions", action="store_true", default=os.getenv("QDATA_BETA6_ROUTE_APPLY_DECISIONS", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--beta6-route-requested-by", default=os.getenv("QDATA_BETA6_ROUTE_REQUESTED_BY", "beta6"))
    parser.add_argument("--beta6-route-environment", default=os.getenv("QDATA_BETA6_ROUTE_ENVIRONMENT", "local"))
    parser.add_argument("--beta6-route-notification-policy", choices=["dedupe_digest", "critical_only", "none"], default=os.getenv("QDATA_BETA6_ROUTE_NOTIFICATION_POLICY", "dedupe_digest"))
    parser.add_argument("--beta6-route-stress-scope", choices=["full_market", "active_sources", "smoke"], default=os.getenv("QDATA_BETA6_ROUTE_STRESS_SCOPE", "full_market"))
    parser.add_argument("--beta6-route-notify-wecom", action="store_true", default=os.getenv("QDATA_BETA6_ROUTE_NOTIFY_WECOM", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--beta6-route-allow-wecom-external", action="store_true", default=os.getenv("QDATA_BETA6_ROUTE_ALLOW_WECOM_EXTERNAL", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--epsilon6-no-sla-automation", action="store_true", default=os.getenv("QDATA_EPSILON6_SLA_AUTOMATION", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--epsilon6-no-hash-verify", action="store_true", default=os.getenv("QDATA_EPSILON6_HASH_VERIFY", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--epsilon6-recovery-drill", choices=["none", "db_reconnect", "webhook_replay", "hash_chain_verify", "lock_contention", "state_machine_restore", "full"], default=os.getenv("QDATA_EPSILON6_RECOVERY_DRILL", "hash_chain_verify"))
    parser.add_argument("--epsilon6-requested-by", default=os.getenv("QDATA_EPSILON6_REQUESTED_BY", "epsilon6"))
    parser.add_argument("--epsilon6-environment", default=os.getenv("QDATA_EPSILON6_ENVIRONMENT", "local"))
    parser.add_argument("--epsilon6-sla-limit", type=int, default=int(os.getenv("QDATA_EPSILON6_SLA_LIMIT", "100")))
    parser.add_argument("--epsilon6-audit-verify-limit", type=int, default=int(os.getenv("QDATA_EPSILON6_AUDIT_VERIFY_LIMIT", "1000")))
    parser.add_argument("--zeta6-environment", choices=["local", "staging", "production"], default=os.getenv("QDATA_ZETA6_ENVIRONMENT", "local"))
    parser.add_argument("--zeta6-release-version", default=os.getenv("QDATA_ZETA6_RELEASE_VERSION", "zeta6-local"))
    parser.add_argument("--zeta6-requested-by", default=os.getenv("QDATA_ZETA6_REQUESTED_BY", "zeta6"))
    parser.add_argument("--zeta6-require-dual-secret", action="store_true", default=os.getenv("QDATA_ZETA6_REQUIRE_DUAL_SECRET", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--zeta6-no-audit-export", action="store_true", default=os.getenv("QDATA_ZETA6_EXPORT_AUDIT", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--zeta6-export-chain-scope", default=os.getenv("QDATA_ZETA6_EXPORT_CHAIN_SCOPE", ""))
    parser.add_argument("--zeta6-export-control-code", default=os.getenv("QDATA_ZETA6_EXPORT_CONTROL_CODE", ""))
    parser.add_argument("--zeta6-export-limit", type=int, default=int(os.getenv("QDATA_ZETA6_EXPORT_LIMIT", "1000")))
    parser.add_argument("--eta6-source-code", default=os.getenv("QDATA_VENDOR_SOURCE_CODE", "vendor_http"))
    parser.add_argument("--eta6-primary-source-code", default=os.getenv("QDATA_PRIMARY_SOURCE_CODE", "csv"))
    parser.add_argument("--eta6-dataset-code", action="append", default=[])
    parser.add_argument("--eta6-environment", choices=["local", "staging", "production"], default=os.getenv("QDATA_ETA6_ENVIRONMENT", "local"))
    parser.add_argument("--eta6-closure-scope", choices=["production_primary", "canary", "full_market"], default=os.getenv("QDATA_ETA6_CLOSURE_SCOPE", "production_primary"))
    parser.add_argument("--eta6-closure-mode", choices=["review_only", "dry_run", "apply"], default=os.getenv("QDATA_ETA6_CLOSURE_MODE", "review_only"))
    parser.add_argument("--eta6-requested-by", default=os.getenv("QDATA_ETA6_REQUESTED_BY", "eta6"))
    parser.add_argument("--eta6-no-real-vendor-env-required", action="store_true", default=os.getenv("QDATA_ETA6_REQUIRE_REAL_VENDOR_ENV", "true").lower() in {"0", "false", "no"})
    parser.add_argument("--eta6-external-probe-allowed", action="store_true", default=os.getenv("QDATA_ETA6_EXTERNAL_PROBE_ALLOWED", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--eta6-min-stability-score", type=float, default=float(os.getenv("QDATA_ETA6_MIN_STABILITY_SCORE", "70")))
    parser.add_argument("--eta6-allow-cost-watch", action="store_true", default=os.getenv("QDATA_ETA6_ALLOW_COST_WATCH", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    trigger_mode = args.trigger_mode or ("once" if args.once else "manual")
    result = run_lambda_worker(
        args.postgres_dsn,
        task_names=args.task,
        trade_date=args.trade_date or None,
        start_date=args.start_date or None,
        end_date=args.end_date or None,
        dry_run=args.dry_run,
        trigger_mode=trigger_mode,
        channel_code=args.channel_code or None,
        alert_limit=args.alert_limit,
        schedule_code=args.schedule_code or None,
        include_manual_schedules=args.include_manual_schedules,
        cost_per_request=args.cost_per_request,
        cost_per_1000_rows=args.cost_per_1000_rows,
        free_source_lookback_hours=args.free_source_lookback_hours,
        free_source_max_actions=args.free_source_max_actions,
        free_source_min_retry_score=args.free_source_min_retry_score,
        free_source_write_alerts=not args.no_free_source_alerts,
        mu5_max_actions=args.mu5_max_actions,
        mu5_start_date=args.mu5_start_date,
        mu5_end_date=args.mu5_end_date,
        mu5_execute_retry_canary=not args.mu5_no_retry_canary,
        mu5_request_manual_review=not args.mu5_no_manual_review,
        mu5_notify_wecom=not args.mu5_no_wecom,
        mu5_allow_wecom_external=args.mu5_allow_wecom_external,
        mu5_baostock_timeout_seconds=args.mu5_baostock_timeout_seconds,
        nu5_lookback_hours=args.nu5_lookback_hours,
        nu5_approval_sla_hours=args.nu5_approval_sla_hours,
        nu5_max_backlog_actions=args.nu5_max_backlog_actions,
        nu5_max_failure_rate=args.nu5_max_failure_rate,
        nu5_max_stale_minutes=args.nu5_max_stale_minutes,
        xi5_lookback_days=args.xi5_lookback_days,
        xi5_min_validator_score=args.xi5_min_validator_score,
        xi5_min_backup_score=args.xi5_min_backup_score,
        xi5_min_primary_score=args.xi5_min_primary_score,
        xi5_min_coverage_rate=args.xi5_min_coverage_rate,
        xi5_max_conflict_rate_bps=args.xi5_max_conflict_rate_bps,
        omicron5_min_sla_uptime_pct=args.omicron5_min_sla_uptime_pct,
        omicron5_min_rate_limit_per_min=args.omicron5_min_rate_limit_per_min,
        omicron5_require_live_evidence=args.omicron5_require_live_evidence,
        pi5_promotion_scope=args.pi5_promotion_scope,
        pi5_require_full_market=not args.pi5_no_full_market_required,
        pi5_require_signoff=not args.pi5_no_signoff_required,
        pi5_apply_routing=args.pi5_apply_routing,
        pi5_target_priority=args.pi5_target_priority,
        rho5_monitor_scope=args.rho5_monitor_scope,
        rho5_require_applied_promotion=not args.rho5_no_applied_promotion_required,
        rho5_apply_rollback=args.rho5_apply_rollback,
        rho5_shadow_window_hours=args.rho5_shadow_window_hours,
        rho5_max_conflict_rate_bps=args.rho5_max_conflict_rate_bps,
        rho5_max_failure_rate=args.rho5_max_failure_rate,
        rho5_max_stale_minutes=args.rho5_max_stale_minutes,
        sigma5_monitor_scope=args.sigma5_monitor_scope,
        sigma5_lookback_hours=args.sigma5_lookback_hours,
        sigma5_capacity_window_days=args.sigma5_capacity_window_days,
        sigma5_min_success_rate=args.sigma5_min_success_rate,
        sigma5_max_error_rate=args.sigma5_max_error_rate,
        sigma5_max_latency_p95_ms=args.sigma5_max_latency_p95_ms,
        sigma5_max_timeout_rate=args.sigma5_max_timeout_rate,
        sigma5_max_cost_units=args.sigma5_max_cost_units,
        sigma5_max_scheduler_lag_minutes=args.sigma5_max_scheduler_lag_minutes,
        sigma5_max_backlog_count=args.sigma5_max_backlog_count,
        sigma5_max_post_promotion_no_applied_count=args.sigma5_max_post_promotion_no_applied_count,
        tau5_optimization_scope=args.tau5_optimization_scope,
        tau5_lookback_hours=args.tau5_lookback_hours,
        tau5_forecast_window_days=args.tau5_forecast_window_days,
        tau5_monthly_budget_amount=args.tau5_monthly_budget_amount,
        tau5_max_budget_usage_pct=args.tau5_max_budget_usage_pct,
        tau5_max_daily_quota_usage_pct=args.tau5_max_daily_quota_usage_pct,
        tau5_max_monthly_quota_usage_pct=args.tau5_max_monthly_quota_usage_pct,
        tau5_min_stability_score=args.tau5_min_stability_score,
        tau5_cost_safety_margin_pct=args.tau5_cost_safety_margin_pct,
        tau5_default_unit_cost=args.tau5_default_unit_cost,
        tau5_stress_multipliers=tuple(args.tau5_stress_multiplier or [1.0, 5.0, 10.0]),
        upsilon5_execution_scope=args.upsilon5_execution_scope,
        upsilon5_execution_mode=args.upsilon5_execution_mode,
        upsilon5_approval_policy=args.upsilon5_approval_policy,
        upsilon5_approval_status=args.upsilon5_approval_status,
        upsilon5_rollout_policy=args.upsilon5_rollout_policy,
        upsilon5_rollout_stages=tuple(args.upsilon5_rollout_stage or [10.0, 30.0, 60.0, 90.0]),
        upsilon5_current_stage_sequence=args.upsilon5_current_stage_sequence,
        upsilon5_max_initial_primary_weight_pct=args.upsilon5_max_initial_primary_weight_pct,
        upsilon5_allow_over_budget=args.upsilon5_allow_over_budget,
        upsilon5_allow_quota_risk=args.upsilon5_allow_quota_risk,
        upsilon5_rollback_requested=args.upsilon5_rollback_requested,
        chi5_lookback_hours=args.chi5_lookback_hours,
        chi5_min_request_count=args.chi5_min_request_count,
        chi5_min_success_rate=args.chi5_min_success_rate,
        chi5_max_failure_rate=args.chi5_max_failure_rate,
        chi5_max_fallback_rate=args.chi5_max_fallback_rate,
        chi5_max_empty_rate=args.chi5_max_empty_rate,
        chi5_max_latency_p95_ms=args.chi5_max_latency_p95_ms,
        chi5_circuit_open_minutes=args.chi5_circuit_open_minutes,
        chi5_recovery_probe_min_success_rate=args.chi5_recovery_probe_min_success_rate,
        psi5_route_lookback_hours=args.psi5_route_lookback_hours,
        psi5_route_max_actions=args.psi5_route_max_actions,
        psi5_route_execution_mode=args.psi5_route_execution_mode,
        psi5_route_approve_high_risk=args.psi5_route_approve_high_risk,
        psi5_route_approved_by=args.psi5_route_approved_by or None,
        psi5_route_owner=args.psi5_route_owner,
        psi5_route_include_recovered=not args.psi5_route_no_recovered,
        omega5_route_lookback_hours=args.omega5_route_lookback_hours,
        omega5_route_max_controls=args.omega5_route_max_controls,
        omega5_route_execution_mode=args.omega5_route_execution_mode,
        omega5_route_auto_approve=args.omega5_route_auto_approve,
        omega5_route_approved_by=args.omega5_route_approved_by or None,
        omega5_route_requested_by=args.omega5_route_requested_by,
        omega5_route_approval_sla_hours=args.omega5_route_approval_sla_hours,
        omega5_route_notify_wecom=not args.omega5_route_no_wecom,
        omega5_route_allow_wecom_external=args.omega5_route_allow_wecom_external,
        omega5_route_create_rollback=not args.omega5_route_no_rollback,
        alpha6_route_lookback_hours=args.alpha6_route_lookback_hours,
        alpha6_route_approval_sla_hours=args.alpha6_route_approval_sla_hours,
        alpha6_route_max_pending_controls=args.alpha6_route_max_pending_controls,
        alpha6_route_max_failed_execution_rate=args.alpha6_route_max_failed_execution_rate,
        alpha6_route_max_blocked_receipt_rate=args.alpha6_route_max_blocked_receipt_rate,
        alpha6_route_max_stale_minutes=args.alpha6_route_max_stale_minutes,
        alpha6_route_requested_by=args.alpha6_route_requested_by,
        alpha6_route_environment=args.alpha6_route_environment,
        alpha6_route_control_schedule_code=args.alpha6_route_control_schedule_code,
        beta6_route_lookback_hours=args.beta6_route_lookback_hours,
        beta6_route_max_controls=args.beta6_route_max_controls,
        beta6_route_approval_decision=args.beta6_route_approval_decision,
        beta6_route_apply_decisions=args.beta6_route_apply_decisions,
        beta6_route_requested_by=args.beta6_route_requested_by,
        beta6_route_environment=args.beta6_route_environment,
        beta6_route_notification_policy=args.beta6_route_notification_policy,
        beta6_route_stress_scope=args.beta6_route_stress_scope,
        beta6_route_notify_wecom=args.beta6_route_notify_wecom,
        beta6_route_allow_wecom_external=args.beta6_route_allow_wecom_external,
        epsilon6_sla_automation=not args.epsilon6_no_sla_automation,
        epsilon6_hash_verify=not args.epsilon6_no_hash_verify,
        epsilon6_recovery_drill=args.epsilon6_recovery_drill,
        epsilon6_requested_by=args.epsilon6_requested_by,
        epsilon6_environment=args.epsilon6_environment,
        epsilon6_sla_limit=args.epsilon6_sla_limit,
        epsilon6_audit_verify_limit=args.epsilon6_audit_verify_limit,
        zeta6_environment=args.zeta6_environment,
        zeta6_release_version=args.zeta6_release_version,
        zeta6_requested_by=args.zeta6_requested_by,
        zeta6_require_dual_secret=args.zeta6_require_dual_secret,
        zeta6_export_audit=not args.zeta6_no_audit_export,
        zeta6_export_chain_scope=args.zeta6_export_chain_scope or None,
        zeta6_export_control_code=args.zeta6_export_control_code or None,
        zeta6_export_limit=args.zeta6_export_limit,
        eta6_source_code=args.eta6_source_code,
        eta6_primary_source_code=args.eta6_primary_source_code,
        eta6_dataset_codes=tuple(args.eta6_dataset_code or ()),
        eta6_environment=args.eta6_environment,
        eta6_closure_scope=args.eta6_closure_scope,
        eta6_closure_mode=args.eta6_closure_mode,
        eta6_requested_by=args.eta6_requested_by,
        eta6_require_real_vendor_env=not args.eta6_no_real_vendor_env_required,
        eta6_external_probe_allowed=args.eta6_external_probe_allowed,
        eta6_min_stability_score=args.eta6_min_stability_score,
        eta6_allow_cost_watch=args.eta6_allow_cost_watch,
    )
    if args.json:
        print(json.dumps(_result_dict(result), ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_worker_report(result))
    return 0


def _result_dict(result) -> dict:
    return {
        "run_code": result.run_code,
        "status": result.status,
        "worker_run_id": result.worker_run_id,
        "processed_count": result.processed_count,
        "success_count": result.success_count,
        "failed_count": result.failed_count,
        "warning_count": result.warning_count,
        "duration_ms": result.duration_ms,
        "dry_run": result.dry_run,
        "task_results": [
            {
                "task_name": item.task_name,
                "status": item.status,
                "processed_count": item.processed_count,
                "success_count": item.success_count,
                "failed_count": item.failed_count,
                "warning_count": item.warning_count,
                "details": item.details or {},
                "error_message": item.error_message,
            }
            for item in result.task_results
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
