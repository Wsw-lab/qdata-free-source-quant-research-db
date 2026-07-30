import unittest

from qdata.exceptions import QDataValidationError
from qdata.kappa import (
    KappaResult,
    _limit_offset,
    format_kappa_report,
    is_kappa_path,
    render_kappa_console,
)


class KappaTest(unittest.TestCase):
    def test_admin_path_registry_includes_usage_and_console(self) -> None:
        self.assertTrue(is_kappa_path("/admin/overview"))
        self.assertTrue(is_kappa_path("/admin/worker-runs"))
        self.assertTrue(is_kappa_path("/admin/worker-schedules"))
        self.assertTrue(is_kappa_path("/admin/worker-heartbeats"))
        self.assertTrue(is_kappa_path("/admin/worker-schedule-ticks"))
        self.assertTrue(is_kappa_path("/admin/deployment-health"))
        self.assertTrue(is_kappa_path("/admin/deployment-releases"))
        self.assertTrue(is_kappa_path("/admin/data-products"))
        self.assertTrue(is_kappa_path("/admin/pricing-plans"))
        self.assertTrue(is_kappa_path("/admin/budget-policies"))
        self.assertTrue(is_kappa_path("/admin/budget-alerts"))
        self.assertTrue(is_kappa_path("/admin/access-decisions"))
        self.assertTrue(is_kappa_path("/admin/project-governance"))
        self.assertTrue(is_kappa_path("/admin/governance-actions"))
        self.assertTrue(is_kappa_path("/admin/automation-runs"))
        self.assertTrue(is_kappa_path("/admin/automation-actions"))
        self.assertTrue(is_kappa_path("/admin/automation-approvals"))
        self.assertTrue(is_kappa_path("/admin/automation-executors"))
        self.assertTrue(is_kappa_path("/admin/automation-allowlists"))
        self.assertTrue(is_kappa_path("/admin/automation-secrets"))
        self.assertTrue(is_kappa_path("/admin/automation-channels"))
        self.assertTrue(is_kappa_path("/admin/automation-dispatches"))
        self.assertTrue(is_kappa_path("/admin/automation-runbooks"))
        self.assertTrue(is_kappa_path("/admin/automation-channel-profiles"))
        self.assertTrue(is_kappa_path("/admin/automation-channel-validations"))
        self.assertTrue(is_kappa_path("/admin/automation-secret-rotations"))
        self.assertTrue(is_kappa_path("/admin/automation-live-receipts"))
        self.assertTrue(is_kappa_path("/admin/automation-attempts"))
        self.assertTrue(is_kappa_path("/admin/automation-rollbacks"))
        self.assertTrue(is_kappa_path("/admin/vendor-onboarding-runs"))
        self.assertTrue(is_kappa_path("/admin/vendor-onboarding-results"))
        self.assertTrue(is_kappa_path("/admin/vendor-live-closures"))
        self.assertTrue(is_kappa_path("/admin/vendor-live-probes"))
        self.assertTrue(is_kappa_path("/admin/vendor-live-pilots"))
        self.assertTrue(is_kappa_path("/admin/vendor-live-pilot-results"))
        self.assertTrue(is_kappa_path("/admin/vendor-contract-profiles"))
        self.assertTrue(is_kappa_path("/admin/vendor-contract-entitlements"))
        self.assertTrue(is_kappa_path("/admin/vendor-procurement-readiness"))
        self.assertTrue(is_kappa_path("/admin/vendor-primary-promotions"))
        self.assertTrue(is_kappa_path("/admin/vendor-primary-promotion-results"))
        self.assertTrue(is_kappa_path("/admin/vendor-post-promotion-monitors"))
        self.assertTrue(is_kappa_path("/admin/vendor-post-promotion-results"))
        self.assertTrue(is_kappa_path("/admin/vendor-primary-stability"))
        self.assertTrue(is_kappa_path("/admin/vendor-primary-stability-datasets"))
        self.assertTrue(is_kappa_path("/admin/vendor-cost-optimizations"))
        self.assertTrue(is_kappa_path("/admin/vendor-route-weight-plans"))
        self.assertTrue(is_kappa_path("/admin/vendor-budget-stress"))
        self.assertTrue(is_kappa_path("/admin/vendor-route-executions"))
        self.assertTrue(is_kappa_path("/admin/vendor-route-execution-datasets"))
        self.assertTrue(is_kappa_path("/admin/vendor-route-rollout-stages"))
        self.assertTrue(is_kappa_path("/admin/source-route-weight-policies"))
        self.assertTrue(is_kappa_path("/admin/source-route-decisions"))
        self.assertTrue(is_kappa_path("/admin/source-route-health"))
        self.assertTrue(is_kappa_path("/admin/source-route-circuit-breakers"))
        self.assertTrue(is_kappa_path("/admin/source-route-recovery-probes"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-actions"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-controls"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-control-health"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-operation-batches"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-operation-items"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-commands"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-command-items"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-signatures"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-role-bindings"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-policies"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-callbacks"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-escalations"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-lock-events"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-state-transitions"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-audit-chain"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-sla-actions"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-recovery-drills"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-release-preflights"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-secret-rotations"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-concurrency-tests"))
        self.assertTrue(is_kappa_path("/admin/source-route-incident-approval-audit-exports"))
        self.assertTrue(is_kappa_path("/admin/free-source-fabric-runs"))
        self.assertTrue(is_kappa_path("/admin/free-source-fabric-results"))
        self.assertTrue(is_kappa_path("/admin/free-source-reliability"))
        self.assertTrue(is_kappa_path("/admin/free-source-recovery-runs"))
        self.assertTrue(is_kappa_path("/admin/free-source-recovery-actions"))
        self.assertTrue(is_kappa_path("/admin/free-source-recovery-executions"))
        self.assertTrue(is_kappa_path("/admin/free-source-recovery-health"))
        self.assertTrue(is_kappa_path("/admin/free-source-admission-profiles"))
        self.assertTrue(is_kappa_path("/admin/free-source-admission"))
        self.assertTrue(is_kappa_path("/admin/vendor-live-gates"))
        self.assertTrue(is_kappa_path("/admin/vendor-readiness"))
        self.assertTrue(is_kappa_path("/admin/vendor-readiness-windows"))
        self.assertTrue(is_kappa_path("/admin/invoices"))
        self.assertTrue(is_kappa_path("/admin/revenue-summary"))
        self.assertTrue(is_kappa_path("/admin/revenue-reconciliation"))
        self.assertTrue(is_kappa_path("/admin/revenue-reconciliation-lines"))
        self.assertTrue(is_kappa_path("/admin/ar-aging"))
        self.assertTrue(is_kappa_path("/admin/customer-health"))
        self.assertTrue(is_kappa_path("/admin/payment-batches"))
        self.assertTrue(is_kappa_path("/admin/payments"))
        self.assertTrue(is_kappa_path("/admin/payment-matches"))
        self.assertTrue(is_kappa_path("/admin/revenue-ledger"))
        self.assertTrue(is_kappa_path("/admin/fx-rates"))
        self.assertTrue(is_kappa_path("/admin/runtime-logs"))
        self.assertTrue(is_kappa_path("/admin/runtime-metrics"))
        self.assertTrue(is_kappa_path("/admin/runtime-daily-reports"))
        self.assertTrue(is_kappa_path("/admin/capacity-alerts"))
        self.assertTrue(is_kappa_path("/admin/strategy-runs"))
        self.assertTrue(is_kappa_path("/admin/strategy-signals"))
        self.assertTrue(is_kappa_path("/admin/strategy-decisions"))
        self.assertTrue(is_kappa_path("/admin/strategy-escalations"))
        self.assertTrue(is_kappa_path("/usage/daily"))
        self.assertTrue(is_kappa_path("/admin/console"))
        self.assertFalse(is_kappa_path("/price"))

    def test_limit_offset_validation(self) -> None:
        self.assertEqual(_limit_offset({"limit": ["50"], "offset": ["10"]}), (50, 10))
        with self.assertRaises(QDataValidationError):
            _limit_offset({"limit": ["0"]})
        with self.assertRaises(QDataValidationError):
            _limit_offset({"offset": ["-1"]})

    def test_kappa_report_formats_rows(self) -> None:
        report = format_kappa_report(
            KappaResult(
                "usage.daily",
                [{"project_code": "quant-research", "api_name": "price", "request_count": 4}],
                {"row_count": 1},
            )
        )

        self.assertIn("kappa resource=usage.daily rows=1", report)
        self.assertIn("project_code=quant-research", report)
        self.assertIn("api_name=price", report)

        overview_report = format_kappa_report(
            KappaResult(
                "overview",
                [
                    {
                        "active_tenant_count": 1,
                        "usage_7d_request_count": 117,
                        "worker_7d_run_count": 7,
                        "active_worker_schedule_count": 3,
                        "latest_scheduler_tick_status": "success",
                        "latest_deployment_health_status": "success",
                        "latest_deployment_release_status": "healthy",
                        "active_product_count": 1,
                        "active_budget_policy_count": 1,
                        "budget_open_alert_count": 1,
                        "vendor_readiness_ready_count": 1,
                        "vendor_readiness_watch_count": 0,
                        "vendor_readiness_rejected_count": 0,
                        "latest_vendor_readiness_status": "ready",
                        "vendor_24h_live_gate_count": 1,
                        "vendor_24h_live_gate_blocked_count": 1,
                        "vendor_24h_live_gate_executed_count": 0,
                        "latest_vendor_live_gate_status": "blocked",
                        "vendor_24h_onboarding_count": 1,
                        "vendor_24h_onboarding_blocked_count": 1,
                        "latest_vendor_onboarding_status": "blocked",
                        "vendor_24h_live_closure_count": 1,
                        "vendor_24h_live_closure_blocked_count": 1,
                        "latest_vendor_live_closure_status": "blocked",
                        "vendor_24h_live_pilot_count": 1,
                        "vendor_24h_live_pilot_blocked_count": 1,
                        "latest_vendor_live_pilot_status": "blocked",
                        "vendor_contract_profile_count": 1,
                        "vendor_active_contract_count": 0,
                        "vendor_active_entitlement_count": 0,
                        "vendor_24h_procurement_readiness_count": 7,
                        "vendor_24h_procurement_ready_count": 0,
                        "vendor_24h_procurement_review_required_count": 7,
                        "vendor_24h_procurement_blocked_count": 0,
                        "latest_vendor_procurement_status": "review_required",
                        "vendor_procurement_primary_candidate_count": 0,
                        "vendor_24h_primary_promotion_count": 1,
                        "vendor_24h_primary_promotion_approved_count": 0,
                        "vendor_24h_primary_promotion_blocked_count": 7,
                        "vendor_24h_primary_promotion_applied_count": 0,
                        "latest_vendor_primary_promotion_status": "blocked",
                        "vendor_primary_promotion_routing_allowed_count": 0,
                        "vendor_24h_post_promotion_monitor_count": 1,
                        "vendor_24h_post_promotion_healthy_count": 0,
                        "vendor_24h_post_promotion_rollback_recommended_count": 0,
                        "vendor_24h_post_promotion_rolled_back_count": 0,
                        "vendor_24h_post_promotion_no_applied_count": 7,
                        "latest_vendor_post_promotion_status": "no_applied_promotion",
                        "vendor_post_promotion_rollback_allowed_count": 0,
                        "vendor_24h_primary_stability_count": 1,
                        "vendor_24h_primary_stability_healthy_count": 0,
                        "vendor_24h_primary_stability_warning_count": 0,
                        "vendor_24h_primary_stability_critical_count": 0,
                        "vendor_24h_primary_stability_no_primary_count": 1,
                        "latest_vendor_primary_stability_status": "no_primary_promotion",
                        "latest_vendor_primary_stability_role": "watch",
                        "vendor_primary_stability_primary_dataset_count": 0,
                        "vendor_primary_stability_score": "0.0000",
                        "vendor_primary_stability_cost_units": "0.000000",
                        "vendor_primary_stability_scheduler_lag_minutes": 0,
                        "vendor_primary_stability_backlog_count": 0,
                        "vendor_24h_cost_optimization_count": 1,
                        "vendor_24h_cost_optimized_count": 0,
                        "vendor_24h_cost_over_budget_count": 0,
                        "vendor_24h_cost_quota_risk_count": 0,
                        "vendor_24h_cost_no_primary_count": 1,
                        "latest_vendor_cost_optimization_status": "no_primary_promotion",
                        "latest_vendor_cost_optimization_role": "watch",
                        "vendor_cost_primary_weight_pct": "0.0000",
                        "vendor_cost_backup_weight_pct": "100.0000",
                        "vendor_cost_free_source_weight_pct": "0.0000",
                        "vendor_cost_budget_usage_pct": "0.0000",
                        "vendor_cost_monthly_quota_usage_pct": "0.0000",
                        "vendor_cost_optimization_score": "0.0000",
                        "vendor_24h_route_execution_count": 1,
                        "vendor_24h_route_pending_approval_count": 7,
                        "vendor_24h_route_staged_count": 0,
                        "vendor_24h_route_applied_count": 0,
                        "vendor_24h_route_blocked_count": 7,
                        "latest_vendor_route_execution_status": "pending_approval",
                        "latest_vendor_route_execution_approval_status": "pending",
                        "vendor_route_applied_primary_weight_pct": "0.0000",
                        "vendor_route_current_stage_sequence": 0,
                        "active_source_route_weight_policy_count": 0,
                        "source_route_24h_decision_count": 1,
                        "source_route_24h_fallback_count": 1,
                        "latest_source_route_decision_status": "fallback_success",
                        "latest_source_route_final_source_code": "csv",
                        "source_route_24h_health_count": 2,
                        "source_route_24h_unhealthy_count": 1,
                        "latest_source_route_health_status": "degraded",
                        "source_route_open_circuit_count": 1,
                        "source_route_24h_recovery_probe_count": 1,
                        "source_route_24h_recovered_probe_count": 1,
                        "source_route_24h_incident_action_count": 2,
                        "source_route_pending_incident_action_count": 1,
                        "latest_source_route_incident_action_status": "approval_required",
                        "source_route_24h_incident_control_count": 1,
                        "source_route_pending_incident_control_count": 1,
                        "latest_source_route_incident_control_stage": "rollback_planned",
                        "source_route_latest_control_health_status": "warning",
                        "source_route_control_health_issue_count": 3,
                        "source_route_control_health_overdue_approval_count": 0,
                        "source_route_control_health_blocked_receipt_count": 1,
                        "source_route_latest_operation_status": "warning",
                        "source_route_operation_queue_count": 3,
                        "source_route_operation_suppressed_notification_count": 2,
                        "source_route_operation_stress_scenario_count": 20,
                        "source_route_latest_approval_command_status": "pending_quorum",
                        "source_route_approval_pending_quorum_count": 1,
                        "source_route_approval_24h_applied_count": 1,
                        "source_route_approval_24h_signature_count": 2,
                        "source_route_approval_active_role_binding_count": 2,
                        "source_route_approval_active_policy_count": 1,
                        "source_route_latest_approval_callback_status": "pending_quorum",
                        "source_route_approval_24h_verified_callback_count": 2,
                        "source_route_approval_24h_replay_rejected_count": 1,
                        "source_route_approval_24h_denied_callback_count": 1,
                        "source_route_approval_open_escalation_count": 1,
                        "source_route_approval_24h_lock_event_count": 3,
                        "source_route_approval_24h_lock_busy_count": 1,
                        "source_route_approval_24h_state_transition_count": 3,
                        "source_route_approval_24h_state_blocked_count": 1,
                        "source_route_approval_audit_hash_count": 5,
                        "source_route_approval_broken_audit_hash_count": 0,
                        "source_route_approval_planned_sla_action_count": 1,
                        "source_route_latest_approval_recovery_drill_status": "success",
                        "source_route_approval_24h_successful_recovery_drill_count": 1,
                        "free_source_24h_fabric_count": 1,
                        "free_source_24h_fabric_blocked_count": 0,
                        "latest_free_source_fabric_status": "success",
                        "free_source_24h_reliability_count": 2,
                        "free_source_24h_reliability_ready_count": 1,
                        "free_source_24h_reliability_degraded_count": 1,
                        "free_source_24h_reliability_rejected_count": 0,
                        "latest_free_source_reliability_status": "degraded",
                        "free_source_24h_recovery_count": 1,
                        "free_source_24h_recovery_action_count": 3,
                        "free_source_24h_recovery_alert_count": 2,
                        "latest_free_source_recovery_status": "warning",
                        "free_source_24h_recovery_execution_count": 1,
                        "free_source_24h_recovered_count": 1,
                        "free_source_24h_recovery_failed_count": 0,
                        "latest_free_source_recovery_execution_status": "recovered",
                        "free_source_24h_recovery_health_count": 1,
                        "latest_free_source_recovery_health_status": "warning",
                        "free_source_recovery_overdue_approval_count": 0,
                        "free_source_recovery_backlog_count": 3,
                        "free_source_24h_admission_count": 4,
                        "free_source_24h_admission_approved_count": 0,
                        "free_source_24h_admission_conditional_count": 1,
                        "free_source_24h_admission_review_required_count": 2,
                        "free_source_24h_admission_blocked_count": 1,
                        "free_source_24h_admission_no_data_count": 0,
                        "latest_free_source_admission_status": "review_required",
                        "free_source_primary_candidate_count": 0,
                        "invoice_month_count": 1,
                        "invoice_month_total_amount": "0.16002800",
                        "invoice_month_paid_amount": "0.00000000",
                        "invoice_month_outstanding_amount": "0.16002800",
                        "overdue_invoice_count": 0,
                        "revenue_reconciliation_mismatch_count": 0,
                        "latest_reconciliation_status": "matched",
                        "latest_ar_outstanding_amount": "0.00000000",
                        "customer_health_active_count": 1,
                        "customer_health_risk_count": 0,
                        "payment_month_received_amount": "100.00000000",
                        "payment_month_matched_amount": "100.00000000",
                        "unmatched_payment_count": 0,
                        "latest_payment_batch_status": "matched",
                        "revenue_ledger_month_credit_amount": "100.00000000",
                        "runtime_24h_error_log_count": 0,
                        "runtime_metric_warning_count": 1,
                        "runtime_metric_critical_count": 0,
                        "open_capacity_alert_count": 1,
                        "latest_runtime_report_status": "warning",
                        "latest_strategy_status": "warning",
                        "latest_strategy_severity": "high",
                        "strategy_24h_action_decision_count": 3,
                        "open_strategy_escalation_count": 2,
                        "access_denied_24h_count": 1,
                        "project_governance_warning_count": 1,
                        "project_governance_critical_count": 0,
                        "open_governance_action_count": 1,
                        "automation_24h_run_count": 1,
                        "automation_24h_action_count": 3,
                        "automation_approval_required_count": 1,
                        "automation_24h_failed_count": 0,
                        "automation_pending_approval_count": 1,
                        "automation_retry_scheduled_count": 0,
                        "automation_rollback_required_count": 0,
                        "automation_active_sandbox_executor_count": 2,
                        "automation_active_allowlist_count": 2,
                        "automation_active_secret_ref_count": 1,
                        "automation_active_channel_count": 2,
                        "automation_24h_dispatch_count": 3,
                        "automation_dead_letter_count": 0,
                        "latest_automation_dispatch_status": "recovered",
                        "automation_active_profile_count": 3,
                        "automation_ready_profile_count": 1,
                        "automation_24h_validation_count": 2,
                        "latest_automation_validation_status": "success",
                        "automation_applied_rotation_count": 1,
                        "latest_automation_rotation_status": "applied",
                        "automation_24h_live_receipt_count": 1,
                        "automation_24h_wecom_success_count": 1,
                        "latest_automation_live_receipt_status": "success",
                        "latest_automation_attempt_status": "approval_required",
                        "latest_automation_status": "warning",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("latest_deployment_health_status=success", overview_report)
        self.assertIn("latest_deployment_release_status=healthy", overview_report)
        self.assertIn("active_product_count=1", overview_report)
        self.assertIn("budget_open_alert_count=1", overview_report)
        self.assertIn("vendor_readiness_ready_count=1", overview_report)
        self.assertIn("vendor_24h_live_gate_count=1", overview_report)
        self.assertIn("latest_vendor_live_gate_status=blocked", overview_report)
        self.assertIn("vendor_24h_onboarding_count=1", overview_report)
        self.assertIn("latest_vendor_onboarding_status=blocked", overview_report)
        self.assertIn("vendor_24h_live_closure_count=1", overview_report)
        self.assertIn("latest_vendor_live_closure_status=blocked", overview_report)
        self.assertIn("vendor_24h_live_pilot_count=1", overview_report)
        self.assertIn("latest_vendor_live_pilot_status=blocked", overview_report)
        self.assertIn("vendor_contract_profile_count=1", overview_report)
        self.assertIn("vendor_24h_procurement_readiness_count=7", overview_report)
        self.assertIn("latest_vendor_procurement_status=review_required", overview_report)
        self.assertIn("vendor_procurement_primary_candidate_count=0", overview_report)
        self.assertIn("vendor_24h_primary_promotion_count=1", overview_report)
        self.assertIn("vendor_24h_primary_promotion_blocked_count=7", overview_report)
        self.assertIn("latest_vendor_primary_promotion_status=blocked", overview_report)
        self.assertIn("vendor_24h_post_promotion_monitor_count=1", overview_report)
        self.assertIn("vendor_24h_post_promotion_no_applied_count=7", overview_report)
        self.assertIn("latest_vendor_post_promotion_status=no_applied_promotion", overview_report)
        self.assertIn("vendor_24h_primary_stability_count=1", overview_report)
        self.assertIn("latest_vendor_primary_stability_status=no_primary_promotion", overview_report)
        self.assertIn("vendor_primary_stability_scheduler_lag_minutes=0", overview_report)
        self.assertIn("vendor_24h_cost_optimization_count=1", overview_report)
        self.assertIn("latest_vendor_cost_optimization_status=no_primary_promotion", overview_report)
        self.assertIn("vendor_cost_primary_weight_pct=0.0000", overview_report)
        self.assertIn("vendor_24h_route_execution_count=1", overview_report)
        self.assertIn("latest_vendor_route_execution_status=pending_approval", overview_report)
        self.assertIn("latest_vendor_route_execution_approval_status=pending", overview_report)
        self.assertIn("vendor_route_applied_primary_weight_pct=0.0000", overview_report)
        self.assertIn("active_source_route_weight_policy_count=0", overview_report)
        self.assertIn("source_route_24h_decision_count=1", overview_report)
        self.assertIn("latest_source_route_final_source_code=csv", overview_report)
        self.assertIn("source_route_24h_health_count=2", overview_report)
        self.assertIn("latest_source_route_health_status=degraded", overview_report)
        self.assertIn("source_route_open_circuit_count=1", overview_report)
        self.assertIn("source_route_24h_recovery_probe_count=1", overview_report)
        self.assertIn("source_route_24h_incident_action_count=2", overview_report)
        self.assertIn("source_route_pending_incident_action_count=1", overview_report)
        self.assertIn("latest_source_route_incident_action_status=approval_required", overview_report)
        self.assertIn("source_route_24h_incident_control_count=1", overview_report)
        self.assertIn("source_route_pending_incident_control_count=1", overview_report)
        self.assertIn("latest_source_route_incident_control_stage=rollback_planned", overview_report)
        self.assertIn("source_route_latest_control_health_status=warning", overview_report)
        self.assertIn("source_route_control_health_issue_count=3", overview_report)
        self.assertIn("source_route_control_health_blocked_receipt_count=1", overview_report)
        self.assertIn("source_route_latest_operation_status=warning", overview_report)
        self.assertIn("source_route_operation_queue_count=3", overview_report)
        self.assertIn("source_route_operation_suppressed_notification_count=2", overview_report)
        self.assertIn("source_route_operation_stress_scenario_count=20", overview_report)
        self.assertIn("source_route_latest_approval_command_status=pending_quorum", overview_report)
        self.assertIn("source_route_approval_pending_quorum_count=1", overview_report)
        self.assertIn("source_route_approval_24h_applied_count=1", overview_report)
        self.assertIn("source_route_approval_24h_signature_count=2", overview_report)
        self.assertIn("source_route_approval_active_role_binding_count=2", overview_report)
        self.assertIn("source_route_approval_active_policy_count=1", overview_report)
        self.assertIn("source_route_latest_approval_callback_status=pending_quorum", overview_report)
        self.assertIn("source_route_approval_24h_verified_callback_count=2", overview_report)
        self.assertIn("source_route_approval_24h_replay_rejected_count=1", overview_report)
        self.assertIn("source_route_approval_24h_denied_callback_count=1", overview_report)
        self.assertIn("source_route_approval_open_escalation_count=1", overview_report)
        self.assertIn("source_route_approval_24h_lock_event_count=3", overview_report)
        self.assertIn("source_route_approval_24h_lock_busy_count=1", overview_report)
        self.assertIn("source_route_approval_24h_state_transition_count=3", overview_report)
        self.assertIn("source_route_approval_24h_state_blocked_count=1", overview_report)
        self.assertIn("source_route_approval_audit_hash_count=5", overview_report)
        self.assertIn("source_route_approval_broken_audit_hash_count=0", overview_report)
        self.assertIn("source_route_approval_planned_sla_action_count=1", overview_report)
        self.assertIn("source_route_latest_approval_recovery_drill_status=success", overview_report)
        self.assertIn("source_route_approval_24h_successful_recovery_drill_count=1", overview_report)
        controls_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-controls",
                [{"control_code": "omega5-route-control-demo", "incident_action_code": "psi5-route-incident-demo", "action_code": "psi-action-route-demo", "control_stage": "rollback_planned", "approval_status": "pending"}],
                {"row_count": 1},
            )
        )
        self.assertIn("control_code=omega5-route-control-demo", controls_report)
        self.assertIn("approval_status=pending", controls_report)
        control_health_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-control-health",
                [
                    {
                        "snapshot_code": "alpha6-route-control-health-demo",
                        "status": "warning",
                        "control_count": 3,
                        "pending_control_count": 1,
                        "approval_pending_count": 1,
                        "notification_blocked_count": 1,
                        "blocked_receipt_rate": "1.0000",
                        "health_issues": ["route_control_wecom_blocked"],
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=alpha6-route-control-health-demo", control_health_report)
        self.assertIn("pending_control_count=1", control_health_report)
        self.assertIn("health_issues=['route_control_wecom_blocked']", control_health_report)
        operation_batch_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-operation-batches",
                [
                    {
                        "batch_code": "beta6-route-ops-demo",
                        "status": "warning",
                        "approval_decision": "hold",
                        "candidate_count": 3,
                        "eligible_count": 3,
                        "suppressed_notification_count": 2,
                        "stress_scenario_count": 20,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("batch_code=beta6-route-ops-demo", operation_batch_report)
        self.assertIn("stress_scenario_count=20", operation_batch_report)
        operation_item_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-operation-items",
                [
                    {
                        "batch_code": "beta6-route-ops-demo",
                        "control_code": "omega5-route-control-demo",
                        "approval_code": "omega-approval-demo",
                        "operation_decision": "approve",
                        "operation_status": "applied",
                        "approval_status_after": "approved",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("control_code=omega5-route-control-demo", operation_item_report)
        self.assertIn("approval_status_after=approved", operation_item_report)
        approval_command_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-commands",
                [
                    {
                        "command_code": "gamma6-route-approval-demo",
                        "status": "pending_quorum",
                        "decision": "approve",
                        "principal_code": "approver-a",
                        "required_approvals": 2,
                        "approval_count": 1,
                        "quorum_status": "pending",
                        "target_count": 1,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("command_code=gamma6-route-approval-demo", approval_command_report)
        self.assertIn("quorum_status=pending", approval_command_report)
        approval_item_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-command-items",
                [
                    {
                        "command_code": "gamma6-route-approval-demo",
                        "control_code": "omega5-route-control-demo",
                        "approval_code": "omega-approval-demo",
                        "decision": "approve",
                        "item_status": "pending_quorum",
                        "signer_code": "approver-a",
                        "signature_count": 1,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("item_status=pending_quorum", approval_item_report)
        approval_signature_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-signatures",
                [
                    {
                        "signature_code": "gamma6-sig-demo",
                        "command_code": "gamma6-route-approval-demo",
                        "control_code": "omega5-route-control-demo",
                        "decision": "approve",
                        "signer_code": "approver-a",
                        "status": "active",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("signature_code=gamma6-sig-demo", approval_signature_report)
        self.assertIn("signer_code=approver-a", approval_signature_report)
        role_binding_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-role-bindings",
                [
                    {
                        "binding_code": "delta6-role-demo",
                        "principal_code": "approver-a",
                        "role_code": "route_approver",
                        "dataset_code": "*",
                        "source_code": "*",
                        "safety_level": "*",
                        "status": "active",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("binding_code=delta6-role-demo", role_binding_report)
        self.assertIn("role_code=route_approver", role_binding_report)
        policy_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-policies",
                [
                    {
                        "policy_code": "delta6-default-route-approval-policy",
                        "dataset_code": "*",
                        "source_code": "*",
                        "safety_level": "*",
                        "status": "active",
                        "min_approvals": 2,
                        "timeout_minutes": 240,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("policy_code=delta6-default-route-approval-policy", policy_report)
        self.assertIn("min_approvals=2", policy_report)
        callback_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-callbacks",
                [
                    {
                        "callback_code": "delta6-callback-demo",
                        "provider_code": "wecom",
                        "signature_status": "verified",
                        "governance_status": "pending_quorum",
                        "decision": "approve",
                        "signer_code": "approver-a",
                        "control_code": "omega5-route-control-demo",
                        "replay_count": 1,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("callback_code=delta6-callback-demo", callback_report)
        self.assertIn("governance_status=pending_quorum", callback_report)
        escalation_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-escalations",
                [
                    {
                        "escalation_code": "delta6-escalation-demo",
                        "reason_code": "approval_timeout",
                        "status": "open",
                        "severity": "high",
                        "owner_principal_code": "platform-ops",
                        "control_code": "omega5-route-control-demo",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("escalation_code=delta6-escalation-demo", escalation_report)
        self.assertIn("reason_code=approval_timeout", escalation_report)
        lock_event_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-lock-events",
                [
                    {
                        "lock_event_code": "epsilon6-lock-demo",
                        "lock_status": "released",
                        "lock_scope": "route-approval:control_code:omega5-route-control-demo",
                        "provider_code": "wecom",
                        "control_code": "omega5-route-control-demo",
                        "callback_code": "delta6-callback-demo",
                        "command_code": "gamma6-route-approval-demo",
                        "held_ms": 12,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("lock_event_code=epsilon6-lock-demo", lock_event_report)
        self.assertIn("lock_status=released", lock_event_report)
        state_transition_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-state-transitions",
                [
                    {
                        "transition_code": "epsilon6-transition-demo",
                        "transition_status": "blocked",
                        "reason_code": "invalid_terminal_state",
                        "control_code": "omega5-route-control-demo",
                        "requested_decision": "reject",
                        "approval_status_before": "approved",
                        "approval_status_after": "approved",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("transition_code=epsilon6-transition-demo", state_transition_report)
        self.assertIn("reason_code=invalid_terminal_state", state_transition_report)
        audit_chain_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-audit-chain",
                [
                    {
                        "audit_hash_code": "epsilon6-audit-demo",
                        "chain_scope": "route-approval:control_code:omega5-route-control-demo",
                        "sequence_no": 1,
                        "entity_type": "callback",
                        "entity_code": "delta6-callback-demo",
                        "entry_hash": "abc123",
                        "verification_status": "chained",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("audit_hash_code=epsilon6-audit-demo", audit_chain_report)
        self.assertIn("verification_status=chained", audit_chain_report)
        sla_action_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-sla-actions",
                [
                    {
                        "sla_action_code": "epsilon6-sla-demo",
                        "action_status": "planned",
                        "action_type": "escalate_risk_admin",
                        "reason_code": "approval_timeout",
                        "owner_principal_code": "platform-ops",
                        "control_code": "omega5-route-control-demo",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("sla_action_code=epsilon6-sla-demo", sla_action_report)
        self.assertIn("action_type=escalate_risk_admin", sla_action_report)
        recovery_drill_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-recovery-drills",
                [
                    {
                        "drill_code": "epsilon6-drill-demo",
                        "drill_type": "full",
                        "status": "success",
                        "check_count": 4,
                        "passed_count": 4,
                        "failed_count": 0,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("drill_code=epsilon6-drill-demo", recovery_drill_report)
        self.assertIn("status=success", recovery_drill_report)
        release_preflight_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-release-preflights",
                [
                    {
                        "preflight_code": "zeta6-preflight-demo",
                        "environment": "local",
                        "status": "success",
                        "release_version": "zeta6-local",
                        "check_count": 5,
                        "failed_count": 0,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("preflight_code=zeta6-preflight-demo", release_preflight_report)
        secret_rotation_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-secret-rotations",
                [
                    {
                        "rotation_code": "zeta6-rotation-demo",
                        "environment": "local",
                        "rotation_phase": "dual_accept",
                        "status": "success",
                        "verified_secret_label": "next",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("verified_secret_label=next", secret_rotation_report)
        concurrency_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-concurrency-tests",
                [
                    {
                        "test_code": "zeta6-concurrency-demo",
                        "status": "success",
                        "target_scope": "route-approval:control_code:omega5-route-control-demo",
                        "callback_count": 8,
                        "success_count": 1,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("test_code=zeta6-concurrency-demo", concurrency_report)
        audit_export_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-approval-audit-exports",
                [
                    {
                        "export_code": "zeta6-export-demo",
                        "status": "success",
                        "chain_scope": "route-approval:control_code:omega5-route-control-demo",
                        "included_entity_count": 12,
                        "package_hash": "abc123",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("export_code=zeta6-export-demo", audit_export_report)
        self.assertIn("free_source_24h_fabric_count=1", overview_report)
        self.assertIn("latest_free_source_fabric_status=success", overview_report)
        self.assertIn("free_source_24h_reliability_count=2", overview_report)
        self.assertIn("latest_free_source_reliability_status=degraded", overview_report)
        self.assertIn("free_source_24h_recovery_count=1", overview_report)
        self.assertIn("latest_free_source_recovery_status=warning", overview_report)
        self.assertIn("free_source_24h_recovery_execution_count=1", overview_report)
        self.assertIn("latest_free_source_recovery_execution_status=recovered", overview_report)
        self.assertIn("free_source_24h_recovery_health_count=1", overview_report)
        self.assertIn("latest_free_source_recovery_health_status=warning", overview_report)
        self.assertIn("free_source_recovery_backlog_count=3", overview_report)
        self.assertIn("free_source_24h_admission_count=4", overview_report)
        self.assertIn("free_source_24h_admission_review_required_count=2", overview_report)
        self.assertIn("latest_free_source_admission_status=review_required", overview_report)
        self.assertIn("free_source_primary_candidate_count=0", overview_report)
        self.assertIn("invoice_month_total_amount=0.16002800", overview_report)
        self.assertIn("latest_reconciliation_status=matched", overview_report)
        self.assertIn("customer_health_active_count=1", overview_report)
        self.assertIn("payment_month_received_amount=100.00000000", overview_report)
        self.assertIn("latest_payment_batch_status=matched", overview_report)
        self.assertIn("latest_runtime_report_status=warning", overview_report)
        self.assertIn("latest_strategy_status=warning", overview_report)
        self.assertIn("open_strategy_escalation_count=2", overview_report)
        self.assertIn("access_denied_24h_count=1", overview_report)
        self.assertIn("open_governance_action_count=1", overview_report)
        self.assertIn("automation_24h_action_count=3", overview_report)
        self.assertIn("automation_pending_approval_count=1", overview_report)
        self.assertIn("automation_active_sandbox_executor_count=2", overview_report)
        self.assertIn("automation_active_allowlist_count=2", overview_report)
        self.assertIn("automation_active_secret_ref_count=1", overview_report)
        self.assertIn("automation_active_channel_count=2", overview_report)
        self.assertIn("automation_24h_dispatch_count=3", overview_report)
        self.assertIn("latest_automation_dispatch_status=recovered", overview_report)
        self.assertIn("automation_active_profile_count=3", overview_report)
        self.assertIn("automation_ready_profile_count=1", overview_report)
        self.assertIn("latest_automation_validation_status=success", overview_report)
        self.assertIn("latest_automation_rotation_status=applied", overview_report)
        self.assertIn("automation_24h_live_receipt_count=1", overview_report)
        self.assertIn("latest_automation_live_receipt_status=success", overview_report)
        self.assertIn("latest_automation_attempt_status=approval_required", overview_report)
        self.assertIn("latest_automation_status=warning", overview_report)

        governance_report = format_kappa_report(
            KappaResult(
                "admin.project-governance",
                [
                    {
                        "snapshot_code": "chi-gov-demo-quant-research-20260727",
                        "tenant_code": "demo",
                        "project_code": "quant-research",
                        "status": "warning",
                        "risk_score": "42.0000",
                        "recommended_action": "review_access_policy",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=chi-gov-demo-quant-research-20260727", governance_report)
        self.assertIn("recommended_action=review_access_policy", governance_report)

        invoice_report = format_kappa_report(
            KappaResult(
                "admin.invoices",
                [
                    {
                        "invoice_code": "inv-demo-quant",
                        "tenant_code": "demo",
                        "status": "paid",
                        "total_amount": "0.16002800",
                        "paid_amount": "0.16002800",
                        "outstanding_amount": "0E-8",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("status=paid", invoice_report)
        self.assertIn("paid_amount=0.16002800", invoice_report)

        readiness_report = format_kappa_report(
            KappaResult(
                "admin.vendor-readiness",
                [
                    {
                        "review_code": "pi-readiness-vendor-http",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "status": "ready",
                        "recommendation": "approve_primary",
                        "recommended_role": "primary",
                        "suite_count": 3,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("recommendation=approve_primary", readiness_report)
        self.assertIn("recommended_role=primary", readiness_report)

        live_gate_report = format_kappa_report(
            KappaResult(
                "admin.vendor-live-gates",
                [
                    {
                        "gate_code": "epsilon3-live-gate-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "run_mode": "blocked",
                        "status": "blocked",
                        "required_windows": [5, 20, 60],
                        "executed_windows": [],
                        "live_base_url_present": False,
                        "live_token_present": False,
                        "error_message": "external_vendor_live_disabled",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("gate_code=epsilon3-live-gate-demo", live_gate_report)
        self.assertIn("run_mode=blocked", live_gate_report)

        procurement_report = format_kappa_report(
            KappaResult(
                "admin.vendor-procurement-readiness",
                [
                    {
                        "snapshot_code": "omicron5-procurement-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "status": "review_required",
                        "procurement_role": "validator",
                        "contract_status": "draft",
                        "entitlement_status": "review_required",
                        "blocking_issues": ["contract_status_draft"],
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=omicron5-procurement-demo", procurement_report)
        self.assertIn("procurement_role=validator", procurement_report)

        primary_promotion_report = format_kappa_report(
            KappaResult(
                "admin.vendor-primary-promotions",
                [
                    {
                        "promotion_code": "pi5-primary-promotion-demo",
                        "source_code": "vendor_http",
                        "primary_source_code": "csv",
                        "status": "blocked",
                        "promotion_scope": "full_market",
                        "apply_mode": "review_only",
                        "dataset_count": 7,
                        "blocked_dataset_count": 7,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("promotion_code=pi5-primary-promotion-demo", primary_promotion_report)
        self.assertIn("apply_mode=review_only", primary_promotion_report)

        primary_promotion_result_report = format_kappa_report(
            KappaResult(
                "admin.vendor-primary-promotion-results",
                [
                    {
                        "promotion_code": "pi5-primary-promotion-demo",
                        "result_code": "pi5-primary-promotion-result-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "status": "blocked",
                        "promotion_role": "blocked",
                        "procurement_status": "review_required",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("result_code=pi5-primary-promotion-result-demo", primary_promotion_result_report)
        self.assertIn("promotion_role=blocked", primary_promotion_result_report)

        post_promotion_report = format_kappa_report(
            KappaResult(
                "admin.vendor-post-promotion-monitors",
                [
                    {
                        "monitor_code": "rho5-post-promotion-demo",
                        "promotion_code": "pi5-primary-promotion-demo",
                        "source_code": "vendor_http",
                        "primary_source_code": "csv",
                        "status": "no_applied_promotion",
                        "monitor_scope": "post_promotion",
                        "rollback_mode": "review_only",
                        "dataset_count": 7,
                        "no_applied_dataset_count": 7,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("monitor_code=rho5-post-promotion-demo", post_promotion_report)
        self.assertIn("rollback_mode=review_only", post_promotion_report)

        post_promotion_result_report = format_kappa_report(
            KappaResult(
                "admin.vendor-post-promotion-results",
                [
                    {
                        "monitor_code": "rho5-post-promotion-demo",
                        "result_code": "rho5-post-promotion-result-demo",
                        "promotion_code": "pi5-primary-promotion-demo",
                        "promotion_result_code": "pi5-primary-promotion-result-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "status": "no_applied_promotion",
                        "monitor_scope": "post_promotion",
                        "rollback_mode": "review_only",
                        "promotion_status": "blocked",
                        "shadow_status": "not_available",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("result_code=rho5-post-promotion-result-demo", post_promotion_result_report)
        self.assertIn("shadow_status=not_available", post_promotion_result_report)

        primary_stability_report = format_kappa_report(
            KappaResult(
                "admin.vendor-primary-stability",
                [
                    {
                        "snapshot_code": "sigma5-primary-stability-demo",
                        "source_code": "vendor_http",
                        "primary_source_code": "csv",
                        "status": "no_primary_promotion",
                        "stability_role": "watch",
                        "monitor_scope": "primary_source",
                        "dataset_count": 7,
                        "primary_dataset_count": 0,
                        "no_primary_dataset_count": 7,
                        "api_success_rate": "1.000000",
                        "scheduler_lag_minutes": 0,
                        "stability_score": "0.0000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=sigma5-primary-stability-demo", primary_stability_report)
        self.assertIn("stability_role=watch", primary_stability_report)

        primary_stability_dataset_report = format_kappa_report(
            KappaResult(
                "admin.vendor-primary-stability-datasets",
                [
                    {
                        "snapshot_code": "sigma5-primary-stability-demo",
                        "dataset_snapshot_code": "sigma5-primary-stability-dataset-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "primary_source_code": "csv",
                        "status": "no_primary_promotion",
                        "stability_role": "watch",
                        "is_primary_route": False,
                        "current_primary_source_code": "csv",
                        "entitlement_status": "review_required",
                        "promotion_status": "blocked",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("dataset_snapshot_code=sigma5-primary-stability-dataset-demo", primary_stability_dataset_report)
        self.assertIn("is_primary_route=False", primary_stability_dataset_report)

        cost_optimization_report = format_kappa_report(
            KappaResult(
                "admin.vendor-cost-optimizations",
                [
                    {
                        "optimization_code": "tau5-cost-optimization-demo",
                        "source_code": "vendor_http",
                        "primary_source_code": "csv",
                        "status": "no_primary_promotion",
                        "optimization_role": "watch",
                        "optimization_scope": "primary_source",
                        "dataset_count": 7,
                        "no_primary_dataset_count": 7,
                        "recommended_primary_weight_pct": "0.0000",
                        "recommended_backup_weight_pct": "100.0000",
                        "projected_budget_usage_pct": "0.0000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("optimization_code=tau5-cost-optimization-demo", cost_optimization_report)
        self.assertIn("recommended_primary_weight_pct=0.0000", cost_optimization_report)

        route_weight_report = format_kappa_report(
            KappaResult(
                "admin.vendor-route-weight-plans",
                [
                    {
                        "optimization_code": "tau5-cost-optimization-demo",
                        "plan_code": "tau5-route-weight-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "primary_source_code": "csv",
                        "backup_source_code": "akshare",
                        "status": "no_primary_promotion",
                        "plan_role": "watch",
                        "current_primary_source_code": "csv",
                        "routing_change_allowed": False,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("plan_code=tau5-route-weight-demo", route_weight_report)
        self.assertIn("routing_change_allowed=False", route_weight_report)

        budget_stress_report = format_kappa_report(
            KappaResult(
                "admin.vendor-budget-stress",
                [
                    {
                        "optimization_code": "tau5-cost-optimization-demo",
                        "plan_code": "tau5-route-weight-demo",
                        "stress_code": "tau5-budget-stress-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "stress_multiplier": "10.0000",
                        "status": "no_primary_promotion",
                        "recommended_action": "wait_primary_promotion",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("stress_code=tau5-budget-stress-demo", budget_stress_report)
        self.assertIn("recommended_action=wait_primary_promotion", budget_stress_report)

        route_execution_report = format_kappa_report(
            KappaResult(
                "admin.vendor-route-executions",
                [
                    {
                        "execution_code": "upsilon5-route-execution-demo",
                        "optimization_code": "tau5-cost-optimization-demo",
                        "source_code": "vendor_http",
                        "primary_source_code": "csv",
                        "status": "pending_approval",
                        "approval_status": "pending",
                        "execution_mode": "review_only",
                        "rollout_policy": "gradual",
                        "dataset_count": 7,
                        "pending_approval_dataset_count": 7,
                        "applied_primary_weight_pct": "0.0000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("execution_code=upsilon5-route-execution-demo", route_execution_report)
        self.assertIn("approval_status=pending", route_execution_report)

        route_execution_dataset_report = format_kappa_report(
            KappaResult(
                "admin.vendor-route-execution-datasets",
                [
                    {
                        "execution_code": "upsilon5-route-execution-demo",
                        "execution_dataset_code": "upsilon5-route-dataset-demo",
                        "optimization_code": "tau5-cost-optimization-demo",
                        "plan_code": "tau5-route-weight-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "status": "pending_approval",
                        "approval_status": "pending",
                        "target_primary_weight_pct": "90.0000",
                        "applied_primary_weight_pct": "0.0000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("execution_dataset_code=upsilon5-route-dataset-demo", route_execution_dataset_report)
        self.assertIn("target_primary_weight_pct=90.0000", route_execution_dataset_report)

        route_stage_report = format_kappa_report(
            KappaResult(
                "admin.vendor-route-rollout-stages",
                [
                    {
                        "execution_code": "upsilon5-route-execution-demo",
                        "execution_dataset_code": "upsilon5-route-dataset-demo",
                        "stage_code": "upsilon5-route-stage-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "stage_sequence": 1,
                        "stage_label": "10pct",
                        "status": "pending",
                        "approval_status": "pending",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("stage_code=upsilon5-route-stage-demo", route_stage_report)
        self.assertIn("stage_sequence=1", route_stage_report)

        route_policy_report = format_kappa_report(
            KappaResult(
                "admin.source-route-weight-policies",
                [
                    {
                        "policy_code": "upsilon5-route-policy-demo",
                        "execution_code": "upsilon5-route-execution-demo",
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "policy_status": "active",
                        "execution_mode": "apply",
                        "primary_weight_pct": "10.0000",
                        "backup_weight_pct": "90.0000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("policy_code=upsilon5-route-policy-demo", route_policy_report)
        self.assertIn("primary_weight_pct=10.0000", route_policy_report)

        route_decision_report = format_kappa_report(
            KappaResult(
                "admin.source-route-decisions",
                [
                    {
                        "decision_code": "phi5-route-decision-demo",
                        "policy_code": "upsilon5-route-policy-demo",
                        "dataset_code": "daily_bar",
                        "requested_source_code": "csv",
                        "selected_source_code": "vendor_http",
                        "final_source_code": "csv",
                        "decision_context": "sync",
                        "route_mode": "fallback",
                        "decision_status": "fallback_success",
                        "selected_role": "fallback",
                        "fallback_applied": True,
                        "row_count": 1,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("decision_code=phi5-route-decision-demo", route_decision_report)
        self.assertIn("final_source_code=csv", route_decision_report)

        route_health_report = format_kappa_report(
            KappaResult(
                "admin.source-route-health",
                [
                    {
                        "snapshot_code": "chi5-route-health-demo",
                        "dataset_code": "daily_bar",
                        "source_code": "vendor_http",
                        "status": "degraded",
                        "previous_circuit_status": "closed",
                        "circuit_status": "open",
                        "circuit_action": "open_circuit",
                        "request_count": 4,
                        "success_count": 2,
                        "failed_count": 2,
                        "fallback_count": 1,
                        "success_rate": "0.500000",
                        "failure_rate": "0.500000",
                        "fallback_rate": "0.250000",
                        "latency_p95_ms": 3200,
                        "health_issues": ["failure_rate_high"],
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=chi5-route-health-demo", route_health_report)
        self.assertIn("circuit_action=open_circuit", route_health_report)

        circuit_report = format_kappa_report(
            KappaResult(
                "admin.source-route-circuit-breakers",
                [
                    {
                        "breaker_code": "chi5-breaker-demo",
                        "dataset_code": "daily_bar",
                        "source_code": "vendor_http",
                        "status": "open",
                        "snapshot_code": "chi5-route-health-demo",
                        "open_reason": "failure_rate_high",
                        "failure_rate": "0.500000",
                        "fallback_rate": "0.250000",
                        "latency_p95_ms": 3200,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("breaker_code=chi5-breaker-demo", circuit_report)
        self.assertIn("open_reason=failure_rate_high", circuit_report)

        probe_report = format_kappa_report(
            KappaResult(
                "admin.source-route-recovery-probes",
                [
                    {
                        "probe_code": "chi5-probe-demo",
                        "breaker_code": "chi5-breaker-demo",
                        "snapshot_code": "chi5-route-health-demo",
                        "dataset_code": "daily_bar",
                        "source_code": "vendor_http",
                        "status": "recovered",
                        "observed_request_count": 3,
                        "observed_success_count": 3,
                        "observed_failed_count": 0,
                        "observed_success_rate": "1.000000",
                        "required_success_rate": "1.000000",
                        "decision_summary": "circuit closed after healthy probe",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("probe_code=chi5-probe-demo", probe_report)
        self.assertIn("status=recovered", probe_report)

        incident_action_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-actions",
                [
                    {
                        "incident_action_code": "psi5-route-incident-demo",
                        "run_code": "psi5-route-smoke",
                        "action_code": "psi-action-route-demo",
                        "source_signal_type": "circuit_open",
                        "dataset_code": "daily_bar",
                        "source_code": "baostock",
                        "action_type": "degrade_vendor",
                        "safety_level": "high",
                        "execution_mode": "execute",
                        "status": "approval_required",
                        "approval_required": True,
                        "owner": "platform-ops",
                        "circuit_status": "open",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("incident_action_code=psi5-route-incident-demo", incident_action_report)
        self.assertIn("source_signal_type=circuit_open", incident_action_report)

        incident_control_health_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-control-health",
                [
                    {
                        "snapshot_code": "alpha6-route-control-health-demo",
                        "status": "warning",
                        "control_count": 3,
                        "pending_control_count": 1,
                        "approval_pending_count": 1,
                        "notification_blocked_count": 1,
                        "health_issues": ["route_control_wecom_blocked"],
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=alpha6-route-control-health-demo", incident_control_health_report)
        self.assertIn("pending_control_count=1", incident_control_health_report)

        incident_operation_report = format_kappa_report(
            KappaResult(
                "admin.source-route-incident-operation-batches",
                [
                    {
                        "batch_code": "beta6-route-ops-demo",
                        "status": "warning",
                        "eligible_count": 3,
                        "approved_count": 1,
                        "suppressed_notification_count": 2,
                        "stress_scenario_count": 20,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("batch_code=beta6-route-ops-demo", incident_operation_report)
        self.assertIn("suppressed_notification_count=2", incident_operation_report)

        recovery_report = format_kappa_report(
            KappaResult(
                "admin.free-source-recovery-actions",
                [
                    {
                        "action_code": "lambda5-akshare-daily_bar-retry",
                        "recovery_code": "lambda5-free-source-recovery-demo",
                        "source_code": "akshare",
                        "dataset_code": "daily_bar",
                        "action_type": "retry_canary",
                        "status": "alerted",
                        "severity": "high",
                        "reason_code": "source_degraded",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("action_code=lambda5-akshare-daily_bar-retry", recovery_report)
        self.assertIn("action_type=retry_canary", recovery_report)

        recovery_execution_report = format_kappa_report(
            KappaResult(
                "admin.free-source-recovery-executions",
                [
                    {
                        "execution_code": "mu5-retry-canary-recovered-demo",
                        "action_code": "lambda5-akshare-daily_bar-retry",
                        "source_code": "akshare",
                        "dataset_code": "daily_bar",
                        "execution_type": "retry_canary",
                        "status": "recovered",
                        "iota5_pool_status": "ok",
                        "fabric_code": "iota3-free-source-fabric-demo",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("execution_code=mu5-retry-canary-recovered-demo", recovery_execution_report)
        self.assertIn("iota5_pool_status=ok", recovery_execution_report)

        recovery_health_report = format_kappa_report(
            KappaResult(
                "admin.free-source-recovery-health",
                [
                    {
                        "snapshot_code": "nu5-recovery-health-demo",
                        "status": "warning",
                        "as_of_at": "2026-07-28T10:00:00+08:00",
                        "backlog_count": 3,
                        "pending_action_count": 3,
                        "approval_pending_count": 1,
                        "approval_overdue_count": 0,
                        "failure_rate": "0.0000",
                        "stale_schedule_count": 0,
                        "latest_worker_status": "warning",
                        "health_issues": ["recovery_backlog_pending"],
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=nu5-recovery-health-demo", recovery_health_report)
        self.assertIn("backlog_count=3", recovery_health_report)
        self.assertIn("health_issues=['recovery_backlog_pending']", recovery_health_report)

        onboarding_report = format_kappa_report(
            KappaResult(
                "admin.vendor-onboarding-runs",
                [
                    {
                        "run_code": "zeta3-onboarding-demo",
                        "source_code": "vendor_http",
                        "status": "blocked",
                        "preflight_status": "blocked",
                        "canary_status": "blocked",
                        "gate_status": "blocked",
                        "recommendation": "research_only",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("run_code=zeta3-onboarding-demo", onboarding_report)
        self.assertIn("recommendation=research_only", onboarding_report)

        onboarding_result_report = format_kappa_report(
            KappaResult(
                "admin.vendor-onboarding-results",
                [
                    {
                        "run_code": "zeta3-onboarding-demo",
                        "dataset_code": "daily_bar",
                        "stage_status": "blocked",
                        "gate_status": "blocked",
                        "gate_code": "epsilon3-live-gate-demo",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("dataset_code=daily_bar", onboarding_result_report)
        self.assertIn("gate_code=epsilon3-live-gate-demo", onboarding_result_report)

        live_closure_report = format_kappa_report(
            KappaResult(
                "admin.vendor-live-closures",
                [
                    {
                        "closure_code": "eta3-live-closure-demo",
                        "source_code": "vendor_http",
                        "status": "blocked",
                        "config_status": "blocked",
                        "endpoint_status": "blocked",
                        "recommendation": "research_only",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("closure_code=eta3-live-closure-demo", live_closure_report)
        self.assertIn("endpoint_status=blocked", live_closure_report)

        live_probe_report = format_kappa_report(
            KappaResult(
                "admin.vendor-live-probes",
                [
                    {
                        "closure_code": "eta3-live-closure-demo",
                        "probe_code": "eta3-live-probe-demo",
                        "dataset_code": "daily_bar",
                        "status": "blocked",
                        "auth_status": "blocked",
                        "schema_status": "skipped",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("probe_code=eta3-live-probe-demo", live_probe_report)
        self.assertIn("schema_status=skipped", live_probe_report)

        live_pilot_report = format_kappa_report(
            KappaResult(
                "admin.vendor-live-pilots",
                [
                    {
                        "pilot_code": "theta3-live-pilot-demo",
                        "source_code": "vendor_http",
                        "status": "blocked",
                        "pilot_scope": "canary",
                        "closure_status": "blocked",
                        "endpoint_status": "blocked",
                        "signoff_status": "not_ready",
                        "recommendation": "research_only",
                        "risk_level": "high",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("pilot_code=theta3-live-pilot-demo", live_pilot_report)
        self.assertIn("signoff_status=not_ready", live_pilot_report)

        live_pilot_result_report = format_kappa_report(
            KappaResult(
                "admin.vendor-live-pilot-results",
                [
                    {
                        "pilot_code": "theta3-live-pilot-demo",
                        "result_code": "theta3-live-pilot-result-demo",
                        "dataset_code": "daily_bar",
                        "status": "blocked",
                        "schema_status": "skipped",
                        "risk_level": "high",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("result_code=theta3-live-pilot-result-demo", live_pilot_result_report)
        self.assertIn("risk_level=high", live_pilot_result_report)

        free_fabric_report = format_kappa_report(
            KappaResult(
                "admin.free-source-fabric-runs",
                [
                    {
                        "fabric_code": "iota3-free-source-fabric-demo",
                        "status": "success",
                        "fabric_scope": "canary",
                        "recommendation": "backup",
                        "risk_level": "low",
                        "coverage_rate": "1.000000",
                        "conflict_rate_bps": "0.000000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("fabric_code=iota3-free-source-fabric-demo", free_fabric_report)
        self.assertIn("recommendation=backup", free_fabric_report)

        free_fabric_result_report = format_kappa_report(
            KappaResult(
                "admin.free-source-fabric-results",
                [
                    {
                        "fabric_code": "iota3-free-source-fabric-demo",
                        "result_code": "iota3-free-source-result-demo",
                        "dataset_code": "daily_bar",
                        "status": "success",
                        "coverage_status": "success",
                        "consistency_status": "success",
                        "license_status": "local_smoke",
                        "risk_level": "low",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("result_code=iota3-free-source-result-demo", free_fabric_result_report)
        self.assertIn("license_status=local_smoke", free_fabric_result_report)

        free_reliability_report = format_kappa_report(
            KappaResult(
                "admin.free-source-reliability",
                [
                    {
                        "snapshot_code": "kappa5-free-source-sse-public-demo",
                        "source_code": "sse_public",
                        "dataset_code": "daily_bar",
                        "status": "ready",
                        "recommended_role": "backup",
                        "reliability_score": "82.0000",
                        "commercial_clearance": "review_required",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("snapshot_code=kappa5-free-source-sse-public-demo", free_reliability_report)
        self.assertIn("commercial_clearance=review_required", free_reliability_report)

        reconciliation_report = format_kappa_report(
            KappaResult(
                "admin.revenue-reconciliation",
                [
                    {
                        "reconciliation_code": "rho-recon-demo",
                        "tenant_code": "demo",
                        "project_code": "quant-research",
                        "status": "matched",
                        "invoice_total_amount": "0.16002800",
                        "recomputed_total_amount": "0.16002800",
                        "amount_delta": "0E-8",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("reconciliation_code=rho-recon-demo", reconciliation_report)
        self.assertIn("amount_delta=0E-8", reconciliation_report)

        health_report = format_kappa_report(
            KappaResult(
                "admin.customer-health",
                [
                    {
                        "health_code": "rho-health-demo",
                        "tenant_code": "demo",
                        "project_code": "quant-research",
                        "status": "active",
                        "retention_signal": "healthy",
                        "health_score": 100,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("retention_signal=healthy", health_report)

        payment_report = format_kappa_report(
            KappaResult(
                "admin.payment-matches",
                [
                    {
                        "match_code": "tau-match-demo",
                        "transaction_code": "tau-pay-demo",
                        "invoice_code": "inv-demo-quant",
                        "match_type": "auto_exact",
                        "status": "matched",
                        "matched_amount": "100.00000000",
                        "invoice_status": "paid",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("match_code=tau-match-demo", payment_report)
        self.assertIn("invoice_status=paid", payment_report)

        runtime_report = format_kappa_report(
            KappaResult(
                "admin.runtime-metrics",
                [
                    {
                        "metric_time": "2026-07-26T12:00:00+00:00",
                        "environment": "local",
                        "component": "api",
                        "metric_name": "api_request_count_7d",
                        "metric_value": "227.000000000000",
                        "unit": "requests",
                        "status": "warning",
                        "warning_threshold": "200.000000000000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("metric_name=api_request_count_7d", runtime_report)
        self.assertIn("status=warning", runtime_report)

        strategy_report = format_kappa_report(
            KappaResult(
                "admin.strategy-decisions",
                [
                    {
                        "decision_code": "phi-decision-local-runtime",
                        "run_code": "phi-local-20260727",
                        "domain": "runtime",
                        "subject_code": "local",
                        "action": "investigate_runtime",
                        "status": "block",
                        "severity": "critical",
                        "priority_score": "41.000000",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("action=investigate_runtime", strategy_report)
        self.assertIn("severity=critical", strategy_report)

        automation_report = format_kappa_report(
            KappaResult(
                "admin.automation-actions",
                [
                    {
                        "action_code": "psi-action-demo",
                        "run_code": "psi-local-20260727-dry-run",
                        "source_type": "phi_decision",
                        "source_code": "phi-decision-demo",
                        "action_type": "escalate_commercial",
                        "safety_level": "medium",
                        "execution_mode": "dry_run",
                        "status": "skipped",
                        "approval_required": False,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("action_type=escalate_commercial", automation_report)
        self.assertIn("execution_mode=dry_run", automation_report)

        approval_report = format_kappa_report(
            KappaResult(
                "admin.automation-approvals",
                [
                    {
                        "approval_code": "omega-approval-demo",
                        "action_code": "psi-action-demo",
                        "run_code": "psi-local-20260727-execute",
                        "action_type": "freeze_budget",
                        "safety_level": "high",
                        "status": "pending",
                        "requested_by": "omega",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("approval_code=omega-approval-demo", approval_report)
        self.assertIn("status=pending", approval_report)

        attempt_report = format_kappa_report(
            KappaResult(
                "admin.automation-attempts",
                [
                    {
                        "attempt_code": "omega-attempt-demo",
                        "action_code": "psi-action-demo",
                        "executor_code": "omega-noop-freeze-budget",
                        "action_type": "freeze_budget",
                        "status": "approval_required",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("attempt_code=omega-attempt-demo", attempt_report)
        self.assertIn("executor_code=omega-noop-freeze-budget", attempt_report)

        rollback_report = format_kappa_report(
            KappaResult(
                "admin.automation-rollbacks",
                [
                    {
                        "rollback_code": "omega-rollback-demo",
                        "action_code": "psi-action-demo",
                        "rollback_type": "noop",
                        "status": "planned",
                        "requested_by": "omega",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("rollback_code=omega-rollback-demo", rollback_report)

        executor_report = format_kappa_report(
            KappaResult(
                "admin.automation-executors",
                [
                    {
                        "executor_code": "omega-noop-freeze-budget",
                        "executor_type": "noop",
                        "action_type": "freeze_budget",
                        "safety_level": "high",
                        "status": "active",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("executor_code=omega-noop-freeze-budget", executor_report)

        allowlist_report = format_kappa_report(
            KappaResult(
                "admin.automation-allowlists",
                [
                    {
                        "allowlist_code": "alpha2-script-reporter",
                        "executor_type": "script",
                        "target_pattern": "scripts/alpha2_executor_sandbox.py",
                        "status": "active",
                        "sandbox_only": True,
                        "max_timeout_seconds": 5,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("allowlist_code=alpha2-script-reporter", allowlist_report)
        self.assertIn("target_pattern=scripts/alpha2_executor_sandbox.py", allowlist_report)

        secret_report = format_kappa_report(
            KappaResult(
                "admin.automation-secrets",
                [
                    {
                        "secret_ref": "alpha2-local-hmac",
                        "secret_scope": "automation",
                        "secret_kind": "hmac",
                        "status": "active",
                        "owner": "platform-ops",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("secret_ref=alpha2-local-hmac", secret_report)
        self.assertIn("secret_kind=hmac", secret_report)

        channel_report = format_kappa_report(
            KappaResult(
                "admin.automation-channels",
                [
                    {
                        "channel_code": "beta2-local-approval-webhook",
                        "channel_type": "webhook",
                        "environment": "local",
                        "status": "active",
                        "allowlist_code": "alpha2-webhook-localhost",
                        "secret_ref": "alpha2-local-hmac",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("channel_code=beta2-local-approval-webhook", channel_report)
        self.assertIn("allowlist_code=alpha2-webhook-localhost", channel_report)

        dispatch_report = format_kappa_report(
            KappaResult(
                "admin.automation-dispatches",
                [
                    {
                        "dispatch_code": "beta2-dispatch-demo",
                        "action_code": "omega-smoke-retry-action",
                        "channel_code": "beta2-local-approval-webhook",
                        "dispatch_type": "approval_request",
                        "status": "acknowledged",
                        "retry_count": 0,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("dispatch_code=beta2-dispatch-demo", dispatch_report)
        self.assertIn("dispatch_type=approval_request", dispatch_report)

        runbook_report = format_kappa_report(
            KappaResult(
                "admin.automation-runbooks",
                [
                    {
                        "runbook_code": "beta2-webhook-timeout",
                        "failure_class": "webhook_timeout",
                        "severity": "high",
                        "status": "active",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("runbook_code=beta2-webhook-timeout", runbook_report)
        self.assertIn("failure_class=webhook_timeout", runbook_report)

        profile_report = format_kappa_report(
            KappaResult(
                "admin.automation-channel-profiles",
                [
                    {
                        "profile_code": "gamma2-local-feishu-profile",
                        "channel_code": "gamma2-local-feishu-dryrun",
                        "provider_code": "feishu",
                        "environment": "local",
                        "profile_status": "active",
                        "readiness_status": "dry_run_ready",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("profile_code=gamma2-local-feishu-profile", profile_report)
        self.assertIn("readiness_status=dry_run_ready", profile_report)

        validation_report = format_kappa_report(
            KappaResult(
                "admin.automation-channel-validations",
                [
                    {
                        "validation_code": "gamma2-validation-demo",
                        "profile_code": "gamma2-local-feishu-profile",
                        "channel_code": "gamma2-local-feishu-dryrun",
                        "provider_code": "feishu",
                        "validation_type": "secret_rotation",
                        "status": "success",
                        "dispatch_code": "beta2-dispatch-demo",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("validation_code=gamma2-validation-demo", validation_report)
        self.assertIn("validation_type=secret_rotation", validation_report)

        rotation_report = format_kappa_report(
            KappaResult(
                "admin.automation-secret-rotations",
                [
                    {
                        "rotation_code": "gamma2-rotation-demo",
                        "environment": "local",
                        "secret_ref": "gamma2-local-hmac-current",
                        "next_secret_ref": "gamma2-local-hmac-next",
                        "rotation_type": "drill",
                        "status": "applied",
                        "profile_code": "gamma2-local-feishu-profile",
                        "validation_status": "success",
                        "affected_channel_count": 1,
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("rotation_code=gamma2-rotation-demo", rotation_report)
        self.assertIn("next_secret_ref=gamma2-local-hmac-next", rotation_report)

        live_receipt_report = format_kappa_report(
            KappaResult(
                "admin.automation-live-receipts",
                [
                    {
                        "receipt_code": "delta2-wecom-receipt-demo",
                        "validation_code": "delta2-wecom-validation-demo",
                        "profile_code": "delta2-wecom-live-profile",
                        "channel_code": "delta2-wecom-live-webhook",
                        "provider_code": "wecom",
                        "environment": "live_test",
                        "message_type": "markdown",
                        "status": "success",
                        "provider_status_code": 200,
                        "provider_errcode": 0,
                        "provider_errmsg": "ok",
                    }
                ],
                {"row_count": 1},
            )
        )
        self.assertIn("receipt_code=delta2-wecom-receipt-demo", live_receipt_report)
        self.assertIn("provider_errcode=0", live_receipt_report)

    def test_console_html_escapes_dynamic_values(self) -> None:
        html = render_kappa_console(
            {
                "overview": {
                    "active_tenant_count": 1,
                    "active_project_count": 1,
                    "active_token_count": 1,
                    "open_alert_count": 2,
                    "usage_7d_request_count": 4,
                    "usage_7d_cost_units": "4.000700",
                    "active_worker_schedule_count": 3,
                    "live_scheduler_count": 1,
                    "latest_deployment_health_status": "success",
                    "deployment_24h_failed_count": 0,
                    "active_product_count": 1,
                    "budget_open_alert_count": 1,
                    "budget_month_usage_amount": "0.820215",
                    "vendor_readiness_ready_count": 1,
                    "vendor_readiness_watch_count": 0,
                    "latest_vendor_readiness_status": "ready",
                    "vendor_24h_live_gate_count": 1,
                    "vendor_24h_live_gate_blocked_count": 1,
                    "vendor_24h_live_gate_executed_count": 0,
                    "latest_vendor_live_gate_status": "blocked",
                    "vendor_24h_onboarding_count": 1,
                    "vendor_24h_onboarding_blocked_count": 1,
                    "latest_vendor_onboarding_status": "blocked",
                    "vendor_24h_live_closure_count": 1,
                    "vendor_24h_live_closure_blocked_count": 1,
                    "latest_vendor_live_closure_status": "blocked",
                    "vendor_24h_live_pilot_count": 1,
                    "vendor_24h_live_pilot_blocked_count": 1,
                    "latest_vendor_live_pilot_status": "blocked",
                    "vendor_contract_profile_count": 1,
                    "vendor_active_contract_count": 0,
                    "vendor_active_entitlement_count": 0,
                    "vendor_24h_procurement_readiness_count": 7,
                    "vendor_24h_procurement_ready_count": 0,
                    "vendor_24h_procurement_review_required_count": 7,
                    "vendor_24h_procurement_blocked_count": 0,
                    "latest_vendor_procurement_status": "review_required",
                    "vendor_procurement_primary_candidate_count": 0,
                    "vendor_24h_cost_optimization_count": 1,
                    "vendor_24h_cost_optimized_count": 0,
                    "vendor_24h_cost_over_budget_count": 0,
                    "vendor_24h_cost_quota_risk_count": 0,
                    "vendor_24h_cost_no_primary_count": 1,
                    "latest_vendor_cost_optimization_status": "no_primary_promotion",
                    "latest_vendor_cost_optimization_role": "watch",
                    "vendor_cost_primary_weight_pct": "0.0000",
                    "vendor_cost_backup_weight_pct": "100.0000",
                    "vendor_cost_free_source_weight_pct": "0.0000",
                    "vendor_cost_budget_usage_pct": "0.0000",
                    "vendor_cost_monthly_quota_usage_pct": "0.0000",
                    "vendor_cost_optimization_score": "0.0000",
                    "vendor_24h_route_execution_count": 1,
                    "vendor_24h_route_pending_approval_count": 7,
                    "vendor_24h_route_staged_count": 0,
                    "vendor_24h_route_applied_count": 0,
                    "vendor_24h_route_blocked_count": 7,
                    "latest_vendor_route_execution_status": "pending_approval",
                    "latest_vendor_route_execution_approval_status": "pending",
                    "vendor_route_applied_primary_weight_pct": "0.0000",
                    "vendor_route_current_stage_sequence": 0,
                    "active_source_route_weight_policy_count": 0,
                    "source_route_24h_decision_count": 1,
                    "source_route_24h_fallback_count": 1,
                    "latest_source_route_decision_status": "fallback_success",
                    "latest_source_route_final_source_code": "csv",
                    "source_route_24h_health_count": 2,
                    "source_route_24h_unhealthy_count": 1,
                    "latest_source_route_health_status": "degraded",
                    "source_route_open_circuit_count": 1,
                    "source_route_24h_recovery_probe_count": 1,
                    "source_route_24h_recovered_probe_count": 1,
                    "source_route_24h_incident_action_count": 2,
                    "source_route_pending_incident_action_count": 1,
                    "latest_source_route_incident_action_status": "approval_required",
                    "source_route_24h_incident_control_count": 1,
                    "source_route_pending_incident_control_count": 1,
                    "latest_source_route_incident_control_stage": "rollback_planned",
                    "source_route_latest_control_health_status": "warning",
                    "source_route_control_health_issue_count": 2,
                    "source_route_control_health_overdue_approval_count": 0,
                    "source_route_control_health_blocked_receipt_count": 1,
                    "source_route_latest_operation_status": "warning",
                    "source_route_operation_queue_count": 3,
                    "source_route_operation_suppressed_notification_count": 2,
                    "source_route_operation_stress_scenario_count": 20,
                    "source_route_latest_approval_command_status": "pending_quorum",
                    "source_route_approval_pending_quorum_count": 1,
                    "source_route_approval_24h_applied_count": 1,
                    "source_route_approval_24h_signature_count": 2,
                    "source_route_approval_24h_lock_event_count": 3,
                    "source_route_approval_24h_lock_busy_count": 1,
                    "source_route_approval_24h_state_transition_count": 3,
                    "source_route_approval_24h_state_blocked_count": 1,
                    "source_route_approval_audit_hash_count": 5,
                    "source_route_approval_broken_audit_hash_count": 0,
                    "source_route_approval_planned_sla_action_count": 1,
                    "source_route_latest_approval_recovery_drill_status": "success",
                    "source_route_approval_24h_successful_recovery_drill_count": 1,
                    "invoice_month_count": 1,
                    "invoice_month_total_amount": "0.16002800",
                    "invoice_month_paid_amount": "0.00000000",
                    "invoice_month_outstanding_amount": "0.16002800",
                    "overdue_invoice_count": 0,
                    "revenue_reconciliation_mismatch_count": 0,
                    "latest_reconciliation_status": "matched",
                    "latest_ar_outstanding_amount": "0.00000000",
                    "customer_health_active_count": 1,
                    "customer_health_risk_count": 0,
                    "payment_month_received_amount": "100.00000000",
                    "payment_month_matched_amount": "100.00000000",
                    "unmatched_payment_count": 0,
                    "latest_payment_batch_status": "matched",
                    "revenue_ledger_month_credit_amount": "100.00000000",
                    "runtime_24h_error_log_count": 0,
                    "runtime_metric_warning_count": 1,
                    "runtime_metric_critical_count": 0,
                    "open_capacity_alert_count": 1,
                    "latest_runtime_report_status": "warning",
                    "automation_pending_approval_count": 1,
                    "automation_retry_scheduled_count": 0,
                    "automation_rollback_required_count": 1,
                    "automation_active_sandbox_executor_count": 2,
                    "automation_active_allowlist_count": 2,
                    "automation_active_secret_ref_count": 1,
                    "automation_active_channel_count": 2,
                    "automation_24h_dispatch_count": 3,
                    "automation_dead_letter_count": 0,
                    "latest_automation_dispatch_status": "recovered",
                    "automation_active_profile_count": 3,
                    "automation_ready_profile_count": 1,
                    "automation_24h_validation_count": 2,
                    "latest_automation_validation_status": "success",
                    "automation_applied_rotation_count": 1,
                    "latest_automation_rotation_status": "applied",
                    "automation_24h_live_receipt_count": 1,
                    "automation_24h_wecom_success_count": 1,
                    "latest_automation_live_receipt_status": "success",
                    "latest_automation_attempt_status": "success",
                },
                "usage": [{"usage_date": "2026-07-24", "project_code": "<ops>", "api_name": "price"}],
                "access_decisions": [{"decision_code": "chi-access-demo", "decision": "deny", "reason": "<denied>"}],
                "project_governance": [{"snapshot_code": "chi-gov-demo", "status": "warning", "recommended_action": "review_access_policy"}],
                "governance_actions": [{"action_code": "chi-action-demo", "action_type": "review_access_policy", "status": "open", "severity": "medium"}],
                "automation_runs": [{"run_code": "psi-local-20260727-dry-run", "execution_mode": "dry_run", "status": "success", "action_count": 3}],
                "automation_actions": [{"action_code": "psi-action-demo", "action_type": "escalate_commercial", "status": "skipped", "safety_level": "medium"}],
                "automation_approvals": [{"approval_code": "omega-approval-demo", "action_code": "psi-action-demo", "status": "pending", "requested_by": "omega"}],
                "automation_attempts": [{"attempt_code": "omega-attempt-demo", "action_code": "psi-action-demo", "executor_code": "omega-noop-freeze-budget", "status": "success"}],
                "automation_rollbacks": [{"rollback_code": "omega-rollback-demo", "action_code": "psi-action-demo", "rollback_type": "noop", "status": "planned"}],
                "automation_executors": [{"executor_code": "alpha2-script-notify-owner", "executor_type": "script", "action_type": "notify_owner", "status": "active", "sandbox_mode": True, "allowlist_code": "alpha2-script-reporter"}],
                "automation_allowlists": [{"allowlist_code": "alpha2-script-reporter", "executor_type": "script", "target_pattern": "scripts/alpha2_executor_sandbox.py", "status": "active"}],
                "automation_secrets": [{"secret_ref": "alpha2-local-hmac", "secret_kind": "hmac", "status": "active", "owner": "platform-ops"}],
                "automation_channels": [{"channel_code": "beta2-local-approval-webhook", "channel_type": "webhook", "environment": "local", "status": "active"}],
                "automation_dispatches": [{"dispatch_code": "beta2-dispatch-demo", "action_code": "omega-smoke-retry-action", "channel_code": "beta2-local-approval-webhook", "dispatch_type": "approval_request", "status": "acknowledged"}],
                "automation_runbooks": [{"runbook_code": "beta2-webhook-timeout", "failure_class": "webhook_timeout", "severity": "high", "status": "active"}],
                "automation_channel_profiles": [{"profile_code": "gamma2-local-feishu-profile", "channel_code": "gamma2-local-feishu-dryrun", "provider_code": "feishu", "environment": "local", "profile_status": "active", "readiness_status": "dry_run_ready"}],
                "automation_channel_validations": [{"validation_code": "gamma2-validation-demo", "profile_code": "gamma2-local-feishu-profile", "channel_code": "gamma2-local-feishu-dryrun", "provider_code": "feishu", "validation_type": "secret_rotation", "status": "success"}],
                "automation_secret_rotations": [{"rotation_code": "gamma2-rotation-demo", "environment": "local", "secret_ref": "gamma2-local-hmac-current", "next_secret_ref": "gamma2-local-hmac-next", "rotation_type": "drill", "status": "applied"}],
                "automation_live_receipts": [{"receipt_code": "delta2-wecom-receipt-demo", "validation_code": "delta2-wecom-validation-demo", "profile_code": "delta2-wecom-live-profile", "channel_code": "delta2-wecom-live-webhook", "provider_code": "wecom", "environment": "live_test", "message_type": "markdown", "status": "success", "provider_errcode": 0}],
                "deliveries": [],
                "schedules": [],
                "vendor_onboarding_runs": [{"run_code": "zeta3-onboarding-demo", "source_code": "vendor_http", "status": "blocked", "preflight_status": "blocked", "canary_status": "blocked", "gate_status": "blocked", "recommendation": "research_only"}],
                "vendor_onboarding_results": [{"run_code": "zeta3-onboarding-demo", "dataset_code": "daily_bar", "source_code": "vendor_http", "stage_status": "blocked", "gate_status": "blocked", "gate_code": "epsilon3-live-gate-demo"}],
                "vendor_live_closures": [{"closure_code": "eta3-live-closure-demo", "source_code": "vendor_http", "status": "blocked", "config_status": "blocked", "endpoint_status": "blocked", "recommendation": "research_only"}],
                "vendor_live_probes": [{"closure_code": "eta3-live-closure-demo", "probe_code": "eta3-live-probe-demo", "dataset_code": "daily_bar", "status": "blocked", "auth_status": "blocked", "schema_status": "skipped"}],
                "vendor_live_pilots": [{"pilot_code": "theta3-live-pilot-demo", "source_code": "vendor_http", "status": "blocked", "pilot_scope": "canary", "closure_status": "blocked", "endpoint_status": "blocked", "signoff_status": "not_ready", "risk_level": "high"}],
                "vendor_live_pilot_results": [{"pilot_code": "theta3-live-pilot-demo", "result_code": "theta3-live-pilot-result-demo", "dataset_code": "daily_bar", "status": "blocked", "schema_status": "skipped", "risk_level": "high"}],
                "vendor_contract_profiles": [{"contract_code": "omicron5-contract-vendor_http-draft", "source_code": "vendor_http", "provider_name": "Commercial HTTP Vendor", "procurement_status": "review_required", "contract_status": "draft", "commercial_clearance": "review_required"}],
                "vendor_contract_entitlements": [{"entitlement_code": "omicron5-entitlement-vendor_http-daily_bar", "contract_code": "omicron5-contract-vendor_http-draft", "source_code": "vendor_http", "dataset_code": "daily_bar", "entitlement_status": "review_required", "allowed_role": "primary_candidate", "schema_status": "pending"}],
                "vendor_procurement_readiness": [{"snapshot_code": "omicron5-procurement-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "status": "review_required", "procurement_role": "validator", "contract_status": "draft", "entitlement_status": "review_required"}],
                "vendor_cost_optimizations": [{"optimization_code": "tau5-cost-optimization-demo", "source_code": "vendor_http", "primary_source_code": "csv", "status": "no_primary_promotion", "optimization_role": "watch", "optimization_scope": "primary_source", "dataset_count": 7, "no_primary_dataset_count": 7, "recommended_primary_weight_pct": "0.0000", "recommended_backup_weight_pct": "100.0000"}],
                "vendor_route_weight_plans": [{"optimization_code": "tau5-cost-optimization-demo", "plan_code": "tau5-route-weight-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "primary_source_code": "csv", "backup_source_code": "akshare", "status": "no_primary_promotion", "plan_role": "watch", "current_primary_source_code": "csv", "routing_change_allowed": False}],
                "vendor_budget_stress": [{"optimization_code": "tau5-cost-optimization-demo", "plan_code": "tau5-route-weight-demo", "stress_code": "tau5-budget-stress-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "stress_multiplier": "10.0000", "status": "no_primary_promotion", "recommended_action": "wait_primary_promotion"}],
                "vendor_route_executions": [{"execution_code": "upsilon5-route-execution-demo", "optimization_code": "tau5-cost-optimization-demo", "source_code": "vendor_http", "primary_source_code": "csv", "status": "pending_approval", "approval_status": "pending", "execution_mode": "review_only", "rollout_policy": "gradual", "dataset_count": 7, "pending_approval_dataset_count": 7, "applied_primary_weight_pct": "0.0000"}],
                "vendor_route_execution_datasets": [{"execution_code": "upsilon5-route-execution-demo", "execution_dataset_code": "upsilon5-route-dataset-demo", "optimization_code": "tau5-cost-optimization-demo", "plan_code": "tau5-route-weight-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "status": "pending_approval", "approval_status": "pending", "target_primary_weight_pct": "90.0000", "applied_primary_weight_pct": "0.0000"}],
                "vendor_route_rollout_stages": [{"execution_code": "upsilon5-route-execution-demo", "execution_dataset_code": "upsilon5-route-dataset-demo", "stage_code": "upsilon5-route-stage-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "stage_sequence": 1, "stage_label": "10pct", "status": "pending", "approval_status": "pending"}],
                "source_route_weight_policies": [{"policy_code": "upsilon5-route-policy-demo", "execution_code": "upsilon5-route-execution-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "policy_status": "active", "execution_mode": "apply", "primary_weight_pct": "10.0000", "backup_weight_pct": "90.0000"}],
                "source_route_decisions": [{"decision_code": "phi5-route-decision-demo", "policy_code": "upsilon5-route-policy-demo", "dataset_code": "daily_bar", "requested_source_code": "csv", "selected_source_code": "vendor_http", "final_source_code": "csv", "decision_context": "sync", "route_mode": "fallback", "decision_status": "fallback_success", "selected_role": "fallback", "fallback_applied": True, "row_count": 1}],
                "source_route_health": [{"snapshot_code": "chi5-route-health-demo", "dataset_code": "daily_bar", "source_code": "vendor_http", "status": "degraded", "previous_circuit_status": "closed", "circuit_status": "open", "circuit_action": "open_circuit", "request_count": 4, "success_count": 2, "failed_count": 2, "fallback_count": 1, "success_rate": "0.500000", "failure_rate": "0.500000", "fallback_rate": "0.250000", "latency_p95_ms": 3200, "health_issues": ["failure_rate_high"]}],
                "source_route_circuit_breakers": [{"breaker_code": "chi5-breaker-demo", "dataset_code": "daily_bar", "source_code": "vendor_http", "status": "open", "snapshot_code": "chi5-route-health-demo", "open_reason": "failure_rate_high", "failure_rate": "0.500000", "fallback_rate": "0.250000", "latency_p95_ms": 3200}],
                "source_route_recovery_probes": [{"probe_code": "chi5-probe-demo", "breaker_code": "chi5-breaker-demo", "snapshot_code": "chi5-route-health-demo", "dataset_code": "daily_bar", "source_code": "vendor_http", "status": "recovered", "observed_request_count": 3, "observed_success_count": 3, "observed_failed_count": 0, "observed_success_rate": "1.000000", "required_success_rate": "1.000000", "decision_summary": "circuit closed after healthy probe"}],
                "source_route_incident_actions": [{"incident_action_code": "psi5-route-incident-demo", "run_code": "psi5-route-smoke", "action_code": "psi-action-route-demo", "source_signal_type": "circuit_open", "dataset_code": "daily_bar", "source_code": "baostock", "action_type": "degrade_vendor", "safety_level": "high", "execution_mode": "execute", "status": "approval_required", "approval_required": True, "owner": "platform-ops", "circuit_status": "open"}],
                "source_route_incident_controls": [{"control_code": "omega5-route-control-demo", "incident_action_code": "psi5-route-incident-demo", "run_code": "psi5-route-smoke", "action_code": "psi-action-route-demo", "dataset_code": "daily_bar", "source_code": "baostock", "source_signal_type": "circuit_open", "action_type": "degrade_vendor", "safety_level": "high", "control_stage": "rollback_planned", "approval_status": "pending", "dispatch_status": "acknowledged", "receipt_status": "blocked", "rollback_status": "planned", "owner": "platform-ops", "requested_by": "omega5"}],
                "source_route_incident_control_health": [{"snapshot_code": "alpha6-route-control-health-demo", "status": "warning", "control_count": 3, "pending_control_count": 1, "approval_pending_count": 1, "notification_blocked_count": 1, "blocked_receipt_rate": "1.0000", "execution_failure_rate": "0.0000", "missing_rollback_count": 0, "stale_schedule_count": 0, "latest_control_stage": "rollback_planned", "health_issues": ["route_control_wecom_blocked"]}],
                "source_route_incident_operation_batches": [{"batch_code": "beta6-route-ops-demo", "status": "warning", "operation_mode": "approval_queue", "approval_decision": "hold", "dry_run": True, "apply_decisions": False, "candidate_count": 3, "eligible_count": 3, "held_count": 3, "suppressed_notification_count": 2, "stress_scenario_count": 20, "operation_issues": ["approval_queue_waiting_for_operator"]}],
                "source_route_incident_operation_items": [{"batch_code": "beta6-route-ops-demo", "control_code": "omega5-route-control-demo", "approval_code": "omega-approval-demo", "dataset_code": "daily_bar", "source_code": "baostock", "source_signal_type": "circuit_open", "safety_level": "high", "operation_decision": "hold", "operation_status": "preview", "approval_status_before": "pending", "approval_status_after": "pending", "suppress_notification": False, "priority_score": "332.00"}],
                "source_route_incident_approval_commands": [{"command_code": "gamma6-route-approval-demo", "status": "pending_quorum", "decision": "approve", "principal_code": "approver-a", "required_approvals": 2, "approval_count": 1, "quorum_status": "pending", "target_count": 1}],
                "source_route_incident_approval_command_items": [{"command_code": "gamma6-route-approval-demo", "control_code": "omega5-route-control-demo", "approval_code": "omega-approval-demo", "dataset_code": "daily_bar", "source_code": "baostock", "decision": "approve", "item_status": "pending_quorum", "signer_code": "approver-a", "signature_count": 1, "required_approvals": 2}],
                "source_route_incident_approval_signatures": [{"signature_code": "gamma6-sig-demo", "command_code": "gamma6-route-approval-demo", "control_code": "omega5-route-control-demo", "approval_code": "omega-approval-demo", "decision": "approve", "signer_code": "approver-a", "status": "active", "idempotency_key": "gamma6-key-demo"}],
                "source_route_incident_approval_lock_events": [{"lock_event_code": "epsilon6-lock-demo", "lock_status": "released", "lock_scope": "route-approval:control_code:omega5-route-control-demo", "provider_code": "wecom", "control_code": "omega5-route-control-demo", "callback_code": "delta6-callback-demo", "command_code": "gamma6-route-approval-demo", "held_ms": 12}],
                "source_route_incident_approval_state_transitions": [{"transition_code": "epsilon6-transition-demo", "transition_status": "blocked", "reason_code": "invalid_terminal_state", "control_code": "omega5-route-control-demo", "requested_decision": "reject", "approval_status_before": "approved", "approval_status_after": "approved"}],
                "source_route_incident_approval_audit_chain": [{"audit_hash_code": "epsilon6-audit-demo", "chain_scope": "route-approval:control_code:omega5-route-control-demo", "sequence_no": 1, "entity_type": "callback", "entity_code": "delta6-callback-demo", "entry_hash": "abc123", "verification_status": "chained"}],
                "source_route_incident_approval_sla_actions": [{"sla_action_code": "epsilon6-sla-demo", "action_status": "planned", "action_type": "escalate_risk_admin", "reason_code": "approval_timeout", "owner_principal_code": "platform-ops", "control_code": "omega5-route-control-demo"}],
                "source_route_incident_approval_recovery_drills": [{"drill_code": "epsilon6-drill-demo", "drill_type": "full", "status": "success", "check_count": 4, "passed_count": 4, "failed_count": 0}],
                "source_route_incident_approval_release_preflights": [{"preflight_code": "zeta6-preflight-demo", "environment": "local", "status": "success", "release_version": "zeta6-local", "check_count": 5, "passed_count": 5, "failed_count": 0}],
                "source_route_incident_approval_secret_rotations": [{"rotation_code": "zeta6-rotation-demo", "environment": "local", "rotation_phase": "dual_accept", "status": "success", "verified_secret_label": "next"}],
                "source_route_incident_approval_concurrency_tests": [{"test_code": "zeta6-concurrency-demo", "environment": "local", "status": "success", "target_scope": "route-approval:control_code:omega5-route-control-demo", "callback_count": 8, "success_count": 1}],
                "source_route_incident_approval_audit_exports": [{"export_code": "zeta6-export-demo", "environment": "local", "status": "success", "chain_scope": "route-approval:control_code:omega5-route-control-demo", "included_entity_count": 12, "package_hash": "abc123"}],
                "vendor_live_gates": [{"gate_code": "epsilon3-live-gate-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "run_mode": "blocked", "status": "blocked", "live_base_url_present": False, "live_token_present": False}],
                "vendor_readiness": [{"source_code": "vendor_http", "dataset_code": "daily_bar", "status": "ready", "recommendation": "approve_primary"}],
                "worker_runs": [{"run_code": "lambda-worker-test", "status": "success"}],
                "worker_schedules": [{"schedule_code": "mu_usage_rollup_5m", "task_name": "usage_rollup"}],
                "worker_heartbeats": [{"scheduler_id": "mu-test", "status": "running"}],
                "worker_ticks": [{"schedule_code": "mu_usage_rollup_5m", "status": "success"}],
                "deployment_health": [{"snapshot_code": "nu-health-test", "status": "success"}],
                "deployment_releases": [{"release_code": "nu-local", "status": "healthy"}],
                "products": [{"product_code": "a_share_daily_core", "status": "active"}],
                "budget_policies": [{"budget_code": "demo_quant_budget", "latest_usage_status": "warning"}],
                "budget_usage": [{"budget_code": "demo_quant_budget", "status": "warning"}],
                "budget_alerts": [{"budget_code": "demo_quant_budget", "alert_type": "budget_threshold_warning"}],
                "invoices": [{"invoice_code": "inv-demo-quant-research", "status": "issued", "total_amount": "0.16002800"}],
                "revenue_summary": [{"tenant_code": "demo", "project_code": "quant-research", "total_amount": "0.16002800"}],
                "reconciliation": [{"reconciliation_code": "rho-recon-demo", "status": "matched", "amount_delta": "0E-8"}],
                "ar_aging": [{"aging_code": "rho-ar-demo", "status": "current", "outstanding_amount": "0.00000000"}],
                "customer_health": [{"health_code": "rho-health-demo", "status": "active", "retention_signal": "healthy"}],
                "payment_batches": [{"batch_code": "tau-demo-payments-20260727", "source_type": "demo", "status": "matched", "transaction_count": 1}],
                "payments": [{"transaction_code": "tau-demo-payment-20260727", "invoice_code": "inv-demo-quant", "status": "matched", "amount": "100.00000000"}],
                "payment_matches": [{"match_code": "tau-match-demo", "invoice_code": "inv-demo-quant", "status": "matched", "matched_amount": "100.00000000"}],
                "revenue_ledger": [{"ledger_code": "tau-ledger-demo", "entry_type": "payment_received", "credit_amount": "100.00000000"}],
                "fx_rates": [{"rate_date": "2026-07-27", "from_currency": "CNY", "to_currency": "CNY", "rate": "1.000000000000"}],
                "runtime_logs": [{"log_time": "2026-07-26T12:00:00+00:00", "component": "sigma", "severity": "info", "event_type": "runtime_collection", "message": "<done>"}],
                "runtime_metrics": [{"metric_time": "2026-07-26T12:00:00+00:00", "component": "api", "metric_name": "api_request_count_7d", "metric_value": "227", "status": "warning"}],
                "runtime_daily_reports": [{"report_date": "2026-07-26", "environment": "local", "status": "warning", "api_request_count": 227, "open_capacity_alert_count": 1}],
                "capacity_alerts": [{"alert_key": "sigma-capacity-local-api-api-request-count-7d", "component": "api", "metric_name": "api_request_count_7d", "severity": "medium", "status": "open"}],
            }
        )

        self.assertIn("QData Kappa Ops Console", html)
        self.assertIn("&lt;ops&gt;", html)
        self.assertIn("API Usage", html)
        self.assertIn("Access Decisions", html)
        self.assertIn("Project Governance", html)
        self.assertIn("Governance Actions", html)
        self.assertIn("Automation Runs", html)
        self.assertIn("Automation Actions", html)
        self.assertIn("Automation Approvals", html)
        self.assertIn("Automation Attempts", html)
        self.assertIn("Automation Rollbacks", html)
        self.assertIn("Automation Executors", html)
        self.assertIn("Automation Allowlists", html)
        self.assertIn("Automation Secrets", html)
        self.assertIn("Automation Channels", html)
        self.assertIn("Automation Dispatches", html)
        self.assertIn("Automation Runbooks", html)
        self.assertIn("Automation Channel Profiles", html)
        self.assertIn("Automation Channel Validations", html)
        self.assertIn("Automation Secret Rotations", html)
        self.assertIn("Automation Live Receipts", html)
        self.assertIn("alpha2-script-notify-owner", html)
        self.assertIn("alpha2-script-reporter", html)
        self.assertIn("alpha2-local-hmac", html)
        self.assertIn("beta2-local-approval-webhook", html)
        self.assertIn("beta2-webhook-timeout", html)
        self.assertIn("gamma2-local-feishu-profile", html)
        self.assertIn("gamma2-rotation-demo", html)
        self.assertIn("delta2-wecom-receipt-demo", html)
        self.assertIn("Vendor Onboarding Runs", html)
        self.assertIn("Vendor Onboarding Results", html)
        self.assertIn("zeta3-onboarding-demo", html)
        self.assertIn("Vendor Live Closures", html)
        self.assertIn("Vendor Live Probes", html)
        self.assertIn("eta3-live-closure-demo", html)
        self.assertIn("eta3-live-probe-demo", html)
        self.assertIn("Vendor Live Pilots", html)
        self.assertIn("Vendor Live Pilot Results", html)
        self.assertIn("theta3-live-pilot-demo", html)
        self.assertIn("theta3-live-pilot-result-demo", html)
        self.assertIn("Vendor Contract Profiles", html)
        self.assertIn("Vendor Contract Entitlements", html)
        self.assertIn("Vendor Procurement Readiness", html)
        self.assertIn("omicron5-contract-vendor_http-draft", html)
        self.assertIn("omicron5-entitlement-vendor_http-daily_bar", html)
        self.assertIn("omicron5-procurement-demo", html)
        self.assertIn("Vendor Cost Optimizations", html)
        self.assertIn("Vendor Route Weight Plans", html)
        self.assertIn("Vendor Budget Stress", html)
        self.assertIn("Vendor Route Executions", html)
        self.assertIn("Vendor Route Execution Datasets", html)
        self.assertIn("Vendor Route Rollout Stages", html)
        self.assertIn("Source Route Weight Policies", html)
        self.assertIn("Source Route Decisions", html)
        self.assertIn("Source Route Health", html)
        self.assertIn("Source Route Circuit Breakers", html)
        self.assertIn("Source Route Recovery Probes", html)
        self.assertIn("Source Route Incident Actions", html)
        self.assertIn("Source Route Incident Controls", html)
        self.assertIn("Source Route Incident Control Health", html)
        self.assertIn("Source Route Incident Operation Batches", html)
        self.assertIn("Source Route Incident Operation Items", html)
        self.assertIn("Source Route Incident Approval Commands", html)
        self.assertIn("Source Route Incident Approval Command Items", html)
        self.assertIn("Source Route Incident Approval Signatures", html)
        self.assertIn("Source Route Incident Approval Lock Events", html)
        self.assertIn("Source Route Incident Approval State Transitions", html)
        self.assertIn("Source Route Incident Approval Audit Chain", html)
        self.assertIn("Source Route Incident Approval SLA Actions", html)
        self.assertIn("Source Route Incident Approval Recovery Drills", html)
        self.assertIn("Source Route Incident Approval Release Preflights", html)
        self.assertIn("Source Route Incident Approval Secret Rotations", html)
        self.assertIn("Source Route Incident Approval Concurrency Tests", html)
        self.assertIn("Source Route Incident Approval Audit Exports", html)
        self.assertIn("gamma6-route-approval-demo", html)
        self.assertIn("gamma6-sig-demo", html)
        self.assertIn("epsilon6-lock-demo", html)
        self.assertIn("epsilon6-transition-demo", html)
        self.assertIn("epsilon6-audit-demo", html)
        self.assertIn("epsilon6-sla-demo", html)
        self.assertIn("epsilon6-drill-demo", html)
        self.assertIn("zeta6-preflight-demo", html)
        self.assertIn("zeta6-rotation-demo", html)
        self.assertIn("zeta6-concurrency-demo", html)
        self.assertIn("zeta6-export-demo", html)
        self.assertIn("data-gamma6-action", html)
        self.assertIn("tau5-cost-optimization-demo", html)
        self.assertIn("tau5-route-weight-demo", html)
        self.assertIn("tau5-budget-stress-demo", html)
        self.assertIn("upsilon5-route-execution-demo", html)
        self.assertIn("upsilon5-route-dataset-demo", html)
        self.assertIn("upsilon5-route-stage-demo", html)
        self.assertIn("upsilon5-route-policy-demo", html)
        self.assertIn("phi5-route-decision-demo", html)
        self.assertIn("chi5-route-health-demo", html)
        self.assertIn("chi5-breaker-demo", html)
        self.assertIn("chi5-probe-demo", html)
        self.assertIn("psi5-route-incident-demo", html)
        self.assertIn("omega5-route-control-demo", html)
        self.assertIn("alpha6-route-control-health-demo", html)
        self.assertIn("beta6-route-ops-demo", html)
        self.assertIn("Vendor Live Gates", html)
        self.assertIn("epsilon3-live-gate-demo", html)
        self.assertIn("&lt;denied&gt;", html)
        self.assertIn("Vendor Readiness", html)
        self.assertIn("Worker Runs", html)
        self.assertIn("Worker Schedules", html)
        self.assertIn("Scheduler Heartbeats", html)
        self.assertIn("Scheduler Ticks", html)
        self.assertIn("Deployment Health", html)
        self.assertIn("Deployment Releases", html)
        self.assertIn("Data Products", html)
        self.assertIn("Budget Policies", html)
        self.assertIn("Budget Usage", html)
        self.assertIn("Budget Alerts", html)
        self.assertIn("Invoices", html)
        self.assertIn("Revenue Summary", html)
        self.assertIn("Revenue Reconciliation", html)
        self.assertIn("AR Aging", html)
        self.assertIn("Customer Health", html)
        self.assertIn("Payment Batches", html)
        self.assertIn("Payments", html)
        self.assertIn("Payment Matches", html)
        self.assertIn("Revenue Ledger", html)
        self.assertIn("FX Rates", html)
        self.assertIn("Runtime Logs", html)
        self.assertIn("&lt;done&gt;", html)
        self.assertIn("Runtime Metrics", html)
        self.assertIn("Runtime Daily Reports", html)
        self.assertIn("Capacity Alerts", html)


if __name__ == "__main__":
    unittest.main()
