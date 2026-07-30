from __future__ import annotations

import unittest

from qdata.kappa import render_kappa_console


class UpsilonConsoleTest(unittest.TestCase):
    def test_console_contains_interactive_controls_and_payment_views(self) -> None:
        html = render_kappa_console(
            {
                "overview": {
                    "active_tenant_count": 1,
                    "active_project_count": 1,
                    "active_token_count": 1,
                    "open_alert_count": 1,
                    "payment_month_received_amount": "100.00000000",
                    "payment_month_matched_amount": "100.00000000",
                    "unmatched_payment_count": 0,
                    "latest_payment_batch_status": "matched",
                    "runtime_metric_warning_count": 1,
                    "open_capacity_alert_count": 1,
                    "latest_strategy_status": "warning",
                    "latest_strategy_severity": "high",
                    "strategy_24h_action_decision_count": 2,
                    "open_strategy_escalation_count": 1,
                    "access_denied_24h_count": 1,
                    "project_governance_warning_count": 1,
                    "project_governance_critical_count": 0,
                    "open_governance_action_count": 1,
                    "automation_24h_run_count": 1,
                    "automation_24h_action_count": 3,
                    "automation_approval_required_count": 1,
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
                    "free_source_24h_recovery_action_count": 2,
                    "free_source_24h_recovery_alert_count": 1,
                    "latest_free_source_recovery_status": "warning",
                    "free_source_24h_recovery_execution_count": 1,
                    "free_source_24h_recovered_count": 1,
                    "free_source_24h_recovery_failed_count": 0,
                    "latest_free_source_recovery_execution_status": "review_requested",
                    "free_source_24h_recovery_health_count": 1,
                    "latest_free_source_recovery_health_status": "warning",
                    "free_source_recovery_overdue_approval_count": 0,
                    "free_source_recovery_backlog_count": 2,
                    "free_source_24h_admission_count": 2,
                    "free_source_24h_admission_approved_count": 0,
                    "free_source_24h_admission_conditional_count": 1,
                    "free_source_24h_admission_review_required_count": 1,
                    "free_source_24h_admission_blocked_count": 0,
                    "free_source_24h_admission_no_data_count": 0,
                    "latest_free_source_admission_status": "review_required",
                    "free_source_primary_candidate_count": 0,
                },
                "usage": [{"usage_date": "2026-07-27", "project_code": "<ops>", "api_name": "admin/console"}],
                "access_decisions": [{"decision_code": "chi-access-demo", "decision": "deny", "reason": "dataset access denied"}],
                "project_governance": [{"snapshot_code": "chi-gov-demo", "status": "warning", "recommended_action": "review_access_policy"}],
                "governance_actions": [{"action_code": "chi-action-demo", "action_type": "review_access_policy", "status": "open", "severity": "medium"}],
                "automation_runs": [{"run_code": "psi-local-20260727-dry-run", "execution_mode": "dry_run", "status": "success", "action_count": 3}],
                "automation_actions": [{"action_code": "psi-action-demo", "source_type": "phi_decision", "action_type": "escalate_commercial", "status": "skipped"}],
                "automation_approvals": [{"approval_code": "omega-approval-demo", "action_code": "psi-action-demo", "status": "pending"}],
                "automation_attempts": [{"attempt_code": "omega-attempt-demo", "action_code": "psi-action-demo", "status": "approval_required"}],
                "automation_rollbacks": [{"rollback_code": "omega-rollback-demo", "action_code": "psi-action-demo", "status": "planned"}],
                "automation_executors": [{"executor_code": "alpha2-script-notify-owner", "action_type": "notify_owner", "executor_type": "script", "status": "active", "sandbox_mode": True, "allowlist_code": "alpha2-script-reporter"}],
                "automation_allowlists": [{"allowlist_code": "alpha2-script-reporter", "executor_type": "script", "target_pattern": "scripts/alpha2_executor_sandbox.py", "status": "active"}],
                "automation_secrets": [{"secret_ref": "alpha2-local-hmac", "secret_kind": "hmac", "status": "active", "owner": "platform-ops"}],
                "automation_channels": [{"channel_code": "beta2-local-approval-webhook", "channel_type": "webhook", "environment": "local", "status": "active"}],
                "automation_dispatches": [{"dispatch_code": "beta2-dispatch-demo", "action_code": "omega-smoke-retry-action", "channel_code": "beta2-local-approval-webhook", "dispatch_type": "approval_request", "status": "acknowledged"}],
                "automation_runbooks": [{"runbook_code": "beta2-webhook-timeout", "failure_class": "webhook_timeout", "severity": "high", "status": "active"}],
                "automation_channel_profiles": [{"profile_code": "gamma2-local-feishu-profile", "channel_code": "gamma2-local-feishu-dryrun", "provider_code": "feishu", "environment": "local", "profile_status": "active", "readiness_status": "dry_run_ready"}],
                "automation_channel_validations": [{"validation_code": "gamma2-validation-demo", "profile_code": "gamma2-local-feishu-profile", "channel_code": "gamma2-local-feishu-dryrun", "provider_code": "feishu", "validation_type": "secret_rotation", "status": "success"}],
                "automation_secret_rotations": [{"rotation_code": "gamma2-rotation-demo", "environment": "local", "secret_ref": "gamma2-local-hmac-current", "next_secret_ref": "gamma2-local-hmac-next", "rotation_type": "drill", "status": "applied"}],
                "automation_live_receipts": [{"receipt_code": "delta2-wecom-receipt-demo", "validation_code": "delta2-wecom-validation-demo", "profile_code": "delta2-wecom-live-profile", "channel_code": "delta2-wecom-live-webhook", "provider_code": "wecom", "environment": "live_test", "message_type": "markdown", "status": "success", "provider_errcode": 0}],
                "vendor_onboarding_runs": [{"run_code": "zeta3-onboarding-demo", "source_code": "vendor_http", "status": "blocked", "preflight_status": "blocked", "recommendation": "research_only"}],
                "vendor_onboarding_results": [{"run_code": "zeta3-onboarding-demo", "dataset_code": "daily_bar", "stage_status": "blocked", "gate_status": "blocked", "gate_code": "epsilon3-live-gate-demo"}],
                "vendor_live_closures": [{"closure_code": "eta3-live-closure-demo", "source_code": "vendor_http", "status": "blocked", "config_status": "blocked", "endpoint_status": "blocked", "recommendation": "research_only"}],
                "vendor_live_probes": [{"closure_code": "eta3-live-closure-demo", "probe_code": "eta3-live-probe-demo", "dataset_code": "daily_bar", "status": "blocked", "auth_status": "blocked", "schema_status": "skipped"}],
                "vendor_live_pilots": [{"pilot_code": "theta3-live-pilot-demo", "source_code": "vendor_http", "status": "blocked", "pilot_scope": "canary", "closure_status": "blocked", "signoff_status": "not_ready", "risk_level": "high"}],
                "vendor_live_pilot_results": [{"pilot_code": "theta3-live-pilot-demo", "result_code": "theta3-live-pilot-result-demo", "dataset_code": "daily_bar", "status": "blocked", "schema_status": "skipped", "risk_level": "high"}],
                "vendor_contract_profiles": [{"contract_code": "omicron5-contract-vendor_http-draft", "source_code": "vendor_http", "provider_name": "Commercial HTTP Vendor", "procurement_status": "review_required", "contract_status": "draft", "commercial_clearance": "review_required"}],
                "vendor_contract_entitlements": [{"entitlement_code": "omicron5-entitlement-vendor_http-daily_bar", "contract_code": "omicron5-contract-vendor_http-draft", "source_code": "vendor_http", "dataset_code": "daily_bar", "entitlement_status": "review_required", "allowed_role": "primary_candidate", "schema_status": "pending"}],
                "vendor_procurement_readiness": [{"snapshot_code": "omicron5-procurement-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "status": "review_required", "procurement_role": "validator", "contract_status": "draft", "entitlement_status": "review_required"}],
                "vendor_primary_promotions": [{"promotion_code": "pi5-primary-promotion-demo", "source_code": "vendor_http", "primary_source_code": "csv", "status": "blocked", "promotion_scope": "full_market", "apply_mode": "review_only", "dataset_count": 7, "blocked_dataset_count": 7}],
                "vendor_primary_promotion_results": [{"promotion_code": "pi5-primary-promotion-demo", "result_code": "pi5-primary-promotion-result-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "status": "blocked", "promotion_role": "blocked", "procurement_status": "review_required"}],
                "vendor_post_promotion_monitors": [{"monitor_code": "rho5-post-promotion-demo", "promotion_code": "pi5-primary-promotion-demo", "source_code": "vendor_http", "primary_source_code": "csv", "status": "no_applied_promotion", "monitor_scope": "post_promotion", "rollback_mode": "review_only", "dataset_count": 7, "no_applied_dataset_count": 7}],
                "vendor_post_promotion_results": [{"monitor_code": "rho5-post-promotion-demo", "result_code": "rho5-post-promotion-result-demo", "promotion_code": "pi5-primary-promotion-demo", "promotion_result_code": "pi5-primary-promotion-result-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "status": "no_applied_promotion", "monitor_scope": "post_promotion", "rollback_mode": "review_only", "promotion_status": "blocked", "shadow_status": "not_available"}],
                "vendor_primary_stability": [{"snapshot_code": "sigma5-primary-stability-demo", "source_code": "vendor_http", "primary_source_code": "csv", "status": "no_primary_promotion", "stability_role": "watch", "monitor_scope": "primary_source", "dataset_count": 7, "primary_dataset_count": 0, "no_primary_dataset_count": 7, "api_success_rate": "1.000000", "scheduler_lag_minutes": 0, "stability_score": "0.0000"}],
                "vendor_primary_stability_datasets": [{"snapshot_code": "sigma5-primary-stability-demo", "dataset_snapshot_code": "sigma5-primary-stability-dataset-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "primary_source_code": "csv", "status": "no_primary_promotion", "stability_role": "watch", "is_primary_route": False, "current_primary_source_code": "csv", "entitlement_status": "review_required", "promotion_status": "blocked"}],
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
                "source_route_incident_approval_role_bindings": [{"binding_code": "delta6-role-demo", "principal_code": "approver-a", "role_code": "route_approver", "dataset_code": "*", "source_code": "*", "safety_level": "*", "status": "active"}],
                "source_route_incident_approval_policies": [{"policy_code": "delta6-default-route-approval-policy", "dataset_code": "*", "source_code": "*", "safety_level": "*", "status": "active", "min_approvals": 2, "require_distinct_requester": True, "require_wecom_signature": True, "timeout_minutes": 240}],
                "source_route_incident_approval_callbacks": [{"callback_code": "delta6-callback-demo", "provider_code": "wecom", "signature_status": "verified", "governance_status": "pending_quorum", "decision": "approve", "signer_code": "approver-a", "control_code": "omega5-route-control-demo", "command_code": "gamma6-route-approval-demo", "replay_count": 1}],
                "source_route_incident_approval_escalations": [{"escalation_code": "delta6-escalation-demo", "reason_code": "approval_timeout", "status": "open", "severity": "high", "owner_principal_code": "platform-ops", "control_code": "omega5-route-control-demo"}],
                "source_route_incident_approval_lock_events": [{"lock_event_code": "epsilon6-lock-demo", "lock_status": "released", "lock_scope": "route-approval:control_code:omega5-route-control-demo", "provider_code": "wecom", "control_code": "omega5-route-control-demo", "callback_code": "delta6-callback-demo", "command_code": "gamma6-route-approval-demo", "held_ms": 12}],
                "source_route_incident_approval_state_transitions": [{"transition_code": "epsilon6-transition-demo", "transition_status": "blocked", "reason_code": "invalid_terminal_state", "control_code": "omega5-route-control-demo", "requested_decision": "reject", "approval_status_before": "approved", "approval_status_after": "approved"}],
                "source_route_incident_approval_audit_chain": [{"audit_hash_code": "epsilon6-audit-demo", "chain_scope": "route-approval:control_code:omega5-route-control-demo", "sequence_no": 1, "entity_type": "callback", "entity_code": "delta6-callback-demo", "entry_hash": "abc123", "verification_status": "chained"}],
                "source_route_incident_approval_sla_actions": [{"sla_action_code": "epsilon6-sla-demo", "action_status": "planned", "action_type": "escalate_risk_admin", "reason_code": "approval_timeout", "owner_principal_code": "platform-ops", "control_code": "omega5-route-control-demo"}],
                "source_route_incident_approval_recovery_drills": [{"drill_code": "epsilon6-drill-demo", "drill_type": "full", "status": "success", "check_count": 4, "passed_count": 4, "failed_count": 0}],
                "source_route_incident_approval_release_preflights": [{"preflight_code": "zeta6-preflight-demo", "environment": "local", "status": "success", "release_version": "zeta6-local", "check_count": 5, "passed_count": 5, "failed_count": 0}],
                "source_route_incident_approval_secret_rotations": [{"rotation_code": "zeta6-rotation-demo", "environment": "local", "rotation_phase": "dual_accept", "status": "success", "verified_secret_label": "next"}],
                "source_route_incident_approval_concurrency_tests": [{"test_code": "zeta6-concurrency-demo", "environment": "local", "status": "success", "target_scope": "route-approval:control_code:omega5-route-control-demo", "callback_count": 8, "success_count": 1}],
                "source_route_incident_approval_audit_exports": [{"export_code": "zeta6-export-demo", "environment": "local", "status": "success", "chain_scope": "route-approval:control_code:omega5-route-control-demo", "included_entity_count": 12, "package_hash": "abc123"}],
                "free_source_fabric_runs": [{"fabric_code": "iota3-free-source-fabric-demo", "status": "success", "fabric_scope": "canary", "recommendation": "backup", "risk_level": "low", "coverage_rate": "1.000000", "conflict_rate_bps": "0.000000"}],
                "free_source_fabric_results": [{"fabric_code": "iota3-free-source-fabric-demo", "result_code": "iota3-free-source-result-demo", "dataset_code": "daily_bar", "status": "success", "coverage_status": "success", "consistency_status": "success", "license_status": "local_smoke", "risk_level": "low"}],
                "free_source_reliability": [{"snapshot_code": "kappa5-free-source-demo", "source_code": "sse_public", "dataset_code": "daily_bar", "status": "ready", "recommended_role": "backup", "reliability_score": "82.0000", "commercial_clearance": "review_required"}],
                "free_source_recovery_runs": [{"recovery_code": "lambda5-free-source-recovery-demo", "status": "warning", "action_count": 2, "manual_review_action_count": 1, "created_alert_count": 1}],
                "free_source_recovery_actions": [{"action_code": "lambda5-akshare-daily_bar-retry", "recovery_code": "lambda5-free-source-recovery-demo", "source_code": "akshare", "dataset_code": "daily_bar", "action_type": "retry_canary", "status": "alerted", "severity": "high"}],
                "free_source_recovery_executions": [{"execution_code": "mu5-manual-review-demo", "action_code": "lambda5-akshare-daily_bar-retry", "source_code": "akshare", "dataset_code": "daily_bar", "execution_type": "manual_review", "status": "review_requested", "approval_code": "omega-approval-mu5-demo", "wecom_receipt_code": "delta2-wecom-receipt-mu5-demo"}],
                "free_source_recovery_health": [{"snapshot_code": "nu5-recovery-health-demo", "status": "warning", "backlog_count": 2, "approval_pending_count": 1, "approval_overdue_count": 0, "failure_rate": "0.0000", "health_issues": ["recovery_backlog_pending"]}],
                "free_source_admission": [{"snapshot_code": "xi5-admission-demo", "source_code": "akshare", "dataset_code": "daily_bar", "status": "review_required", "admission_role": "validator", "commercial_clearance": "blocked", "redistribution_allowed": "no", "contract_status": "none", "terms_review_status": "pending", "reliability_score": "82.0000", "blocking_issues": ["license_status_research_only"]}],
                "free_source_admission_profiles": [{"profile_code": "xi5-profile-akshare", "source_code": "akshare", "provider_name": "akshare", "license_type": "open_source", "license_status": "research_only", "commercial_clearance": "blocked", "redistribution_allowed": "no", "contract_status": "none", "terms_review_status": "pending", "max_allowed_role": "validator", "status": "active"}],
                "vendor_live_gates": [{"gate_code": "epsilon3-live-gate-demo", "source_code": "vendor_http", "dataset_code": "daily_bar", "run_mode": "blocked", "status": "blocked"}],
                "payment_batches": [{"batch_code": "tau-demo-payments-20260727", "status": "matched", "transaction_count": 1}],
                "payment_matches": [{"match_code": "tau-match-demo", "invoice_status": "paid", "matched_amount": "100.00000000"}],
                "revenue_ledger": [{"ledger_code": "tau-ledger-demo", "entry_type": "payment_received", "credit_amount": "100.00000000"}],
                "runtime_metrics": [{"metric_name": "api_request_count_7d", "status": "warning"}],
                "capacity_alerts": [{"alert_key": "sigma-capacity-local-api", "status": "open", "severity": "medium"}],
                "strategy_decisions": [{"decision_code": "phi-decision-demo", "domain": "runtime", "action": "investigate_runtime", "status": "block", "severity": "critical"}],
                "strategy_escalations": [{"event_code": "phi-escalation-demo", "status": "open", "severity": "critical", "owner": "platform-ops"}],
            }
        )

        self.assertIn("QData Upsilon Ops Console", html)
        self.assertIn("QData Kappa Ops Console", html)
        self.assertIn("data-upsilon-controls", html)
        self.assertIn('data-view-button="payments"', html)
        self.assertIn('data-view-button="governance"', html)
        self.assertIn('data-view-button="strategy"', html)
        self.assertIn('data-view-button="free_source"', html)
        self.assertIn('data-view="payments"', html)
        self.assertIn('data-view="governance"', html)
        self.assertIn('data-view="strategy"', html)
        self.assertIn('data-view="free_source"', html)
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
        self.assertIn("Vendor Onboarding Runs", html)
        self.assertIn("Vendor Onboarding Results", html)
        self.assertIn("Vendor Live Closures", html)
        self.assertIn("Vendor Live Probes", html)
        self.assertIn("Vendor Live Pilots", html)
        self.assertIn("Vendor Live Pilot Results", html)
        self.assertIn("Vendor Contract Profiles", html)
        self.assertIn("Vendor Contract Entitlements", html)
        self.assertIn("Vendor Procurement Readiness", html)
        self.assertIn("Vendor Primary Promotions", html)
        self.assertIn("Vendor Primary Promotion Results", html)
        self.assertIn("Vendor Post Promotion Monitors", html)
        self.assertIn("Vendor Post Promotion Results", html)
        self.assertIn("Vendor Primary Stability", html)
        self.assertIn("Vendor Primary Stability Datasets", html)
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
        self.assertIn("Source Route Incident Approval Role Bindings", html)
        self.assertIn("Source Route Incident Approval Policies", html)
        self.assertIn("Source Route Incident Approval Callbacks", html)
        self.assertIn("Source Route Incident Approval Escalations", html)
        self.assertIn("Source Route Incident Approval Lock Events", html)
        self.assertIn("Source Route Incident Approval State Transitions", html)
        self.assertIn("Source Route Incident Approval Audit Chain", html)
        self.assertIn("Source Route Incident Approval SLA Actions", html)
        self.assertIn("Source Route Incident Approval Recovery Drills", html)
        self.assertIn("gamma6-route-approval-demo", html)
        self.assertIn("gamma6-sig-demo", html)
        self.assertIn("delta6-role-demo", html)
        self.assertIn("delta6-default-route-approval-policy", html)
        self.assertIn("delta6-callback-demo", html)
        self.assertIn("delta6-escalation-demo", html)
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
        self.assertIn("omega5-route-control-demo", html)
        self.assertIn("alpha6-route-control-health-demo", html)
        self.assertIn("beta6-route-ops-demo", html)
        self.assertIn("Free Source Fabric Runs", html)
        self.assertIn("Free Source Fabric Results", html)
        self.assertIn("Free Source Reliability", html)
        self.assertIn("Free Source Recovery Runs", html)
        self.assertIn("Free Source Recovery Actions", html)
        self.assertIn("Free Source Recovery Executions", html)
        self.assertIn("Free Source Recovery Health", html)
        self.assertIn("Free Source Admission", html)
        self.assertIn("Free Source Admission Profiles", html)
        self.assertIn("Vendor Live Gates", html)
        self.assertIn("alpha2-script-reporter", html)
        self.assertIn("alpha2-local-hmac", html)
        self.assertIn("beta2-local-approval-webhook", html)
        self.assertIn("beta2-webhook-timeout", html)
        self.assertIn("gamma2-local-feishu-profile", html)
        self.assertIn("gamma2-rotation-demo", html)
        self.assertIn("delta2-wecom-receipt-demo", html)
        self.assertIn("zeta3-onboarding-demo", html)
        self.assertIn("eta3-live-closure-demo", html)
        self.assertIn("eta3-live-probe-demo", html)
        self.assertIn("theta3-live-pilot-demo", html)
        self.assertIn("theta3-live-pilot-result-demo", html)
        self.assertIn("omicron5-contract-vendor_http-draft", html)
        self.assertIn("omicron5-entitlement-vendor_http-daily_bar", html)
        self.assertIn("omicron5-procurement-demo", html)
        self.assertIn("pi5-primary-promotion-demo", html)
        self.assertIn("pi5-primary-promotion-result-demo", html)
        self.assertIn("rho5-post-promotion-demo", html)
        self.assertIn("rho5-post-promotion-result-demo", html)
        self.assertIn("sigma5-primary-stability-demo", html)
        self.assertIn("sigma5-primary-stability-dataset-demo", html)
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
        self.assertIn("iota3-free-source-fabric-demo", html)
        self.assertIn("iota3-free-source-result-demo", html)
        self.assertIn("kappa5-free-source-demo", html)
        self.assertIn("lambda5-free-source-recovery-demo", html)
        self.assertIn("lambda5-akshare-daily_bar-retry", html)
        self.assertIn("mu5-manual-review-demo", html)
        self.assertIn("nu5-recovery-health-demo", html)
        self.assertIn("xi5-admission-demo", html)
        self.assertIn("xi5-profile-akshare", html)
        self.assertIn("omega-approval-mu5-demo", html)
        self.assertIn("epsilon3-live-gate-demo", html)
        self.assertIn("Payment Batches", html)
        self.assertIn("Payment Matches", html)
        self.assertIn("Revenue Ledger", html)
        self.assertIn("Runtime Metrics", html)
        self.assertIn("Capacity Alerts", html)
        self.assertIn("Strategy Decisions", html)
        self.assertIn("Strategy Escalations", html)
        self.assertIn("status-chip matched", html)
        self.assertIn("status-chip critical", html)
        self.assertIn("&lt;ops&gt;", html)

    def test_console_table_filtering_script_is_embedded(self) -> None:
        html = render_kappa_console({"overview": {}, "payments": [{"transaction_code": "tau-pay-001", "status": "matched"}]})

        self.assertIn("console-search", html)
        self.assertIn("console-status", html)
        self.assertIn("applyFilters", html)
        self.assertIn("data-visible-count", html)


if __name__ == "__main__":
    unittest.main()
