#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.kappa import dispatch_kappa_endpoint, format_kappa_report


RESOURCE_PATHS = {
    "overview": "/admin/overview",
    "tenants": "/admin/tenants",
    "projects": "/admin/projects",
    "principals": "/admin/principals",
    "tokens": "/admin/tokens",
    "dataset-access": "/admin/dataset-access",
    "access-decisions": "/admin/access-decisions",
    "project-governance": "/admin/project-governance",
    "governance-actions": "/admin/governance-actions",
    "automation-runs": "/admin/automation-runs",
    "automation-actions": "/admin/automation-actions",
    "automation-approvals": "/admin/automation-approvals",
    "automation-executors": "/admin/automation-executors",
    "automation-allowlists": "/admin/automation-allowlists",
    "automation-secrets": "/admin/automation-secrets",
    "automation-channels": "/admin/automation-channels",
    "automation-dispatches": "/admin/automation-dispatches",
    "automation-runbooks": "/admin/automation-runbooks",
    "automation-channel-profiles": "/admin/automation-channel-profiles",
    "automation-channel-validations": "/admin/automation-channel-validations",
    "automation-secret-rotations": "/admin/automation-secret-rotations",
    "automation-live-receipts": "/admin/automation-live-receipts",
    "automation-attempts": "/admin/automation-attempts",
    "automation-rollbacks": "/admin/automation-rollbacks",
    "notification-deliveries": "/admin/notification-deliveries",
    "vendor-schedules": "/admin/vendor-schedules",
    "vendor-onboarding-runs": "/admin/vendor-onboarding-runs",
    "vendor-onboarding-results": "/admin/vendor-onboarding-results",
    "vendor-live-closures": "/admin/vendor-live-closures",
    "vendor-live-probes": "/admin/vendor-live-probes",
    "vendor-live-pilots": "/admin/vendor-live-pilots",
    "vendor-live-pilot-results": "/admin/vendor-live-pilot-results",
    "vendor-contract-profiles": "/admin/vendor-contract-profiles",
    "vendor-contract-entitlements": "/admin/vendor-contract-entitlements",
    "vendor-procurement-readiness": "/admin/vendor-procurement-readiness",
    "vendor-primary-promotions": "/admin/vendor-primary-promotions",
    "vendor-primary-promotion-results": "/admin/vendor-primary-promotion-results",
    "vendor-post-promotion-monitors": "/admin/vendor-post-promotion-monitors",
    "vendor-post-promotion-results": "/admin/vendor-post-promotion-results",
    "vendor-primary-stability": "/admin/vendor-primary-stability",
    "vendor-primary-stability-datasets": "/admin/vendor-primary-stability-datasets",
    "vendor-cost-optimizations": "/admin/vendor-cost-optimizations",
    "vendor-route-weight-plans": "/admin/vendor-route-weight-plans",
    "vendor-budget-stress": "/admin/vendor-budget-stress",
    "vendor-route-executions": "/admin/vendor-route-executions",
    "vendor-route-execution-datasets": "/admin/vendor-route-execution-datasets",
    "vendor-route-rollout-stages": "/admin/vendor-route-rollout-stages",
    "vendor-production-source-runs": "/admin/vendor-production-source-runs",
    "vendor-production-source-dataset-checks": "/admin/vendor-production-source-dataset-checks",
    "vendor-production-source-decisions": "/admin/vendor-production-source-decisions",
    "source-route-weight-policies": "/admin/source-route-weight-policies",
    "source-route-decisions": "/admin/source-route-decisions",
    "source-route-health": "/admin/source-route-health",
    "source-route-circuit-breakers": "/admin/source-route-circuit-breakers",
    "source-route-recovery-probes": "/admin/source-route-recovery-probes",
    "source-route-incident-actions": "/admin/source-route-incident-actions",
    "source-route-incident-controls": "/admin/source-route-incident-controls",
    "source-route-incident-control-health": "/admin/source-route-incident-control-health",
    "source-route-incident-operation-batches": "/admin/source-route-incident-operation-batches",
    "source-route-incident-operation-items": "/admin/source-route-incident-operation-items",
    "source-route-incident-approval-commands": "/admin/source-route-incident-approval-commands",
    "source-route-incident-approval-command-items": "/admin/source-route-incident-approval-command-items",
    "source-route-incident-approval-signatures": "/admin/source-route-incident-approval-signatures",
    "source-route-incident-approval-role-bindings": "/admin/source-route-incident-approval-role-bindings",
    "source-route-incident-approval-policies": "/admin/source-route-incident-approval-policies",
    "source-route-incident-approval-callbacks": "/admin/source-route-incident-approval-callbacks",
    "source-route-incident-approval-escalations": "/admin/source-route-incident-approval-escalations",
    "source-route-incident-approval-lock-events": "/admin/source-route-incident-approval-lock-events",
    "source-route-incident-approval-state-transitions": "/admin/source-route-incident-approval-state-transitions",
    "source-route-incident-approval-audit-chain": "/admin/source-route-incident-approval-audit-chain",
    "source-route-incident-approval-sla-actions": "/admin/source-route-incident-approval-sla-actions",
    "source-route-incident-approval-recovery-drills": "/admin/source-route-incident-approval-recovery-drills",
    "source-route-incident-approval-release-preflights": "/admin/source-route-incident-approval-release-preflights",
    "source-route-incident-approval-secret-rotations": "/admin/source-route-incident-approval-secret-rotations",
    "source-route-incident-approval-concurrency-tests": "/admin/source-route-incident-approval-concurrency-tests",
    "source-route-incident-approval-audit-exports": "/admin/source-route-incident-approval-audit-exports",
    "free-source-fabric-runs": "/admin/free-source-fabric-runs",
    "free-source-fabric-results": "/admin/free-source-fabric-results",
    "free-source-reliability": "/admin/free-source-reliability",
    "free-source-recovery-runs": "/admin/free-source-recovery-runs",
    "free-source-recovery-actions": "/admin/free-source-recovery-actions",
    "free-source-recovery-executions": "/admin/free-source-recovery-executions",
    "free-source-recovery-health": "/admin/free-source-recovery-health",
    "free-source-admission-profiles": "/admin/free-source-admission-profiles",
    "free-source-admission": "/admin/free-source-admission",
    "vendor-live-gates": "/admin/vendor-live-gates",
    "vendor-readiness": "/admin/vendor-readiness",
    "vendor-readiness-windows": "/admin/vendor-readiness-windows",
    "worker-runs": "/admin/worker-runs",
    "worker-schedules": "/admin/worker-schedules",
    "worker-locks": "/admin/worker-locks",
    "worker-heartbeats": "/admin/worker-heartbeats",
    "worker-schedule-ticks": "/admin/worker-schedule-ticks",
    "deployment-releases": "/admin/deployment-releases",
    "deployment-health": "/admin/deployment-health",
    "deployment-health-checks": "/admin/deployment-health-checks",
    "deployment-events": "/admin/deployment-events",
    "data-products": "/admin/data-products",
    "pricing-plans": "/admin/pricing-plans",
    "pricing-rules": "/admin/pricing-rules",
    "product-subscriptions": "/admin/product-subscriptions",
    "budget-policies": "/admin/budget-policies",
    "budget-usage": "/admin/budget-usage",
    "budget-alerts": "/admin/budget-alerts",
    "invoices": "/admin/invoices",
    "invoice-lines": "/admin/invoice-lines",
    "invoice-events": "/admin/invoice-events",
    "revenue-summary": "/admin/revenue-summary",
    "revenue-reconciliation": "/admin/revenue-reconciliation",
    "revenue-reconciliation-lines": "/admin/revenue-reconciliation-lines",
    "ar-aging": "/admin/ar-aging",
    "customer-health": "/admin/customer-health",
    "payment-batches": "/admin/payment-batches",
    "payments": "/admin/payments",
    "payment-matches": "/admin/payment-matches",
    "revenue-ledger": "/admin/revenue-ledger",
    "fx-rates": "/admin/fx-rates",
    "runtime-logs": "/admin/runtime-logs",
    "runtime-metrics": "/admin/runtime-metrics",
    "runtime-daily-reports": "/admin/runtime-daily-reports",
    "capacity-alerts": "/admin/capacity-alerts",
    "strategy-runs": "/admin/strategy-runs",
    "strategy-signals": "/admin/strategy-signals",
    "strategy-decisions": "/admin/strategy-decisions",
    "strategy-escalations": "/admin/strategy-escalations",
    "usage-daily": "/usage/daily",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Kappa read-only admin resources.")
    parser.add_argument("--resource", choices=sorted(RESOURCE_PATHS), default="overview")
    parser.add_argument("--tenant-code", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--principal-code", default="")
    parser.add_argument("--dataset-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--effective-scope", default="")
    parser.add_argument("--recommended-action", default="")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--execution-code", default="")
    parser.add_argument("--execution-type", default="")
    parser.add_argument("--action-type", default="")
    parser.add_argument("--execution-mode", default="")
    parser.add_argument("--safety-level", default="")
    parser.add_argument("--approval-code", default="")
    parser.add_argument("--executor-code", default="")
    parser.add_argument("--executor-type", default="")
    parser.add_argument("--allowlist-code", default="")
    parser.add_argument("--secret-ref", default="")
    parser.add_argument("--secret-scope", default="")
    parser.add_argument("--secret-kind", default="")
    parser.add_argument("--channel-code", default="")
    parser.add_argument("--channel-type", default="")
    parser.add_argument("--profile-code", default="")
    parser.add_argument("--provider-code", default="")
    parser.add_argument("--readiness-status", default="")
    parser.add_argument("--validation-code", default="")
    parser.add_argument("--validation-type", default="")
    parser.add_argument("--target-secret-ref", default="")
    parser.add_argument("--rotation-code", default="")
    parser.add_argument("--rotation-type", default="")
    parser.add_argument("--next-secret-ref", default="")
    parser.add_argument("--receipt-code", default="")
    parser.add_argument("--message-type", default="")
    parser.add_argument("--endpoint-secret-ref", default="")
    parser.add_argument("--provider-errcode", default="")
    parser.add_argument("--dispatch-code", default="")
    parser.add_argument("--dispatch-type", default="")
    parser.add_argument("--runbook-code", default="")
    parser.add_argument("--failure-class", default="")
    parser.add_argument("--attempt-code", default="")
    parser.add_argument("--rollback-code", default="")
    parser.add_argument("--rollback-type", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--decided-by", default="")
    parser.add_argument("--executed-by", default="")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--api-name", default="")
    parser.add_argument("--task-name", default="")
    parser.add_argument("--trigger-mode", default="")
    parser.add_argument("--schedule-code", default="")
    parser.add_argument("--review-code", default="")
    parser.add_argument("--source-code", default="")
    parser.add_argument("--primary-source-code", default="")
    parser.add_argument("--scheduler-id", default="")
    parser.add_argument("--lock-name", default="")
    parser.add_argument("--owner-id", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--release-code", default="")
    parser.add_argument("--snapshot-code", default="")
    parser.add_argument("--component", default="")
    parser.add_argument("--service-name", default="")
    parser.add_argument("--check-name", default="")
    parser.add_argument("--event-type", default="")
    parser.add_argument("--product-code", default="")
    parser.add_argument("--product-type", default="")
    parser.add_argument("--plan-code", default="")
    parser.add_argument("--subscription-code", default="")
    parser.add_argument("--budget-code", default="")
    parser.add_argument("--invoice-code", default="")
    parser.add_argument("--batch-code", default="")
    parser.add_argument("--transaction-code", default="")
    parser.add_argument("--match-code", default="")
    parser.add_argument("--ledger-code", default="")
    parser.add_argument("--reconciliation-code", default="")
    parser.add_argument("--aging-code", default="")
    parser.add_argument("--health-code", default="")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--report-date", default="")
    parser.add_argument("--cost-center", default="")
    parser.add_argument("--metric-name", default="")
    parser.add_argument("--payment-channel", default="")
    parser.add_argument("--entry-type", default="")
    parser.add_argument("--from-currency", default="")
    parser.add_argument("--to-currency", default="")
    parser.add_argument("--provider", default="")
    parser.add_argument("--source-type", default="")
    parser.add_argument("--account-code", default="")
    parser.add_argument("--direction", default="")
    parser.add_argument("--alert-type", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--policy-code", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--subject-code", default="")
    parser.add_argument("--signal-type", default="")
    parser.add_argument("--decision-type", default="")
    parser.add_argument("--action", default="")
    parser.add_argument("--escalation-type", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--recovery-code", default="")
    parser.add_argument("--monitor-code", default="")
    parser.add_argument("--promotion-code", default="")
    parser.add_argument("--pilot-code", default="")
    parser.add_argument("--fabric-code", default="")
    parser.add_argument("--result-code", default="")
    parser.add_argument("--closure-code", default="")
    parser.add_argument("--probe-code", default="")
    parser.add_argument("--onboarding-code", default="")
    parser.add_argument("--gate-code", default="")
    parser.add_argument("--run-mode", default="")
    parser.add_argument("--config-status", default="")
    parser.add_argument("--profile-check-status", default="")
    parser.add_argument("--profile-update-status", default="")
    parser.add_argument("--contract-status", default="")
    parser.add_argument("--contract-code", default="")
    parser.add_argument("--entitlement-code", default="")
    parser.add_argument("--entitlement-status", default="")
    parser.add_argument("--allowed-role", default="")
    parser.add_argument("--procurement-status", default="")
    parser.add_argument("--procurement-role", default="")
    parser.add_argument("--field-mapping-status", default="")
    parser.add_argument("--endpoint-status", default="")
    parser.add_argument("--onboarding-status", default="")
    parser.add_argument("--promotion-status", default="")
    parser.add_argument("--promotion-role", default="")
    parser.add_argument("--auth-status", default="")
    parser.add_argument("--schema-status", default="")
    parser.add_argument("--preflight-status", default="")
    parser.add_argument("--canary-status", default="")
    parser.add_argument("--gate-status", default="")
    parser.add_argument("--benchmark-status", default="")
    parser.add_argument("--pilot-scope", default="")
    parser.add_argument("--promotion-scope", default="")
    parser.add_argument("--monitor-scope", default="")
    parser.add_argument("--optimization-code", default="")
    parser.add_argument("--execution-dataset-code", default="")
    parser.add_argument("--stage-code", default="")
    parser.add_argument("--approval-status", default="")
    parser.add_argument("--execution-scope", default="")
    parser.add_argument("--rollout-policy", default="")
    parser.add_argument("--policy-status", default="")
    parser.add_argument("--decision-code", default="")
    parser.add_argument("--requested-source-code", default="")
    parser.add_argument("--selected-source-code", default="")
    parser.add_argument("--final-source-code", default="")
    parser.add_argument("--decision-context", default="")
    parser.add_argument("--route-mode", default="")
    parser.add_argument("--decision-status", default="")
    parser.add_argument("--selected-role", default="")
    parser.add_argument("--breaker-code", default="")
    parser.add_argument("--circuit-status", default="")
    parser.add_argument("--circuit-action", default="")
    parser.add_argument("--decision-summary", default="")
    parser.add_argument("--incident-action-code", default="")
    parser.add_argument("--source-signal-type", default="")
    parser.add_argument("--control-code", default="")
    parser.add_argument("--control-stage", default="")
    parser.add_argument("--operation-mode", default="")
    parser.add_argument("--approval-decision", default="")
    parser.add_argument("--operation-decision", default="")
    parser.add_argument("--operation-status", default="")
    parser.add_argument("--command-code", default="")
    parser.add_argument("--command-scope", default="")
    parser.add_argument("--quorum-status", default="")
    parser.add_argument("--item-status", default="")
    parser.add_argument("--signer-code", default="")
    parser.add_argument("--signature-code", default="")
    parser.add_argument("--binding-code", default="")
    parser.add_argument("--role-code", default="")
    parser.add_argument("--callback-code", default="")
    parser.add_argument("--provider-code-filter", default="")
    parser.add_argument("--signature-status", default="")
    parser.add_argument("--governance-status", default="")
    parser.add_argument("--escalation-code", default="")
    parser.add_argument("--reason-code", default="")
    parser.add_argument("--owner-principal-code", default="")
    parser.add_argument("--lock-event-code", default="")
    parser.add_argument("--lock-scope", default="")
    parser.add_argument("--lock-status", default="")
    parser.add_argument("--transition-code", default="")
    parser.add_argument("--transition-status", default="")
    parser.add_argument("--requested-decision", default="")
    parser.add_argument("--audit-hash-code", default="")
    parser.add_argument("--chain-scope", default="")
    parser.add_argument("--entity-type", default="")
    parser.add_argument("--entity-code", default="")
    parser.add_argument("--entry-hash", default="")
    parser.add_argument("--verification-status", default="")
    parser.add_argument("--sla-action-code", default="")
    parser.add_argument("--action-status", default="")
    parser.add_argument("--drill-code", default="")
    parser.add_argument("--drill-type", default="")
    parser.add_argument("--target-control-code", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--notification-policy", default="")
    parser.add_argument("--stress-scope", default="")
    parser.add_argument("--dispatch-status", default="")
    parser.add_argument("--receipt-status", default="")
    parser.add_argument("--attempt-status", default="")
    parser.add_argument("--rollback-status", default="")
    parser.add_argument("--stage-sequence", default="")
    parser.add_argument("--optimization-role", default="")
    parser.add_argument("--optimization-scope", default="")
    parser.add_argument("--stress-code", default="")
    parser.add_argument("--stress-multiplier", default="")
    parser.add_argument("--plan-role", default="")
    parser.add_argument("--apply-mode", default="")
    parser.add_argument("--rollback-mode", default="")
    parser.add_argument("--shadow-status", default="")
    parser.add_argument("--fabric-scope", default="")
    parser.add_argument("--signoff-status", default="")
    parser.add_argument("--coverage-status", default="")
    parser.add_argument("--consistency-status", default="")
    parser.add_argument("--license-status", default="")
    parser.add_argument("--commercial-clearance", default="")
    parser.add_argument("--license-type", default="")
    parser.add_argument("--redistribution-allowed", default="")
    parser.add_argument("--terms-review-status", default="")
    parser.add_argument("--admission-role", default="")
    parser.add_argument("--max-allowed-role", default="")
    parser.add_argument("--freshness-status", default="")
    parser.add_argument("--baseline-source-code", default="")
    parser.add_argument("--recommendation", default="")
    parser.add_argument("--recommended-role", default="")
    parser.add_argument("--risk-level", default="")
    parser.add_argument("--window-days", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    params = _params(args)
    result = dispatch_kappa_endpoint(args.postgres_dsn, RESOURCE_PATHS[args.resource], params)
    if args.json:
        print(json.dumps({"resource": result.resource, "meta": result.meta, "data": result.rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_kappa_report(result))
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "tenant_code",
        "project_code",
        "principal_code",
        "dataset_code",
        "status",
        "decision",
        "effective_scope",
        "recommended_action",
        "action_code",
        "execution_code",
        "execution_type",
        "action_type",
        "execution_mode",
        "safety_level",
        "approval_code",
        "executor_code",
        "executor_type",
        "allowlist_code",
        "secret_ref",
        "secret_scope",
        "secret_kind",
        "channel_code",
        "channel_type",
        "profile_code",
        "provider_code",
        "readiness_status",
        "validation_code",
        "validation_type",
        "target_secret_ref",
        "rotation_code",
        "rotation_type",
        "next_secret_ref",
        "receipt_code",
        "message_type",
        "endpoint_secret_ref",
        "provider_errcode",
        "dispatch_code",
        "dispatch_type",
        "runbook_code",
        "failure_class",
        "attempt_code",
        "rollback_code",
        "rollback_type",
        "requested_by",
        "decided_by",
        "executed_by",
        "trade_date",
        "start_date",
        "end_date",
        "api_name",
        "task_name",
        "trigger_mode",
        "schedule_code",
        "review_code",
        "source_code",
        "primary_source_code",
        "scheduler_id",
        "lock_name",
        "owner_id",
        "environment",
        "release_code",
        "snapshot_code",
        "component",
        "service_name",
        "check_name",
        "event_type",
        "product_code",
        "product_type",
        "plan_code",
        "subscription_code",
        "budget_code",
        "invoice_code",
        "batch_code",
        "transaction_code",
        "match_code",
        "ledger_code",
        "reconciliation_code",
        "aging_code",
        "health_code",
        "as_of_date",
        "report_date",
        "cost_center",
        "metric_name",
        "payment_channel",
        "entry_type",
        "from_currency",
        "to_currency",
        "provider",
        "source_type",
        "account_code",
        "direction",
        "alert_type",
        "severity",
        "policy_code",
        "domain",
        "subject_code",
        "signal_type",
        "decision_type",
        "action",
        "escalation_type",
        "owner",
        "run_code",
        "recovery_code",
        "monitor_code",
        "promotion_code",
        "pilot_code",
        "fabric_code",
        "result_code",
        "closure_code",
        "probe_code",
        "onboarding_code",
        "gate_code",
        "run_mode",
        "config_status",
        "profile_check_status",
        "profile_update_status",
        "contract_status",
        "contract_code",
        "entitlement_code",
        "entitlement_status",
        "allowed_role",
        "procurement_status",
        "procurement_role",
        "field_mapping_status",
        "endpoint_status",
        "onboarding_status",
        "promotion_status",
        "promotion_role",
        "auth_status",
        "schema_status",
        "preflight_status",
        "canary_status",
        "gate_status",
        "benchmark_status",
        "pilot_scope",
        "promotion_scope",
        "monitor_scope",
        "optimization_code",
        "execution_dataset_code",
        "stage_code",
        "approval_status",
        "execution_scope",
        "rollout_policy",
        "policy_status",
        "decision_code",
        "requested_source_code",
        "selected_source_code",
        "final_source_code",
        "decision_context",
        "route_mode",
        "decision_status",
        "selected_role",
        "breaker_code",
        "circuit_status",
        "circuit_action",
        "decision_summary",
        "incident_action_code",
        "source_signal_type",
        "control_code",
        "control_stage",
        "operation_mode",
        "approval_decision",
        "operation_decision",
        "operation_status",
        "command_code",
        "command_scope",
        "quorum_status",
        "item_status",
        "signer_code",
        "signature_code",
        "binding_code",
        "role_code",
        "callback_code",
        "provider_code_filter",
        "signature_status",
        "governance_status",
        "escalation_code",
        "reason_code",
        "owner_principal_code",
        "lock_event_code",
        "lock_scope",
        "lock_status",
        "transition_code",
        "transition_status",
        "requested_decision",
        "audit_hash_code",
        "chain_scope",
        "entity_type",
        "entity_code",
        "entry_hash",
        "verification_status",
        "sla_action_code",
        "action_status",
        "drill_code",
        "drill_type",
        "target_control_code",
        "idempotency_key",
        "notification_policy",
        "stress_scope",
        "dispatch_status",
        "receipt_status",
        "attempt_status",
        "rollback_status",
        "stage_sequence",
        "optimization_role",
        "optimization_scope",
        "stress_code",
        "stress_multiplier",
        "plan_role",
        "apply_mode",
        "rollback_mode",
        "shadow_status",
        "fabric_scope",
        "signoff_status",
        "coverage_status",
        "consistency_status",
        "license_status",
        "commercial_clearance",
        "license_type",
        "redistribution_allowed",
        "terms_review_status",
        "admission_role",
        "max_allowed_role",
        "freshness_status",
        "baseline_source_code",
        "recommendation",
        "recommended_role",
        "risk_level",
        "window_days",
    ):
        value = getattr(args, name)
        if value:
            params["provider_code" if name == "provider_code_filter" else name] = [value]
    return params


if __name__ == "__main__":
    raise SystemExit(main())
