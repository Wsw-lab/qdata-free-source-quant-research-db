#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Kappa admin API endpoints.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    parser.add_argument("--token", required=True)
    parser.add_argument("--trade-date", default="")
    args = parser.parse_args()

    endpoints = [
        ("overview", "/admin/overview", {}),
        ("tenants", "/admin/tenants", {"limit": "20"}),
        ("projects", "/admin/projects", {"limit": "20"}),
        ("tokens", "/admin/tokens", {"limit": "20"}),
        ("dataset_access", "/admin/dataset-access", {"limit": "20"}),
        ("access_decisions", "/admin/access-decisions", {"limit": "20"}),
        ("project_governance", "/admin/project-governance", {"limit": "20"}),
        ("governance_actions", "/admin/governance-actions", {"limit": "20"}),
        ("automation_runs", "/admin/automation-runs", {"limit": "20"}),
        ("automation_actions", "/admin/automation-actions", {"limit": "20"}),
        ("automation_approvals", "/admin/automation-approvals", {"limit": "20"}),
        ("automation_executors", "/admin/automation-executors", {"limit": "20"}),
        ("automation_allowlists", "/admin/automation-allowlists", {"limit": "20"}),
        ("automation_secrets", "/admin/automation-secrets", {"limit": "20"}),
        ("automation_channels", "/admin/automation-channels", {"limit": "20"}),
        ("automation_dispatches", "/admin/automation-dispatches", {"limit": "20"}),
        ("automation_runbooks", "/admin/automation-runbooks", {"limit": "20"}),
        ("automation_channel_profiles", "/admin/automation-channel-profiles", {"limit": "20"}),
        ("automation_channel_validations", "/admin/automation-channel-validations", {"limit": "20"}),
        ("automation_secret_rotations", "/admin/automation-secret-rotations", {"limit": "20"}),
        ("automation_live_receipts", "/admin/automation-live-receipts", {"limit": "20"}),
        ("automation_attempts", "/admin/automation-attempts", {"limit": "20"}),
        ("automation_rollbacks", "/admin/automation-rollbacks", {"limit": "20"}),
        ("notification_deliveries", "/admin/notification-deliveries", {"limit": "20"}),
        ("vendor_schedules", "/admin/vendor-schedules", {"limit": "20"}),
        ("vendor_onboarding_runs", "/admin/vendor-onboarding-runs", {"limit": "20"}),
        ("vendor_onboarding_results", "/admin/vendor-onboarding-results", {"limit": "20"}),
        ("vendor_live_closures", "/admin/vendor-live-closures", {"limit": "20"}),
        ("vendor_live_probes", "/admin/vendor-live-probes", {"limit": "20"}),
        ("vendor_live_pilots", "/admin/vendor-live-pilots", {"limit": "20"}),
        ("vendor_live_pilot_results", "/admin/vendor-live-pilot-results", {"limit": "20"}),
        ("free_source_fabric_runs", "/admin/free-source-fabric-runs", {"limit": "20"}),
        ("free_source_fabric_results", "/admin/free-source-fabric-results", {"limit": "20"}),
        ("free_source_reliability", "/admin/free-source-reliability", {"limit": "20"}),
        ("free_source_recovery_runs", "/admin/free-source-recovery-runs", {"limit": "20"}),
        ("free_source_recovery_actions", "/admin/free-source-recovery-actions", {"limit": "20"}),
        ("free_source_recovery_executions", "/admin/free-source-recovery-executions", {"limit": "20"}),
        ("free_source_recovery_health", "/admin/free-source-recovery-health", {"limit": "20"}),
        ("free_source_admission_profiles", "/admin/free-source-admission-profiles", {"limit": "20"}),
        ("free_source_admission", "/admin/free-source-admission", {"limit": "20"}),
        ("vendor_contract_profiles", "/admin/vendor-contract-profiles", {"limit": "20"}),
        ("vendor_contract_entitlements", "/admin/vendor-contract-entitlements", {"limit": "20"}),
        ("vendor_procurement_readiness", "/admin/vendor-procurement-readiness", {"limit": "20"}),
        ("vendor_primary_promotions", "/admin/vendor-primary-promotions", {"limit": "20"}),
        ("vendor_primary_promotion_results", "/admin/vendor-primary-promotion-results", {"limit": "20"}),
        ("vendor_post_promotion_monitors", "/admin/vendor-post-promotion-monitors", {"limit": "20"}),
        ("vendor_post_promotion_results", "/admin/vendor-post-promotion-results", {"limit": "20"}),
        ("vendor_primary_stability", "/admin/vendor-primary-stability", {"limit": "20"}),
        ("vendor_primary_stability_datasets", "/admin/vendor-primary-stability-datasets", {"limit": "20"}),
        ("vendor_cost_optimizations", "/admin/vendor-cost-optimizations", {"limit": "20"}),
        ("vendor_route_weight_plans", "/admin/vendor-route-weight-plans", {"limit": "20"}),
        ("vendor_budget_stress", "/admin/vendor-budget-stress", {"limit": "20"}),
        ("vendor_route_executions", "/admin/vendor-route-executions", {"limit": "20"}),
        ("vendor_route_execution_datasets", "/admin/vendor-route-execution-datasets", {"limit": "20"}),
        ("vendor_route_rollout_stages", "/admin/vendor-route-rollout-stages", {"limit": "20"}),
        ("vendor_production_source_runs", "/admin/vendor-production-source-runs", {"limit": "20"}),
        ("vendor_production_source_dataset_checks", "/admin/vendor-production-source-dataset-checks", {"limit": "20"}),
        ("vendor_production_source_decisions", "/admin/vendor-production-source-decisions", {"limit": "20"}),
        ("source_route_weight_policies", "/admin/source-route-weight-policies", {"limit": "20"}),
        ("source_route_decisions", "/admin/source-route-decisions", {"limit": "20"}),
        ("source_route_health", "/admin/source-route-health", {"limit": "20"}),
        ("source_route_circuit_breakers", "/admin/source-route-circuit-breakers", {"limit": "20"}),
        ("source_route_recovery_probes", "/admin/source-route-recovery-probes", {"limit": "20"}),
        ("source_route_incident_actions", "/admin/source-route-incident-actions", {"limit": "20"}),
        ("source_route_incident_controls", "/admin/source-route-incident-controls", {"limit": "20"}),
        ("source_route_incident_control_health", "/admin/source-route-incident-control-health", {"limit": "20"}),
        ("source_route_incident_operation_batches", "/admin/source-route-incident-operation-batches", {"limit": "20"}),
        ("source_route_incident_operation_items", "/admin/source-route-incident-operation-items", {"limit": "20"}),
        ("source_route_incident_approval_commands", "/admin/source-route-incident-approval-commands", {"limit": "20"}),
        ("source_route_incident_approval_command_items", "/admin/source-route-incident-approval-command-items", {"limit": "20"}),
        ("source_route_incident_approval_signatures", "/admin/source-route-incident-approval-signatures", {"limit": "20"}),
        ("source_route_incident_approval_role_bindings", "/admin/source-route-incident-approval-role-bindings", {"limit": "20"}),
        ("source_route_incident_approval_policies", "/admin/source-route-incident-approval-policies", {"limit": "20"}),
        ("source_route_incident_approval_callbacks", "/admin/source-route-incident-approval-callbacks", {"limit": "20"}),
        ("source_route_incident_approval_escalations", "/admin/source-route-incident-approval-escalations", {"limit": "20"}),
        ("source_route_incident_approval_lock_events", "/admin/source-route-incident-approval-lock-events", {"limit": "20"}),
        ("source_route_incident_approval_state_transitions", "/admin/source-route-incident-approval-state-transitions", {"limit": "20"}),
        ("source_route_incident_approval_audit_chain", "/admin/source-route-incident-approval-audit-chain", {"limit": "20"}),
        ("source_route_incident_approval_sla_actions", "/admin/source-route-incident-approval-sla-actions", {"limit": "20"}),
        ("source_route_incident_approval_recovery_drills", "/admin/source-route-incident-approval-recovery-drills", {"limit": "20"}),
        ("source_route_incident_approval_release_preflights", "/admin/source-route-incident-approval-release-preflights", {"limit": "20"}),
        ("source_route_incident_approval_secret_rotations", "/admin/source-route-incident-approval-secret-rotations", {"limit": "20"}),
        ("source_route_incident_approval_concurrency_tests", "/admin/source-route-incident-approval-concurrency-tests", {"limit": "20"}),
        ("source_route_incident_approval_audit_exports", "/admin/source-route-incident-approval-audit-exports", {"limit": "20"}),
        ("vendor_live_gates", "/admin/vendor-live-gates", {"limit": "20"}),
        ("vendor_readiness", "/admin/vendor-readiness", {"limit": "20"}),
        ("vendor_readiness_windows", "/admin/vendor-readiness-windows", {"limit": "20"}),
        ("worker_runs", "/admin/worker-runs", {"limit": "20"}),
        ("worker_schedules", "/admin/worker-schedules", {"limit": "20"}),
        ("worker_locks", "/admin/worker-locks", {"limit": "20"}),
        ("worker_heartbeats", "/admin/worker-heartbeats", {"limit": "20"}),
        ("worker_schedule_ticks", "/admin/worker-schedule-ticks", {"limit": "20"}),
        ("deployment_releases", "/admin/deployment-releases", {"limit": "20"}),
        ("deployment_health", "/admin/deployment-health", {"limit": "20"}),
        ("deployment_health_checks", "/admin/deployment-health-checks", {"limit": "20"}),
        ("deployment_events", "/admin/deployment-events", {"limit": "20"}),
        ("data_products", "/admin/data-products", {"limit": "20"}),
        ("pricing_plans", "/admin/pricing-plans", {"limit": "20"}),
        ("pricing_rules", "/admin/pricing-rules", {"limit": "20"}),
        ("product_subscriptions", "/admin/product-subscriptions", {"limit": "20"}),
        ("budget_policies", "/admin/budget-policies", {"limit": "20"}),
        ("budget_usage", "/admin/budget-usage", {"limit": "20"}),
        ("budget_alerts", "/admin/budget-alerts", {"limit": "20"}),
        ("invoices", "/admin/invoices", {"limit": "20"}),
        ("invoice_lines", "/admin/invoice-lines", {"limit": "20"}),
        ("invoice_events", "/admin/invoice-events", {"limit": "20"}),
        ("revenue_summary", "/admin/revenue-summary", {"limit": "20"}),
        ("revenue_reconciliation", "/admin/revenue-reconciliation", {"limit": "20"}),
        ("revenue_reconciliation_lines", "/admin/revenue-reconciliation-lines", {"limit": "20"}),
        ("ar_aging", "/admin/ar-aging", {"limit": "20"}),
        ("customer_health", "/admin/customer-health", {"limit": "20"}),
        ("payment_batches", "/admin/payment-batches", {"limit": "20"}),
        ("payments", "/admin/payments", {"limit": "20"}),
        ("payment_matches", "/admin/payment-matches", {"limit": "20"}),
        ("revenue_ledger", "/admin/revenue-ledger", {"limit": "20"}),
        ("fx_rates", "/admin/fx-rates", {"limit": "20"}),
        ("runtime_logs", "/admin/runtime-logs", {"limit": "20"}),
        ("runtime_metrics", "/admin/runtime-metrics", {"limit": "20"}),
        ("runtime_daily_reports", "/admin/runtime-daily-reports", {"limit": "20"}),
        ("capacity_alerts", "/admin/capacity-alerts", {"limit": "20"}),
        ("strategy_runs", "/admin/strategy-runs", {"limit": "20"}),
        ("strategy_signals", "/admin/strategy-signals", {"limit": "20"}),
        ("strategy_decisions", "/admin/strategy-decisions", {"limit": "20"}),
        ("strategy_escalations", "/admin/strategy-escalations", {"limit": "20"}),
        ("usage_daily", "/usage/daily", {"trade_date": args.trade_date} if args.trade_date else {"limit": "20"}),
        ("console", "/admin/console", {}),
    ]
    tokens = [item.strip() for item in args.token.split(",") if item.strip()]
    if not tokens:
        parser.error("--token must contain at least one token")
    for index, (label, path, query) in enumerate(endpoints):
        body, content_type = _get(args.base_url, path, query, tokens[index % len(tokens)])
        if "text/html" in content_type:
            print(f"{label}=ok html_bytes={len(body)}")
            continue
        payload = json.loads(body)
        print(f"{label}=ok rows={payload.get('meta', {}).get('row_count', len(payload.get('data', [])))}")
    return 0


def _get(base_url: str, path: str, query: dict[str, str], token: str) -> tuple[str, str]:
    suffix = f"?{urlencode(query)}" if query else ""
    request = Request(f"{base_url.rstrip('/')}{path}{suffix}", headers={"Authorization": f"Bearer {token}"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8"), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            if exc.code != 429 or attempt == 2:
                raise
            retry_after = exc.headers.get("Retry-After")
            try:
                wait_seconds = float(retry_after) if retry_after else 61.0
            except ValueError:
                wait_seconds = 61.0
            print(f"rate_limit=retry path={path} wait_seconds={int(wait_seconds)}", file=sys.stderr)
            time.sleep(wait_seconds)
    raise RuntimeError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
