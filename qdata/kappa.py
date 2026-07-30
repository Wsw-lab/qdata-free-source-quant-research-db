from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from typing import Any

from qdata.alpha6_route_incident_control_health import list_route_incident_control_health
from qdata.backend_utils import date_range, normalize_rows
from qdata.beta6_route_incident_ops import (
    list_route_incident_operation_batches,
    list_route_incident_operation_items,
)
from qdata.beta2_external import (
    list_automation_channels,
    list_automation_dispatches,
    list_automation_runbooks,
)
from qdata.chi5_route_feedback import (
    list_source_route_circuit_breakers,
    list_source_route_health_snapshots,
    list_source_route_recovery_probes,
)
from qdata.chi_governance import (
    list_access_decisions,
    list_governance_actions,
    list_project_governance,
)
from qdata.delta2_wecom import list_automation_live_receipts
from qdata.epsilon3_vendor_gate import list_vendor_live_gate_runs
from qdata.eta6_vendor_production_source import (
    list_vendor_production_source_dataset_checks,
    list_vendor_production_source_decisions,
    list_vendor_production_source_runs,
)
from qdata.eta3_vendor_live_closure import (
    list_vendor_live_closures,
    list_vendor_live_probes,
)
from qdata.exceptions import QDataValidationError
from qdata.gamma2_external import (
    list_automation_channel_profiles,
    list_automation_channel_validations,
    list_automation_secret_rotations,
)
from qdata.gamma6_route_incident_approval_api import (
    list_route_incident_approval_command_items,
    list_route_incident_approval_commands,
    list_route_incident_approval_signatures,
)
from qdata.delta6_route_incident_approval_governance import (
    list_route_incident_approval_callbacks,
    list_route_incident_approval_escalations,
    list_route_incident_approval_policies,
    list_route_incident_approval_role_bindings,
)
from qdata.epsilon6_route_incident_approval_resilience import (
    list_route_incident_approval_audit_hashes,
    list_route_incident_approval_lock_events,
    list_route_incident_approval_recovery_drills,
    list_route_incident_approval_sla_actions,
    list_route_incident_approval_state_transitions,
)
from qdata.iota3_free_source_fabric import (
    list_free_source_fabric_results,
    list_free_source_fabric_runs,
)
from qdata.kappa5_free_source_reliability import list_free_source_reliability_snapshots
from qdata.lambda5_free_source_recovery import (
    list_free_source_recovery_actions,
    list_free_source_recovery_runs,
)
from qdata.mu5_free_source_recovery_executor import list_free_source_recovery_executions
from qdata.nu5_free_source_recovery_health import list_free_source_recovery_health
from qdata.omicron5_vendor_contract import (
    list_vendor_contract_entitlements,
    list_vendor_contract_profiles,
    list_vendor_procurement_readiness,
)
from qdata.phi5_route_policy import list_source_route_decision_audits
from qdata.pi5_vendor_primary_promotion import (
    list_vendor_primary_promotion_results,
    list_vendor_primary_promotions,
)
from qdata.rho5_post_promotion_monitor import (
    list_vendor_post_promotion_monitors,
    list_vendor_post_promotion_results,
)
from qdata.sigma5_vendor_primary_stability import (
    list_vendor_primary_stability_datasets,
    list_vendor_primary_stability_snapshots,
)
from qdata.tau5_vendor_cost_optimization import (
    list_vendor_budget_stress_snapshots,
    list_vendor_cost_optimizations,
    list_vendor_route_weight_plans,
)
from qdata.upsilon5_route_weight_execution import (
    list_source_route_weight_policies,
    list_vendor_route_weight_execution_datasets,
    list_vendor_route_weight_executions,
    list_vendor_route_weight_rollout_stages,
)
from qdata.xi5_free_source_admission import (
    list_free_source_admission_profiles,
    list_free_source_admission_snapshots,
)
from qdata.zeta6_route_incident_approval_release import (
    list_route_incident_approval_audit_exports,
    list_route_incident_approval_concurrency_tests,
    list_route_incident_approval_release_preflights,
    list_route_incident_approval_secret_rotations,
)
from qdata.phi_strategy import (
    list_strategy_decisions,
    list_strategy_escalations,
    list_strategy_runs,
    list_strategy_signals,
)
from qdata.omega_control import (
    list_automation_allowlists,
    list_automation_approvals,
    list_automation_attempts,
    list_automation_executors,
    list_automation_rollbacks,
    list_automation_secret_refs,
)
from qdata.omega5_route_incident_control import list_route_incident_controls
from qdata.psi_automation import list_automation_actions, list_automation_runs, list_route_incident_actions
from qdata.theta3_vendor_live_pilot import (
    list_vendor_live_pilot_results,
    list_vendor_live_pilots,
)
from qdata.zeta3_vendor_onboarding import (
    list_vendor_onboarding_results,
    list_vendor_onboarding_runs,
)


KAPPA_ADMIN_PATHS = {
    "/admin/overview",
    "/admin/tenants",
    "/admin/projects",
    "/admin/principals",
    "/admin/tokens",
    "/admin/dataset-access",
    "/admin/access-decisions",
    "/admin/project-governance",
    "/admin/governance-actions",
    "/admin/automation-runs",
    "/admin/automation-actions",
    "/admin/automation-approvals",
    "/admin/automation-executors",
    "/admin/automation-allowlists",
    "/admin/automation-secrets",
    "/admin/automation-channels",
    "/admin/automation-dispatches",
    "/admin/automation-runbooks",
    "/admin/automation-channel-profiles",
    "/admin/automation-channel-validations",
    "/admin/automation-secret-rotations",
    "/admin/automation-live-receipts",
    "/admin/automation-attempts",
    "/admin/automation-rollbacks",
    "/admin/notification-deliveries",
    "/admin/vendor-schedules",
    "/admin/vendor-onboarding-runs",
    "/admin/vendor-onboarding-results",
    "/admin/vendor-live-closures",
    "/admin/vendor-live-probes",
    "/admin/vendor-live-pilots",
    "/admin/vendor-live-pilot-results",
    "/admin/vendor-contract-profiles",
    "/admin/vendor-contract-entitlements",
    "/admin/vendor-procurement-readiness",
    "/admin/vendor-primary-promotions",
    "/admin/vendor-primary-promotion-results",
    "/admin/vendor-post-promotion-monitors",
    "/admin/vendor-post-promotion-results",
    "/admin/vendor-primary-stability",
    "/admin/vendor-primary-stability-datasets",
    "/admin/vendor-cost-optimizations",
    "/admin/vendor-route-weight-plans",
    "/admin/vendor-budget-stress",
    "/admin/vendor-route-executions",
    "/admin/vendor-route-execution-datasets",
    "/admin/vendor-route-rollout-stages",
    "/admin/vendor-production-source-runs",
    "/admin/vendor-production-source-dataset-checks",
    "/admin/vendor-production-source-decisions",
    "/admin/source-route-weight-policies",
    "/admin/source-route-decisions",
    "/admin/source-route-health",
    "/admin/source-route-circuit-breakers",
    "/admin/source-route-recovery-probes",
    "/admin/source-route-incident-actions",
    "/admin/source-route-incident-controls",
    "/admin/source-route-incident-control-health",
    "/admin/source-route-incident-operation-batches",
    "/admin/source-route-incident-operation-items",
    "/admin/source-route-incident-approval-commands",
    "/admin/source-route-incident-approval-command-items",
    "/admin/source-route-incident-approval-signatures",
    "/admin/source-route-incident-approval-role-bindings",
    "/admin/source-route-incident-approval-policies",
    "/admin/source-route-incident-approval-callbacks",
    "/admin/source-route-incident-approval-escalations",
    "/admin/source-route-incident-approval-lock-events",
    "/admin/source-route-incident-approval-state-transitions",
    "/admin/source-route-incident-approval-audit-chain",
    "/admin/source-route-incident-approval-sla-actions",
    "/admin/source-route-incident-approval-recovery-drills",
    "/admin/source-route-incident-approval-release-preflights",
    "/admin/source-route-incident-approval-secret-rotations",
    "/admin/source-route-incident-approval-concurrency-tests",
    "/admin/source-route-incident-approval-audit-exports",
    "/admin/free-source-fabric-runs",
    "/admin/free-source-fabric-results",
    "/admin/free-source-reliability",
    "/admin/free-source-recovery-runs",
    "/admin/free-source-recovery-actions",
    "/admin/free-source-recovery-executions",
    "/admin/free-source-recovery-health",
    "/admin/free-source-admission-profiles",
    "/admin/free-source-admission",
    "/admin/vendor-live-gates",
    "/admin/vendor-readiness",
    "/admin/vendor-readiness-windows",
    "/admin/worker-runs",
    "/admin/worker-schedules",
    "/admin/worker-locks",
    "/admin/worker-heartbeats",
    "/admin/worker-schedule-ticks",
    "/admin/deployment-releases",
    "/admin/deployment-health",
    "/admin/deployment-health-checks",
    "/admin/deployment-events",
    "/admin/data-products",
    "/admin/pricing-plans",
    "/admin/pricing-rules",
    "/admin/product-subscriptions",
    "/admin/budget-policies",
    "/admin/budget-usage",
    "/admin/budget-alerts",
    "/admin/invoices",
    "/admin/invoice-lines",
    "/admin/invoice-events",
    "/admin/revenue-summary",
    "/admin/revenue-reconciliation",
    "/admin/revenue-reconciliation-lines",
    "/admin/ar-aging",
    "/admin/customer-health",
    "/admin/payment-batches",
    "/admin/payments",
    "/admin/payment-matches",
    "/admin/revenue-ledger",
    "/admin/fx-rates",
    "/admin/runtime-logs",
    "/admin/runtime-metrics",
    "/admin/runtime-daily-reports",
    "/admin/capacity-alerts",
    "/admin/strategy-runs",
    "/admin/strategy-signals",
    "/admin/strategy-decisions",
    "/admin/strategy-escalations",
    "/admin/console",
    "/usage/daily",
}


@dataclass(frozen=True)
class KappaResult:
    resource: str
    rows: list[dict[str, Any]]
    meta: dict[str, Any]


def is_kappa_path(path: str) -> bool:
    return path in KAPPA_ADMIN_PATHS


def dispatch_kappa_endpoint(postgres_dsn: str | None, path: str, params: dict[str, list[str]]) -> KappaResult:
    if path not in KAPPA_ADMIN_PATHS:
        raise QDataValidationError(f"unknown Kappa endpoint: {path}")
    if path == "/admin/console":
        snapshot = build_kappa_console_snapshot(postgres_dsn, params)
        return KappaResult("console", [{"html": render_kappa_console(snapshot)}], {"row_count": 1})
    if path == "/admin/overview":
        return KappaResult("overview", [fetch_kappa_overview(postgres_dsn)], {"row_count": 1})
    limit, offset = _limit_offset(params)
    if path == "/admin/tenants":
        rows = list_tenants(postgres_dsn, params, limit, offset)
    elif path == "/admin/projects":
        rows = list_projects(postgres_dsn, params, limit, offset)
    elif path == "/admin/principals":
        rows = list_principals(postgres_dsn, params, limit, offset)
    elif path == "/admin/tokens":
        rows = list_tokens(postgres_dsn, params, limit, offset)
    elif path == "/admin/dataset-access":
        rows = list_dataset_access(postgres_dsn, params, limit, offset)
    elif path == "/admin/access-decisions":
        rows = list_access_decisions(postgres_dsn, params, limit, offset)
    elif path == "/admin/project-governance":
        rows = list_project_governance(postgres_dsn, params, limit, offset)
    elif path == "/admin/governance-actions":
        rows = list_governance_actions(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-runs":
        rows = list_automation_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-actions":
        rows = list_automation_actions(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-approvals":
        rows = list_automation_approvals(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-executors":
        rows = list_automation_executors(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-allowlists":
        rows = list_automation_allowlists(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-secrets":
        rows = list_automation_secret_refs(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-channels":
        rows = list_automation_channels(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-dispatches":
        rows = list_automation_dispatches(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-runbooks":
        rows = list_automation_runbooks(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-channel-profiles":
        rows = list_automation_channel_profiles(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-channel-validations":
        rows = list_automation_channel_validations(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-secret-rotations":
        rows = list_automation_secret_rotations(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-live-receipts":
        rows = list_automation_live_receipts(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-attempts":
        rows = list_automation_attempts(postgres_dsn, params, limit, offset)
    elif path == "/admin/automation-rollbacks":
        rows = list_automation_rollbacks(postgres_dsn, params, limit, offset)
    elif path == "/admin/notification-deliveries":
        rows = list_notification_deliveries(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-schedules":
        rows = list_vendor_schedules(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-onboarding-runs":
        rows = list_vendor_onboarding_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-onboarding-results":
        rows = list_vendor_onboarding_results(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-live-closures":
        rows = list_vendor_live_closures(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-live-probes":
        rows = list_vendor_live_probes(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-live-pilots":
        rows = list_vendor_live_pilots(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-live-pilot-results":
        rows = list_vendor_live_pilot_results(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-contract-profiles":
        rows = list_vendor_contract_profiles(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-contract-entitlements":
        rows = list_vendor_contract_entitlements(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-procurement-readiness":
        rows = list_vendor_procurement_readiness(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-primary-promotions":
        rows = list_vendor_primary_promotions(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-primary-promotion-results":
        rows = list_vendor_primary_promotion_results(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-post-promotion-monitors":
        rows = list_vendor_post_promotion_monitors(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-post-promotion-results":
        rows = list_vendor_post_promotion_results(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-primary-stability":
        rows = list_vendor_primary_stability_snapshots(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-primary-stability-datasets":
        rows = list_vendor_primary_stability_datasets(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-cost-optimizations":
        rows = list_vendor_cost_optimizations(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-route-weight-plans":
        rows = list_vendor_route_weight_plans(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-budget-stress":
        rows = list_vendor_budget_stress_snapshots(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-route-executions":
        rows = list_vendor_route_weight_executions(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-route-execution-datasets":
        rows = list_vendor_route_weight_execution_datasets(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-route-rollout-stages":
        rows = list_vendor_route_weight_rollout_stages(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-production-source-runs":
        rows = list_vendor_production_source_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-production-source-dataset-checks":
        rows = list_vendor_production_source_dataset_checks(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-production-source-decisions":
        rows = list_vendor_production_source_decisions(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-weight-policies":
        rows = list_source_route_weight_policies(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-decisions":
        rows = list_source_route_decision_audits(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-health":
        rows = list_source_route_health_snapshots(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-circuit-breakers":
        rows = list_source_route_circuit_breakers(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-recovery-probes":
        rows = list_source_route_recovery_probes(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-actions":
        rows = list_route_incident_actions(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-controls":
        rows = list_route_incident_controls(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-control-health":
        rows = list_route_incident_control_health(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-operation-batches":
        rows = list_route_incident_operation_batches(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-operation-items":
        rows = list_route_incident_operation_items(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-commands":
        rows = list_route_incident_approval_commands(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-command-items":
        rows = list_route_incident_approval_command_items(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-signatures":
        rows = list_route_incident_approval_signatures(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-role-bindings":
        rows = list_route_incident_approval_role_bindings(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-policies":
        rows = list_route_incident_approval_policies(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-callbacks":
        rows = list_route_incident_approval_callbacks(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-escalations":
        rows = list_route_incident_approval_escalations(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-lock-events":
        rows = list_route_incident_approval_lock_events(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-state-transitions":
        rows = list_route_incident_approval_state_transitions(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-audit-chain":
        rows = list_route_incident_approval_audit_hashes(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-sla-actions":
        rows = list_route_incident_approval_sla_actions(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-recovery-drills":
        rows = list_route_incident_approval_recovery_drills(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-release-preflights":
        rows = list_route_incident_approval_release_preflights(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-secret-rotations":
        rows = list_route_incident_approval_secret_rotations(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-concurrency-tests":
        rows = list_route_incident_approval_concurrency_tests(postgres_dsn, params, limit, offset)
    elif path == "/admin/source-route-incident-approval-audit-exports":
        rows = list_route_incident_approval_audit_exports(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-fabric-runs":
        rows = list_free_source_fabric_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-fabric-results":
        rows = list_free_source_fabric_results(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-reliability":
        rows = list_free_source_reliability_snapshots(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-recovery-runs":
        rows = list_free_source_recovery_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-recovery-actions":
        rows = list_free_source_recovery_actions(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-recovery-executions":
        rows = list_free_source_recovery_executions(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-recovery-health":
        rows = list_free_source_recovery_health(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-admission-profiles":
        rows = list_free_source_admission_profiles(postgres_dsn, params, limit, offset)
    elif path == "/admin/free-source-admission":
        rows = list_free_source_admission_snapshots(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-live-gates":
        rows = list_vendor_live_gate_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-readiness":
        rows = list_vendor_readiness_reviews(postgres_dsn, params, limit, offset)
    elif path == "/admin/vendor-readiness-windows":
        rows = list_vendor_readiness_windows(postgres_dsn, params, limit, offset)
    elif path == "/admin/worker-runs":
        rows = list_worker_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/worker-schedules":
        rows = list_worker_schedules(postgres_dsn, params, limit, offset)
    elif path == "/admin/worker-locks":
        rows = list_worker_locks(postgres_dsn, params, limit, offset)
    elif path == "/admin/worker-heartbeats":
        rows = list_worker_heartbeats(postgres_dsn, params, limit, offset)
    elif path == "/admin/worker-schedule-ticks":
        rows = list_worker_schedule_ticks(postgres_dsn, params, limit, offset)
    elif path == "/admin/deployment-releases":
        rows = list_deployment_releases(postgres_dsn, params, limit, offset)
    elif path == "/admin/deployment-health":
        rows = list_deployment_health(postgres_dsn, params, limit, offset)
    elif path == "/admin/deployment-health-checks":
        rows = list_deployment_health_checks(postgres_dsn, params, limit, offset)
    elif path == "/admin/deployment-events":
        rows = list_deployment_events(postgres_dsn, params, limit, offset)
    elif path == "/admin/data-products":
        rows = list_data_products(postgres_dsn, params, limit, offset)
    elif path == "/admin/pricing-plans":
        rows = list_pricing_plans(postgres_dsn, params, limit, offset)
    elif path == "/admin/pricing-rules":
        rows = list_pricing_rules(postgres_dsn, params, limit, offset)
    elif path == "/admin/product-subscriptions":
        rows = list_product_subscriptions(postgres_dsn, params, limit, offset)
    elif path == "/admin/budget-policies":
        rows = list_budget_policies(postgres_dsn, params, limit, offset)
    elif path == "/admin/budget-usage":
        rows = list_budget_usage(postgres_dsn, params, limit, offset)
    elif path == "/admin/budget-alerts":
        rows = list_budget_alerts(postgres_dsn, params, limit, offset)
    elif path == "/admin/invoices":
        rows = list_invoices(postgres_dsn, params, limit, offset)
    elif path == "/admin/invoice-lines":
        rows = list_invoice_lines(postgres_dsn, params, limit, offset)
    elif path == "/admin/invoice-events":
        rows = list_invoice_events(postgres_dsn, params, limit, offset)
    elif path == "/admin/revenue-summary":
        rows = list_revenue_summary(postgres_dsn, params, limit, offset)
    elif path == "/admin/revenue-reconciliation":
        rows = list_revenue_reconciliation(postgres_dsn, params, limit, offset)
    elif path == "/admin/revenue-reconciliation-lines":
        rows = list_revenue_reconciliation_lines(postgres_dsn, params, limit, offset)
    elif path == "/admin/ar-aging":
        rows = list_ar_aging(postgres_dsn, params, limit, offset)
    elif path == "/admin/customer-health":
        rows = list_customer_health(postgres_dsn, params, limit, offset)
    elif path == "/admin/payment-batches":
        rows = list_payment_batches(postgres_dsn, params, limit, offset)
    elif path == "/admin/payments":
        rows = list_payments(postgres_dsn, params, limit, offset)
    elif path == "/admin/payment-matches":
        rows = list_payment_matches(postgres_dsn, params, limit, offset)
    elif path == "/admin/revenue-ledger":
        rows = list_revenue_ledger(postgres_dsn, params, limit, offset)
    elif path == "/admin/fx-rates":
        rows = list_fx_rates(postgres_dsn, params, limit, offset)
    elif path == "/admin/runtime-logs":
        rows = list_runtime_logs(postgres_dsn, params, limit, offset)
    elif path == "/admin/runtime-metrics":
        rows = list_runtime_metrics(postgres_dsn, params, limit, offset)
    elif path == "/admin/runtime-daily-reports":
        rows = list_runtime_daily_reports(postgres_dsn, params, limit, offset)
    elif path == "/admin/capacity-alerts":
        rows = list_capacity_alerts(postgres_dsn, params, limit, offset)
    elif path == "/admin/strategy-runs":
        rows = list_strategy_runs(postgres_dsn, params, limit, offset)
    elif path == "/admin/strategy-signals":
        rows = list_strategy_signals(postgres_dsn, params, limit, offset)
    elif path == "/admin/strategy-decisions":
        rows = list_strategy_decisions(postgres_dsn, params, limit, offset)
    elif path == "/admin/strategy-escalations":
        rows = list_strategy_escalations(postgres_dsn, params, limit, offset)
    elif path == "/usage/daily":
        rows = list_usage_daily(postgres_dsn, params, limit, offset)
    else:
        raise QDataValidationError(f"unknown Kappa endpoint: {path}")
    resource = path.strip("/").replace("/", ".")
    return KappaResult(resource, rows, {"row_count": len(rows), "limit": limit, "offset": offset})


def fetch_kappa_overview(postgres_dsn: str | None) -> dict[str, Any]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM qmeta.tenant WHERE status = 'active') AS active_tenant_count,
                    (SELECT COUNT(*) FROM qmeta.project WHERE status = 'active') AS active_project_count,
                    (SELECT COUNT(*) FROM qmeta.principal WHERE status = 'active') AS active_principal_count,
                    (SELECT COUNT(*) FROM qmeta.api_token WHERE is_active = TRUE) AS active_token_count,
                    (SELECT COUNT(*) FROM qmeta.dataset_access_policy WHERE status = 'active') AS active_dataset_policy_count,
                    (SELECT COUNT(*) FROM qmeta.alert_event WHERE status = 'open') AS open_alert_count,
                    (SELECT COUNT(*) FROM qmeta.alert_notification_delivery WHERE status = 'sent') AS sent_notification_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_benchmark_schedule WHERE status = 'active') AS active_vendor_schedule_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_readiness_review WHERE review_date >= current_date - INTERVAL '30 days' AND status = 'ready') AS vendor_readiness_ready_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_readiness_review WHERE review_date >= current_date - INTERVAL '30 days' AND status = 'watch') AS vendor_readiness_watch_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_readiness_review WHERE review_date >= current_date - INTERVAL '30 days' AND status = 'rejected') AS vendor_readiness_rejected_count,
                    (SELECT status FROM qmeta.vendor_readiness_review ORDER BY review_date DESC, updated_at DESC LIMIT 1) AS latest_vendor_readiness_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_live_gate_run WHERE started_at >= now() - INTERVAL '24 hours') AS vendor_24h_live_gate_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_live_gate_run WHERE status = 'blocked' AND started_at >= now() - INTERVAL '24 hours') AS vendor_24h_live_gate_blocked_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_live_gate_run WHERE status IN ('success', 'warning') AND run_mode = 'live' AND started_at >= now() - INTERVAL '24 hours') AS vendor_24h_live_gate_executed_count,
                    (SELECT status FROM qmeta.vendor_live_gate_run ORDER BY started_at DESC, gate_id DESC LIMIT 1) AS latest_vendor_live_gate_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_onboarding_run WHERE started_at >= now() - INTERVAL '24 hours') AS vendor_24h_onboarding_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_onboarding_run WHERE status = 'blocked' AND started_at >= now() - INTERVAL '24 hours') AS vendor_24h_onboarding_blocked_count,
                    (SELECT status FROM qmeta.vendor_onboarding_run ORDER BY started_at DESC, run_id DESC LIMIT 1) AS latest_vendor_onboarding_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_live_closure_run WHERE started_at >= now() - INTERVAL '24 hours') AS vendor_24h_live_closure_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_live_closure_run WHERE status = 'blocked' AND started_at >= now() - INTERVAL '24 hours') AS vendor_24h_live_closure_blocked_count,
                    (SELECT status FROM qmeta.vendor_live_closure_run ORDER BY started_at DESC, closure_id DESC LIMIT 1) AS latest_vendor_live_closure_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_live_pilot_run WHERE started_at >= now() - INTERVAL '24 hours') AS vendor_24h_live_pilot_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_live_pilot_run WHERE status = 'blocked' AND started_at >= now() - INTERVAL '24 hours') AS vendor_24h_live_pilot_blocked_count,
                    (SELECT status FROM qmeta.vendor_live_pilot_run ORDER BY started_at DESC, pilot_id DESC LIMIT 1) AS latest_vendor_live_pilot_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_contract_profile WHERE status = 'active') AS vendor_contract_profile_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_contract_profile WHERE status = 'active' AND procurement_status = 'active' AND contract_status = 'active') AS vendor_active_contract_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_contract_dataset_entitlement WHERE status = 'active' AND entitlement_status = 'active') AS vendor_active_entitlement_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_procurement_readiness_snapshot WHERE created_at >= now() - INTERVAL '24 hours') AS vendor_24h_procurement_readiness_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_procurement_readiness_snapshot WHERE status = 'ready' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_procurement_ready_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_procurement_readiness_snapshot WHERE status = 'review_required' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_procurement_review_required_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_procurement_readiness_snapshot WHERE status IN ('blocked', 'no_contract') AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_procurement_blocked_count,
                    (SELECT status FROM qmeta.vendor_procurement_readiness_snapshot ORDER BY created_at DESC, snapshot_id DESC LIMIT 1) AS latest_vendor_procurement_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_procurement_readiness_snapshot WHERE procurement_role = 'primary_candidate' AND as_of_date = (SELECT MAX(as_of_date) FROM qmeta.vendor_procurement_readiness_snapshot)) AS vendor_procurement_primary_candidate_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_promotion_run WHERE started_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_promotion_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_promotion_dataset_result WHERE status = 'approved_for_primary' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_promotion_approved_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_promotion_dataset_result WHERE status = 'blocked' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_promotion_blocked_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_promotion_dataset_result WHERE status = 'applied' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_promotion_applied_count,
                    (SELECT status FROM qmeta.vendor_primary_promotion_run ORDER BY started_at DESC, promotion_id DESC LIMIT 1) AS latest_vendor_primary_promotion_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_promotion_dataset_result WHERE routing_change_allowed = TRUE AND created_at >= now() - INTERVAL '24 hours') AS vendor_primary_promotion_routing_allowed_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_post_promotion_monitor_run WHERE started_at >= now() - INTERVAL '24 hours') AS vendor_24h_post_promotion_monitor_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_post_promotion_dataset_monitor WHERE status = 'healthy' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_post_promotion_healthy_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_post_promotion_dataset_monitor WHERE status = 'rollback_recommended' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_post_promotion_rollback_recommended_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_post_promotion_dataset_monitor WHERE status = 'rolled_back' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_post_promotion_rolled_back_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_post_promotion_dataset_monitor WHERE status = 'no_applied_promotion' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_post_promotion_no_applied_count,
                    (SELECT status FROM qmeta.vendor_post_promotion_monitor_run ORDER BY started_at DESC, monitor_id DESC LIMIT 1) AS latest_vendor_post_promotion_status,
                    (SELECT COUNT(*) FROM qmeta.vendor_post_promotion_dataset_monitor WHERE rollback_allowed = TRUE AND created_at >= now() - INTERVAL '24 hours') AS vendor_post_promotion_rollback_allowed_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_stability_snapshot WHERE as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_stability_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_stability_snapshot WHERE status = 'healthy' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_stability_healthy_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_stability_snapshot WHERE status = 'warning' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_stability_warning_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_stability_snapshot WHERE status = 'critical' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_stability_critical_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_primary_stability_snapshot WHERE status = 'no_primary_promotion' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_primary_stability_no_primary_count,
                    (SELECT status FROM qmeta.vendor_primary_stability_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS latest_vendor_primary_stability_status,
                    (SELECT stability_role FROM qmeta.vendor_primary_stability_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS latest_vendor_primary_stability_role,
                    (SELECT primary_dataset_count FROM qmeta.vendor_primary_stability_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS vendor_primary_stability_primary_dataset_count,
                    (SELECT stability_score FROM qmeta.vendor_primary_stability_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS vendor_primary_stability_score,
                    (SELECT cost_units FROM qmeta.vendor_primary_stability_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS vendor_primary_stability_cost_units,
                    (SELECT scheduler_lag_minutes FROM qmeta.vendor_primary_stability_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS vendor_primary_stability_scheduler_lag_minutes,
                    (SELECT backlog_count FROM qmeta.vendor_primary_stability_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS vendor_primary_stability_backlog_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_cost_optimization_snapshot WHERE as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_cost_optimization_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_cost_optimization_snapshot WHERE status = 'optimized' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_cost_optimized_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_cost_optimization_snapshot WHERE status = 'over_budget' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_cost_over_budget_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_cost_optimization_snapshot WHERE status = 'quota_risk' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_cost_quota_risk_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_cost_optimization_snapshot WHERE status = 'no_primary_promotion' AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_cost_no_primary_count,
                    (SELECT status FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS latest_vendor_cost_optimization_status,
                    (SELECT optimization_role FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS latest_vendor_cost_optimization_role,
                    (SELECT recommended_primary_weight_pct FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS vendor_cost_primary_weight_pct,
                    (SELECT recommended_backup_weight_pct FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS vendor_cost_backup_weight_pct,
                    (SELECT recommended_free_source_weight_pct FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS vendor_cost_free_source_weight_pct,
                    (SELECT projected_budget_usage_pct FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS vendor_cost_budget_usage_pct,
                    (SELECT projected_monthly_quota_usage_pct FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS vendor_cost_monthly_quota_usage_pct,
                    (SELECT optimization_score FROM qmeta.vendor_cost_optimization_snapshot ORDER BY as_of_at DESC, optimization_id DESC LIMIT 1) AS vendor_cost_optimization_score,
                    (SELECT COUNT(*) FROM qmeta.vendor_route_weight_execution_run WHERE started_at >= now() - INTERVAL '24 hours') AS vendor_24h_route_execution_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_route_weight_execution_dataset WHERE status = 'pending_approval' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_route_pending_approval_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_route_weight_execution_dataset WHERE status = 'staged' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_route_staged_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_route_weight_execution_dataset WHERE status = 'applied' AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_route_applied_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_route_weight_execution_dataset WHERE status IN ('blocked', 'review_required', 'rollback_recommended', 'no_primary_promotion') AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_route_blocked_count,
                    (SELECT status FROM qmeta.vendor_route_weight_execution_run ORDER BY as_of_at DESC, execution_id DESC LIMIT 1) AS latest_vendor_route_execution_status,
                    (SELECT approval_status FROM qmeta.vendor_route_weight_execution_run ORDER BY as_of_at DESC, execution_id DESC LIMIT 1) AS latest_vendor_route_execution_approval_status,
                    (SELECT applied_primary_weight_pct FROM qmeta.vendor_route_weight_execution_run ORDER BY as_of_at DESC, execution_id DESC LIMIT 1) AS vendor_route_applied_primary_weight_pct,
                    (SELECT current_stage_sequence FROM qmeta.vendor_route_weight_execution_run ORDER BY as_of_at DESC, execution_id DESC LIMIT 1) AS vendor_route_current_stage_sequence,
                    (SELECT COUNT(*) FROM qmeta.vendor_production_source_run WHERE as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_production_source_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_production_source_run WHERE status IN ('production_ready', 'applied', 'monitoring') AND as_of_at >= now() - INTERVAL '24 hours') AS vendor_24h_production_source_ready_count,
                    (SELECT COUNT(*) FROM qmeta.vendor_production_source_dataset_check WHERE status IN ('blocked', 'failed', 'rollback_required') AND created_at >= now() - INTERVAL '24 hours') AS vendor_24h_production_source_blocked_count,
                    (SELECT status FROM qmeta.vendor_production_source_run ORDER BY as_of_at DESC, production_id DESC LIMIT 1) AS latest_vendor_production_source_status,
                    (SELECT production_role FROM qmeta.vendor_production_source_run ORDER BY as_of_at DESC, production_id DESC LIMIT 1) AS latest_vendor_production_source_role,
                    (SELECT production_score FROM qmeta.vendor_production_source_run ORDER BY as_of_at DESC, production_id DESC LIMIT 1) AS vendor_production_source_score,
                    (SELECT live_base_url_present FROM qmeta.vendor_production_source_run ORDER BY as_of_at DESC, production_id DESC LIMIT 1) AS vendor_production_source_live_base_url_present,
                    (SELECT live_token_present FROM qmeta.vendor_production_source_run ORDER BY as_of_at DESC, production_id DESC LIMIT 1) AS vendor_production_source_live_token_present,
                    (SELECT COUNT(*) FROM qmeta.source_route_weight_policy WHERE policy_status = 'active' AND effective_date <= current_date AND (end_date IS NULL OR end_date >= current_date)) AS active_source_route_weight_policy_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_decision_audit WHERE started_at >= now() - INTERVAL '24 hours') AS source_route_24h_decision_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_decision_audit WHERE fallback_applied = TRUE AND started_at >= now() - INTERVAL '24 hours') AS source_route_24h_fallback_count,
                    (SELECT decision_status FROM qmeta.source_route_decision_audit ORDER BY started_at DESC, decision_id DESC LIMIT 1) AS latest_source_route_decision_status,
                    (SELECT fin.source_code FROM qmeta.source_route_decision_audit srda LEFT JOIN qmeta.source_system fin ON fin.source_id = srda.final_source_id ORDER BY srda.started_at DESC, srda.decision_id DESC LIMIT 1) AS latest_source_route_final_source_code,
                    (SELECT COUNT(*) FROM qmeta.source_route_health_snapshot WHERE as_of_at >= now() - INTERVAL '24 hours') AS source_route_24h_health_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_health_snapshot WHERE status IN ('degraded', 'circuit_open') AND as_of_at >= now() - INTERVAL '24 hours') AS source_route_24h_unhealthy_count,
                    (SELECT status FROM qmeta.source_route_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS latest_source_route_health_status,
                    (SELECT COUNT(*) FROM qmeta.source_route_circuit_breaker WHERE status = 'open') AS source_route_open_circuit_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_recovery_probe WHERE probe_started_at >= now() - INTERVAL '24 hours') AS source_route_24h_recovery_probe_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_recovery_probe WHERE status = 'recovered' AND probe_started_at >= now() - INTERVAL '24 hours') AS source_route_24h_recovered_probe_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_action WHERE updated_at >= now() - INTERVAL '24 hours') AS source_route_24h_incident_action_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_action WHERE status = 'approval_required') AS source_route_pending_incident_action_count,
                    (SELECT status FROM qmeta.source_route_incident_action ORDER BY updated_at DESC, incident_action_id DESC LIMIT 1) AS latest_source_route_incident_action_status,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_control WHERE updated_at >= now() - INTERVAL '24 hours') AS source_route_24h_incident_control_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_control WHERE approval_status = 'pending') AS source_route_pending_incident_control_count,
                    (SELECT control_stage FROM qmeta.source_route_incident_control ORDER BY updated_at DESC, control_id DESC LIMIT 1) AS latest_source_route_incident_control_stage,
                    (SELECT status FROM qmeta.source_route_incident_control_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS source_route_latest_control_health_status,
                    (SELECT COALESCE(cardinality(health_issues), 0) FROM qmeta.source_route_incident_control_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS source_route_control_health_issue_count,
                    (SELECT approval_overdue_count FROM qmeta.source_route_incident_control_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS source_route_control_health_overdue_approval_count,
                    (SELECT notification_blocked_count FROM qmeta.source_route_incident_control_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS source_route_control_health_blocked_receipt_count,
                    (SELECT status FROM qmeta.source_route_incident_operation_batch ORDER BY started_at DESC, batch_id DESC LIMIT 1) AS source_route_latest_operation_status,
                    (SELECT eligible_count FROM qmeta.source_route_incident_operation_batch ORDER BY started_at DESC, batch_id DESC LIMIT 1) AS source_route_operation_queue_count,
                    (SELECT suppressed_notification_count FROM qmeta.source_route_incident_operation_batch ORDER BY started_at DESC, batch_id DESC LIMIT 1) AS source_route_operation_suppressed_notification_count,
                    (SELECT stress_scenario_count FROM qmeta.source_route_incident_operation_batch ORDER BY started_at DESC, batch_id DESC LIMIT 1) AS source_route_operation_stress_scenario_count,
                    (SELECT status FROM qmeta.source_route_incident_approval_command ORDER BY started_at DESC, command_id DESC LIMIT 1) AS source_route_latest_approval_command_status,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_command WHERE status = 'pending_quorum') AS source_route_approval_pending_quorum_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_command WHERE status = 'applied' AND started_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_applied_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_signature WHERE signed_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_signature_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_role_binding WHERE status = 'active') AS source_route_approval_active_role_binding_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_policy WHERE status = 'active') AS source_route_approval_active_policy_count,
                    (SELECT governance_status FROM qmeta.source_route_incident_approval_callback ORDER BY received_at DESC, callback_id DESC LIMIT 1) AS source_route_latest_approval_callback_status,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_callback WHERE signature_status = 'verified' AND received_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_verified_callback_count,
                    (SELECT COALESCE(SUM(replay_count), 0) FROM qmeta.source_route_incident_approval_callback WHERE received_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_replay_rejected_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_callback WHERE governance_status IN ('denied', 'invalid_signature', 'payload_invalid', 'failed') AND received_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_denied_callback_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_escalation WHERE status = 'open') AS source_route_approval_open_escalation_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_lock_event WHERE started_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_lock_event_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_lock_event WHERE lock_status = 'busy' AND started_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_lock_busy_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_state_transition WHERE observed_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_state_transition_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_state_transition WHERE transition_status = 'blocked' AND observed_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_state_blocked_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_audit_hash) AS source_route_approval_audit_hash_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_audit_hash WHERE verification_status = 'broken') AS source_route_approval_broken_audit_hash_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_sla_action WHERE action_status = 'planned') AS source_route_approval_planned_sla_action_count,
                    (SELECT status FROM qmeta.source_route_incident_approval_recovery_drill ORDER BY started_at DESC, drill_id DESC LIMIT 1) AS source_route_latest_approval_recovery_drill_status,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_recovery_drill WHERE status = 'success' AND started_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_successful_recovery_drill_count,
                    (SELECT status FROM qmeta.source_route_incident_approval_release_preflight ORDER BY started_at DESC, preflight_id DESC LIMIT 1) AS source_route_latest_approval_release_preflight_status,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_release_preflight WHERE started_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_release_preflight_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_release_preflight WHERE status = 'failed' AND started_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_failed_release_preflight_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_secret_rotation WHERE observed_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_secret_rotation_count,
                    (SELECT status FROM qmeta.source_route_incident_approval_secret_rotation ORDER BY observed_at DESC, rotation_id DESC LIMIT 1) AS source_route_latest_approval_secret_rotation_status,
                    (SELECT verified_secret_label FROM qmeta.source_route_incident_approval_secret_rotation ORDER BY observed_at DESC, rotation_id DESC LIMIT 1) AS source_route_latest_approval_verified_secret_label,
                    (SELECT status FROM qmeta.source_route_incident_approval_concurrency_test ORDER BY started_at DESC, test_id DESC LIMIT 1) AS source_route_latest_approval_concurrency_test_status,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_concurrency_test WHERE started_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_concurrency_test_count,
                    (SELECT COUNT(*) FROM qmeta.source_route_incident_approval_audit_export WHERE generated_at >= now() - INTERVAL '24 hours') AS source_route_approval_24h_audit_export_count,
                    (SELECT broken_hash_count FROM qmeta.source_route_incident_approval_audit_export ORDER BY generated_at DESC, export_id DESC LIMIT 1) AS source_route_latest_approval_audit_export_broken_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_fabric_run WHERE started_at >= now() - INTERVAL '24 hours') AS free_source_24h_fabric_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_fabric_run WHERE status = 'blocked' AND started_at >= now() - INTERVAL '24 hours') AS free_source_24h_fabric_blocked_count,
                    (SELECT status FROM qmeta.free_source_fabric_run ORDER BY started_at DESC, fabric_id DESC LIMIT 1) AS latest_free_source_fabric_status,
                    (SELECT COUNT(*) FROM qmeta.free_source_reliability_snapshot WHERE created_at >= now() - INTERVAL '24 hours') AS free_source_24h_reliability_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_reliability_snapshot WHERE status = 'ready' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_reliability_ready_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_reliability_snapshot WHERE status = 'degraded' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_reliability_degraded_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_reliability_snapshot WHERE status = 'rejected' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_reliability_rejected_count,
                    (SELECT status FROM qmeta.free_source_reliability_snapshot ORDER BY created_at DESC, snapshot_id DESC LIMIT 1) AS latest_free_source_reliability_status,
                    (SELECT COUNT(*) FROM qmeta.free_source_recovery_run WHERE started_at >= now() - INTERVAL '24 hours') AS free_source_24h_recovery_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_recovery_action WHERE created_at >= now() - INTERVAL '24 hours') AS free_source_24h_recovery_action_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_recovery_action WHERE alert_id IS NOT NULL AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_recovery_alert_count,
                    (SELECT status FROM qmeta.free_source_recovery_run ORDER BY started_at DESC, recovery_run_id DESC LIMIT 1) AS latest_free_source_recovery_status,
                    (SELECT COUNT(*) FROM qmeta.free_source_recovery_execution WHERE started_at >= now() - INTERVAL '24 hours') AS free_source_24h_recovery_execution_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_recovery_execution WHERE status = 'recovered' AND started_at >= now() - INTERVAL '24 hours') AS free_source_24h_recovered_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_recovery_execution WHERE status = 'failed' AND started_at >= now() - INTERVAL '24 hours') AS free_source_24h_recovery_failed_count,
                    (SELECT status FROM qmeta.free_source_recovery_execution ORDER BY started_at DESC, execution_id DESC LIMIT 1) AS latest_free_source_recovery_execution_status,
                    (SELECT COUNT(*) FROM qmeta.free_source_recovery_health_snapshot WHERE as_of_at >= now() - INTERVAL '24 hours') AS free_source_24h_recovery_health_count,
                    (SELECT status FROM qmeta.free_source_recovery_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS latest_free_source_recovery_health_status,
                    (SELECT approval_overdue_count FROM qmeta.free_source_recovery_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS free_source_recovery_overdue_approval_count,
                    (SELECT backlog_count FROM qmeta.free_source_recovery_health_snapshot ORDER BY as_of_at DESC, snapshot_id DESC LIMIT 1) AS free_source_recovery_backlog_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_admission_snapshot WHERE created_at >= now() - INTERVAL '24 hours') AS free_source_24h_admission_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_admission_snapshot WHERE status = 'approved' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_admission_approved_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_admission_snapshot WHERE status = 'conditional' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_admission_conditional_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_admission_snapshot WHERE status = 'review_required' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_admission_review_required_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_admission_snapshot WHERE status = 'blocked' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_admission_blocked_count,
                    (SELECT COUNT(*) FROM qmeta.free_source_admission_snapshot WHERE status = 'no_data' AND created_at >= now() - INTERVAL '24 hours') AS free_source_24h_admission_no_data_count,
                    (SELECT status FROM qmeta.free_source_admission_snapshot ORDER BY created_at DESC, admission_id DESC LIMIT 1) AS latest_free_source_admission_status,
                    (SELECT COUNT(*) FROM qmeta.free_source_admission_snapshot WHERE admission_role = 'primary_candidate' AND as_of_date = (SELECT MAX(as_of_date) FROM qmeta.free_source_admission_snapshot)) AS free_source_primary_candidate_count,
                    (SELECT COALESCE(SUM(request_count), 0) FROM qmeta.api_usage_daily WHERE usage_date >= current_date - INTERVAL '6 days') AS usage_7d_request_count,
                    (SELECT COALESCE(SUM(cost_units), 0) FROM qmeta.api_usage_daily WHERE usage_date >= current_date - INTERVAL '6 days') AS usage_7d_cost_units,
                    (SELECT COUNT(*) FROM qmeta.worker_run WHERE started_at >= current_date - INTERVAL '6 days') AS worker_7d_run_count,
                    (SELECT status FROM qmeta.worker_run ORDER BY started_at DESC LIMIT 1) AS latest_worker_status,
                    (SELECT COUNT(*) FROM qmeta.worker_schedule WHERE status = 'active') AS active_worker_schedule_count,
                    (SELECT COUNT(*) FROM qmeta.worker_heartbeat WHERE status = 'running' AND last_seen_at >= now() - INTERVAL '2 minutes') AS live_scheduler_count,
                    (SELECT COUNT(*) FROM qmeta.worker_lock WHERE expires_at <= now()) AS expired_worker_lock_count,
                    (SELECT status FROM qmeta.worker_schedule_tick ORDER BY started_at DESC LIMIT 1) AS latest_scheduler_tick_status,
                    (SELECT status FROM qmeta.deployment_health_snapshot ORDER BY checked_at DESC LIMIT 1) AS latest_deployment_health_status,
                    (SELECT status FROM qmeta.deployment_release ORDER BY created_at DESC LIMIT 1) AS latest_deployment_release_status,
                    (SELECT COUNT(*) FROM qmeta.deployment_health_snapshot WHERE checked_at >= now() - INTERVAL '24 hours' AND status = 'failed') AS deployment_24h_failed_count,
                    (SELECT COUNT(*) FROM qmeta.data_product WHERE status = 'active') AS active_product_count,
                    (SELECT COUNT(*) FROM qmeta.product_subscription WHERE status = 'active') AS active_subscription_count,
                    (SELECT COUNT(*) FROM qmeta.budget_policy WHERE status = 'active') AS active_budget_policy_count,
                    (SELECT COUNT(*) FROM qmeta.budget_alert WHERE status = 'open') AS budget_open_alert_count,
                    (SELECT COUNT(*) FROM qmeta.budget_usage_snapshot WHERE period_start >= date_trunc('month', current_date)::date AND status = 'blocked') AS budget_blocked_count,
                    (SELECT COALESCE(SUM(usage_amount), 0) FROM qmeta.budget_usage_snapshot WHERE period_start >= date_trunc('month', current_date)::date) AS budget_month_usage_amount,
                    (SELECT COALESCE(SUM(budget_amount), 0) FROM qmeta.budget_policy WHERE status = 'active' AND period = 'monthly') AS budget_month_limit_amount,
                    (SELECT COUNT(*) FROM qmeta.invoice WHERE invoice_date >= date_trunc('month', current_date)::date AND status <> 'void') AS invoice_month_count,
                    (SELECT COALESCE(SUM(total_amount), 0) FROM qmeta.invoice WHERE invoice_date >= date_trunc('month', current_date)::date AND status <> 'void') AS invoice_month_total_amount,
                    (SELECT COALESCE(SUM(paid_amount), 0) FROM qmeta.invoice WHERE invoice_date >= date_trunc('month', current_date)::date AND status <> 'void') AS invoice_month_paid_amount,
                    (SELECT COALESCE(SUM(outstanding_amount), 0) FROM qmeta.invoice WHERE invoice_date >= date_trunc('month', current_date)::date AND status <> 'void') AS invoice_month_outstanding_amount,
                    (SELECT COUNT(*) FROM qmeta.invoice WHERE status = 'overdue' OR (status IN ('issued', 'partially_paid') AND due_date < current_date AND outstanding_amount > 0)) AS overdue_invoice_count,
                    (SELECT COUNT(*) FROM qmeta.revenue_reconciliation_run WHERE reconciliation_date >= current_date - INTERVAL '30 days' AND status = 'mismatch') AS revenue_reconciliation_mismatch_count,
                    (SELECT status FROM qmeta.revenue_reconciliation_run ORDER BY reconciliation_date DESC, updated_at DESC LIMIT 1) AS latest_reconciliation_status,
                    (SELECT COALESCE(SUM(outstanding_amount), 0) FROM qmeta.ar_aging_snapshot WHERE as_of_date = (SELECT MAX(as_of_date) FROM qmeta.ar_aging_snapshot)) AS latest_ar_outstanding_amount,
                    (SELECT COUNT(*) FROM qmeta.customer_health_snapshot WHERE as_of_date = (SELECT MAX(as_of_date) FROM qmeta.customer_health_snapshot) AND status = 'active') AS customer_health_active_count,
                    (SELECT COUNT(*) FROM qmeta.customer_health_snapshot WHERE as_of_date = (SELECT MAX(as_of_date) FROM qmeta.customer_health_snapshot) AND status IN ('at_risk', 'dormant', 'churned')) AS customer_health_risk_count,
                    (SELECT COALESCE(SUM(base_amount), 0) FROM qmeta.payment_transaction WHERE direction = 'inbound' AND value_date >= date_trunc('month', current_date)::date AND status <> 'reversed') AS payment_month_received_amount,
                    (SELECT COALESCE(SUM(base_matched_amount), 0) FROM qmeta.payment_invoice_match WHERE matched_at >= date_trunc('month', current_date) AND status IN ('matched', 'partial', 'overpaid')) AS payment_month_matched_amount,
                    (SELECT COUNT(*) FROM qmeta.payment_transaction WHERE direction = 'inbound' AND status IN ('imported', 'unmatched')) AS unmatched_payment_count,
                    (SELECT status FROM qmeta.payment_import_batch ORDER BY imported_at DESC, updated_at DESC LIMIT 1) AS latest_payment_batch_status,
                    (SELECT COALESCE(SUM(base_credit_amount), 0) FROM qmeta.revenue_ledger_entry WHERE entry_date >= date_trunc('month', current_date)::date) AS revenue_ledger_month_credit_amount,
                    (SELECT COUNT(*) FROM qmeta.runtime_log WHERE log_time >= now() - INTERVAL '24 hours' AND severity IN ('error', 'critical')) AS runtime_24h_error_log_count,
                    (SELECT COUNT(*) FROM qmeta.runtime_metric_snapshot WHERE metric_time >= now() - INTERVAL '24 hours' AND status = 'warning') AS runtime_metric_warning_count,
                    (SELECT COUNT(*) FROM qmeta.runtime_metric_snapshot WHERE metric_time >= now() - INTERVAL '24 hours' AND status = 'critical') AS runtime_metric_critical_count,
                    (SELECT COUNT(*) FROM qmeta.capacity_alert WHERE status = 'open') AS open_capacity_alert_count,
                    (SELECT status FROM qmeta.runtime_daily_report ORDER BY report_date DESC, updated_at DESC LIMIT 1) AS latest_runtime_report_status,
                    (SELECT status FROM qmeta.strategy_run ORDER BY run_date DESC, started_at DESC LIMIT 1) AS latest_strategy_status,
                    (SELECT highest_severity FROM qmeta.strategy_run ORDER BY run_date DESC, started_at DESC LIMIT 1) AS latest_strategy_severity,
                    (SELECT COUNT(*) FROM qmeta.strategy_decision WHERE decided_at >= now() - INTERVAL '24 hours' AND status IN ('review', 'escalate', 'block', 'hold')) AS strategy_24h_action_decision_count,
                    (SELECT COUNT(*) FROM qmeta.strategy_escalation_event WHERE status = 'open') AS open_strategy_escalation_count,
                    (SELECT COUNT(*) FROM qmeta.access_decision_audit WHERE evaluated_at >= now() - INTERVAL '24 hours' AND decision = 'deny') AS access_denied_24h_count,
                    (SELECT COUNT(*) FROM qmeta.project_governance_snapshot WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM qmeta.project_governance_snapshot) AND status = 'warning') AS project_governance_warning_count,
                    (SELECT COUNT(*) FROM qmeta.project_governance_snapshot WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM qmeta.project_governance_snapshot) AND status = 'critical') AS project_governance_critical_count,
                    (SELECT COUNT(*) FROM qmeta.governance_action WHERE status IN ('open', 'in_progress')) AS open_governance_action_count,
                    (SELECT COUNT(*) FROM qmeta.automation_run WHERE started_at >= now() - INTERVAL '24 hours') AS automation_24h_run_count,
                    (SELECT COUNT(*) FROM qmeta.automation_action WHERE created_at >= now() - INTERVAL '24 hours') AS automation_24h_action_count,
                    (SELECT COUNT(*) FROM qmeta.automation_action WHERE status = 'approval_required') AS automation_approval_required_count,
                    (SELECT COUNT(*) FROM qmeta.automation_action WHERE status = 'failed' AND updated_at >= now() - INTERVAL '24 hours') AS automation_24h_failed_count,
                    (SELECT COUNT(*) FROM qmeta.automation_approval WHERE status = 'pending') AS automation_pending_approval_count,
                    (SELECT COUNT(*) FROM qmeta.automation_action WHERE omega_control_status = 'retry_scheduled') AS automation_retry_scheduled_count,
                    (SELECT COUNT(*) FROM qmeta.automation_action WHERE rollback_required = TRUE OR omega_control_status = 'rollback_required') AS automation_rollback_required_count,
                    (SELECT COUNT(*) FROM qmeta.automation_executor WHERE status = 'active' AND executor_type IN ('webhook', 'script') AND sandbox_mode = TRUE) AS automation_active_sandbox_executor_count,
                    (SELECT COUNT(*) FROM qmeta.automation_executor_allowlist WHERE status = 'active') AS automation_active_allowlist_count,
                    (SELECT COUNT(*) FROM qmeta.automation_secret_ref WHERE status = 'active') AS automation_active_secret_ref_count,
                    (SELECT COUNT(*) FROM qmeta.automation_external_channel WHERE status = 'active') AS automation_active_channel_count,
                    (SELECT COUNT(*) FROM qmeta.automation_external_dispatch WHERE created_at >= now() - INTERVAL '24 hours') AS automation_24h_dispatch_count,
                    (SELECT COUNT(*) FROM qmeta.automation_external_dispatch WHERE status = 'dead_letter') AS automation_dead_letter_count,
                    (SELECT status FROM qmeta.automation_external_dispatch ORDER BY updated_at DESC, dispatch_id DESC LIMIT 1) AS latest_automation_dispatch_status,
                    (SELECT COUNT(*) FROM qmeta.automation_channel_profile WHERE profile_status = 'active') AS automation_active_profile_count,
                    (SELECT COUNT(*) FROM qmeta.automation_channel_profile WHERE readiness_status IN ('dry_run_ready', 'live_ready')) AS automation_ready_profile_count,
                    (SELECT COUNT(*) FROM qmeta.automation_channel_validation WHERE started_at >= now() - INTERVAL '24 hours') AS automation_24h_validation_count,
                    (SELECT status FROM qmeta.automation_channel_validation ORDER BY started_at DESC, validation_id DESC LIMIT 1) AS latest_automation_validation_status,
                    (SELECT COUNT(*) FROM qmeta.automation_secret_rotation WHERE status = 'applied') AS automation_applied_rotation_count,
                    (SELECT status FROM qmeta.automation_secret_rotation ORDER BY created_at DESC, rotation_id DESC LIMIT 1) AS latest_automation_rotation_status,
                    (SELECT COUNT(*) FROM qmeta.automation_live_provider_receipt WHERE created_at >= now() - INTERVAL '24 hours') AS automation_24h_live_receipt_count,
                    (SELECT COUNT(*) FROM qmeta.automation_live_provider_receipt WHERE provider_code = 'wecom' AND status = 'success' AND created_at >= now() - INTERVAL '24 hours') AS automation_24h_wecom_success_count,
                    (SELECT status FROM qmeta.automation_live_provider_receipt ORDER BY created_at DESC, receipt_id DESC LIMIT 1) AS latest_automation_live_receipt_status,
                    (SELECT status FROM qmeta.automation_execution_attempt ORDER BY started_at DESC, attempt_id DESC LIMIT 1) AS latest_automation_attempt_status,
                    (SELECT status FROM qmeta.automation_run ORDER BY started_at DESC, automation_run_id DESC LIMIT 1) AS latest_automation_status
                """
            )
            return normalize_rows([dict(cursor.fetchone())])[0]


def list_tenants(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(params, [("tenant_code", "t.tenant_code"), ("status", "t.status")])
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            t.tenant_id, t.tenant_code, t.tenant_name, t.status, t.owner,
            COUNT(DISTINCT p.project_id) AS project_count,
            COUNT(DISTINCT pr.principal_id) AS principal_count,
            COUNT(DISTINCT tok.token_id) AS token_count,
            t.created_at, t.updated_at
        FROM qmeta.tenant t
        LEFT JOIN qmeta.project p ON p.tenant_id = t.tenant_id
        LEFT JOIN qmeta.principal pr ON pr.tenant_id = t.tenant_id
        LEFT JOIN qmeta.api_token tok ON tok.tenant_id = t.tenant_id
        {where}
        GROUP BY t.tenant_id
        ORDER BY t.tenant_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_projects(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("status", "p.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            p.project_id, t.tenant_code, p.project_code, p.project_name, p.status, p.owner,
            COUNT(DISTINCT pm.member_id) AS member_count,
            COUNT(DISTINCT tok.token_id) AS token_count,
            COUNT(DISTINCT dap.access_id) AS dataset_policy_count,
            p.created_at, p.updated_at
        FROM qmeta.project p
        JOIN qmeta.tenant t ON t.tenant_id = p.tenant_id
        LEFT JOIN qmeta.project_member pm ON pm.project_id = p.project_id
        LEFT JOIN qmeta.api_token tok ON tok.project_id = p.project_id
        LEFT JOIN qmeta.dataset_access_policy dap ON dap.project_id = p.project_id
        {where}
        GROUP BY p.project_id, t.tenant_code
        ORDER BY t.tenant_code, p.project_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_principals(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("tenant_code", "t.tenant_code"),
            ("principal_code", "pr.principal_code"),
            ("principal_type", "pr.principal_type"),
            ("status", "pr.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            pr.principal_id, t.tenant_code, pr.principal_code, pr.principal_name,
            pr.principal_type, pr.email, pr.status,
            COUNT(DISTINCT pm.project_id) AS project_count,
            COUNT(DISTINCT tok.token_id) AS token_count,
            pr.created_at, pr.updated_at
        FROM qmeta.principal pr
        JOIN qmeta.tenant t ON t.tenant_id = pr.tenant_id
        LEFT JOIN qmeta.project_member pm ON pm.principal_id = pr.principal_id
        LEFT JOIN qmeta.api_token tok ON tok.principal_id = pr.principal_id
        {where}
        GROUP BY pr.principal_id, t.tenant_code
        ORDER BY t.tenant_code, pr.principal_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_tokens(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("principal_code", "pr.principal_code"),
            ("token_name", "tok.token_name"),
            ("cost_center", "tok.cost_center"),
        ],
    )
    active = _param(params, "is_active")
    if active is not None:
        where, values = _append_where(where, values, "tok.is_active = %s", _bool(active))
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            tok.token_id, tok.token_name, tok.owner, RIGHT(tok.token_hash, 8) AS token_hash_tail,
            tok.scopes, tok.quota_per_min, tok.is_active, tok.last_used_at, tok.expires_at,
            tok.cost_center, t.tenant_code, p.project_code, pr.principal_code,
            tok.created_at
        FROM qmeta.api_token tok
        LEFT JOIN qmeta.tenant t ON t.tenant_id = tok.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = tok.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = tok.principal_id
        {where}
        ORDER BY COALESCE(tok.last_used_at, tok.created_at) DESC, tok.token_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_dataset_access(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("dataset_code", "dc.dataset_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("principal_code", "pr.principal_code"),
            ("status", "dap.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            dap.access_id, dc.dataset_code, t.tenant_code, p.project_code, pr.principal_code,
            dap.access_level, dap.field_allowlist, dap.field_denylist, dap.row_filter,
            dap.status, dap.expires_at, dap.created_at, dap.updated_at
        FROM qmeta.dataset_access_policy dap
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = dap.dataset_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = dap.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = dap.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = dap.principal_id
        {where}
        ORDER BY dc.dataset_code, t.tenant_code NULLS LAST, p.project_code NULLS LAST, pr.principal_code NULLS LAST
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_notification_deliveries(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("channel_code", "nc.channel_code"),
            ("status", "d.status"),
            ("severity", "ae.severity"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            d.delivery_id, d.delivery_key, d.status, d.attempt_count, d.last_attempt_at,
            d.delivered_at, nc.channel_code, nc.channel_type, ae.alert_id, ae.alert_type,
            ae.severity, ae.trade_date, ae.message, d.response_summary, d.error_message,
            d.created_at, d.updated_at
        FROM qmeta.alert_notification_delivery d
        JOIN qmeta.notification_channel nc ON nc.channel_id = d.channel_id
        JOIN qmeta.alert_event ae ON ae.alert_id = d.alert_id
        {where}
        ORDER BY d.updated_at DESC, d.delivery_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_schedules(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("schedule_code", "vbs.schedule_code"),
            ("dataset_code", "dc.dataset_code"),
            ("status", "vbs.status"),
            ("cadence", "vbs.cadence"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vbs.schedule_id, vbs.schedule_code, dc.dataset_code,
            ps.source_code AS primary_source_code,
            ss.source_code AS secondary_source_code,
            vbs.start_date, vbs.end_date, vbs.target_trade_days, vbs.shard_size,
            vbs.max_symbols, vbs.cadence, vbs.status, vbs.last_suite_id,
            suite.suite_code AS last_suite_code,
            suite.status AS last_suite_status,
            suite.conflict_rate AS last_conflict_rate,
            suite.coverage_rate AS last_coverage_rate,
            vbs.last_run_at, vbs.next_run_at, vbs.details, vbs.created_at, vbs.updated_at
        FROM qmeta.vendor_benchmark_schedule vbs
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vbs.dataset_id
        JOIN qmeta.source_system ps ON ps.source_id = vbs.primary_source_id
        JOIN qmeta.source_system ss ON ss.source_id = vbs.secondary_source_id
        LEFT JOIN qmeta.provider_benchmark_suite_run suite ON suite.suite_id = vbs.last_suite_id
        {where}
        ORDER BY vbs.status, vbs.next_run_at NULLS LAST, vbs.schedule_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_readiness_reviews(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("review_code", "vrr.review_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vrr.status"),
            ("recommendation", "vrr.recommendation"),
            ("recommended_role", "vrr.recommended_role"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vrr.review_id, vrr.review_code, dc.dataset_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vrr.review_date, vrr.required_windows, vrr.suite_count,
            vrr.passed_window_count, vrr.warning_window_count,
            vrr.failed_window_count, vrr.missing_window_count,
            vrr.status, vrr.recommendation, vrr.recommended_role,
            vrr.observed_min_coverage_rate, vrr.observed_max_conflict_rate,
            vrr.observed_max_failure_rate, vrr.observed_max_p95_latency_ms,
            vrr.observed_min_rows_per_second, vrr.profile_status,
            vrr.runtime_mode, vrr.blocking_issues, vrr.next_actions,
            vrr.details, vrr.created_at, vrr.updated_at
        FROM qmeta.vendor_readiness_review vrr
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrr.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = vrr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vrr.primary_source_id
        {where}
        ORDER BY vrr.review_date DESC, vrr.updated_at DESC, vrr.review_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_vendor_readiness_windows(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("review_code", "vrr.review_code"),
            ("dataset_code", "dc.dataset_code"),
            ("source_code", "ss.source_code"),
            ("primary_source_code", "ps.source_code"),
            ("status", "vrw.status"),
            ("window_days", "vrw.window_days"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            vrw.window_id, vrr.review_code, dc.dataset_code,
            ss.source_code, ps.source_code AS primary_source_code,
            vrw.window_days, vrw.status, suite.suite_code,
            vrw.coverage_rate, vrw.conflict_rate, vrw.failure_rate,
            vrw.p95_latency_ms, vrw.rows_per_second,
            vrw.symbol_count, vrw.benchmark_count,
            vrw.blocking_issues, vrw.details, vrw.created_at, vrw.updated_at
        FROM qmeta.vendor_readiness_window vrw
        JOIN qmeta.vendor_readiness_review vrr ON vrr.review_id = vrw.review_id
        JOIN qmeta.dataset_catalog dc ON dc.dataset_id = vrr.dataset_id
        JOIN qmeta.source_system ss ON ss.source_id = vrr.source_id
        LEFT JOIN qmeta.source_system ps ON ps.source_id = vrr.primary_source_id
        LEFT JOIN qmeta.provider_benchmark_suite_run suite ON suite.suite_id = vrw.suite_id
        {where}
        ORDER BY vrr.review_date DESC, vrr.updated_at DESC, vrw.window_days
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_worker_runs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("status", "wr.status"),
            ("trigger_mode", "wr.trigger_mode"),
        ],
    )
    task_name = _param(params, "task_name")
    if task_name:
        where, values = _append_where(where, values, "EXISTS (SELECT 1 FROM qmeta.worker_task_run x WHERE x.worker_run_id = wr.worker_run_id AND x.task_name = %s)", task_name)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            wr.worker_run_id, wr.run_code, wr.trigger_mode, wr.status, wr.task_filter,
            wr.dry_run, wr.started_at, wr.finished_at, wr.duration_ms,
            wr.processed_count, wr.success_count, wr.warning_count, wr.failed_count,
            COUNT(wtr.task_run_id) AS task_count,
            COALESCE(SUM(wtr.processed_count), 0) AS task_processed_count,
            wr.details, wr.error_message, wr.created_at, wr.updated_at
        FROM qmeta.worker_run wr
        LEFT JOIN qmeta.worker_task_run wtr ON wtr.worker_run_id = wr.worker_run_id
        {where}
        GROUP BY wr.worker_run_id
        ORDER BY wr.started_at DESC, wr.worker_run_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_worker_schedules(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("schedule_code", "ws.schedule_code"),
            ("task_name", "ws.task_name"),
            ("status", "ws.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ws.schedule_id, ws.schedule_code, ws.task_name, ws.status,
            ws.frequency_seconds, ws.max_runtime_seconds, ws.lock_timeout_seconds,
            ws.retry_limit, ws.retry_backoff_seconds, ws.dry_run, ws.task_args,
            ws.last_status, ws.last_run_at, ws.next_run_at, ws.run_count,
            ws.success_count, ws.warning_count, ws.failed_count,
            ws.last_worker_run_id, wr.run_code AS last_worker_run_code,
            ws.details, ws.created_at, ws.updated_at
        FROM qmeta.worker_schedule ws
        LEFT JOIN qmeta.worker_run wr ON wr.worker_run_id = ws.last_worker_run_id
        {where}
        ORDER BY ws.status, ws.next_run_at NULLS FIRST, ws.schedule_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_worker_locks(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("lock_name", "wl.lock_name"),
            ("owner_id", "wl.owner_id"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            wl.lock_name, wl.owner_id, wl.acquired_at, wl.heartbeat_at,
            wl.expires_at, wl.expires_at <= now() AS is_expired,
            wl.details, wl.created_at, wl.updated_at
        FROM qmeta.worker_lock wl
        {where}
        ORDER BY wl.expires_at, wl.lock_name
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_worker_heartbeats(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("scheduler_id", "wh.scheduler_id"),
            ("status", "wh.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            wh.scheduler_id, wh.status, wh.host_name, wh.process_id,
            wh.started_at, wh.last_seen_at, wh.stopped_at,
            wh.current_schedule_code, wh.tick_count, wh.run_count,
            wh.last_seen_at < now() - INTERVAL '2 minutes' AS is_stale,
            wh.details, wh.created_at, wh.updated_at
        FROM qmeta.worker_heartbeat wh
        {where}
        ORDER BY wh.last_seen_at DESC, wh.scheduler_id
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_worker_schedule_ticks(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("schedule_code", "wst.schedule_code"),
            ("scheduler_id", "wst.scheduler_id"),
            ("task_name", "wst.task_name"),
            ("status", "wst.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            wst.tick_id, wst.tick_code, wst.scheduler_id, wst.schedule_code,
            wst.task_name, wst.status, wst.due_at, wst.started_at,
            wst.finished_at, wst.duration_ms, wst.worker_run_id,
            wr.run_code AS worker_run_code, wst.lock_name, wst.lock_acquired,
            wst.dry_run, wst.details, wst.error_message, wst.created_at, wst.updated_at
        FROM qmeta.worker_schedule_tick wst
        LEFT JOIN qmeta.worker_run wr ON wr.worker_run_id = wst.worker_run_id
        {where}
        ORDER BY wst.started_at DESC, wst.tick_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_deployment_releases(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("release_code", "dr.release_code"),
            ("environment", "dr.environment"),
            ("status", "dr.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            dr.release_id, dr.release_code, dr.release_name, dr.environment,
            dr.version_label, dr.git_ref, dr.status, dr.started_at, dr.finished_at,
            dr.health_snapshot_id, dhs.status AS health_status,
            dhs.checked_at AS health_checked_at, dr.details, dr.created_at, dr.updated_at
        FROM qmeta.deployment_release dr
        LEFT JOIN qmeta.deployment_health_snapshot dhs ON dhs.snapshot_id = dr.health_snapshot_id
        {where}
        ORDER BY dr.created_at DESC, dr.release_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_deployment_health(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "dhs.snapshot_code"),
            ("environment", "dhs.environment"),
            ("status", "dhs.status"),
            ("release_code", "dr.release_code"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            dhs.snapshot_id, dhs.snapshot_code, dhs.environment, dhs.status,
            dhs.checked_at, dhs.duration_ms, dhs.check_count,
            dhs.success_count, dhs.warning_count, dhs.failed_count,
            dr.release_code, dhs.details, dhs.created_at
        FROM qmeta.deployment_health_snapshot dhs
        LEFT JOIN qmeta.deployment_release dr ON dr.release_id = dhs.release_id
        {where}
        ORDER BY dhs.checked_at DESC, dhs.snapshot_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_deployment_health_checks(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "dhs.snapshot_code"),
            ("component", "dhc.component"),
            ("status", "dhc.status"),
            ("check_name", "dhc.check_name"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            dhc.health_check_id, dhs.snapshot_code, dhc.check_name, dhc.component,
            dhc.status, dhc.duration_ms, dhc.details, dhc.error_message, dhc.created_at
        FROM qmeta.deployment_health_check dhc
        JOIN qmeta.deployment_health_snapshot dhs ON dhs.snapshot_id = dhc.snapshot_id
        {where}
        ORDER BY dhc.created_at DESC, dhc.health_check_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_deployment_events(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("environment", "de.environment"),
            ("event_type", "de.event_type"),
            ("status", "de.status"),
            ("release_code", "dr.release_code"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            de.event_id, de.event_code, de.environment, de.event_type, de.status,
            de.message, dr.release_code, de.details, de.created_at
        FROM qmeta.deployment_event de
        LEFT JOIN qmeta.deployment_release dr ON dr.release_id = de.release_id
        {where}
        ORDER BY de.created_at DESC, de.event_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_data_products(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("product_code", "dp.product_code"),
            ("product_type", "dp.product_type"),
            ("status", "dp.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            dp.product_id, dp.product_code, dp.product_name, dp.product_type,
            dp.status, dp.billing_unit, dp.update_frequency, dp.sla_level,
            COUNT(DISTINCT dpd.dataset_id) AS dataset_count,
            COUNT(DISTINCT dpa.api_name) AS api_count,
            dp.license_scope, dp.owner, dp.details, dp.created_at, dp.updated_at
        FROM qmeta.data_product dp
        LEFT JOIN qmeta.data_product_dataset dpd ON dpd.product_id = dp.product_id
        LEFT JOIN qmeta.data_product_api dpa ON dpa.product_id = dp.product_id
        {where}
        GROUP BY dp.product_id
        ORDER BY dp.status, dp.product_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_pricing_plans(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("plan_code", "pp.plan_code"),
            ("billing_cycle", "pp.billing_cycle"),
            ("status", "pp.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            pp.plan_id, pp.plan_code, pp.plan_name, pp.billing_cycle, pp.currency,
            pp.base_fee, pp.included_cost_units, pp.included_requests, pp.status,
            COUNT(DISTINCT pr.rule_id) AS rule_count,
            COUNT(DISTINCT ps.subscription_id) AS subscription_count,
            pp.details, pp.created_at, pp.updated_at
        FROM qmeta.pricing_plan pp
        LEFT JOIN qmeta.pricing_rule pr ON pr.plan_id = pp.plan_id
        LEFT JOIN qmeta.product_subscription ps ON ps.plan_id = pp.plan_id
        {where}
        GROUP BY pp.plan_id
        ORDER BY pp.status, pp.plan_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_pricing_rules(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("plan_code", "pp.plan_code"),
            ("product_code", "dp.product_code"),
            ("api_name", "pr.api_name"),
            ("metric_name", "pr.metric_name"),
            ("status", "pr.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            pr.rule_id, pr.rule_code, pp.plan_code, dp.product_code,
            pr.metric_name, pr.api_name, pr.unit_price, pr.free_quantity,
            pr.tier_start, pr.tier_end, pr.effective_from, pr.effective_to,
            pr.status, pr.details, pr.created_at, pr.updated_at
        FROM qmeta.pricing_rule pr
        JOIN qmeta.pricing_plan pp ON pp.plan_id = pr.plan_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = pr.product_id
        {where}
        ORDER BY pp.plan_code, dp.product_code NULLS LAST, pr.api_name NULLS LAST, pr.rule_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_product_subscriptions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("subscription_code", "ps.subscription_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("plan_code", "pp.plan_code"),
            ("product_code", "dp.product_code"),
            ("status", "ps.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ps.subscription_id, ps.subscription_code, t.tenant_code, p.project_code,
            pp.plan_code, dp.product_code, ps.status, ps.starts_on, ps.ends_on,
            ps.auto_renew, ps.hard_limit_enabled, ps.details, ps.created_at, ps.updated_at
        FROM qmeta.product_subscription ps
        JOIN qmeta.tenant t ON t.tenant_id = ps.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = ps.project_id
        JOIN qmeta.pricing_plan pp ON pp.plan_id = ps.plan_id
        JOIN qmeta.data_product dp ON dp.product_id = ps.product_id
        {where}
        ORDER BY ps.status, t.tenant_code, p.project_code NULLS LAST, dp.product_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_budget_policies(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("budget_code", "bp.budget_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("principal_code", "pr.principal_code"),
            ("cost_center", "bp.cost_center"),
            ("plan_code", "pp.plan_code"),
            ("product_code", "dp.product_code"),
            ("status", "bp.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            bp.budget_id, bp.budget_code, bp.budget_name, t.tenant_code,
            p.project_code, pr.principal_code, bp.cost_center, pp.plan_code,
            dp.product_code, bp.period, bp.budget_amount, bp.currency,
            bp.soft_threshold_pct, bp.hard_threshold_pct, bp.hard_limit_enabled,
            bp.status, latest.status AS latest_usage_status,
            latest.usage_amount AS latest_usage_amount,
            latest.usage_pct AS latest_usage_pct,
            bp.starts_on, bp.ends_on, bp.details, bp.created_at, bp.updated_at
        FROM qmeta.budget_policy bp
        LEFT JOIN qmeta.tenant t ON t.tenant_id = bp.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = bp.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = bp.principal_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = bp.plan_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = bp.product_id
        LEFT JOIN LATERAL (
            SELECT bus.status, bus.usage_amount, bus.usage_pct
            FROM qmeta.budget_usage_snapshot bus
            WHERE bus.budget_id = bp.budget_id
            ORDER BY bus.period_start DESC, bus.updated_at DESC
            LIMIT 1
        ) latest ON TRUE
        {where}
        ORDER BY bp.status, t.tenant_code NULLS LAST, p.project_code NULLS LAST, bp.budget_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_budget_usage(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("budget_code", "bp.budget_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("cost_center", "bp.cost_center"),
            ("status", "bus.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            bus.snapshot_id, bus.snapshot_code, bp.budget_code, t.tenant_code,
            p.project_code, bp.cost_center, bus.period_start, bus.period_end,
            bus.usage_amount, bus.budget_amount, bus.usage_pct,
            bus.request_count, bus.row_count, bus.cost_units, bus.status,
            bus.details, bus.created_at, bus.updated_at
        FROM qmeta.budget_usage_snapshot bus
        JOIN qmeta.budget_policy bp ON bp.budget_id = bus.budget_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = bp.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = bp.project_id
        {where}
        ORDER BY bus.period_start DESC, bus.status DESC, bus.usage_amount DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_budget_alerts(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("budget_code", "bp.budget_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("cost_center", "bp.cost_center"),
            ("alert_type", "ba.alert_type"),
            ("severity", "ba.severity"),
            ("status", "ba.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ba.budget_alert_id, ba.alert_key, bp.budget_code, t.tenant_code,
            p.project_code, bp.cost_center, ba.alert_type, ba.severity,
            ba.status, ba.threshold_pct, ba.usage_pct, ba.message,
            bus.snapshot_code, ba.details, ba.first_seen_at, ba.last_seen_at,
            ba.resolved_at, ba.created_at, ba.updated_at
        FROM qmeta.budget_alert ba
        JOIN qmeta.budget_policy bp ON bp.budget_id = ba.budget_id
        LEFT JOIN qmeta.budget_usage_snapshot bus ON bus.snapshot_id = ba.snapshot_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = bp.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = bp.project_id
        {where}
        ORDER BY ba.status, ba.severity DESC, ba.last_seen_at DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_invoices(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("invoice_code", "i.invoice_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("subscription_code", "ps.subscription_code"),
            ("plan_code", "pp.plan_code"),
            ("product_code", "dp.product_code"),
            ("status", "i.status"),
        ],
    )
    where, values = _append_period_filter(where, values, params, "i.period_start", "i.period_end")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            i.invoice_id, i.invoice_code, t.tenant_code, p.project_code,
            ps.subscription_code, pp.plan_code, dp.product_code,
            i.period_start, i.period_end, i.invoice_date, i.due_date,
            i.currency, i.status, i.subtotal_amount, i.discount_amount,
            i.tax_amount, i.total_amount, i.paid_amount, i.outstanding_amount,
            COALESCE(line_counts.line_count, 0) AS line_count,
            i.issued_at, i.paid_at, i.voided_at, i.details, i.created_at, i.updated_at
        FROM qmeta.invoice i
        JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = i.project_id
        LEFT JOIN qmeta.product_subscription ps ON ps.subscription_id = i.subscription_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = i.plan_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = i.product_id
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS line_count
            FROM qmeta.invoice_line il
            WHERE il.invoice_id = i.invoice_id
        ) line_counts ON TRUE
        {where}
        ORDER BY i.invoice_date DESC, i.period_start DESC, i.invoice_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_invoice_lines(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("invoice_code", "i.invoice_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("product_code", "dp.product_code"),
            ("api_name", "il.api_name"),
            ("metric_name", "il.metric_name"),
        ],
    )
    where, values = _append_period_filter(where, values, params, "il.period_start", "il.period_end")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            il.line_id, il.line_code, i.invoice_code, t.tenant_code, p.project_code,
            dp.product_code, pp.plan_code, ps.subscription_code, il.api_name,
            il.metric_name, il.period_start, il.period_end, il.quantity,
            il.unit_price, il.amount, il.request_count, il.row_count,
            il.cost_units, pr.rule_code, il.details, il.created_at, il.updated_at
        FROM qmeta.invoice_line il
        JOIN qmeta.invoice i ON i.invoice_id = il.invoice_id
        JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = i.project_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = il.product_id
        LEFT JOIN qmeta.pricing_rule pr ON pr.rule_id = il.pricing_rule_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = i.plan_id
        LEFT JOIN qmeta.product_subscription ps ON ps.subscription_id = i.subscription_id
        {where}
        ORDER BY i.invoice_date DESC, il.line_id
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_invoice_events(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("invoice_code", "i.invoice_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("event_type", "ie.event_type"),
            ("status", "ie.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ie.event_id, ie.event_code, i.invoice_code, t.tenant_code,
            p.project_code, ie.event_type, ie.status, ie.message,
            ie.details, ie.created_at
        FROM qmeta.invoice_event ie
        JOIN qmeta.invoice i ON i.invoice_id = ie.invoice_id
        JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = i.project_id
        {where}
        ORDER BY ie.created_at DESC, ie.event_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_revenue_summary(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("product_code", "dp.product_code"),
            ("plan_code", "pp.plan_code"),
            ("subscription_code", "ps.subscription_code"),
            ("status", "i.status"),
        ],
    )
    if not _param(params, "status"):
        where = f"{where} AND i.status <> 'void'" if where else "WHERE i.status <> 'void'"
    where, values = _append_period_filter(where, values, params, "i.period_start", "i.period_end")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            t.tenant_code, p.project_code, dp.product_code, pp.plan_code,
            i.currency, MIN(i.period_start) AS first_period_start,
            MAX(i.period_end) AS last_period_end, COUNT(*) AS invoice_count,
            COALESCE(SUM(i.total_amount), 0) AS total_amount,
            COALESCE(SUM(i.paid_amount), 0) AS paid_amount,
            COALESCE(SUM(i.outstanding_amount), 0) AS outstanding_amount,
            COALESCE(SUM(CASE WHEN i.status = 'overdue' OR (i.status IN ('issued', 'partially_paid') AND i.due_date < current_date AND i.outstanding_amount > 0) THEN 1 ELSE 0 END), 0) AS overdue_invoice_count
        FROM qmeta.invoice i
        JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = i.project_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = i.product_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = i.plan_id
        LEFT JOIN qmeta.product_subscription ps ON ps.subscription_id = i.subscription_id
        {where}
        GROUP BY t.tenant_code, p.project_code, dp.product_code, pp.plan_code, i.currency
        ORDER BY total_amount DESC, outstanding_amount DESC, t.tenant_code, p.project_code NULLS LAST
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_revenue_reconciliation(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("reconciliation_code", "rrr.reconciliation_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("product_code", "dp.product_code"),
            ("plan_code", "pp.plan_code"),
            ("subscription_code", "ps.subscription_code"),
            ("invoice_code", "i.invoice_code"),
            ("status", "rrr.status"),
        ],
    )
    where, values = _append_period_filter(where, values, params, "rrr.period_start", "rrr.period_end")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rrr.reconciliation_id, rrr.reconciliation_code, t.tenant_code,
            p.project_code, ps.subscription_code, pp.plan_code, dp.product_code,
            i.invoice_code, rrr.period_start, rrr.period_end,
            rrr.reconciliation_date, rrr.currency, rrr.status,
            rrr.recomputed_total_amount, rrr.invoice_total_amount,
            rrr.amount_delta, rrr.invoice_paid_amount,
            rrr.invoice_outstanding_amount, rrr.recomputed_line_count,
            rrr.invoice_line_count, rrr.matched_line_count,
            rrr.mismatch_line_count, rrr.missing_line_count,
            rrr.extra_line_count, rrr.request_count, rrr.row_count,
            rrr.cost_units, rrr.details, rrr.created_at, rrr.updated_at
        FROM qmeta.revenue_reconciliation_run rrr
        JOIN qmeta.tenant t ON t.tenant_id = rrr.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = rrr.project_id
        LEFT JOIN qmeta.product_subscription ps ON ps.subscription_id = rrr.subscription_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = rrr.plan_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = rrr.product_id
        LEFT JOIN qmeta.invoice i ON i.invoice_id = rrr.invoice_id
        {where}
        ORDER BY rrr.reconciliation_date DESC, rrr.updated_at DESC, rrr.reconciliation_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_revenue_reconciliation_lines(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("reconciliation_code", "rrr.reconciliation_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("product_code", "dp.product_code"),
            ("plan_code", "pp.plan_code"),
            ("subscription_code", "ps.subscription_code"),
            ("invoice_code", "i.invoice_code"),
            ("api_name", "rrl.api_name"),
            ("metric_name", "rrl.metric_name"),
            ("status", "rrl.status"),
        ],
    )
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rrl.line_reconciliation_id, rrr.reconciliation_code, t.tenant_code,
            p.project_code, ps.subscription_code, pp.plan_code, dp.product_code,
            i.invoice_code, rrl.line_key, rrl.api_name, rrl.metric_name,
            pr.rule_code, rrl.status, rrl.recomputed_quantity,
            rrl.invoice_quantity, rrl.quantity_delta, rrl.recomputed_amount,
            rrl.invoice_amount, rrl.amount_delta, rrl.request_count,
            rrl.row_count, rrl.cost_units, rrl.details,
            rrl.created_at, rrl.updated_at
        FROM qmeta.revenue_reconciliation_line rrl
        JOIN qmeta.revenue_reconciliation_run rrr ON rrr.reconciliation_id = rrl.reconciliation_id
        JOIN qmeta.tenant t ON t.tenant_id = rrr.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = rrr.project_id
        LEFT JOIN qmeta.product_subscription ps ON ps.subscription_id = rrr.subscription_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = rrr.plan_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = rrl.product_id
        LEFT JOIN qmeta.pricing_rule pr ON pr.rule_id = rrl.pricing_rule_id
        LEFT JOIN qmeta.invoice i ON i.invoice_id = rrr.invoice_id
        {where}
        ORDER BY rrr.reconciliation_date DESC, rrl.status DESC, rrl.amount_delta DESC, rrl.line_reconciliation_id
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_ar_aging(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("aging_code", "aas.aging_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("product_code", "dp.product_code"),
            ("plan_code", "pp.plan_code"),
            ("status", "aas.status"),
        ],
    )
    as_of_date = _param(params, "as_of_date")
    if as_of_date:
        date_range(as_of_date, as_of_date)
        where, values = _append_where(where, values, "aas.as_of_date = %s", as_of_date)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            aas.aging_id, aas.aging_code, t.tenant_code, p.project_code,
            dp.product_code, pp.plan_code, aas.as_of_date, aas.currency,
            aas.status, aas.invoice_count, aas.overdue_invoice_count,
            aas.outstanding_amount, aas.current_amount, aas.bucket_1_30_amount,
            aas.bucket_31_60_amount, aas.bucket_61_90_amount,
            aas.bucket_90_plus_amount, aas.max_days_past_due,
            aas.details, aas.created_at, aas.updated_at
        FROM qmeta.ar_aging_snapshot aas
        JOIN qmeta.tenant t ON t.tenant_id = aas.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = aas.project_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = aas.product_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = aas.plan_id
        {where}
        ORDER BY aas.as_of_date DESC, aas.status DESC, aas.outstanding_amount DESC, t.tenant_code, p.project_code NULLS LAST
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_customer_health(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("health_code", "chs.health_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("product_code", "dp.product_code"),
            ("plan_code", "pp.plan_code"),
            ("subscription_code", "ps.subscription_code"),
            ("status", "chs.status"),
        ],
    )
    as_of_date = _param(params, "as_of_date")
    if as_of_date:
        date_range(as_of_date, as_of_date)
        where, values = _append_where(where, values, "chs.as_of_date = %s", as_of_date)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            chs.health_id, chs.health_code, t.tenant_code, p.project_code,
            ps.subscription_code, dp.product_code, pp.plan_code,
            chs.as_of_date, chs.status, chs.retention_signal,
            chs.health_score, chs.last_usage_date, chs.days_since_last_usage,
            chs.request_count_7d, chs.request_count_30d,
            chs.request_count_90d, chs.cost_units_30d,
            chs.invoice_count_90d, chs.paid_amount_90d,
            chs.total_amount_90d, chs.outstanding_amount,
            chs.overdue_amount, chs.overdue_invoice_count,
            chs.details, chs.created_at, chs.updated_at
        FROM qmeta.customer_health_snapshot chs
        JOIN qmeta.tenant t ON t.tenant_id = chs.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = chs.project_id
        LEFT JOIN qmeta.product_subscription ps ON ps.subscription_id = chs.subscription_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = chs.product_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = chs.plan_id
        {where}
        ORDER BY chs.as_of_date DESC, chs.status DESC, chs.health_score, t.tenant_code, p.project_code NULLS LAST
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_payment_batches(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("batch_code", "pib.batch_code"),
            ("source_type", "pib.source_type"),
            ("account_code", "pib.account_code"),
            ("currency", "pib.currency"),
            ("status", "pib.status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "pib.imported_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            pib.batch_id, pib.batch_code, pib.source_type, pib.account_code,
            pib.statement_start, pib.statement_end, pib.currency, pib.status,
            pib.transaction_count, pib.matched_count, pib.unmatched_count,
            pib.total_amount, pib.matched_amount, pib.unmatched_amount,
            pib.imported_at, pib.details, pib.created_at, pib.updated_at
        FROM qmeta.payment_import_batch pib
        {where}
        ORDER BY pib.imported_at DESC, pib.batch_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_payments(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("batch_code", "pib.batch_code"),
            ("transaction_code", "pt.transaction_code"),
            ("invoice_code", "i.invoice_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("status", "pt.status"),
            ("currency", "pt.currency"),
            ("payment_channel", "pt.payment_channel"),
            ("direction", "pt.direction"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "pt.value_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            pt.transaction_id, pt.transaction_code, pib.batch_code,
            t.tenant_code, p.project_code, i.invoice_code,
            pt.payment_channel, pt.external_transaction_id,
            pt.counterparty_name, pt.transaction_time, pt.value_date,
            pt.direction, pt.currency, pt.amount, pt.base_currency,
            pt.fx_rate_to_base, pt.base_amount, pt.status,
            pt.reference_text, pt.details, pt.created_at, pt.updated_at
        FROM qmeta.payment_transaction pt
        LEFT JOIN qmeta.payment_import_batch pib ON pib.batch_id = pt.batch_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = pt.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = pt.project_id
        LEFT JOIN qmeta.invoice i ON i.invoice_id = pt.invoice_id
        {where}
        ORDER BY pt.value_date DESC, pt.transaction_time DESC, pt.transaction_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_payment_matches(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("batch_code", "pib.batch_code"),
            ("match_code", "pim.match_code"),
            ("transaction_code", "pt.transaction_code"),
            ("invoice_code", "i.invoice_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("status", "pim.status"),
            ("currency", "pim.currency"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "pim.matched_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            pim.match_id, pim.match_code, pib.batch_code,
            pt.transaction_code, i.invoice_code, t.tenant_code, p.project_code,
            pim.match_type, pim.status, pim.currency, pim.matched_amount,
            pim.base_currency, pim.fx_rate_to_base, pim.base_matched_amount,
            pim.unmatched_amount, pim.match_score, pim.matched_at,
            pt.amount AS payment_amount, pt.status AS payment_status,
            i.status AS invoice_status, i.paid_amount AS invoice_paid_amount,
            i.outstanding_amount AS invoice_outstanding_amount,
            pim.details, pim.created_at, pim.updated_at
        FROM qmeta.payment_invoice_match pim
        JOIN qmeta.payment_transaction pt ON pt.transaction_id = pim.transaction_id
        LEFT JOIN qmeta.payment_import_batch pib ON pib.batch_id = pt.batch_id
        JOIN qmeta.invoice i ON i.invoice_id = pim.invoice_id
        LEFT JOIN qmeta.tenant t ON t.tenant_id = pim.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = pim.project_id
        {where}
        ORDER BY pim.matched_at DESC, pim.match_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_revenue_ledger(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("ledger_code", "rle.ledger_code"),
            ("invoice_code", "i.invoice_code"),
            ("transaction_code", "pt.transaction_code"),
            ("match_code", "pim.match_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("entry_type", "rle.entry_type"),
            ("currency", "rle.currency"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "rle.entry_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rle.ledger_id, rle.ledger_code, t.tenant_code, p.project_code,
            i.invoice_code, pt.transaction_code, pim.match_code,
            rle.entry_date, rle.entry_type, rle.currency,
            rle.debit_amount, rle.credit_amount, rle.balance_amount,
            rle.base_currency, rle.base_debit_amount, rle.base_credit_amount,
            rle.base_balance_amount, rle.details, rle.created_at, rle.updated_at
        FROM qmeta.revenue_ledger_entry rle
        LEFT JOIN qmeta.tenant t ON t.tenant_id = rle.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = rle.project_id
        LEFT JOIN qmeta.invoice i ON i.invoice_id = rle.invoice_id
        LEFT JOIN qmeta.payment_transaction pt ON pt.transaction_id = rle.transaction_id
        LEFT JOIN qmeta.payment_invoice_match pim ON pim.match_id = rle.match_id
        {where}
        ORDER BY rle.entry_date DESC, rle.ledger_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_fx_rates(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("rate_code", "frd.rate_code"),
            ("from_currency", "frd.from_currency"),
            ("to_currency", "frd.to_currency"),
            ("provider", "frd.provider"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "frd.rate_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            frd.rate_id, frd.rate_code, frd.rate_date, frd.from_currency,
            frd.to_currency, frd.rate, frd.provider, frd.details,
            frd.created_at, frd.updated_at
        FROM qmeta.fx_rate_daily frd
        {where}
        ORDER BY frd.rate_date DESC, frd.from_currency, frd.to_currency, frd.provider
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_runtime_logs(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("environment", "rl.environment"),
            ("component", "rl.component"),
            ("service_name", "rl.service_name"),
            ("severity", "rl.severity"),
            ("event_type", "rl.event_type"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "rl.log_time")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rl.log_id, rl.log_code, rl.environment, rl.component,
            rl.service_name, rl.severity, rl.event_type, rl.message,
            rl.trace_id, rl.request_id, rl.log_time, dr.release_code,
            wr.run_code AS worker_run_code, rl.details, rl.created_at,
            rl.updated_at
        FROM qmeta.runtime_log rl
        LEFT JOIN qmeta.deployment_release dr ON dr.release_id = rl.release_id
        LEFT JOIN qmeta.worker_run wr ON wr.worker_run_id = rl.worker_run_id
        {where}
        ORDER BY rl.log_time DESC, rl.log_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_runtime_metrics(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("environment", "rms.environment"),
            ("component", "rms.component"),
            ("service_name", "rms.service_name"),
            ("metric_name", "rms.metric_name"),
            ("status", "rms.status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "rms.metric_time")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rms.metric_id, rms.metric_code, rms.environment, rms.component,
            rms.service_name, rms.metric_name, rms.metric_time, rms.metric_value,
            rms.unit, rms.status, rms.warning_threshold, rms.critical_threshold,
            rms.details, rms.created_at, rms.updated_at
        FROM qmeta.runtime_metric_snapshot rms
        {where}
        ORDER BY rms.metric_time DESC, rms.metric_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_runtime_daily_reports(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("environment", "rdr.environment"),
            ("report_code", "rdr.report_code"),
            ("report_date", "rdr.report_date"),
            ("status", "rdr.status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "rdr.report_date")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            rdr.report_id, rdr.report_code, rdr.environment, rdr.report_date,
            rdr.status, rdr.api_request_count, rdr.api_failed_count,
            rdr.api_error_rate, rdr.api_slowest_duration_ms,
            rdr.worker_run_count, rdr.worker_failed_count,
            rdr.worker_warning_count, rdr.deployment_health_status,
            rdr.vendor_readiness_watch_count, rdr.invoice_outstanding_amount,
            rdr.customer_health_risk_count, rdr.capacity_alert_count,
            rdr.open_capacity_alert_count, rdr.details, rdr.created_at,
            rdr.updated_at
        FROM qmeta.runtime_daily_report rdr
        {where}
        ORDER BY rdr.report_date DESC, rdr.updated_at DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_capacity_alerts(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("environment", "ca.environment"),
            ("component", "ca.component"),
            ("metric_name", "ca.metric_name"),
            ("severity", "ca.severity"),
            ("status", "ca.status"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "ca.observed_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ca.capacity_alert_id, ca.alert_key, ca.alert_id, ca.environment,
            ca.component, ca.metric_name, ca.severity, ca.status,
            ca.metric_value, ca.threshold_value, ca.unit, ca.message,
            ca.observed_at, ca.first_seen_at, ca.last_seen_at, ca.resolved_at,
            ae.alert_type, ca.details, ca.created_at, ca.updated_at
        FROM qmeta.capacity_alert ca
        LEFT JOIN qmeta.alert_event ae ON ae.alert_id = ca.alert_id
        {where}
        ORDER BY ca.status, ca.severity DESC, ca.last_seen_at DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_usage_daily(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    start_date, end_date = _date_window(params)
    where = ["aud.usage_date BETWEEN %s AND %s"]
    values: list[Any] = [start_date, end_date]
    extra_where, extra_values = _where_equal(
        params,
        [
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("principal_code", "pr.principal_code"),
            ("api_name", "aud.api_name"),
        ],
        include_where=False,
    )
    if extra_where:
        where.append(extra_where.replace("WHERE ", "", 1))
        values.extend(extra_values)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            aud.usage_date, t.tenant_code, p.project_code, pr.principal_code,
            tok.token_name, tok.cost_center, aud.api_name, aud.request_count,
            aud.failed_count, aud.row_count, aud.duration_ms, aud.cost_units,
            aud.created_at, aud.updated_at
        FROM qmeta.api_usage_daily aud
        LEFT JOIN qmeta.tenant t ON t.tenant_id = aud.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = aud.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = aud.principal_id
        LEFT JOIN qmeta.api_token tok ON tok.token_id = aud.token_id
        WHERE {' AND '.join(where)}
        ORDER BY aud.usage_date DESC, p.project_code NULLS LAST, aud.cost_units DESC, aud.api_name
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def build_kappa_console_snapshot(postgres_dsn: str | None, params: dict[str, list[str]] | None = None) -> dict[str, Any]:
    params = params or {}
    return {
        "overview": fetch_kappa_overview(postgres_dsn),
        "usage": list_usage_daily(postgres_dsn, params, 20, 0),
        "access_decisions": list_access_decisions(postgres_dsn, params, 20, 0),
        "project_governance": list_project_governance(postgres_dsn, params, 20, 0),
        "governance_actions": list_governance_actions(postgres_dsn, params, 20, 0),
        "automation_runs": list_automation_runs(postgres_dsn, params, 20, 0),
        "automation_actions": list_automation_actions(postgres_dsn, params, 20, 0),
        "automation_approvals": list_automation_approvals(postgres_dsn, params, 20, 0),
        "automation_executors": list_automation_executors(postgres_dsn, params, 20, 0),
        "automation_allowlists": list_automation_allowlists(postgres_dsn, params, 20, 0),
        "automation_secrets": list_automation_secret_refs(postgres_dsn, params, 20, 0),
        "automation_channels": list_automation_channels(postgres_dsn, params, 20, 0),
        "automation_dispatches": list_automation_dispatches(postgres_dsn, params, 20, 0),
        "automation_runbooks": list_automation_runbooks(postgres_dsn, params, 20, 0),
        "automation_channel_profiles": list_automation_channel_profiles(postgres_dsn, params, 20, 0),
        "automation_channel_validations": list_automation_channel_validations(postgres_dsn, params, 20, 0),
        "automation_secret_rotations": list_automation_secret_rotations(postgres_dsn, params, 20, 0),
        "automation_live_receipts": list_automation_live_receipts(postgres_dsn, params, 20, 0),
        "automation_attempts": list_automation_attempts(postgres_dsn, params, 20, 0),
        "automation_rollbacks": list_automation_rollbacks(postgres_dsn, params, 20, 0),
        "deliveries": list_notification_deliveries(postgres_dsn, params, 20, 0),
        "schedules": list_vendor_schedules(postgres_dsn, params, 20, 0),
        "vendor_onboarding_runs": list_vendor_onboarding_runs(postgres_dsn, params, 20, 0),
        "vendor_onboarding_results": list_vendor_onboarding_results(postgres_dsn, params, 20, 0),
        "vendor_live_closures": list_vendor_live_closures(postgres_dsn, params, 20, 0),
        "vendor_live_probes": list_vendor_live_probes(postgres_dsn, params, 20, 0),
        "vendor_live_pilots": list_vendor_live_pilots(postgres_dsn, params, 20, 0),
        "vendor_live_pilot_results": list_vendor_live_pilot_results(postgres_dsn, params, 20, 0),
        "vendor_contract_profiles": list_vendor_contract_profiles(postgres_dsn, params, 20, 0),
        "vendor_contract_entitlements": list_vendor_contract_entitlements(postgres_dsn, params, 20, 0),
        "vendor_procurement_readiness": list_vendor_procurement_readiness(postgres_dsn, params, 20, 0),
        "vendor_primary_promotions": list_vendor_primary_promotions(postgres_dsn, params, 20, 0),
        "vendor_primary_promotion_results": list_vendor_primary_promotion_results(postgres_dsn, params, 20, 0),
        "vendor_post_promotion_monitors": list_vendor_post_promotion_monitors(postgres_dsn, params, 20, 0),
        "vendor_post_promotion_results": list_vendor_post_promotion_results(postgres_dsn, params, 20, 0),
        "vendor_primary_stability": list_vendor_primary_stability_snapshots(postgres_dsn, params, 20, 0),
        "vendor_primary_stability_datasets": list_vendor_primary_stability_datasets(postgres_dsn, params, 20, 0),
        "vendor_cost_optimizations": list_vendor_cost_optimizations(postgres_dsn, params, 20, 0),
        "vendor_route_weight_plans": list_vendor_route_weight_plans(postgres_dsn, params, 20, 0),
        "vendor_budget_stress": list_vendor_budget_stress_snapshots(postgres_dsn, params, 20, 0),
        "vendor_route_executions": list_vendor_route_weight_executions(postgres_dsn, params, 20, 0),
        "vendor_route_execution_datasets": list_vendor_route_weight_execution_datasets(postgres_dsn, params, 20, 0),
        "vendor_route_rollout_stages": list_vendor_route_weight_rollout_stages(postgres_dsn, params, 20, 0),
        "vendor_production_source_runs": list_vendor_production_source_runs(postgres_dsn, params, 20, 0),
        "vendor_production_source_dataset_checks": list_vendor_production_source_dataset_checks(postgres_dsn, params, 20, 0),
        "vendor_production_source_decisions": list_vendor_production_source_decisions(postgres_dsn, params, 20, 0),
        "source_route_weight_policies": list_source_route_weight_policies(postgres_dsn, params, 20, 0),
        "source_route_decisions": list_source_route_decision_audits(postgres_dsn, params, 20, 0),
        "source_route_health": list_source_route_health_snapshots(postgres_dsn, params, 20, 0),
        "source_route_circuit_breakers": list_source_route_circuit_breakers(postgres_dsn, params, 20, 0),
        "source_route_recovery_probes": list_source_route_recovery_probes(postgres_dsn, params, 20, 0),
        "source_route_incident_actions": list_route_incident_actions(postgres_dsn, params, 20, 0),
        "source_route_incident_controls": list_route_incident_controls(postgres_dsn, params, 20, 0),
        "source_route_incident_control_health": list_route_incident_control_health(postgres_dsn, params, 20, 0),
        "source_route_incident_operation_batches": list_route_incident_operation_batches(postgres_dsn, params, 20, 0),
        "source_route_incident_operation_items": list_route_incident_operation_items(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_commands": list_route_incident_approval_commands(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_command_items": list_route_incident_approval_command_items(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_signatures": list_route_incident_approval_signatures(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_role_bindings": list_route_incident_approval_role_bindings(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_policies": list_route_incident_approval_policies(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_callbacks": list_route_incident_approval_callbacks(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_escalations": list_route_incident_approval_escalations(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_lock_events": list_route_incident_approval_lock_events(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_state_transitions": list_route_incident_approval_state_transitions(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_audit_chain": list_route_incident_approval_audit_hashes(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_sla_actions": list_route_incident_approval_sla_actions(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_recovery_drills": list_route_incident_approval_recovery_drills(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_release_preflights": list_route_incident_approval_release_preflights(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_secret_rotations": list_route_incident_approval_secret_rotations(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_concurrency_tests": list_route_incident_approval_concurrency_tests(postgres_dsn, params, 20, 0),
        "source_route_incident_approval_audit_exports": list_route_incident_approval_audit_exports(postgres_dsn, params, 20, 0),
        "free_source_fabric_runs": list_free_source_fabric_runs(postgres_dsn, params, 20, 0),
        "free_source_fabric_results": list_free_source_fabric_results(postgres_dsn, params, 20, 0),
        "free_source_reliability": list_free_source_reliability_snapshots(postgres_dsn, params, 20, 0),
        "free_source_recovery_runs": list_free_source_recovery_runs(postgres_dsn, params, 20, 0),
        "free_source_recovery_actions": list_free_source_recovery_actions(postgres_dsn, params, 20, 0),
        "free_source_recovery_executions": list_free_source_recovery_executions(postgres_dsn, params, 20, 0),
        "free_source_recovery_health": list_free_source_recovery_health(postgres_dsn, params, 20, 0),
        "free_source_admission_profiles": list_free_source_admission_profiles(postgres_dsn, params, 20, 0),
        "free_source_admission": list_free_source_admission_snapshots(postgres_dsn, params, 20, 0),
        "vendor_live_gates": list_vendor_live_gate_runs(postgres_dsn, params, 20, 0),
        "vendor_readiness": list_vendor_readiness_reviews(postgres_dsn, params, 20, 0),
        "worker_runs": list_worker_runs(postgres_dsn, params, 20, 0),
        "worker_schedules": list_worker_schedules(postgres_dsn, params, 20, 0),
        "worker_heartbeats": list_worker_heartbeats(postgres_dsn, params, 20, 0),
        "worker_ticks": list_worker_schedule_ticks(postgres_dsn, params, 20, 0),
        "deployment_releases": list_deployment_releases(postgres_dsn, params, 20, 0),
        "deployment_health": list_deployment_health(postgres_dsn, params, 20, 0),
        "products": list_data_products(postgres_dsn, params, 20, 0),
        "budget_policies": list_budget_policies(postgres_dsn, params, 20, 0),
        "budget_usage": list_budget_usage(postgres_dsn, params, 20, 0),
        "budget_alerts": list_budget_alerts(postgres_dsn, params, 20, 0),
        "invoices": list_invoices(postgres_dsn, params, 20, 0),
        "revenue_summary": list_revenue_summary(postgres_dsn, params, 20, 0),
        "reconciliation": list_revenue_reconciliation(postgres_dsn, params, 20, 0),
        "ar_aging": list_ar_aging(postgres_dsn, params, 20, 0),
        "customer_health": list_customer_health(postgres_dsn, params, 20, 0),
        "payment_batches": list_payment_batches(postgres_dsn, params, 20, 0),
        "payments": list_payments(postgres_dsn, params, 20, 0),
        "payment_matches": list_payment_matches(postgres_dsn, params, 20, 0),
        "revenue_ledger": list_revenue_ledger(postgres_dsn, params, 20, 0),
        "fx_rates": list_fx_rates(postgres_dsn, params, 20, 0),
        "runtime_logs": list_runtime_logs(postgres_dsn, params, 20, 0),
        "runtime_metrics": list_runtime_metrics(postgres_dsn, params, 20, 0),
        "runtime_daily_reports": list_runtime_daily_reports(postgres_dsn, params, 20, 0),
        "capacity_alerts": list_capacity_alerts(postgres_dsn, params, 20, 0),
        "strategy_runs": list_strategy_runs(postgres_dsn, params, 20, 0),
        "strategy_signals": list_strategy_signals(postgres_dsn, params, 20, 0),
        "strategy_decisions": list_strategy_decisions(postgres_dsn, params, 20, 0),
        "strategy_escalations": list_strategy_escalations(postgres_dsn, params, 20, 0),
    }


def render_kappa_console(snapshot: dict[str, Any]) -> str:
    overview = snapshot.get("overview") or {}
    tiles = [
        ("Active Tenants", overview.get("active_tenant_count", 0), "governance", "neutral"),
        ("Active Projects", overview.get("active_project_count", 0), "governance", "neutral"),
        ("Active Tokens", overview.get("active_token_count", 0), "governance", "neutral"),
        ("Open Alerts", overview.get("open_alert_count", 0), "runtime", "risk"),
        ("7D Requests", overview.get("usage_7d_request_count", 0), "governance", "neutral"),
        ("7D Cost", overview.get("usage_7d_cost_units", 0), "governance", "neutral"),
        ("Ready Vendors", overview.get("vendor_readiness_ready_count", 0), "vendor", "good"),
        ("Vendor Watch", overview.get("vendor_readiness_watch_count", 0), "vendor", "warn"),
        ("Vendor Gates", overview.get("vendor_24h_live_gate_count", 0), "vendor", "neutral"),
        ("Gate Blocked", overview.get("vendor_24h_live_gate_blocked_count", 0), "vendor", "risk"),
        ("Gate Live", overview.get("vendor_24h_live_gate_executed_count", 0), "vendor", "good"),
        ("Gate Status", overview.get("latest_vendor_live_gate_status", "none"), "vendor", "warn"),
        ("Onboarding", overview.get("vendor_24h_onboarding_count", 0), "vendor", "neutral"),
        ("Onboard Blocked", overview.get("vendor_24h_onboarding_blocked_count", 0), "vendor", "risk"),
        ("Onboard Status", overview.get("latest_vendor_onboarding_status", "none"), "vendor", "warn"),
        ("Live Closures", overview.get("vendor_24h_live_closure_count", 0), "vendor", "neutral"),
        ("Closure Blocked", overview.get("vendor_24h_live_closure_blocked_count", 0), "vendor", "risk"),
        ("Closure Status", overview.get("latest_vendor_live_closure_status", "none"), "vendor", "warn"),
        ("Live Pilots", overview.get("vendor_24h_live_pilot_count", 0), "vendor", "neutral"),
        ("Pilot Blocked", overview.get("vendor_24h_live_pilot_blocked_count", 0), "vendor", "risk"),
        ("Pilot Status", overview.get("latest_vendor_live_pilot_status", "none"), "vendor", "warn"),
        ("Vendor Contracts", overview.get("vendor_contract_profile_count", 0), "vendor", "neutral"),
        ("Active Contracts", overview.get("vendor_active_contract_count", 0), "vendor", "good"),
        ("Entitlements", overview.get("vendor_active_entitlement_count", 0), "vendor", "good"),
        ("Procurement", overview.get("vendor_24h_procurement_readiness_count", 0), "vendor", "neutral"),
        ("Procurement Ready", overview.get("vendor_24h_procurement_ready_count", 0), "vendor", "good"),
        ("Procurement Review", overview.get("vendor_24h_procurement_review_required_count", 0), "vendor", "warn"),
        ("Procurement Blocked", overview.get("vendor_24h_procurement_blocked_count", 0), "vendor", "risk"),
        ("Procurement Status", overview.get("latest_vendor_procurement_status", "none"), "vendor", "warn"),
        ("Vendor Primary", overview.get("vendor_procurement_primary_candidate_count", 0), "vendor", "good"),
        ("Primary Promotions", overview.get("vendor_24h_primary_promotion_count", 0), "vendor", "neutral"),
        ("Promotion Approved", overview.get("vendor_24h_primary_promotion_approved_count", 0), "vendor", "good"),
        ("Promotion Blocked", overview.get("vendor_24h_primary_promotion_blocked_count", 0), "vendor", "risk"),
        ("Promotion Applied", overview.get("vendor_24h_primary_promotion_applied_count", 0), "vendor", "good"),
        ("Promotion Status", overview.get("latest_vendor_primary_promotion_status", "none"), "vendor", "warn"),
        ("Routing Allowed", overview.get("vendor_primary_promotion_routing_allowed_count", 0), "vendor", "good"),
        ("Post Monitors", overview.get("vendor_24h_post_promotion_monitor_count", 0), "vendor", "neutral"),
        ("Post Healthy", overview.get("vendor_24h_post_promotion_healthy_count", 0), "vendor", "good"),
        ("Rollback Rec", overview.get("vendor_24h_post_promotion_rollback_recommended_count", 0), "vendor", "risk"),
        ("Post Rolled Back", overview.get("vendor_24h_post_promotion_rolled_back_count", 0), "vendor", "warn"),
        ("Post No Applied", overview.get("vendor_24h_post_promotion_no_applied_count", 0), "vendor", "warn"),
        ("Post Status", overview.get("latest_vendor_post_promotion_status", "none"), "vendor", "warn"),
        ("Rollback Allowed", overview.get("vendor_post_promotion_rollback_allowed_count", 0), "vendor", "risk"),
        ("Primary SLA", overview.get("vendor_24h_primary_stability_count", 0), "vendor", "neutral"),
        ("Primary Stable", overview.get("vendor_24h_primary_stability_healthy_count", 0), "vendor", "good"),
        ("Primary Critical", overview.get("vendor_24h_primary_stability_critical_count", 0), "vendor", "risk"),
        ("Primary No Route", overview.get("vendor_24h_primary_stability_no_primary_count", 0), "vendor", "warn"),
        ("Primary Status", overview.get("latest_vendor_primary_stability_status", "none"), "vendor", "warn"),
        ("Primary Cost", overview.get("vendor_primary_stability_cost_units", 0), "vendor", "neutral"),
        ("Primary Lag", overview.get("vendor_primary_stability_scheduler_lag_minutes", 0), "vendor", "warn"),
        ("Cost Plans", overview.get("vendor_24h_cost_optimization_count", 0), "vendor", "neutral"),
        ("Cost Optimized", overview.get("vendor_24h_cost_optimized_count", 0), "vendor", "good"),
        ("Cost Over", overview.get("vendor_24h_cost_over_budget_count", 0), "vendor", "risk"),
        ("Quota Risk", overview.get("vendor_24h_cost_quota_risk_count", 0), "vendor", "risk"),
        ("Cost Status", overview.get("latest_vendor_cost_optimization_status", "none"), "vendor", "warn"),
        ("Primary Weight", overview.get("vendor_cost_primary_weight_pct", 0), "vendor", "neutral"),
        ("Budget Usage", overview.get("vendor_cost_budget_usage_pct", 0), "vendor", "warn"),
        ("Quota Usage", overview.get("vendor_cost_monthly_quota_usage_pct", 0), "vendor", "warn"),
        ("Route Execs", overview.get("vendor_24h_route_execution_count", 0), "vendor", "neutral"),
        ("Route Pending", overview.get("vendor_24h_route_pending_approval_count", 0), "vendor", "warn"),
        ("Route Staged", overview.get("vendor_24h_route_staged_count", 0), "vendor", "neutral"),
        ("Route Applied", overview.get("vendor_24h_route_applied_count", 0), "vendor", "good"),
        ("Route Status", overview.get("latest_vendor_route_execution_status", "none"), "vendor", "warn"),
        ("Route Approval", overview.get("latest_vendor_route_execution_approval_status", "none"), "vendor", "warn"),
        ("Route Applied Wt", overview.get("vendor_route_applied_primary_weight_pct", 0), "vendor", "neutral"),
        ("Route Stage", overview.get("vendor_route_current_stage_sequence", 0), "vendor", "neutral"),
        ("Prod Closure", overview.get("vendor_24h_production_source_count", 0), "vendor", "neutral"),
        ("Prod Ready", overview.get("vendor_24h_production_source_ready_count", 0), "vendor", "good"),
        ("Prod Blocked", overview.get("vendor_24h_production_source_blocked_count", 0), "vendor", "risk"),
        ("Prod Status", overview.get("latest_vendor_production_source_status", "none"), "vendor", "warn"),
        ("Prod Role", overview.get("latest_vendor_production_source_role", "none"), "vendor", "neutral"),
        ("Prod Score", overview.get("vendor_production_source_score", 0), "vendor", "neutral"),
        ("Active Policies", overview.get("active_source_route_weight_policy_count", 0), "vendor", "good"),
        ("Route Decisions", overview.get("source_route_24h_decision_count", 0), "vendor", "neutral"),
        ("Route Fallbacks", overview.get("source_route_24h_fallback_count", 0), "vendor", "warn"),
        ("Route Final", overview.get("latest_source_route_final_source_code", "none"), "vendor", "neutral"),
        ("Route Health", overview.get("latest_source_route_health_status", "none"), "vendor", "warn"),
        ("Open Circuits", overview.get("source_route_open_circuit_count", 0), "vendor", "risk"),
        ("Recovery Probes", overview.get("source_route_24h_recovery_probe_count", 0), "vendor", "neutral"),
        ("Route Actions", overview.get("source_route_24h_incident_action_count", 0), "vendor", "warn"),
        ("Route Pending", overview.get("source_route_pending_incident_action_count", 0), "vendor", "risk"),
        ("Control Health", overview.get("source_route_latest_control_health_status", "none"), "vendor", "warn"),
        ("Control Issues", overview.get("source_route_control_health_issue_count", 0), "vendor", "risk"),
        ("Control Overdue", overview.get("source_route_control_health_overdue_approval_count", 0), "vendor", "risk"),
        ("Control Blocked", overview.get("source_route_control_health_blocked_receipt_count", 0), "vendor", "warn"),
        ("Ops Status", overview.get("source_route_latest_operation_status", "none"), "vendor", "warn"),
        ("Ops Queue", overview.get("source_route_operation_queue_count", 0), "vendor", "risk"),
        ("Ops Dedupe", overview.get("source_route_operation_suppressed_notification_count", 0), "vendor", "warn"),
        ("Ops Stress", overview.get("source_route_operation_stress_scenario_count", 0), "vendor", "neutral"),
        ("Approval API", overview.get("source_route_latest_approval_command_status", "none"), "vendor", "warn"),
        ("Approval Quorum", overview.get("source_route_approval_pending_quorum_count", 0), "vendor", "risk"),
        ("Approval Applied", overview.get("source_route_approval_24h_applied_count", 0), "vendor", "good"),
        ("Approval Sigs", overview.get("source_route_approval_24h_signature_count", 0), "vendor", "neutral"),
        ("Approval Roles", overview.get("source_route_approval_active_role_binding_count", 0), "vendor", "good"),
        ("Approval Policies", overview.get("source_route_approval_active_policy_count", 0), "vendor", "good"),
        ("Callback Status", overview.get("source_route_latest_approval_callback_status", "none"), "vendor", "warn"),
        ("Callback Verified", overview.get("source_route_approval_24h_verified_callback_count", 0), "vendor", "good"),
        ("Callback Replay", overview.get("source_route_approval_24h_replay_rejected_count", 0), "vendor", "risk"),
        ("Callback Denied", overview.get("source_route_approval_24h_denied_callback_count", 0), "vendor", "risk"),
        ("Approval Esc", overview.get("source_route_approval_open_escalation_count", 0), "vendor", "risk"),
        ("Approval Locks", overview.get("source_route_approval_24h_lock_event_count", 0), "vendor", "neutral"),
        ("Lock Busy", overview.get("source_route_approval_24h_lock_busy_count", 0), "vendor", "risk"),
        ("State Checks", overview.get("source_route_approval_24h_state_transition_count", 0), "vendor", "neutral"),
        ("State Blocks", overview.get("source_route_approval_24h_state_blocked_count", 0), "vendor", "risk"),
        ("Audit Hashes", overview.get("source_route_approval_audit_hash_count", 0), "vendor", "good"),
        ("Hash Broken", overview.get("source_route_approval_broken_audit_hash_count", 0), "vendor", "risk"),
        ("SLA Actions", overview.get("source_route_approval_planned_sla_action_count", 0), "vendor", "warn"),
        ("Recovery Drill", overview.get("source_route_latest_approval_recovery_drill_status", "none"), "vendor", "warn"),
        ("Release Gate", overview.get("source_route_latest_approval_release_preflight_status", "none"), "vendor", "warn"),
        ("Release Checks", overview.get("source_route_approval_24h_release_preflight_count", 0), "vendor", "neutral"),
        ("Release Failed", overview.get("source_route_approval_24h_failed_release_preflight_count", 0), "vendor", "risk"),
        ("Secret Rotations", overview.get("source_route_approval_24h_secret_rotation_count", 0), "vendor", "neutral"),
        ("Secret Label", overview.get("source_route_latest_approval_verified_secret_label", "none"), "vendor", "warn"),
        ("Concurrency Tests", overview.get("source_route_approval_24h_concurrency_test_count", 0), "vendor", "neutral"),
        ("Audit Exports", overview.get("source_route_approval_24h_audit_export_count", 0), "vendor", "good"),
        ("Export Broken", overview.get("source_route_latest_approval_audit_export_broken_count", 0), "vendor", "risk"),
        ("Free Fabrics", overview.get("free_source_24h_fabric_count", 0), "free_source", "neutral"),
        ("Fabric Blocked", overview.get("free_source_24h_fabric_blocked_count", 0), "free_source", "risk"),
        ("Fabric Status", overview.get("latest_free_source_fabric_status", "none"), "free_source", "warn"),
        ("Free Scores", overview.get("free_source_24h_reliability_count", 0), "free_source", "neutral"),
        ("Free Ready", overview.get("free_source_24h_reliability_ready_count", 0), "free_source", "good"),
        ("Free Degraded", overview.get("free_source_24h_reliability_degraded_count", 0), "free_source", "warn"),
        ("Free Rejected", overview.get("free_source_24h_reliability_rejected_count", 0), "free_source", "risk"),
        ("Score Status", overview.get("latest_free_source_reliability_status", "none"), "free_source", "warn"),
        ("Free Recovery", overview.get("free_source_24h_recovery_count", 0), "free_source", "neutral"),
        ("Recovery Actions", overview.get("free_source_24h_recovery_action_count", 0), "free_source", "warn"),
        ("Recovery Alerts", overview.get("free_source_24h_recovery_alert_count", 0), "free_source", "risk"),
        ("Recovery Status", overview.get("latest_free_source_recovery_status", "none"), "free_source", "warn"),
        ("Recovery Exec", overview.get("free_source_24h_recovery_execution_count", 0), "free_source", "neutral"),
        ("Recovered", overview.get("free_source_24h_recovered_count", 0), "free_source", "good"),
        ("Recovery Failed", overview.get("free_source_24h_recovery_failed_count", 0), "free_source", "risk"),
        ("Exec Status", overview.get("latest_free_source_recovery_execution_status", "none"), "free_source", "warn"),
        ("Recovery Health", overview.get("latest_free_source_recovery_health_status", "none"), "free_source", "warn"),
        ("Health Snapshots", overview.get("free_source_24h_recovery_health_count", 0), "free_source", "neutral"),
        ("Overdue Approvals", overview.get("free_source_recovery_overdue_approval_count", 0), "free_source", "risk"),
        ("Recovery Backlog", overview.get("free_source_recovery_backlog_count", 0), "free_source", "warn"),
        ("Admission", overview.get("free_source_24h_admission_count", 0), "free_source", "neutral"),
        ("Admission Approved", overview.get("free_source_24h_admission_approved_count", 0), "free_source", "good"),
        ("Admission Review", overview.get("free_source_24h_admission_review_required_count", 0), "free_source", "warn"),
        ("Admission Blocked", overview.get("free_source_24h_admission_blocked_count", 0), "free_source", "risk"),
        ("Primary Candidates", overview.get("free_source_primary_candidate_count", 0), "free_source", "good"),
        ("Admission Status", overview.get("latest_free_source_admission_status", "none"), "free_source", "warn"),
        ("Worker Runs", overview.get("worker_7d_run_count", 0), "automation", "neutral"),
        ("Worker Schedules", overview.get("active_worker_schedule_count", 0), "automation", "neutral"),
        ("Live Schedulers", overview.get("live_scheduler_count", 0), "automation", "neutral"),
        ("Deploy Health", overview.get("latest_deployment_health_status", "none"), "runtime", "good"),
        ("24H Deploy Fails", overview.get("deployment_24h_failed_count", 0), "runtime", "risk"),
        ("Products", overview.get("active_product_count", 0), "commercial", "neutral"),
        ("Budget Alerts", overview.get("budget_open_alert_count", 0), "commercial", "warn"),
        ("Budget Used", overview.get("budget_month_usage_amount", 0), "commercial", "neutral"),
        ("Invoices", overview.get("invoice_month_count", 0), "revenue", "neutral"),
        ("Revenue", overview.get("invoice_month_total_amount", 0), "revenue", "good"),
        ("Paid", overview.get("invoice_month_paid_amount", 0), "revenue", "good"),
        ("Receivable", overview.get("invoice_month_outstanding_amount", 0), "revenue", "warn"),
        ("Overdue", overview.get("overdue_invoice_count", 0), "revenue", "risk"),
        ("Recon Mismatch", overview.get("revenue_reconciliation_mismatch_count", 0), "revenue", "risk"),
        ("AR Outstanding", overview.get("latest_ar_outstanding_amount", 0), "revenue", "warn"),
        ("Risk Customers", overview.get("customer_health_risk_count", 0), "revenue", "risk"),
        ("Payments", overview.get("payment_month_received_amount", 0), "payments", "good"),
        ("Matched Payments", overview.get("payment_month_matched_amount", 0), "payments", "good"),
        ("Unmatched Payments", overview.get("unmatched_payment_count", 0), "payments", "risk"),
        ("Ledger Credit", overview.get("revenue_ledger_month_credit_amount", 0), "payments", "neutral"),
        ("Payment Batch", overview.get("latest_payment_batch_status", "none"), "payments", "good"),
        ("Runtime Errors", overview.get("runtime_24h_error_log_count", 0), "runtime", "risk"),
        ("Metric Warnings", overview.get("runtime_metric_warning_count", 0), "runtime", "warn"),
        ("Capacity Alerts", overview.get("open_capacity_alert_count", 0), "runtime", "risk"),
        ("Runtime Report", overview.get("latest_runtime_report_status", "none"), "runtime", "warn"),
        ("Strategy Status", overview.get("latest_strategy_status", "none"), "strategy", "warn"),
        ("Strategy Severity", overview.get("latest_strategy_severity", "none"), "strategy", "risk"),
        ("Strategy Actions", overview.get("strategy_24h_action_decision_count", 0), "strategy", "warn"),
        ("Strategy Escalations", overview.get("open_strategy_escalation_count", 0), "strategy", "risk"),
        ("Access Denied", overview.get("access_denied_24h_count", 0), "governance", "risk"),
        ("Gov Warnings", overview.get("project_governance_warning_count", 0), "governance", "warn"),
        ("Gov Critical", overview.get("project_governance_critical_count", 0), "governance", "risk"),
        ("Gov Actions", overview.get("open_governance_action_count", 0), "governance", "warn"),
        ("Psi Runs", overview.get("automation_24h_run_count", 0), "automation", "neutral"),
        ("Psi Actions", overview.get("automation_24h_action_count", 0), "automation", "warn"),
        ("Psi Approvals", overview.get("automation_approval_required_count", 0), "automation", "risk"),
        ("Psi Status", overview.get("latest_automation_status", "none"), "automation", "warn"),
        ("Omega Pending", overview.get("automation_pending_approval_count", 0), "automation", "risk"),
        ("Omega Retries", overview.get("automation_retry_scheduled_count", 0), "automation", "warn"),
        ("Omega Rollbacks", overview.get("automation_rollback_required_count", 0), "automation", "risk"),
        ("Omega Attempt", overview.get("latest_automation_attempt_status", "none"), "automation", "warn"),
        ("Alpha2 Executors", overview.get("automation_active_sandbox_executor_count", 0), "automation", "good"),
        ("Alpha2 Allowlists", overview.get("automation_active_allowlist_count", 0), "automation", "good"),
        ("Alpha2 Secrets", overview.get("automation_active_secret_ref_count", 0), "automation", "warn"),
        ("Beta2 Channels", overview.get("automation_active_channel_count", 0), "automation", "good"),
        ("Beta2 Dispatches", overview.get("automation_24h_dispatch_count", 0), "automation", "neutral"),
        ("Beta2 Dead Letters", overview.get("automation_dead_letter_count", 0), "automation", "risk"),
        ("Beta2 Dispatch", overview.get("latest_automation_dispatch_status", "none"), "automation", "warn"),
        ("Gamma2 Profiles", overview.get("automation_active_profile_count", 0), "automation", "good"),
        ("Gamma2 Ready", overview.get("automation_ready_profile_count", 0), "automation", "good"),
        ("Gamma2 Validations", overview.get("automation_24h_validation_count", 0), "automation", "neutral"),
        ("Gamma2 Rotation", overview.get("latest_automation_rotation_status", "none"), "automation", "warn"),
        ("Delta2 Live", overview.get("automation_24h_live_receipt_count", 0), "automation", "neutral"),
        ("Delta2 WeCom", overview.get("automation_24h_wecom_success_count", 0), "automation", "good"),
        ("Delta2 Receipt", overview.get("latest_automation_live_receipt_status", "none"), "automation", "warn"),
    ]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QData Upsilon Ops Console</title>
  <style>
    :root {{
      color-scheme: light;
      --bg:#f8fafc;
      --ink:#172033;
      --muted:#65758b;
      --soft:#eef2f7;
      --line:#d8e0ea;
      --panel:#ffffff;
      --panel-soft:#fbfdff;
      --rose:#c02668;
      --violet:#6d28d9;
      --teal:#0f766e;
      --amber:#b45309;
      --blue:#1d4ed8;
      --red:#dc2626;
      --green:#15803d;
      --shadow:0 1px 2px rgba(15,23,42,.05),0 8px 22px rgba(30,41,59,.07);
      --radius:8px;
      --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:var(--font); color:var(--ink); background:linear-gradient(180deg,#fbfcff 0%,var(--bg) 100%); }}
    header {{ position:sticky; top:0; z-index:10; border-bottom:1px solid var(--line); background:rgba(255,255,255,.94); backdrop-filter:blur(12px); }}
    .topbar {{ max-width:1480px; margin:0 auto; padding:14px 18px; display:flex; align-items:center; justify-content:space-between; gap:16px; }}
    .brand {{ display:flex; flex-direction:column; gap:3px; min-width:240px; }}
    h1 {{ margin:0; font-size:21px; line-height:1.2; font-weight:750; letter-spacing:0; }}
    .legacy-name {{ color:var(--muted); font-size:12px; font-weight:600; }}
    .header-meta {{ display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:8px; color:var(--muted); font-size:12px; }}
    .pill {{ display:inline-flex; align-items:center; gap:6px; height:28px; padding:0 10px; border:1px solid var(--line); border-radius:999px; background:#fff; font-weight:700; color:var(--ink); }}
    .pill.good {{ color:var(--green); border-color:#bbf7d0; background:#f0fdf4; }}
    .pill.warn {{ color:var(--amber); border-color:#fde68a; background:#fffbeb; }}
    main {{ max-width:1480px; margin:0 auto; padding:18px 18px 32px; }}
    .control-bar {{ display:grid; grid-template-columns:minmax(220px,380px) 190px 1fr; gap:10px; align-items:center; margin-bottom:14px; }}
    .control-bar input,.control-bar select {{ width:100%; height:38px; border:1px solid var(--line); border-radius:var(--radius); background:#fff; color:var(--ink); padding:0 12px; font:inherit; font-size:14px; }}
    .tabs {{ display:flex; gap:6px; overflow-x:auto; padding-bottom:2px; justify-content:flex-end; }}
    .tabs button {{ flex:0 0 auto; height:38px; border:1px solid var(--line); border-radius:var(--radius); background:#fff; color:var(--muted); padding:0 11px; font:inherit; font-size:13px; font-weight:750; cursor:pointer; }}
    .tabs button[aria-pressed="true"] {{ color:#fff; background:#263241; border-color:#263241; }}
    .grid {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; margin-bottom:14px; }}
    .tile {{ border:1px solid var(--line); border-radius:var(--radius); background:var(--panel); padding:12px 13px; min-height:84px; box-shadow:var(--shadow); border-top:3px solid #94a3b8; }}
    .tile.good {{ border-top-color:var(--teal); }}
    .tile.warn {{ border-top-color:var(--amber); }}
    .tile.risk {{ border-top-color:var(--rose); }}
    .tile span {{ display:block; color:var(--muted); font-size:12px; font-weight:700; line-height:1.25; }}
    .tile strong {{ display:block; margin-top:9px; font-size:23px; line-height:1.1; font-weight:800; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }}
    .section-grid {{ display:grid; grid-template-columns:1fr; gap:14px; }}
    .console-section {{ border:1px solid var(--line); border-radius:var(--radius); background:var(--panel); box-shadow:var(--shadow); overflow:hidden; }}
    .section-head {{ display:flex; align-items:center; justify-content:space-between; gap:10px; padding:11px 13px; border-bottom:1px solid var(--line); background:var(--panel-soft); }}
    .section-head h2 {{ margin:0; font-size:15px; line-height:1.25; font-weight:780; letter-spacing:0; }}
    .section-count {{ color:var(--muted); font-size:12px; font-weight:800; font-variant-numeric:tabular-nums; }}
    .table-wrap {{ width:100%; overflow:auto; }}
    table {{ width:100%; min-width:980px; border-collapse:separate; border-spacing:0; table-layout:fixed; }}
    th, td {{ border-bottom:1px solid var(--line); padding:9px 11px; font-size:13px; line-height:1.45; text-align:left; vertical-align:top; overflow-wrap:anywhere; }}
    th {{ position:sticky; top:0; z-index:1; color:#4b5563; background:#f7edf3; font-weight:780; }}
    td {{ background:#fff; }}
    tbody tr:hover td {{ background:#f4f8ff; }}
    tr:last-child td {{ border-bottom:0; }}
    td:first-child, th:first-child {{ width:170px; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .status-chip {{ display:inline-flex; align-items:center; min-height:22px; max-width:100%; border-radius:999px; padding:2px 8px; font-size:12px; line-height:1.25; font-weight:800; background:#eef2f7; color:#475569; }}
    .status-chip.success,.status-chip.matched,.status-chip.paid,.status-chip.ready,.status-chip.active,.status-chip.healthy,.status-chip.acknowledged,.status-chip.dry_run_ready,.status-chip.live_ready,.status-chip.applied,.status-chip.rolled_back,.status-chip.recovered,.status-chip.approved,.status-chip.approved_for_primary {{ background:#ecfdf5; color:var(--green); }}
    .status-chip.warning,.status-chip.watch,.status-chip.open,.status-chip.partially_matched,.status-chip.issued,.status-chip.suppressed,.status-chip.review_requested,.status-chip.review_required,.status-chip.conditional,.status-chip.not_configured,.status-chip.validated,.status-chip.no_data,.status-chip.no_applied_promotion,.status-chip.pending_signoff,.status-chip.canary_required,.status-chip.full_market_required {{ background:#fff7ed; color:var(--amber); }}
	    .status-chip.failed,.status-chip.critical,.status-chip.overdue,.status-chip.unmatched,.status-chip.rejected,.status-chip.at_risk,.status-chip.blocked,.status-chip.dead_letter,.status-chip.degraded,.status-chip.rollback_recommended {{ background:#fff1f2; color:var(--red); }}
    .action-cell {{ display:flex; gap:6px; flex-wrap:wrap; min-width:210px; }}
    .gamma6-action {{ height:28px; min-width:58px; border:1px solid var(--line); border-radius:6px; background:#fff; color:var(--ink); font:inherit; font-size:12px; font-weight:800; cursor:pointer; }}
    .gamma6-action[data-decision="approve"] {{ border-color:#bbf7d0; color:var(--green); background:#f0fdf4; }}
    .gamma6-action[data-decision="reject"] {{ border-color:#fecdd3; color:var(--red); background:#fff1f2; }}
    .gamma6-action[data-decision="hold"] {{ border-color:#fde68a; color:var(--amber); background:#fffbeb; }}
    .gamma6-action:disabled {{ opacity:.55; cursor:not-allowed; }}
    .empty-row td {{ color:var(--muted); text-align:center; padding:18px; }}
    [hidden] {{ display:none !important; }}
    @media (max-width:1120px) {{
      .grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
      .control-bar {{ grid-template-columns:1fr 170px; }}
      .tabs {{ grid-column:1 / -1; justify-content:flex-start; }}
    }}
    @media (max-width:680px) {{
      .topbar {{ align-items:flex-start; flex-direction:column; }}
      .header-meta {{ justify-content:flex-start; }}
      .control-bar {{ grid-template-columns:1fr; }}
      .grid {{ grid-template-columns:1fr 1fr; }}
      main {{ padding:14px 10px 26px; }}
      .tile {{ min-height:78px; }}
      .tile strong {{ font-size:19px; }}
      table {{ min-width:760px; }}
      th, td {{ font-size:12px; padding:8px 9px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand">
        <h1>QData Upsilon Ops Console</h1>
        <span class="legacy-name">QData Kappa Ops Console</span>
      </div>
      <div class="header-meta">
        <span class="pill good">admin scope</span>
        <span class="pill">read-only</span>
        <span class="pill warn">alerts {escape(str(overview.get("open_alert_count", 0)))}</span>
      </div>
    </div>
  </header>
  <main>
    <div class="control-bar" data-upsilon-controls>
      <input id="console-search" type="search" placeholder="搜索代码、状态、项目、批次" aria-label="搜索控制台表格">
      <select id="console-status" aria-label="状态筛选">
        <option value="">All Status</option>
        <option value="open">open</option>
        <option value="warning">warning</option>
        <option value="critical">critical</option>
        <option value="success">success</option>
        <option value="matched">matched</option>
        <option value="paid">paid</option>
        <option value="unmatched">unmatched</option>
        <option value="failed">failed</option>
        <option value="acknowledged">acknowledged</option>
        <option value="blocked">blocked</option>
        <option value="applied">applied</option>
        <option value="rollback_recommended">rollback_recommended</option>
        <option value="rolled_back">rolled_back</option>
        <option value="no_applied_promotion">no_applied_promotion</option>
      </select>
      <div class="tabs" role="tablist" aria-label="Upsilon console views">
        <button type="button" data-view-button="all" aria-pressed="true">All</button>
        <button type="button" data-view-button="runtime" aria-pressed="false">Runtime</button>
        <button type="button" data-view-button="payments" aria-pressed="false">Payments</button>
        <button type="button" data-view-button="revenue" aria-pressed="false">Revenue</button>
        <button type="button" data-view-button="vendor" aria-pressed="false">Vendor</button>
        <button type="button" data-view-button="free_source" aria-pressed="false">Free Sources</button>
        <button type="button" data-view-button="automation" aria-pressed="false">Automation</button>
        <button type="button" data-view-button="commercial" aria-pressed="false">Commercial</button>
        <button type="button" data-view-button="governance" aria-pressed="false">Governance</button>
        <button type="button" data-view-button="strategy" aria-pressed="false">Strategy</button>
      </div>
    </div>
    <div class="grid">{''.join(_tile(label, value, view, tone) for label, value, view, tone in tiles)}</div>
	      <div class="section-grid">
	      {_table("API Usage", snapshot.get("usage") or [], ["usage_date", "project_code", "api_name", "request_count", "failed_count", "cost_units"], "governance")}
	      {_table("Access Decisions", snapshot.get("access_decisions") or [], ["evaluated_at", "project_code", "principal_code", "api_name", "dataset_code", "decision", "effective_scope", "reason"], "governance")}
	      {_table("Project Governance", snapshot.get("project_governance") or [], ["snapshot_date", "tenant_code", "project_code", "status", "risk_score", "recommended_action", "request_count_7d", "denied_access_7d_count", "budget_status", "budget_usage_pct"], "governance")}
	      {_table("Governance Actions", snapshot.get("governance_actions") or [], ["updated_at", "tenant_code", "project_code", "action_type", "severity", "status", "owner", "reason"], "governance")}
	      {_table("Automation Runs", snapshot.get("automation_runs") or [], ["started_at", "run_code", "environment", "execution_mode", "status", "action_count", "executed_count", "approval_required_count", "skipped_count", "failed_count"], "automation")}
	      {_table("Automation Actions", snapshot.get("automation_actions") or [], ["updated_at", "run_code", "source_type", "source_code", "action_type", "safety_level", "execution_mode", "status", "approval_required", "owner"], "automation")}
	      {_table("Automation Approvals", snapshot.get("automation_approvals") or [], ["requested_at", "approval_code", "action_code", "run_code", "action_type", "safety_level", "status", "requested_by", "decided_by"], "automation")}
	      {_table("Automation Attempts", snapshot.get("automation_attempts") or [], ["started_at", "attempt_code", "action_code", "executor_code", "action_type", "status", "retry_count", "max_retry_count", "next_retry_at", "error_message"], "automation")}
	      {_table("Automation Rollbacks", snapshot.get("automation_rollbacks") or [], ["requested_at", "rollback_code", "action_code", "run_code", "rollback_type", "status", "requested_by", "executed_by", "reason"], "automation")}
	      {_table("Automation Executors", snapshot.get("automation_executors") or [], ["executor_code", "executor_type", "action_type", "safety_level", "status", "requires_approval", "sandbox_mode", "allowlist_code", "secret_ref", "signing_algorithm"], "automation")}
	      {_table("Automation Allowlists", snapshot.get("automation_allowlists") or [], ["allowlist_code", "executor_type", "target_pattern", "status", "sandbox_only", "max_timeout_seconds"], "automation")}
	      {_table("Automation Secrets", snapshot.get("automation_secrets") or [], ["secret_ref", "secret_scope", "secret_kind", "status", "owner", "metadata"], "automation")}
	      {_table("Automation Channels", snapshot.get("automation_channels") or [], ["channel_code", "channel_type", "environment", "status", "endpoint_url", "allowlist_code", "secret_ref", "signing_algorithm", "owner", "runbook_code"], "automation")}
	      {_table("Automation Dispatches", snapshot.get("automation_dispatches") or [], ["updated_at", "dispatch_code", "action_code", "channel_code", "dispatch_type", "trigger_mode", "status", "retry_count", "next_retry_at", "error_message", "recovered_by"], "automation")}
	      {_table("Automation Runbooks", snapshot.get("automation_runbooks") or [], ["runbook_code", "failure_class", "severity", "status", "owner", "drill_frequency_days"], "automation")}
	      {_table("Automation Channel Profiles", snapshot.get("automation_channel_profiles") or [], ["profile_code", "channel_code", "provider_code", "environment", "profile_status", "readiness_status", "dry_run_only", "secret_ref", "next_secret_ref", "last_validation_status"], "automation")}
	      {_table("Automation Channel Validations", snapshot.get("automation_channel_validations") or [], ["started_at", "validation_code", "profile_code", "channel_code", "provider_code", "validation_type", "status", "dispatch_code", "target_secret_ref", "error_message"], "automation")}
	      {_table("Automation Secret Rotations", snapshot.get("automation_secret_rotations") or [], ["created_at", "rotation_code", "environment", "secret_ref", "next_secret_ref", "rotation_type", "status", "profile_code", "validation_status", "affected_channel_count"], "automation")}
	      {_table("Automation Live Receipts", snapshot.get("automation_live_receipts") or [], ["created_at", "receipt_code", "validation_code", "profile_code", "channel_code", "provider_code", "environment", "message_type", "status", "provider_status_code", "provider_errcode", "provider_errmsg", "error_message"], "automation")}
      {_table("Notification Deliveries", snapshot.get("deliveries") or [], ["updated_at", "channel_code", "alert_type", "severity", "status", "attempt_count"], "runtime")}
      {_table("Vendor Schedules", snapshot.get("schedules") or [], ["schedule_code", "dataset_code", "secondary_source_code", "cadence", "status", "last_suite_status"], "vendor")}
      {_table("Vendor Onboarding Runs", snapshot.get("vendor_onboarding_runs") or [], ["started_at", "run_code", "source_code", "status", "preflight_status", "canary_status", "gate_status", "orchestration_status", "recommendation", "dataset_codes", "live_base_url_present", "live_token_present", "contract_status", "error_message"], "vendor")}
      {_table("Vendor Onboarding Results", snapshot.get("vendor_onboarding_results") or [], ["started_at", "run_code", "dataset_code", "source_code", "stage_status", "preflight_status", "canary_status", "gate_status", "recommendation", "gate_code", "live_requested", "live_executed", "error_message"], "vendor")}
      {_table("Vendor Live Closures", snapshot.get("vendor_live_closures") or [], ["started_at", "closure_code", "source_code", "status", "config_status", "profile_check_status", "contract_status", "endpoint_status", "onboarding_status", "promotion_status", "recommendation", "missing_dataset_codes", "live_base_url_present", "live_token_present", "error_message"], "vendor")}
      {_table("Vendor Live Probes", snapshot.get("vendor_live_probes") or [], ["started_at", "closure_code", "probe_code", "dataset_code", "status", "auth_status", "schema_status", "endpoint_path", "live_requested", "live_executed", "row_count", "missing_fields", "error_message"], "vendor")}
	      {_table("Vendor Live Pilots", snapshot.get("vendor_live_pilots") or [], ["started_at", "pilot_code", "source_code", "status", "pilot_scope", "closure_status", "endpoint_status", "onboarding_status", "benchmark_status", "signoff_status", "recommendation", "risk_level", "dataset_result_count", "closure_code", "live_base_url_present", "live_token_present", "error_message"], "vendor")}
	      {_table("Vendor Live Pilot Results", snapshot.get("vendor_live_pilot_results") or [], ["started_at", "pilot_code", "result_code", "dataset_code", "status", "closure_status", "endpoint_status", "schema_status", "gate_status", "benchmark_status", "recommendation", "risk_level", "probe_code", "gate_code", "live_requested", "live_executed", "missing_fields", "error_message"], "vendor")}
	      {_table("Vendor Contract Profiles", snapshot.get("vendor_contract_profiles") or [], ["updated_at", "contract_code", "source_code", "provider_name", "procurement_status", "contract_status", "commercial_clearance", "redistribution_allowed", "production_use_allowed", "contract_ref", "contract_end_date", "sla_tier", "sla_uptime_pct", "rate_limit_per_min", "daily_quota", "monthly_quota", "billing_model", "status"], "vendor")}
	      {_table("Vendor Contract Entitlements", snapshot.get("vendor_contract_entitlements") or [], ["updated_at", "entitlement_code", "contract_code", "source_code", "dataset_code", "entitlement_status", "allowed_role", "commercial_use_allowed", "redistribution_allowed", "production_use_allowed", "schema_status", "field_mapping_status", "rate_limit_per_min", "daily_quota", "max_delay_minutes", "sla_uptime_pct", "blocking_issues"], "vendor")}
	      {_table("Vendor Procurement Readiness", snapshot.get("vendor_procurement_readiness") or [], ["as_of_date", "snapshot_code", "source_code", "dataset_code", "status", "procurement_role", "readiness_score", "procurement_status", "contract_status", "commercial_clearance", "redistribution_allowed", "entitlement_status", "entitlement_allowed_role", "rate_limit_per_min", "daily_quota", "sla_uptime_pct", "pi_readiness_status", "live_gate_status", "live_pilot_status", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Primary Promotions", snapshot.get("vendor_primary_promotions") or [], ["started_at", "promotion_code", "source_code", "primary_source_code", "status", "promotion_scope", "apply_mode", "routing_change_allowed", "routing_change_applied", "dataset_count", "approved_dataset_count", "pending_dataset_count", "blocked_dataset_count", "applied_dataset_count", "promotion_score", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Primary Promotion Results", snapshot.get("vendor_primary_promotion_results") or [], ["created_at", "promotion_code", "result_code", "dataset_code", "source_code", "primary_source_code", "status", "promotion_role", "routing_change_allowed", "routing_change_applied", "procurement_status", "procurement_role", "readiness_status", "readiness_recommendation", "canary_status", "canary_signoff_status", "full_market_status", "full_market_signoff_status", "current_primary_source_code", "target_priority", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Post Promotion Monitors", snapshot.get("vendor_post_promotion_monitors") or [], ["started_at", "monitor_code", "promotion_code", "source_code", "primary_source_code", "status", "monitor_scope", "rollback_mode", "rollback_allowed", "rollback_applied", "dataset_count", "healthy_dataset_count", "warning_dataset_count", "rollback_recommended_count", "rolled_back_dataset_count", "blocked_dataset_count", "no_applied_dataset_count", "monitor_score", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Post Promotion Results", snapshot.get("vendor_post_promotion_results") or [], ["created_at", "monitor_code", "result_code", "promotion_code", "promotion_result_code", "dataset_code", "source_code", "primary_source_code", "status", "monitor_scope", "rollback_mode", "rollback_allowed", "rollback_applied", "promotion_status", "promotion_role", "current_primary_source_code", "previous_primary_source_code", "shadow_status", "shadow_conflict_rate_bps", "shadow_failure_rate", "stale_minutes", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Primary Stability", snapshot.get("vendor_primary_stability") or [], ["as_of_at", "snapshot_code", "source_code", "primary_source_code", "status", "stability_role", "monitor_scope", "dataset_count", "primary_dataset_count", "healthy_dataset_count", "warning_dataset_count", "critical_dataset_count", "blocked_dataset_count", "no_primary_dataset_count", "api_success_rate", "api_error_rate", "api_latency_p95_ms", "cost_units", "scheduler_lag_minutes", "backlog_count", "post_promotion_no_applied_count", "stability_score", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Primary Stability Datasets", snapshot.get("vendor_primary_stability_datasets") or [], ["created_at", "snapshot_code", "dataset_snapshot_code", "dataset_code", "source_code", "primary_source_code", "status", "stability_role", "monitor_scope", "is_primary_route", "current_primary_source_code", "current_priority", "entitlement_status", "allowed_role", "production_use_allowed", "schema_status", "promotion_status", "promotion_result_status", "post_promotion_status", "api_success_rate", "api_latency_p95_ms", "cost_units", "stability_score", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Cost Optimizations", snapshot.get("vendor_cost_optimizations") or [], ["as_of_at", "optimization_code", "source_code", "primary_source_code", "status", "optimization_role", "optimization_scope", "dataset_count", "optimized_dataset_count", "watch_dataset_count", "over_budget_dataset_count", "quota_risk_dataset_count", "blocked_dataset_count", "no_primary_dataset_count", "forecast_request_count", "forecast_cost_units", "projected_budget_usage_pct", "projected_monthly_quota_usage_pct", "recommended_primary_weight_pct", "recommended_backup_weight_pct", "recommended_free_source_weight_pct", "optimization_score", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Route Weight Plans", snapshot.get("vendor_route_weight_plans") or [], ["created_at", "optimization_code", "plan_code", "dataset_code", "source_code", "primary_source_code", "backup_source_code", "status", "plan_role", "current_primary_source_code", "is_primary_route", "stability_status", "stability_score", "contract_status", "entitlement_status", "unit_cost", "forecast_request_count", "forecast_cost_units", "projected_budget_usage_pct", "projected_monthly_quota_usage_pct", "recommended_primary_weight_pct", "recommended_backup_weight_pct", "recommended_free_source_weight_pct", "routing_change_allowed", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Budget Stress", snapshot.get("vendor_budget_stress") or [], ["created_at", "optimization_code", "plan_code", "stress_code", "dataset_code", "source_code", "stress_multiplier", "status", "forecast_request_count", "forecast_cost_units", "projected_budget_usage_pct", "projected_daily_quota_usage_pct", "projected_monthly_quota_usage_pct", "quota_exhaustion_days", "recommended_action", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Route Executions", snapshot.get("vendor_route_executions") or [], ["as_of_at", "execution_code", "optimization_code", "source_code", "primary_source_code", "status", "approval_status", "execution_mode", "rollout_policy", "current_stage_sequence", "dataset_count", "pending_approval_dataset_count", "approved_dataset_count", "staged_dataset_count", "applied_dataset_count", "blocked_dataset_count", "no_primary_dataset_count", "target_primary_weight_pct", "applied_primary_weight_pct", "routing_change_allowed", "routing_change_applied", "rollback_allowed", "rollback_applied", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Route Execution Datasets", snapshot.get("vendor_route_execution_datasets") or [], ["created_at", "execution_code", "execution_dataset_code", "optimization_code", "plan_code", "dataset_code", "source_code", "primary_source_code", "backup_source_code", "status", "approval_status", "rollout_policy", "current_stage_sequence", "current_primary_source_code", "tau5_status", "stability_status", "target_primary_weight_pct", "applied_primary_weight_pct", "routing_change_allowed", "routing_change_applied", "rollback_allowed", "rollback_applied", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Route Rollout Stages", snapshot.get("vendor_route_rollout_stages") or [], ["created_at", "execution_code", "execution_dataset_code", "stage_code", "dataset_code", "source_code", "stage_sequence", "stage_label", "status", "approval_required", "approval_status", "gate_status", "target_primary_weight_pct", "target_backup_weight_pct", "target_free_source_weight_pct", "routing_change_allowed", "routing_change_applied", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Production Source Runs", snapshot.get("vendor_production_source_runs") or [], ["as_of_at", "production_code", "source_code", "primary_source_code", "status", "production_role", "closure_mode", "dataset_count", "authorized_dataset_count", "pilot_ready_dataset_count", "promoted_dataset_count", "stable_dataset_count", "optimized_dataset_count", "route_ready_dataset_count", "production_ready_dataset_count", "applied_dataset_count", "blocked_dataset_count", "live_base_url_present", "live_token_present", "routing_change_allowed", "production_score", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Production Source Dataset Checks", snapshot.get("vendor_production_source_dataset_checks") or [], ["created_at", "production_code", "dataset_check_code", "source_code", "dataset_code", "status", "production_role", "contract_status", "entitlement_status", "procurement_status", "canary_status", "full_market_status", "promotion_result_status", "stability_status", "stability_score", "optimization_status", "route_execution_status", "route_policy_status", "current_primary_source_code", "is_primary_route", "recommended_primary_weight_pct", "applied_primary_weight_pct", "production_score", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Vendor Production Source Decisions", snapshot.get("vendor_production_source_decisions") or [], ["created_at", "production_code", "dataset_check_code", "decision_code", "source_code", "dataset_code", "decision_type", "status", "severity", "decision_summary", "blocking_issues", "required_actions"], "vendor")}
	      {_table("Source Route Weight Policies", snapshot.get("source_route_weight_policies") or [], ["created_at", "policy_code", "execution_code", "execution_dataset_code", "stage_code", "dataset_code", "source_code", "primary_source_code", "backup_source_code", "effective_date", "end_date", "policy_status", "execution_mode", "primary_weight_pct", "backup_weight_pct", "free_source_weight_pct", "created_by"], "vendor")}
	      {_table("Source Route Decisions", snapshot.get("source_route_decisions") or [], ["started_at", "decision_code", "policy_code", "dataset_code", "requested_source_code", "selected_source_code", "final_source_code", "decision_context", "route_mode", "decision_status", "selected_role", "primary_weight_pct", "backup_weight_pct", "selected_weight_pct", "deterministic_bucket", "fallback_applied", "candidate_sources", "attempt_sources", "row_count", "duration_ms", "error_message"], "vendor")}
	      {_table("Source Route Health", snapshot.get("source_route_health") or [], ["as_of_at", "snapshot_code", "dataset_code", "source_code", "status", "previous_circuit_status", "circuit_status", "circuit_action", "request_count", "success_count", "failed_count", "fallback_count", "empty_count", "success_rate", "failure_rate", "fallback_rate", "empty_rate", "latency_p95_ms", "open_until", "health_issues", "runbook_actions"], "vendor")}
	      {_table("Source Route Circuit Breakers", snapshot.get("source_route_circuit_breakers") or [], ["updated_at", "breaker_code", "dataset_code", "source_code", "status", "opened_at", "open_until", "closed_at", "snapshot_code", "probe_code", "open_reason", "failure_rate", "fallback_rate", "empty_rate", "latency_p95_ms", "health_issues"], "vendor")}
	      {_table("Source Route Recovery Probes", snapshot.get("source_route_recovery_probes") or [], ["probe_started_at", "probe_code", "breaker_code", "snapshot_code", "dataset_code", "source_code", "status", "observed_request_count", "observed_success_count", "observed_failed_count", "observed_success_rate", "required_success_rate", "decision_summary", "error_message"], "vendor")}
	      {_table("Source Route Incident Actions", snapshot.get("source_route_incident_actions") or [], ["updated_at", "incident_action_code", "run_code", "action_code", "source_signal_type", "dataset_code", "source_code", "action_type", "safety_level", "execution_mode", "status", "approval_required", "owner", "circuit_status", "probe_status", "open_until", "failure_rate", "fallback_rate", "empty_rate", "latency_p95_ms", "health_issues", "reason"], "vendor")}
	      {_table("Source Route Incident Controls", snapshot.get("source_route_incident_controls") or [], ["updated_at", "control_code", "incident_action_code", "run_code", "action_code", "dataset_code", "source_code", "source_signal_type", "action_type", "safety_level", "control_stage", "approval_status", "dispatch_status", "receipt_status", "attempt_status", "rollback_status", "owner", "requested_by", "execution_mode", "control_reason"], "vendor")}
	      {_table("Source Route Incident Control Health", snapshot.get("source_route_incident_control_health") or [], ["as_of_at", "snapshot_code", "status", "control_count", "pending_control_count", "approval_pending_count", "approval_overdue_count", "notification_blocked_count", "blocked_receipt_rate", "execution_failure_rate", "missing_rollback_count", "stale_schedule_count", "latest_worker_status", "latest_schedule_status", "latest_control_stage", "health_issues", "runbook_actions"], "vendor")}
	      {_table("Source Route Incident Operation Batches", snapshot.get("source_route_incident_operation_batches") or [], ["started_at", "batch_code", "status", "operation_mode", "approval_decision", "dry_run", "apply_decisions", "candidate_count", "eligible_count", "approved_count", "rejected_count", "held_count", "suppressed_notification_count", "stress_scenario_count", "operation_issues", "required_actions"], "vendor")}
	      {_table("Source Route Incident Operation Items", snapshot.get("source_route_incident_operation_items") or [], ["created_at", "batch_code", "control_code", "approval_code", "dataset_code", "source_code", "source_signal_type", "safety_level", "operation_decision", "operation_status", "approval_status_before", "approval_status_after", "suppress_notification", "priority_score", "gamma6_actions", "error_message"], "vendor")}
	      {_table("Source Route Incident Approval Commands", snapshot.get("source_route_incident_approval_commands") or [], ["started_at", "command_code", "status", "decision", "principal_code", "command_scope", "batch_code", "control_code", "approval_code", "required_approvals", "approval_count", "quorum_status", "target_count", "applied_count", "held_count", "rejected_count", "skipped_count", "failed_count", "command_issues"], "vendor")}
	      {_table("Source Route Incident Approval Command Items", snapshot.get("source_route_incident_approval_command_items") or [], ["created_at", "command_code", "control_code", "approval_code", "dataset_code", "source_code", "decision", "item_status", "signer_code", "signature_count", "required_approvals", "approval_status_before", "approval_status_after", "error_message"], "vendor")}
	      {_table("Source Route Incident Approval Signatures", snapshot.get("source_route_incident_approval_signatures") or [], ["signed_at", "signature_code", "command_code", "control_code", "approval_code", "decision", "signer_code", "status", "idempotency_key"], "vendor")}
	      {_table("Source Route Incident Approval Role Bindings", snapshot.get("source_route_incident_approval_role_bindings") or [], ["updated_at", "binding_code", "principal_code", "role_code", "dataset_code", "source_code", "safety_level", "status", "effective_at", "expires_at"], "vendor")}
	      {_table("Source Route Incident Approval Policies", snapshot.get("source_route_incident_approval_policies") or [], ["updated_at", "policy_code", "dataset_code", "source_code", "safety_level", "status", "min_approvals", "require_distinct_requester", "require_risk_admin_for_high", "require_wecom_signature", "timeout_minutes", "escalation_principal_code"], "vendor")}
	      {_table("Source Route Incident Approval Callbacks", snapshot.get("source_route_incident_approval_callbacks") or [], ["received_at", "callback_code", "provider_code", "signature_status", "governance_status", "decision", "signer_code", "control_code", "command_code", "required_approvals", "replay_count", "error_message"], "vendor")}
	      {_table("Source Route Incident Approval Escalations", snapshot.get("source_route_incident_approval_escalations") or [], ["created_at", "escalation_code", "reason_code", "status", "severity", "owner_principal_code", "command_code", "control_code", "approval_code", "error_message"], "vendor")}
	      {_table("Source Route Incident Approval Lock Events", snapshot.get("source_route_incident_approval_lock_events") or [], ["started_at", "lock_event_code", "lock_status", "lock_scope", "provider_code", "nonce", "control_code", "callback_code", "command_code", "held_ms", "error_message"], "vendor")}
	      {_table("Source Route Incident Approval State Transitions", snapshot.get("source_route_incident_approval_state_transitions") or [], ["observed_at", "transition_code", "transition_status", "reason_code", "control_code", "requested_decision", "approval_status_before", "approval_status_after", "callback_code", "command_code", "error_message"], "vendor")}
	      {_table("Source Route Incident Approval Audit Chain", snapshot.get("source_route_incident_approval_audit_chain") or [], ["event_time", "audit_hash_code", "chain_scope", "sequence_no", "entity_type", "entity_code", "previous_hash", "entry_hash", "verification_status"], "vendor")}
	      {_table("Source Route Incident Approval SLA Actions", snapshot.get("source_route_incident_approval_sla_actions") or [], ["generated_at", "sla_action_code", "action_status", "action_type", "reason_code", "severity", "owner_principal_code", "escalation_code", "control_code"], "vendor")}
	      {_table("Source Route Incident Approval Recovery Drills", snapshot.get("source_route_incident_approval_recovery_drills") or [], ["started_at", "drill_code", "drill_type", "status", "check_count", "passed_count", "failed_count", "recovered_count", "requested_by"], "vendor")}
	      {_table("Source Route Incident Approval Release Preflights", snapshot.get("source_route_incident_approval_release_preflights") or [], ["started_at", "preflight_code", "environment", "status", "release_version", "check_count", "passed_count", "warning_count", "failed_count", "dual_secret_enabled", "audit_broken_count", "latest_recovery_drill_status"], "vendor")}
	      {_table("Source Route Incident Approval Secret Rotations", snapshot.get("source_route_incident_approval_secret_rotations") or [], ["observed_at", "rotation_code", "environment", "rotation_phase", "status", "active_secret_label", "verified_secret_label", "nonce", "signature_digest", "error_message"], "vendor")}
	      {_table("Source Route Incident Approval Concurrency Tests", snapshot.get("source_route_incident_approval_concurrency_tests") or [], ["started_at", "test_code", "environment", "status", "target_scope", "callback_count", "expected_success_count", "success_count", "locked_count", "blocked_count", "replay_rejected_count", "failed_count", "duration_ms"], "vendor")}
	      {_table("Source Route Incident Approval Audit Exports", snapshot.get("source_route_incident_approval_audit_exports") or [], ["generated_at", "export_code", "environment", "status", "export_format", "chain_scope", "control_code", "included_entity_count", "broken_hash_count", "package_hash", "exported_by"], "vendor")}
	      {_table("Free Source Recovery Runs", snapshot.get("free_source_recovery_runs") or [], ["started_at", "recovery_code", "status", "trigger_mode", "dry_run", "snapshot_count", "action_count", "retry_action_count", "alert_action_count", "manual_review_action_count", "created_alert_count", "blocking_issues"], "free_source")}
	      {_table("Free Source Recovery Actions", snapshot.get("free_source_recovery_actions") or [], ["created_at", "action_code", "recovery_code", "source_code", "dataset_code", "action_type", "status", "severity", "reason_code", "reliability_score", "retry_after_minutes", "alert_id"], "free_source")}
	      {_table("Free Source Recovery Executions", snapshot.get("free_source_recovery_executions") or [], ["started_at", "execution_code", "action_code", "recovery_code", "source_code", "dataset_code", "execution_type", "status", "iota5_pool_status", "fabric_code", "approval_code", "wecom_receipt_code", "error_message"], "free_source")}
	      {_table("Free Source Recovery Health", snapshot.get("free_source_recovery_health") or [], ["as_of_at", "snapshot_code", "status", "backlog_count", "pending_action_count", "approval_pending_count", "approval_overdue_count", "execution_count", "recovered_count", "failed_count", "failure_rate", "stale_schedule_count", "latest_worker_status", "latest_schedule_status", "health_issues", "runbook_actions"], "free_source")}
	      {_table("Free Source Admission", snapshot.get("free_source_admission") or [], ["as_of_date", "snapshot_code", "source_code", "dataset_code", "status", "admission_role", "max_allowed_role", "license_type", "license_status", "commercial_clearance", "redistribution_allowed", "contract_status", "terms_review_status", "rate_limit_per_min", "daily_quota", "reliability_status", "reliability_score", "coverage_rate", "conflict_rate_bps", "blocking_issues", "required_actions"], "free_source")}
	      {_table("Free Source Admission Profiles", snapshot.get("free_source_admission_profiles") or [], ["updated_at", "profile_code", "source_code", "provider_name", "license_type", "license_status", "commercial_clearance", "redistribution_allowed", "contract_status", "contract_ref", "terms_review_status", "rate_limit_per_min", "daily_quota", "max_allowed_role", "status", "reviewed_by", "expires_at"], "free_source")}
	      {_table("Free Source Reliability", snapshot.get("free_source_reliability") or [], ["as_of_date", "snapshot_code", "source_code", "dataset_code", "status", "recommended_role", "reliability_score", "success_rate", "coverage_rate", "conflict_rate_bps", "consecutive_failure_count", "license_status", "commercial_clearance", "degradation_reasons", "recovery_actions"], "free_source")}
	      {_table("Free Source Fabric Runs", snapshot.get("free_source_fabric_runs") or [], ["started_at", "fabric_code", "status", "fabric_scope", "recommendation", "recommended_role", "risk_level", "baseline_source_code", "dataset_result_count", "usable_source_count", "coverage_rate", "conflict_rate_bps", "license_review_required_count", "commercial_blocker_count", "allow_external", "error_message"], "free_source")}
      {_table("Free Source Fabric Results", snapshot.get("free_source_fabric_results") or [], ["started_at", "fabric_code", "result_code", "dataset_code", "status", "coverage_status", "consistency_status", "license_status", "recommendation", "risk_level", "baseline_source_code", "usable_source_count", "coverage_rate", "conflict_rate_bps", "license_blocking_sources", "error_message"], "free_source")}
      {_table("Vendor Live Gates", snapshot.get("vendor_live_gates") or [], ["started_at", "gate_code", "source_code", "dataset_code", "run_mode", "status", "required_windows", "executed_windows", "live_base_url_present", "live_token_present", "readiness_status", "recommendation", "recommended_role", "error_message"], "vendor")}
      {_table("Vendor Readiness", snapshot.get("vendor_readiness") or [], ["review_date", "source_code", "dataset_code", "status", "recommendation", "recommended_role", "suite_count", "missing_window_count"], "vendor")}
      {_table("Worker Runs", snapshot.get("worker_runs") or [], ["started_at", "run_code", "trigger_mode", "status", "processed_count", "failed_count"], "automation")}
      {_table("Worker Schedules", snapshot.get("worker_schedules") or [], ["schedule_code", "task_name", "status", "next_run_at", "last_status", "run_count"], "automation")}
      {_table("Scheduler Heartbeats", snapshot.get("worker_heartbeats") or [], ["scheduler_id", "status", "last_seen_at", "current_schedule_code", "tick_count", "run_count"], "automation")}
      {_table("Scheduler Ticks", snapshot.get("worker_ticks") or [], ["started_at", "schedule_code", "task_name", "status", "worker_run_id", "lock_acquired"], "automation")}
      {_table("Deployment Health", snapshot.get("deployment_health") or [], ["checked_at", "snapshot_code", "environment", "status", "check_count", "failed_count"], "runtime")}
      {_table("Deployment Releases", snapshot.get("deployment_releases") or [], ["created_at", "release_code", "environment", "status", "health_status", "version_label"], "runtime")}
      {_table("Data Products", snapshot.get("products") or [], ["product_code", "product_name", "status", "billing_unit", "dataset_count", "api_count"], "commercial")}
      {_table("Budget Policies", snapshot.get("budget_policies") or [], ["budget_code", "project_code", "cost_center", "period", "budget_amount", "latest_usage_status"], "commercial")}
      {_table("Budget Usage", snapshot.get("budget_usage") or [], ["period_start", "budget_code", "usage_amount", "budget_amount", "usage_pct", "status"], "commercial")}
      {_table("Budget Alerts", snapshot.get("budget_alerts") or [], ["last_seen_at", "budget_code", "alert_type", "severity", "status", "usage_pct"], "commercial")}
      {_table("Invoices", snapshot.get("invoices") or [], ["invoice_date", "invoice_code", "project_code", "product_code", "status", "total_amount", "paid_amount", "outstanding_amount"], "revenue")}
      {_table("Revenue Summary", snapshot.get("revenue_summary") or [], ["tenant_code", "project_code", "product_code", "invoice_count", "total_amount", "paid_amount", "outstanding_amount"], "revenue")}
      {_table("Revenue Reconciliation", snapshot.get("reconciliation") or [], ["reconciliation_date", "reconciliation_code", "project_code", "product_code", "status", "invoice_total_amount", "recomputed_total_amount", "amount_delta"], "revenue")}
      {_table("AR Aging", snapshot.get("ar_aging") or [], ["as_of_date", "tenant_code", "project_code", "product_code", "status", "outstanding_amount", "overdue_invoice_count", "max_days_past_due"], "revenue")}
      {_table("Customer Health", snapshot.get("customer_health") or [], ["as_of_date", "tenant_code", "project_code", "product_code", "status", "retention_signal", "health_score", "request_count_30d"], "revenue")}
      {_table("Payment Batches", snapshot.get("payment_batches") or [], ["imported_at", "batch_code", "source_type", "currency", "status", "transaction_count", "matched_count", "unmatched_count", "total_amount", "matched_amount"], "payments")}
      {_table("Payments", snapshot.get("payments") or [], ["value_date", "transaction_code", "batch_code", "invoice_code", "payment_channel", "status", "currency", "amount", "base_amount"], "payments")}
      {_table("Payment Matches", snapshot.get("payment_matches") or [], ["matched_at", "match_code", "transaction_code", "invoice_code", "match_type", "status", "matched_amount", "unmatched_amount", "invoice_status"], "payments")}
      {_table("Revenue Ledger", snapshot.get("revenue_ledger") or [], ["entry_date", "ledger_code", "entry_type", "invoice_code", "transaction_code", "currency", "debit_amount", "credit_amount", "balance_amount"], "payments")}
      {_table("FX Rates", snapshot.get("fx_rates") or [], ["rate_date", "from_currency", "to_currency", "rate", "provider"], "payments")}
      {_table("Runtime Logs", snapshot.get("runtime_logs") or [], ["log_time", "environment", "component", "severity", "event_type", "message"], "runtime")}
      {_table("Runtime Metrics", snapshot.get("runtime_metrics") or [], ["metric_time", "environment", "component", "metric_name", "metric_value", "unit", "status"], "runtime")}
      {_table("Runtime Daily Reports", snapshot.get("runtime_daily_reports") or [], ["report_date", "environment", "status", "api_request_count", "api_error_rate", "worker_failed_count", "open_capacity_alert_count"], "runtime")}
      {_table("Capacity Alerts", snapshot.get("capacity_alerts") or [], ["last_seen_at", "environment", "component", "metric_name", "severity", "status", "metric_value", "threshold_value"], "runtime")}
      {_table("Strategy Runs", snapshot.get("strategy_runs") or [], ["run_date", "run_code", "environment", "status", "highest_severity", "signal_count", "decision_count", "escalation_count"], "strategy")}
      {_table("Strategy Signals", snapshot.get("strategy_signals") or [], ["observed_at", "domain", "subject_code", "signal_type", "severity", "metric_name", "metric_value", "message"], "strategy")}
      {_table("Strategy Decisions", snapshot.get("strategy_decisions") or [], ["decided_at", "domain", "subject_code", "action", "status", "severity", "priority_score", "reason"], "strategy")}
      {_table("Strategy Escalations", snapshot.get("strategy_escalations") or [], ["created_at", "event_code", "escalation_type", "severity", "status", "owner", "message"], "strategy")}
    </div>
  </main>
  <script>
    (() => {{
      const search = document.getElementById("console-search");
      const status = document.getElementById("console-status");
      const buttons = Array.from(document.querySelectorAll("[data-view-button]"));
      const tiles = Array.from(document.querySelectorAll(".tile[data-view]"));
      const sections = Array.from(document.querySelectorAll(".console-section[data-view]"));
      let activeView = "all";

      function matchesView(element) {{
        return activeView === "all" || element.dataset.view === activeView;
      }}

      function matchesFilters(row, query, statusValue) {{
        const text = row.textContent.toLowerCase();
        const rowStatus = (row.dataset.status || "").toLowerCase();
        return (!query || text.includes(query)) && (!statusValue || rowStatus.includes(statusValue));
      }}

      function applyFilters() {{
        const query = (search.value || "").trim().toLowerCase();
        const statusValue = (status.value || "").trim().toLowerCase();
        buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.viewButton === activeView)));
        tiles.forEach((tile) => tile.hidden = !matchesView(tile));
        sections.forEach((section) => {{
          const inView = matchesView(section);
          let visibleRows = 0;
          Array.from(section.querySelectorAll("tbody tr:not(.empty-row)")).forEach((row) => {{
            const visible = inView && matchesFilters(row, query, statusValue);
            row.hidden = !visible;
            if (visible) visibleRows += 1;
          }});
          const empty = section.querySelector(".empty-row");
          if (empty) empty.hidden = inView && visibleRows > 0;
          section.hidden = !inView || ((query || statusValue) && visibleRows === 0);
          const count = section.querySelector("[data-visible-count]");
          if (count) count.textContent = String(visibleRows);
        }});
      }}

      buttons.forEach((button) => button.addEventListener("click", () => {{
        activeView = button.dataset.viewButton || "all";
        applyFilters();
      }}));
      search.addEventListener("input", applyFilters);
      status.addEventListener("change", applyFilters);
      document.querySelectorAll("[data-gamma6-action]").forEach((button) => {{
        button.addEventListener("click", async () => {{
          const token = new URLSearchParams(window.location.search).get("token") || "";
          const decision = button.dataset.decision || "hold";
          const controlCode = button.dataset.controlCode || "";
          if (!controlCode || button.disabled) return;
          button.disabled = true;
          try {{
            const headers = {{"Content-Type": "application/json"}};
            if (token) headers.Authorization = `Bearer ${{token}}`;
            const response = await fetch("/admin/source-route-incident-approval-commands", {{
              method: "POST",
              headers,
              body: JSON.stringify({{
                decision,
                control_code: controlCode,
                requested_by: "upsilon-console",
                principal_code: "upsilon-console",
                required_approvals: 1,
                idempotency_key: `upsilon-console:${{decision}}:${{controlCode}}:${{Date.now()}}`
              }})
            }});
            if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
            button.textContent = "Done";
          }} catch (error) {{
            button.textContent = "Retry";
            button.disabled = false;
          }}
        }});
      }});
      applyFilters();
    }})();
  </script>
</body>
</html>"""


def format_kappa_report(result: KappaResult) -> str:
    lines = [f"kappa resource={result.resource} rows={len(result.rows)}"]
    for row in result.rows:
        bits = [f"{key}={row[key]}" for key in _report_keys(result.resource, row) if row.get(key) not in (None, "", [], {})]
        limit = None if result.resource == "overview" else 15 if result.resource in {"admin.free-source-reliability", "admin.free-source-recovery-runs", "admin.free-source-recovery-actions", "admin.free-source-recovery-executions", "admin.free-source-recovery-health", "admin.vendor-primary-promotions", "admin.vendor-primary-promotion-results", "admin.vendor-post-promotion-monitors", "admin.vendor-post-promotion-results", "admin.vendor-primary-stability", "admin.vendor-primary-stability-datasets", "admin.vendor-cost-optimizations", "admin.vendor-route-weight-plans", "admin.vendor-budget-stress", "admin.vendor-route-executions", "admin.vendor-route-execution-datasets", "admin.vendor-route-rollout-stages", "admin.vendor-production-source-runs", "admin.vendor-production-source-dataset-checks", "admin.vendor-production-source-decisions", "admin.source-route-weight-policies", "admin.source-route-decisions", "admin.source-route-health", "admin.source-route-circuit-breakers", "admin.source-route-recovery-probes", "admin.source-route-incident-actions", "admin.source-route-incident-controls", "admin.source-route-incident-control-health", "admin.source-route-incident-operation-batches", "admin.source-route-incident-operation-items", "admin.source-route-incident-approval-commands", "admin.source-route-incident-approval-command-items", "admin.source-route-incident-approval-signatures", "admin.source-route-incident-approval-role-bindings", "admin.source-route-incident-approval-policies", "admin.source-route-incident-approval-callbacks", "admin.source-route-incident-approval-escalations"} else 12
        lines.append(" ".join(bits if limit is None else bits[:limit]))
    return "\n".join(lines)


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    if resource == "admin.source-route-decisions":
        preferred = [
            "decision_code",
            "policy_code",
            "dataset_code",
            "requested_source_code",
            "selected_source_code",
            "final_source_code",
            "decision_context",
            "route_mode",
            "decision_status",
            "selected_role",
            "fallback_applied",
            "row_count",
            "duration_ms",
            "started_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-health":
        preferred = [
            "snapshot_code",
            "dataset_code",
            "source_code",
            "status",
            "previous_circuit_status",
            "circuit_status",
            "circuit_action",
            "request_count",
            "success_count",
            "failed_count",
            "fallback_count",
            "success_rate",
            "failure_rate",
            "fallback_rate",
            "latency_p95_ms",
            "open_until",
            "health_issues",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-circuit-breakers":
        preferred = [
            "breaker_code",
            "dataset_code",
            "source_code",
            "status",
            "opened_at",
            "open_until",
            "closed_at",
            "snapshot_code",
            "probe_code",
            "open_reason",
            "failure_rate",
            "fallback_rate",
            "latency_p95_ms",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-recovery-probes":
        preferred = [
            "probe_code",
            "breaker_code",
            "snapshot_code",
            "dataset_code",
            "source_code",
            "status",
            "observed_request_count",
            "observed_success_count",
            "observed_failed_count",
            "observed_success_rate",
            "required_success_rate",
            "decision_summary",
            "probe_started_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-actions":
        preferred = [
            "incident_action_code",
            "run_code",
            "action_code",
            "source_signal_type",
            "dataset_code",
            "source_code",
            "action_type",
            "safety_level",
            "execution_mode",
            "status",
            "approval_required",
            "owner",
            "circuit_status",
            "probe_status",
            "open_until",
            "reason",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-controls":
        preferred = [
            "control_code",
            "incident_action_code",
            "run_code",
            "action_code",
            "dataset_code",
            "source_code",
            "source_signal_type",
            "action_type",
            "safety_level",
            "control_stage",
            "approval_status",
            "dispatch_status",
            "receipt_status",
            "attempt_status",
            "rollback_status",
            "owner",
            "requested_by",
            "execution_mode",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.access-decisions":
        preferred = [
            "decision_code",
            "tenant_code",
            "project_code",
            "principal_code",
            "token_name",
            "api_name",
            "dataset_code",
            "decision",
            "effective_scope",
            "effective_access_level",
            "reason",
            "evaluated_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.project-governance":
        preferred = [
            "snapshot_code",
            "tenant_code",
            "project_code",
            "snapshot_date",
            "status",
            "risk_score",
            "recommended_action",
            "request_count_7d",
            "failed_count_7d",
            "denied_access_7d_count",
            "budget_status",
            "budget_usage_pct",
            "open_budget_alert_count",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.governance-actions":
        preferred = [
            "action_code",
            "tenant_code",
            "project_code",
            "principal_code",
            "token_name",
            "dataset_code",
            "action_type",
            "severity",
            "status",
            "owner",
            "reason",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.payment-batches":
        preferred = [
            "batch_code",
            "source_type",
            "currency",
            "status",
            "transaction_count",
            "matched_count",
            "unmatched_count",
            "total_amount",
            "matched_amount",
            "unmatched_amount",
            "imported_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.payments":
        preferred = [
            "transaction_code",
            "batch_code",
            "invoice_code",
            "tenant_code",
            "project_code",
            "value_date",
            "payment_channel",
            "status",
            "currency",
            "amount",
            "base_amount",
            "reference_text",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.payment-matches":
        preferred = [
            "match_code",
            "transaction_code",
            "invoice_code",
            "tenant_code",
            "project_code",
            "match_type",
            "status",
            "matched_amount",
            "unmatched_amount",
            "invoice_status",
            "matched_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.revenue-ledger":
        preferred = [
            "ledger_code",
            "entry_date",
            "entry_type",
            "tenant_code",
            "project_code",
            "invoice_code",
            "transaction_code",
            "match_code",
            "currency",
            "debit_amount",
            "credit_amount",
            "balance_amount",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.fx-rates":
        preferred = [
            "rate_code",
            "rate_date",
            "from_currency",
            "to_currency",
            "rate",
            "provider",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.invoices":
        preferred = [
            "invoice_code",
            "tenant_code",
            "project_code",
            "product_code",
            "period_start",
            "period_end",
            "status",
            "total_amount",
            "paid_amount",
            "outstanding_amount",
            "line_count",
            "due_date",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.invoice-lines":
        preferred = [
            "line_code",
            "invoice_code",
            "api_name",
            "metric_name",
            "quantity",
            "unit_price",
            "amount",
            "request_count",
            "row_count",
            "cost_units",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.invoice-events":
        preferred = ["created_at", "invoice_code", "event_type", "status", "message"]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.revenue-summary":
        preferred = [
            "tenant_code",
            "project_code",
            "product_code",
            "invoice_count",
            "total_amount",
            "paid_amount",
            "outstanding_amount",
            "overdue_invoice_count",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.revenue-reconciliation":
        preferred = [
            "reconciliation_code",
            "tenant_code",
            "project_code",
            "product_code",
            "period_start",
            "period_end",
            "status",
            "invoice_total_amount",
            "recomputed_total_amount",
            "amount_delta",
            "mismatch_line_count",
            "missing_line_count",
            "extra_line_count",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.revenue-reconciliation-lines":
        preferred = [
            "reconciliation_code",
            "line_key",
            "api_name",
            "metric_name",
            "status",
            "invoice_amount",
            "recomputed_amount",
            "amount_delta",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.ar-aging":
        preferred = [
            "aging_code",
            "tenant_code",
            "project_code",
            "product_code",
            "as_of_date",
            "status",
            "outstanding_amount",
            "current_amount",
            "bucket_1_30_amount",
            "bucket_31_60_amount",
            "bucket_61_90_amount",
            "bucket_90_plus_amount",
            "overdue_invoice_count",
            "max_days_past_due",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.customer-health":
        preferred = [
            "health_code",
            "tenant_code",
            "project_code",
            "product_code",
            "as_of_date",
            "status",
            "retention_signal",
            "health_score",
            "last_usage_date",
            "request_count_30d",
            "outstanding_amount",
            "overdue_invoice_count",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.runtime-logs":
        preferred = [
            "log_time",
            "environment",
            "component",
            "service_name",
            "severity",
            "event_type",
            "message",
            "trace_id",
            "request_id",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.runtime-metrics":
        preferred = [
            "metric_time",
            "environment",
            "component",
            "service_name",
            "metric_name",
            "metric_value",
            "unit",
            "status",
            "warning_threshold",
            "critical_threshold",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.runtime-daily-reports":
        preferred = [
            "report_code",
            "environment",
            "report_date",
            "status",
            "api_request_count",
            "api_failed_count",
            "api_error_rate",
            "worker_failed_count",
            "deployment_health_status",
            "open_capacity_alert_count",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.capacity-alerts":
        preferred = [
            "last_seen_at",
            "alert_key",
            "environment",
            "component",
            "metric_name",
            "severity",
            "status",
            "metric_value",
            "threshold_value",
            "message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.strategy-runs":
        preferred = [
            "run_code",
            "run_date",
            "environment",
            "trigger_mode",
            "status",
            "highest_severity",
            "signal_count",
            "decision_count",
            "escalation_count",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.strategy-signals":
        preferred = [
            "signal_code",
            "run_code",
            "policy_code",
            "domain",
            "subject_code",
            "signal_type",
            "severity",
            "metric_name",
            "metric_value",
            "message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.strategy-decisions":
        preferred = [
            "decision_code",
            "run_code",
            "policy_code",
            "domain",
            "subject_code",
            "action",
            "status",
            "severity",
            "priority_score",
            "reason",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.strategy-escalations":
        preferred = [
            "event_code",
            "run_code",
            "decision_code",
            "escalation_type",
            "severity",
            "status",
            "owner",
            "message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-runs":
        preferred = [
            "run_code",
            "run_date",
            "environment",
            "trigger_mode",
            "execution_mode",
            "status",
            "action_count",
            "executable_count",
            "executed_count",
            "approval_required_count",
            "skipped_count",
            "failed_count",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-actions":
        preferred = [
            "action_code",
            "run_code",
            "source_type",
            "source_code",
            "action_type",
            "safety_level",
            "execution_mode",
            "status",
            "approval_required",
            "owner",
            "reason",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-approvals":
        preferred = [
            "approval_code",
            "action_code",
            "run_code",
            "action_type",
            "safety_level",
            "status",
            "requested_by",
            "requested_at",
            "decided_by",
            "decided_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-executors":
        preferred = [
            "executor_code",
            "executor_type",
            "action_type",
            "safety_level",
            "status",
            "requires_approval",
            "sandbox_mode",
            "allowlist_code",
            "secret_ref",
            "signing_algorithm",
            "max_retry_count",
            "retry_backoff_seconds",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-allowlists":
        preferred = [
            "allowlist_code",
            "executor_type",
            "target_pattern",
            "status",
            "sandbox_only",
            "max_timeout_seconds",
            "description",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-secrets":
        preferred = [
            "secret_ref",
            "secret_scope",
            "secret_kind",
            "status",
            "owner",
            "description",
            "metadata",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-channels":
        preferred = [
            "channel_code",
            "channel_type",
            "environment",
            "status",
            "endpoint_url",
            "allowlist_code",
            "secret_ref",
            "signing_algorithm",
            "owner",
            "runbook_code",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-dispatches":
        preferred = [
            "dispatch_code",
            "action_code",
            "run_code",
            "channel_code",
            "dispatch_type",
            "trigger_mode",
            "status",
            "retry_count",
            "max_retry_count",
            "next_retry_at",
            "error_message",
            "recovered_by",
            "updated_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-runbooks":
        preferred = [
            "runbook_code",
            "failure_class",
            "severity",
            "status",
            "owner",
            "drill_frequency_days",
            "last_drill_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-channel-profiles":
        preferred = [
            "profile_code",
            "channel_code",
            "provider_code",
            "environment",
            "profile_status",
            "readiness_status",
            "dry_run_only",
            "secret_ref",
            "next_secret_ref",
            "last_validation_status",
            "owner",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-channel-validations":
        preferred = [
            "validation_code",
            "profile_code",
            "channel_code",
            "provider_code",
            "validation_type",
            "status",
            "dispatch_code",
            "target_secret_ref",
            "requested_by",
            "error_message",
            "started_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-secret-rotations":
        preferred = [
            "rotation_code",
            "environment",
            "secret_ref",
            "next_secret_ref",
            "rotation_type",
            "status",
            "profile_code",
            "validation_code",
            "validation_status",
            "affected_channel_count",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-live-receipts":
        preferred = [
            "receipt_code",
            "validation_code",
            "profile_code",
            "channel_code",
            "provider_code",
            "environment",
            "message_type",
            "status",
            "provider_status_code",
            "provider_errcode",
            "provider_errmsg",
            "error_message",
            "created_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-attempts":
        preferred = [
            "attempt_code",
            "action_code",
            "run_code",
            "executor_code",
            "action_type",
            "status",
            "retry_count",
            "max_retry_count",
            "next_retry_at",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.automation-rollbacks":
        preferred = [
            "rollback_code",
            "action_code",
            "run_code",
            "rollback_type",
            "status",
            "requested_by",
            "executed_by",
            "reason",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-onboarding-runs":
        preferred = [
            "run_code",
            "source_code",
            "status",
            "preflight_status",
            "canary_status",
            "gate_status",
            "orchestration_status",
            "recommendation",
            "recommended_role",
            "dataset_codes",
            "live_base_url_present",
            "live_token_present",
            "contract_status",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-onboarding-results":
        preferred = [
            "run_code",
            "dataset_code",
            "source_code",
            "stage_status",
            "preflight_status",
            "canary_status",
            "gate_status",
            "recommendation",
            "recommended_role",
            "gate_code",
            "live_requested",
            "live_executed",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-live-closures":
        preferred = [
            "closure_code",
            "source_code",
            "status",
            "config_status",
            "profile_check_status",
            "contract_status",
            "endpoint_status",
            "onboarding_status",
            "promotion_status",
            "recommendation",
            "recommended_role",
            "dataset_codes",
            "missing_dataset_codes",
            "endpoint_probe_count",
            "onboarding_run_code",
            "live_base_url_present",
            "live_token_present",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-live-probes":
        preferred = [
            "closure_code",
            "probe_code",
            "dataset_code",
            "source_code",
            "status",
            "auth_status",
            "schema_status",
            "endpoint_path",
            "live_requested",
            "live_executed",
            "row_count",
            "missing_fields",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-live-pilots":
        preferred = [
            "pilot_code",
            "source_code",
            "status",
            "pilot_scope",
            "closure_status",
            "endpoint_status",
            "onboarding_status",
            "benchmark_status",
            "signoff_status",
            "recommendation",
            "recommended_role",
            "risk_level",
            "dataset_result_count",
            "closure_code",
            "live_base_url_present",
            "live_token_present",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-live-pilot-results":
        preferred = [
            "pilot_code",
            "result_code",
            "dataset_code",
            "source_code",
            "status",
            "closure_status",
            "endpoint_status",
            "schema_status",
            "gate_status",
            "benchmark_status",
            "risk_level",
            "recommendation",
            "recommended_role",
            "probe_code",
            "gate_code",
            "live_requested",
            "live_executed",
            "missing_fields",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-contract-profiles":
        preferred = [
            "contract_code",
            "source_code",
            "provider_name",
            "procurement_status",
            "contract_status",
            "commercial_clearance",
            "redistribution_allowed",
            "production_use_allowed",
            "contract_ref",
            "contract_end_date",
            "sla_tier",
            "sla_uptime_pct",
            "rate_limit_per_min",
            "daily_quota",
            "monthly_quota",
            "billing_model",
            "status",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-contract-entitlements":
        preferred = [
            "entitlement_code",
            "contract_code",
            "source_code",
            "dataset_code",
            "entitlement_status",
            "allowed_role",
            "commercial_use_allowed",
            "redistribution_allowed",
            "production_use_allowed",
            "schema_status",
            "field_mapping_status",
            "rate_limit_per_min",
            "daily_quota",
            "max_delay_minutes",
            "sla_uptime_pct",
            "blocking_issues",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-procurement-readiness":
        preferred = [
            "snapshot_code",
            "source_code",
            "dataset_code",
            "status",
            "procurement_role",
            "readiness_score",
            "procurement_status",
            "contract_status",
            "commercial_clearance",
            "redistribution_allowed",
            "entitlement_status",
            "entitlement_allowed_role",
            "rate_limit_per_min",
            "daily_quota",
            "sla_uptime_pct",
            "pi_readiness_status",
            "live_gate_status",
            "live_pilot_status",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-primary-promotions":
        preferred = [
            "promotion_code",
            "source_code",
            "primary_source_code",
            "as_of_date",
            "status",
            "promotion_scope",
            "apply_mode",
            "routing_change_allowed",
            "routing_change_applied",
            "dataset_count",
            "approved_dataset_count",
            "pending_dataset_count",
            "blocked_dataset_count",
            "applied_dataset_count",
            "promotion_score",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-primary-promotion-results":
        preferred = [
            "promotion_code",
            "result_code",
            "source_code",
            "dataset_code",
            "primary_source_code",
            "status",
            "promotion_role",
            "routing_change_allowed",
            "routing_change_applied",
            "procurement_status",
            "procurement_role",
            "readiness_status",
            "readiness_recommendation",
            "canary_status",
            "canary_signoff_status",
            "full_market_status",
            "full_market_signoff_status",
            "current_primary_source_code",
            "target_priority",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-post-promotion-monitors":
        preferred = [
            "monitor_code",
            "promotion_code",
            "source_code",
            "primary_source_code",
            "as_of_date",
            "status",
            "monitor_scope",
            "rollback_mode",
            "rollback_allowed",
            "rollback_applied",
            "dataset_count",
            "healthy_dataset_count",
            "warning_dataset_count",
            "rollback_recommended_count",
            "rolled_back_dataset_count",
            "blocked_dataset_count",
            "no_applied_dataset_count",
            "monitor_score",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-post-promotion-results":
        preferred = [
            "monitor_code",
            "result_code",
            "promotion_code",
            "promotion_result_code",
            "source_code",
            "dataset_code",
            "primary_source_code",
            "status",
            "monitor_scope",
            "rollback_mode",
            "rollback_allowed",
            "rollback_applied",
            "promotion_status",
            "promotion_role",
            "routing_change_applied",
            "current_primary_source_code",
            "previous_primary_source_code",
            "shadow_status",
            "shadow_conflict_rate_bps",
            "shadow_failure_rate",
            "stale_minutes",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-primary-stability":
        preferred = [
            "snapshot_code",
            "source_code",
            "primary_source_code",
            "status",
            "stability_role",
            "monitor_scope",
            "dataset_count",
            "primary_dataset_count",
            "healthy_dataset_count",
            "warning_dataset_count",
            "critical_dataset_count",
            "blocked_dataset_count",
            "no_primary_dataset_count",
            "api_success_rate",
            "api_error_rate",
            "api_latency_p95_ms",
            "cost_units",
            "scheduler_lag_minutes",
            "backlog_count",
            "post_promotion_no_applied_count",
            "stability_score",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-primary-stability-datasets":
        preferred = [
            "snapshot_code",
            "dataset_snapshot_code",
            "source_code",
            "dataset_code",
            "primary_source_code",
            "status",
            "stability_role",
            "monitor_scope",
            "is_primary_route",
            "current_primary_source_code",
            "current_priority",
            "entitlement_status",
            "allowed_role",
            "production_use_allowed",
            "schema_status",
            "promotion_status",
            "promotion_result_status",
            "post_promotion_status",
            "api_success_rate",
            "api_latency_p95_ms",
            "cost_units",
            "stability_score",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-cost-optimizations":
        preferred = [
            "optimization_code",
            "source_code",
            "primary_source_code",
            "status",
            "optimization_role",
            "optimization_scope",
            "dataset_count",
            "optimized_dataset_count",
            "watch_dataset_count",
            "over_budget_dataset_count",
            "quota_risk_dataset_count",
            "blocked_dataset_count",
            "no_primary_dataset_count",
            "forecast_request_count",
            "forecast_cost_units",
            "projected_budget_usage_pct",
            "projected_monthly_quota_usage_pct",
            "recommended_primary_weight_pct",
            "recommended_backup_weight_pct",
            "recommended_free_source_weight_pct",
            "optimization_score",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-route-weight-plans":
        preferred = [
            "optimization_code",
            "plan_code",
            "source_code",
            "dataset_code",
            "primary_source_code",
            "backup_source_code",
            "status",
            "plan_role",
            "current_primary_source_code",
            "is_primary_route",
            "stability_status",
            "stability_score",
            "contract_status",
            "entitlement_status",
            "unit_cost",
            "forecast_request_count",
            "forecast_cost_units",
            "projected_budget_usage_pct",
            "projected_monthly_quota_usage_pct",
            "recommended_primary_weight_pct",
            "recommended_backup_weight_pct",
            "recommended_free_source_weight_pct",
            "routing_change_allowed",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-budget-stress":
        preferred = [
            "optimization_code",
            "plan_code",
            "stress_code",
            "source_code",
            "dataset_code",
            "stress_multiplier",
            "status",
            "forecast_request_count",
            "forecast_cost_units",
            "projected_budget_usage_pct",
            "projected_daily_quota_usage_pct",
            "projected_monthly_quota_usage_pct",
            "quota_exhaustion_days",
            "recommended_action",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-route-executions":
        preferred = [
            "execution_code",
            "optimization_code",
            "source_code",
            "primary_source_code",
            "status",
            "approval_status",
            "execution_mode",
            "execution_scope",
            "rollout_policy",
            "current_stage_sequence",
            "dataset_count",
            "pending_approval_dataset_count",
            "approved_dataset_count",
            "staged_dataset_count",
            "applied_dataset_count",
            "blocked_dataset_count",
            "no_primary_dataset_count",
            "target_primary_weight_pct",
            "applied_primary_weight_pct",
            "routing_change_allowed",
            "routing_change_applied",
            "rollback_allowed",
            "rollback_applied",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-route-execution-datasets":
        preferred = [
            "execution_code",
            "execution_dataset_code",
            "optimization_code",
            "plan_code",
            "source_code",
            "dataset_code",
            "primary_source_code",
            "backup_source_code",
            "status",
            "approval_status",
            "rollout_policy",
            "current_stage_sequence",
            "current_primary_source_code",
            "tau5_status",
            "stability_status",
            "target_primary_weight_pct",
            "applied_primary_weight_pct",
            "routing_change_allowed",
            "routing_change_applied",
            "rollback_allowed",
            "rollback_applied",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-route-rollout-stages":
        preferred = [
            "execution_code",
            "execution_dataset_code",
            "stage_code",
            "source_code",
            "dataset_code",
            "stage_sequence",
            "stage_label",
            "status",
            "approval_required",
            "approval_status",
            "gate_status",
            "target_primary_weight_pct",
            "target_backup_weight_pct",
            "target_free_source_weight_pct",
            "routing_change_allowed",
            "routing_change_applied",
            "blocking_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-production-source-runs":
        preferred = [
            "production_code",
            "source_code",
            "primary_source_code",
            "status",
            "production_role",
            "closure_mode",
            "dataset_count",
            "authorized_dataset_count",
            "pilot_ready_dataset_count",
            "promoted_dataset_count",
            "stable_dataset_count",
            "optimized_dataset_count",
            "route_ready_dataset_count",
            "production_ready_dataset_count",
            "applied_dataset_count",
            "blocked_dataset_count",
            "live_base_url_present",
            "live_token_present",
            "routing_change_allowed",
            "production_score",
            "blocking_issues",
            "required_actions",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-production-source-dataset-checks":
        preferred = [
            "production_code",
            "dataset_check_code",
            "source_code",
            "dataset_code",
            "status",
            "production_role",
            "contract_status",
            "entitlement_status",
            "procurement_status",
            "canary_status",
            "full_market_status",
            "promotion_result_status",
            "stability_status",
            "optimization_status",
            "route_execution_status",
            "route_policy_status",
            "current_primary_source_code",
            "is_primary_route",
            "production_score",
            "blocking_issues",
            "required_actions",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-production-source-decisions":
        preferred = [
            "production_code",
            "dataset_check_code",
            "decision_code",
            "source_code",
            "dataset_code",
            "decision_type",
            "status",
            "severity",
            "decision_summary",
            "blocking_issues",
            "required_actions",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-weight-policies":
        preferred = [
            "policy_code",
            "execution_code",
            "execution_dataset_code",
            "stage_code",
            "source_code",
            "dataset_code",
            "primary_source_code",
            "backup_source_code",
            "effective_date",
            "end_date",
            "policy_status",
            "execution_mode",
            "primary_weight_pct",
            "backup_weight_pct",
            "free_source_weight_pct",
            "created_by",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.free-source-fabric-runs":
        preferred = [
            "fabric_code",
            "status",
            "fabric_scope",
            "recommendation",
            "recommended_role",
            "risk_level",
            "baseline_source_code",
            "dataset_result_count",
            "usable_source_count",
            "coverage_rate",
            "conflict_rate_bps",
            "license_review_required_count",
            "commercial_blocker_count",
            "allow_external",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.free-source-fabric-results":
        preferred = [
            "fabric_code",
            "result_code",
            "dataset_code",
            "status",
            "coverage_status",
            "consistency_status",
            "license_status",
            "freshness_status",
            "recommendation",
            "recommended_role",
            "risk_level",
            "baseline_source_code",
            "usable_source_count",
            "coverage_rate",
            "conflict_rate_bps",
            "license_blocking_sources",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.free-source-reliability":
        preferred = [
            "snapshot_code",
            "source_code",
            "dataset_code",
            "as_of_date",
            "status",
            "recommended_role",
            "reliability_score",
            "success_rate",
            "coverage_rate",
            "conflict_rate_bps",
            "consecutive_failure_count",
            "license_status",
            "commercial_clearance",
            "degradation_reasons",
            "recovery_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.free-source-recovery-health":
        preferred = [
            "snapshot_code",
            "status",
            "as_of_at",
            "backlog_count",
            "pending_action_count",
            "approval_pending_count",
            "approval_overdue_count",
            "execution_count",
            "recovered_count",
            "failed_count",
            "failure_rate",
            "stale_schedule_count",
            "latest_worker_status",
            "latest_schedule_status",
            "health_issues",
            "runbook_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-control-health":
        preferred = [
            "snapshot_code",
            "status",
            "as_of_at",
            "control_count",
            "pending_control_count",
            "approval_pending_count",
            "approval_overdue_count",
            "notification_blocked_count",
            "blocked_receipt_rate",
            "execution_count",
            "failed_execution_count",
            "execution_failure_rate",
            "rollback_planned_count",
            "missing_rollback_count",
            "stale_schedule_count",
            "latest_worker_status",
            "latest_schedule_status",
            "latest_control_stage",
            "health_issues",
            "runbook_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-operation-batches":
        preferred = [
            "batch_code",
            "status",
            "started_at",
            "operation_mode",
            "approval_decision",
            "dry_run",
            "apply_decisions",
            "candidate_count",
            "eligible_count",
            "approved_count",
            "rejected_count",
            "held_count",
            "skipped_count",
            "failed_count",
            "suppressed_notification_count",
            "stress_scenario_count",
            "operation_issues",
            "required_actions",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-operation-items":
        preferred = [
            "batch_code",
            "control_code",
            "approval_code",
            "dataset_code",
            "source_code",
            "source_signal_type",
            "safety_level",
            "operation_decision",
            "operation_status",
            "approval_status_before",
            "approval_status_after",
            "suppress_notification",
            "priority_score",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-commands":
        preferred = [
            "command_code",
            "status",
            "decision",
            "principal_code",
            "command_scope",
            "batch_code",
            "control_code",
            "approval_code",
            "required_approvals",
            "approval_count",
            "quorum_status",
            "target_count",
            "applied_count",
            "held_count",
            "rejected_count",
            "skipped_count",
            "failed_count",
            "command_issues",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-command-items":
        preferred = [
            "command_code",
            "control_code",
            "approval_code",
            "dataset_code",
            "source_code",
            "decision",
            "item_status",
            "signer_code",
            "signature_count",
            "required_approvals",
            "approval_status_before",
            "approval_status_after",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-signatures":
        preferred = [
            "signature_code",
            "command_code",
            "control_code",
            "approval_code",
            "decision",
            "signer_code",
            "status",
            "idempotency_key",
            "signed_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-role-bindings":
        preferred = [
            "binding_code",
            "principal_code",
            "role_code",
            "dataset_code",
            "source_code",
            "safety_level",
            "status",
            "effective_at",
            "expires_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-policies":
        preferred = [
            "policy_code",
            "dataset_code",
            "source_code",
            "safety_level",
            "status",
            "min_approvals",
            "require_distinct_requester",
            "require_risk_admin_for_high",
            "require_wecom_signature",
            "timeout_minutes",
            "escalation_principal_code",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-callbacks":
        preferred = [
            "callback_code",
            "provider_code",
            "signature_status",
            "governance_status",
            "decision",
            "signer_code",
            "control_code",
            "command_code",
            "required_approvals",
            "replay_count",
            "error_message",
            "received_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-escalations":
        preferred = [
            "escalation_code",
            "reason_code",
            "status",
            "severity",
            "owner_principal_code",
            "command_code",
            "control_code",
            "approval_code",
            "error_message",
            "created_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-lock-events":
        preferred = [
            "lock_event_code",
            "lock_status",
            "lock_scope",
            "provider_code",
            "nonce",
            "control_code",
            "callback_code",
            "command_code",
            "held_ms",
            "error_message",
            "started_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-state-transitions":
        preferred = [
            "transition_code",
            "transition_status",
            "reason_code",
            "control_code",
            "requested_decision",
            "approval_status_before",
            "approval_status_after",
            "callback_code",
            "command_code",
            "error_message",
            "observed_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-audit-chain":
        preferred = [
            "audit_hash_code",
            "chain_scope",
            "sequence_no",
            "entity_type",
            "entity_code",
            "previous_hash",
            "entry_hash",
            "verification_status",
            "event_time",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-sla-actions":
        preferred = [
            "sla_action_code",
            "action_status",
            "action_type",
            "reason_code",
            "severity",
            "owner_principal_code",
            "escalation_code",
            "control_code",
            "generated_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-recovery-drills":
        preferred = [
            "drill_code",
            "drill_type",
            "status",
            "check_count",
            "passed_count",
            "failed_count",
            "recovered_count",
            "requested_by",
            "started_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-release-preflights":
        preferred = [
            "preflight_code",
            "environment",
            "status",
            "release_version",
            "check_count",
            "passed_count",
            "warning_count",
            "failed_count",
            "dual_secret_enabled",
            "audit_broken_count",
            "latest_recovery_drill_status",
            "started_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-secret-rotations":
        preferred = [
            "rotation_code",
            "environment",
            "rotation_phase",
            "status",
            "active_secret_label",
            "verified_secret_label",
            "nonce",
            "signature_digest",
            "observed_at",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-concurrency-tests":
        preferred = [
            "test_code",
            "environment",
            "status",
            "target_scope",
            "callback_count",
            "expected_success_count",
            "success_count",
            "locked_count",
            "blocked_count",
            "replay_rejected_count",
            "failed_count",
            "duration_ms",
            "started_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.source-route-incident-approval-audit-exports":
        preferred = [
            "export_code",
            "environment",
            "status",
            "export_format",
            "chain_scope",
            "control_code",
            "included_entity_count",
            "broken_hash_count",
            "package_hash",
            "exported_by",
            "generated_at",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-readiness":
        preferred = [
            "review_code",
            "source_code",
            "dataset_code",
            "status",
            "recommendation",
            "recommended_role",
            "suite_count",
            "passed_window_count",
            "warning_window_count",
            "failed_window_count",
            "missing_window_count",
            "runtime_mode",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-readiness-windows":
        preferred = [
            "review_code",
            "window_days",
            "status",
            "suite_code",
            "coverage_rate",
            "conflict_rate",
            "failure_rate",
            "p95_latency_ms",
            "rows_per_second",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource == "admin.vendor-live-gates":
        preferred = [
            "gate_code",
            "source_code",
            "dataset_code",
            "run_mode",
            "status",
            "start_date",
            "end_date",
            "required_windows",
            "executed_windows",
            "live_base_url_present",
            "live_token_present",
            "readiness_status",
            "recommendation",
            "recommended_role",
            "error_message",
        ]
        return [key for key in preferred if key in row] + [key for key in row if key not in preferred]
    if resource != "overview":
        return list(row)
    preferred = [
        "active_tenant_count",
        "active_project_count",
        "active_principal_count",
        "active_token_count",
        "active_dataset_policy_count",
        "open_alert_count",
        "sent_notification_count",
        "active_vendor_schedule_count",
        "vendor_readiness_ready_count",
        "vendor_readiness_watch_count",
        "vendor_readiness_rejected_count",
        "latest_vendor_readiness_status",
        "vendor_24h_live_gate_count",
        "vendor_24h_live_gate_blocked_count",
        "vendor_24h_live_gate_executed_count",
        "latest_vendor_live_gate_status",
        "vendor_24h_onboarding_count",
        "vendor_24h_onboarding_blocked_count",
        "latest_vendor_onboarding_status",
        "vendor_24h_live_closure_count",
        "vendor_24h_live_closure_blocked_count",
        "latest_vendor_live_closure_status",
        "vendor_24h_live_pilot_count",
        "vendor_24h_live_pilot_blocked_count",
        "latest_vendor_live_pilot_status",
        "vendor_contract_profile_count",
        "vendor_active_contract_count",
        "vendor_active_entitlement_count",
        "vendor_24h_procurement_readiness_count",
        "vendor_24h_procurement_ready_count",
        "vendor_24h_procurement_review_required_count",
        "vendor_24h_procurement_blocked_count",
        "latest_vendor_procurement_status",
        "vendor_procurement_primary_candidate_count",
        "vendor_24h_primary_promotion_count",
        "vendor_24h_primary_promotion_approved_count",
        "vendor_24h_primary_promotion_blocked_count",
        "vendor_24h_primary_promotion_applied_count",
        "latest_vendor_primary_promotion_status",
        "vendor_primary_promotion_routing_allowed_count",
        "vendor_24h_post_promotion_monitor_count",
        "vendor_24h_post_promotion_healthy_count",
        "vendor_24h_post_promotion_rollback_recommended_count",
        "vendor_24h_post_promotion_rolled_back_count",
        "vendor_24h_post_promotion_no_applied_count",
        "latest_vendor_post_promotion_status",
        "vendor_post_promotion_rollback_allowed_count",
        "vendor_24h_primary_stability_count",
        "vendor_24h_primary_stability_healthy_count",
        "vendor_24h_primary_stability_warning_count",
        "vendor_24h_primary_stability_critical_count",
        "vendor_24h_primary_stability_no_primary_count",
        "latest_vendor_primary_stability_status",
        "latest_vendor_primary_stability_role",
        "vendor_primary_stability_primary_dataset_count",
        "vendor_primary_stability_score",
        "vendor_primary_stability_cost_units",
        "vendor_primary_stability_scheduler_lag_minutes",
        "vendor_primary_stability_backlog_count",
        "vendor_24h_cost_optimization_count",
        "vendor_24h_cost_optimized_count",
        "vendor_24h_cost_over_budget_count",
        "vendor_24h_cost_quota_risk_count",
        "vendor_24h_cost_no_primary_count",
        "latest_vendor_cost_optimization_status",
        "latest_vendor_cost_optimization_role",
        "vendor_cost_primary_weight_pct",
        "vendor_cost_backup_weight_pct",
        "vendor_cost_free_source_weight_pct",
        "vendor_cost_budget_usage_pct",
        "vendor_cost_monthly_quota_usage_pct",
        "vendor_cost_optimization_score",
        "vendor_24h_route_execution_count",
        "vendor_24h_route_pending_approval_count",
        "vendor_24h_route_staged_count",
        "vendor_24h_route_applied_count",
        "vendor_24h_route_blocked_count",
        "latest_vendor_route_execution_status",
        "latest_vendor_route_execution_approval_status",
        "vendor_route_applied_primary_weight_pct",
        "vendor_route_current_stage_sequence",
        "vendor_24h_production_source_count",
        "vendor_24h_production_source_ready_count",
        "vendor_24h_production_source_blocked_count",
        "latest_vendor_production_source_status",
        "latest_vendor_production_source_role",
        "vendor_production_source_score",
        "vendor_production_source_live_base_url_present",
        "vendor_production_source_live_token_present",
        "active_source_route_weight_policy_count",
        "source_route_24h_decision_count",
        "source_route_24h_fallback_count",
        "latest_source_route_decision_status",
        "latest_source_route_final_source_code",
        "source_route_24h_health_count",
        "source_route_24h_unhealthy_count",
        "latest_source_route_health_status",
        "source_route_open_circuit_count",
        "source_route_24h_recovery_probe_count",
        "source_route_24h_recovered_probe_count",
        "source_route_24h_incident_action_count",
        "source_route_pending_incident_action_count",
        "latest_source_route_incident_action_status",
        "source_route_24h_incident_control_count",
        "source_route_pending_incident_control_count",
        "latest_source_route_incident_control_stage",
        "source_route_latest_control_health_status",
        "source_route_control_health_issue_count",
        "source_route_control_health_overdue_approval_count",
        "source_route_control_health_blocked_receipt_count",
        "source_route_latest_operation_status",
        "source_route_operation_queue_count",
        "source_route_operation_suppressed_notification_count",
        "source_route_operation_stress_scenario_count",
        "source_route_latest_approval_command_status",
        "source_route_approval_pending_quorum_count",
        "source_route_approval_24h_applied_count",
        "source_route_approval_24h_signature_count",
        "source_route_approval_active_role_binding_count",
        "source_route_approval_active_policy_count",
        "source_route_latest_approval_callback_status",
        "source_route_approval_24h_verified_callback_count",
        "source_route_approval_24h_replay_rejected_count",
        "source_route_approval_24h_denied_callback_count",
        "source_route_approval_open_escalation_count",
        "source_route_approval_24h_lock_event_count",
        "source_route_approval_24h_lock_busy_count",
        "source_route_approval_24h_state_transition_count",
        "source_route_approval_24h_state_blocked_count",
        "source_route_approval_audit_hash_count",
        "source_route_approval_broken_audit_hash_count",
        "source_route_approval_planned_sla_action_count",
        "source_route_latest_approval_recovery_drill_status",
        "source_route_approval_24h_successful_recovery_drill_count",
        "source_route_latest_approval_release_preflight_status",
        "source_route_approval_24h_release_preflight_count",
        "source_route_approval_24h_failed_release_preflight_count",
        "source_route_approval_24h_secret_rotation_count",
        "source_route_latest_approval_secret_rotation_status",
        "source_route_latest_approval_verified_secret_label",
        "source_route_latest_approval_concurrency_test_status",
        "source_route_approval_24h_concurrency_test_count",
        "source_route_approval_24h_audit_export_count",
        "source_route_latest_approval_audit_export_broken_count",
        "free_source_24h_fabric_count",
        "free_source_24h_fabric_blocked_count",
        "latest_free_source_fabric_status",
        "free_source_24h_reliability_count",
        "free_source_24h_reliability_ready_count",
        "free_source_24h_reliability_degraded_count",
        "free_source_24h_reliability_rejected_count",
        "latest_free_source_reliability_status",
        "free_source_24h_recovery_count",
        "free_source_24h_recovery_action_count",
        "free_source_24h_recovery_alert_count",
        "latest_free_source_recovery_status",
        "free_source_24h_recovery_execution_count",
        "free_source_24h_recovered_count",
        "free_source_24h_recovery_failed_count",
        "latest_free_source_recovery_execution_status",
        "free_source_24h_recovery_health_count",
        "latest_free_source_recovery_health_status",
        "free_source_recovery_overdue_approval_count",
        "free_source_recovery_backlog_count",
        "free_source_24h_admission_count",
        "free_source_24h_admission_approved_count",
        "free_source_24h_admission_conditional_count",
        "free_source_24h_admission_review_required_count",
        "free_source_24h_admission_blocked_count",
        "free_source_24h_admission_no_data_count",
        "latest_free_source_admission_status",
        "free_source_primary_candidate_count",
        "usage_7d_request_count",
        "usage_7d_cost_units",
        "worker_7d_run_count",
        "latest_worker_status",
        "active_worker_schedule_count",
        "live_scheduler_count",
        "expired_worker_lock_count",
        "latest_scheduler_tick_status",
        "latest_deployment_health_status",
        "latest_deployment_release_status",
        "deployment_24h_failed_count",
        "active_product_count",
        "active_subscription_count",
        "active_budget_policy_count",
        "budget_open_alert_count",
        "budget_blocked_count",
        "budget_month_usage_amount",
        "budget_month_limit_amount",
        "invoice_month_count",
        "invoice_month_total_amount",
        "invoice_month_paid_amount",
        "invoice_month_outstanding_amount",
        "overdue_invoice_count",
        "revenue_reconciliation_mismatch_count",
        "latest_reconciliation_status",
        "latest_ar_outstanding_amount",
        "customer_health_active_count",
        "customer_health_risk_count",
        "payment_month_received_amount",
        "payment_month_matched_amount",
        "unmatched_payment_count",
        "latest_payment_batch_status",
        "revenue_ledger_month_credit_amount",
        "runtime_24h_error_log_count",
        "runtime_metric_warning_count",
        "runtime_metric_critical_count",
        "open_capacity_alert_count",
        "latest_runtime_report_status",
        "latest_strategy_status",
        "latest_strategy_severity",
        "strategy_24h_action_decision_count",
        "open_strategy_escalation_count",
        "access_denied_24h_count",
        "project_governance_warning_count",
        "project_governance_critical_count",
        "open_governance_action_count",
        "automation_24h_run_count",
        "automation_24h_action_count",
        "automation_approval_required_count",
        "automation_24h_failed_count",
        "automation_pending_approval_count",
        "automation_retry_scheduled_count",
        "automation_rollback_required_count",
        "automation_active_sandbox_executor_count",
        "automation_active_allowlist_count",
        "automation_active_secret_ref_count",
        "automation_active_channel_count",
        "automation_24h_dispatch_count",
        "automation_dead_letter_count",
        "latest_automation_dispatch_status",
        "latest_automation_attempt_status",
        "latest_automation_status",
    ]
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _where_equal(
    params: dict[str, list[str]],
    fields: list[tuple[str, str]],
    *,
    include_where: bool = True,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for param_name, column_name in fields:
        value = _param(params, param_name)
        if value in (None, ""):
            continue
        clauses.append(f"{column_name} = %s")
        values.append(value)
    if not clauses:
        return "", values
    prefix = "WHERE " if include_where else ""
    return prefix + " AND ".join(clauses), values


def _append_where(where: str, values: list[Any], clause: str, value: Any) -> tuple[str, list[Any]]:
    if where:
        where = f"{where} AND {clause}"
    else:
        where = f"WHERE {clause}"
    return where, values + [value]


def _date_window(params: dict[str, list[str]]) -> tuple[str, str]:
    trade_date = _param(params, "trade_date")
    if trade_date:
        date_range(trade_date, trade_date)
        return trade_date, trade_date
    start_date = _param(params, "start_date")
    end_date = _param(params, "end_date")
    if start_date and end_date:
        date_range(start_date, end_date)
        return start_date, end_date
    today = date.today()
    return (today - timedelta(days=6)).isoformat(), today.isoformat()


def _append_period_filter(
    where: str,
    values: list[Any],
    params: dict[str, list[str]],
    period_start_column: str,
    period_end_column: str,
) -> tuple[str, list[Any]]:
    start_date = _param(params, "start_date")
    end_date = _param(params, "end_date")
    if start_date and end_date:
        date_range(start_date, end_date)
        clause = f"{period_start_column} <= %s AND {period_end_column} >= %s"
        values = values + [end_date, start_date]
    elif start_date:
        date_range(start_date, start_date)
        clause = f"{period_end_column} >= %s"
        values = values + [start_date]
    elif end_date:
        date_range(end_date, end_date)
        clause = f"{period_start_column} <= %s"
        values = values + [end_date]
    else:
        return where, values
    return (f"{where} AND {clause}" if where else f"WHERE {clause}"), values


def _append_date_filter(
    where: str,
    values: list[Any],
    params: dict[str, list[str]],
    column_name: str,
) -> tuple[str, list[Any]]:
    start_date = _param(params, "start_date")
    end_date = _param(params, "end_date")
    if start_date and end_date:
        date_range(start_date, end_date)
        clause = f"{column_name}::date BETWEEN %s AND %s"
        values = values + [start_date, end_date]
    elif start_date:
        date_range(start_date, start_date)
        clause = f"{column_name}::date >= %s"
        values = values + [start_date]
    elif end_date:
        date_range(end_date, end_date)
        clause = f"{column_name}::date <= %s"
        values = values + [end_date]
    else:
        return where, values
    return (f"{where} AND {clause}" if where else f"WHERE {clause}"), values


def _limit_offset(params: dict[str, list[str]]) -> tuple[int, int]:
    limit = _int_param(params, "limit", 100)
    offset = _int_param(params, "offset", 0)
    if limit < 1 or limit > 500:
        raise QDataValidationError("limit must be between 1 and 500")
    if offset < 0:
        raise QDataValidationError("offset must be greater than or equal to 0")
    return limit, offset


def _int_param(params: dict[str, list[str]], name: str, default: int) -> int:
    value = _param(params, name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise QDataValidationError(f"{name} must be an integer") from exc


def _bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "y"}


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[-1]


def _tile(label: str, value: Any, view: str = "all", tone: str = "neutral") -> str:
    return (
        f"<div class=\"tile {escape(tone)}\" data-view=\"{escape(view)}\">"
        f"<span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>"
    )


def _table(title: str, rows: list[dict[str, Any]], columns: list[str], view: str = "all") -> str:
    body = "".join(_table_row(row, columns) for row in rows)
    if not body:
        body = f"<tr class=\"empty-row\"><td colspan=\"{len(columns)}\">No rows</td></tr>"
    header = "".join(f"<th>{escape(column)}</th>" for column in columns)
    return (
        f"<section class=\"console-section\" data-view=\"{escape(view)}\">"
        f"<div class=\"section-head\"><h2>{escape(title)}</h2>"
        f"<span class=\"section-count\"><span data-visible-count>{len(rows)}</span>/{len(rows)}</span></div>"
        f"<div class=\"table-wrap\"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"
        "</section>"
    )


def _table_row(row: dict[str, Any], columns: list[str]) -> str:
    status = _row_status(row)
    cells = "".join(_table_cell(row, column) for column in columns)
    return f"<tr data-status=\"{escape(status)}\">{cells}</tr>"


def _table_cell(row: dict[str, Any], column: str) -> str:
    if column == "gamma6_actions":
        return _gamma6_action_cell(row)
    value = row.get(column, "")
    text = "" if value is None else str(value)
    classes = []
    if _is_numeric_column(column, text):
        classes.append("num")
    class_attr = f" class=\"{' '.join(classes)}\"" if classes else ""
    if column in {"status", "latest_usage_status", "last_status", "health_status", "invoice_status", "retention_signal", "recommendation", "severity"} and text:
        return f"<td{class_attr}><span class=\"status-chip {escape(_status_class(text))}\">{escape(text)}</span></td>"
    return f"<td{class_attr}>{escape(text)}</td>"


def _gamma6_action_cell(row: dict[str, Any]) -> str:
    control_code = row.get("control_code")
    approval_code = row.get("approval_code")
    if not control_code or not approval_code:
        return "<td></td>"
    buttons = []
    for decision, label in (("approve", "Approve"), ("reject", "Reject"), ("hold", "Hold")):
        buttons.append(
            "<button class=\"gamma6-action\" "
            f"data-gamma6-action=\"1\" data-decision=\"{escape(decision)}\" "
            f"data-control-code=\"{escape(str(control_code))}\" "
            f"data-approval-code=\"{escape(str(approval_code))}\" "
            f"title=\"Gamma-6 {escape(label)}\">{escape(label)}</button>"
        )
    return f"<td><div class=\"action-cell\">{''.join(buttons)}</div></td>"


def _row_status(row: dict[str, Any]) -> str:
    for key in (
        "status",
        "latest_usage_status",
        "last_status",
        "health_status",
        "invoice_status",
        "retention_signal",
        "recommendation",
        "severity",
    ):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _status_class(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _is_numeric_column(column: str, text: str) -> bool:
    if not text:
        return False
    if column.endswith(("_amount", "_count", "_rate", "_pct", "_units", "_value", "_threshold", "_ms")):
        return True
    if column in {"quantity", "unit_price", "amount", "rate", "matched_amount", "unmatched_amount", "credit_amount", "debit_amount", "balance_amount"}:
        return True
    return False


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Kappa admin endpoints")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Kappa admin endpoints") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
