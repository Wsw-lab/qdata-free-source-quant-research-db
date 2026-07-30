from datetime import datetime, timezone
import unittest

from qdata.exceptions import QDataValidationError
from qdata.mu_scheduler import (
    MuSchedulerResult,
    MuTickResult,
    build_worker_kwargs,
    compute_next_run_at,
    format_scheduler_report,
    normalize_schedule_codes,
    normalize_task_names,
)


class MuSchedulerTest(unittest.TestCase):
    def test_normalize_schedule_codes_dedupes_and_ignores_blanks(self) -> None:
        self.assertIsNone(normalize_schedule_codes(None))
        self.assertEqual(normalize_schedule_codes(["mu_usage", " ", "mu_usage", "mu_alert"]), ["mu_usage", "mu_alert"])

    def test_normalize_task_names_validates_worker_tasks(self) -> None:
        self.assertEqual(normalize_task_names(["usage_rollup", "usage_rollup"]), ["usage_rollup"])
        with self.assertRaises(QDataValidationError):
            normalize_task_names(["unknown"])

    def test_build_worker_kwargs_merges_schedule_args_and_overrides_dates(self) -> None:
        schedule = {
            "dry_run": False,
            "task_args": {
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "alert_limit": 10,
                "free_source_lookback_hours": 72,
                "free_source_max_actions": 20,
                "mu5_max_actions": 5,
                "mu5_start_date": "2024-01-04",
                "mu5_end_date": "2024-01-04",
                "nu5_lookback_hours": 24,
                "nu5_approval_sla_hours": 4,
                "nu5_max_backlog_actions": 50,
                "nu5_max_failure_rate": 0.5,
                "nu5_max_stale_minutes": 90,
                "xi5_lookback_days": 30,
                "xi5_min_validator_score": 55,
                "xi5_min_backup_score": 75,
                "xi5_min_primary_score": 90,
                "xi5_min_coverage_rate": 0.95,
                "xi5_max_conflict_rate_bps": 5,
                "omicron5_min_sla_uptime_pct": 99.5,
                "omicron5_min_rate_limit_per_min": 60,
                "omicron5_require_live_evidence": False,
                "pi5_promotion_scope": "full_market",
                "pi5_require_full_market": True,
                "pi5_require_signoff": True,
                "pi5_apply_routing": False,
                "pi5_target_priority": 0,
                "rho5_monitor_scope": "post_promotion",
                "rho5_require_applied_promotion": True,
                "rho5_apply_rollback": False,
                "rho5_shadow_window_hours": 24,
                "rho5_max_conflict_rate_bps": 5,
                "rho5_max_failure_rate": 0.01,
                "rho5_max_stale_minutes": 90,
                "sigma5_monitor_scope": "primary_source",
                "sigma5_lookback_hours": 24,
                "sigma5_capacity_window_days": 7,
                "sigma5_min_success_rate": 0.995,
                "sigma5_max_error_rate": 0.005,
                "sigma5_max_latency_p95_ms": 2000,
                "sigma5_max_timeout_rate": 0.01,
                "sigma5_max_cost_units": 500,
                "sigma5_max_scheduler_lag_minutes": 90,
                "sigma5_max_backlog_count": 50,
                "sigma5_max_post_promotion_no_applied_count": 0,
                "tau5_optimization_scope": "primary_source",
                "tau5_lookback_hours": 24,
                "tau5_forecast_window_days": 30,
                "tau5_monthly_budget_amount": 10000,
                "tau5_max_budget_usage_pct": 0.85,
                "tau5_max_daily_quota_usage_pct": 0.85,
                "tau5_max_monthly_quota_usage_pct": 0.85,
                "tau5_min_stability_score": 70,
                "tau5_cost_safety_margin_pct": 0.15,
                "tau5_default_unit_cost": 0.01,
                "tau5_stress_multipliers": [1, 5, 10],
                "upsilon5_execution_scope": "primary_source",
                "upsilon5_execution_mode": "review_only",
                "upsilon5_approval_policy": "manual_required",
                "upsilon5_approval_status": "pending",
                "upsilon5_rollout_policy": "gradual",
                "upsilon5_rollout_stages": [10, 30, 60, 90],
                "upsilon5_current_stage_sequence": 1,
                "upsilon5_max_initial_primary_weight_pct": 10,
                "upsilon5_allow_over_budget": False,
                "upsilon5_allow_quota_risk": False,
                "upsilon5_rollback_requested": False,
                "chi5_lookback_hours": 24,
                "chi5_min_request_count": 1,
                "chi5_min_success_rate": 0.95,
                "chi5_max_failure_rate": 0.1,
                "chi5_max_fallback_rate": 0.2,
                "chi5_max_empty_rate": 0.2,
                "chi5_max_latency_p95_ms": 2000,
                "chi5_circuit_open_minutes": 30,
                "chi5_recovery_probe_min_success_rate": 1.0,
                "psi5_route_lookback_hours": 24,
                "psi5_route_max_actions": 50,
                "psi5_route_execution_mode": "execute",
                "psi5_route_approve_high_risk": False,
                "psi5_route_approved_by": "route-ops",
                "psi5_route_owner": "platform-ops",
                "psi5_route_include_recovered": True,
                "omega5_route_lookback_hours": 24,
                "omega5_route_max_controls": 50,
                "omega5_route_execution_mode": "review_only",
                "omega5_route_auto_approve": False,
                "omega5_route_approved_by": "route-control-ops",
                "omega5_route_requested_by": "omega5",
                "omega5_route_approval_sla_hours": 4,
                "omega5_route_notify_wecom": True,
                "omega5_route_allow_wecom_external": False,
                "omega5_route_create_rollback": True,
                "alpha6_route_lookback_hours": 24,
                "alpha6_route_approval_sla_hours": 4,
                "alpha6_route_max_pending_controls": 50,
                "alpha6_route_max_failed_execution_rate": 0.1,
                "alpha6_route_max_blocked_receipt_rate": 0.8,
                "alpha6_route_max_stale_minutes": 90,
                "alpha6_route_requested_by": "alpha6",
                "alpha6_route_environment": "local",
                "alpha6_route_control_schedule_code": "omega5_route_incident_control_15m",
                "beta6_route_lookback_hours": 24,
                "beta6_route_max_controls": 100,
                "beta6_route_approval_decision": "hold",
                "beta6_route_apply_decisions": False,
                "beta6_route_requested_by": "beta6",
                "beta6_route_environment": "local",
                "beta6_route_notification_policy": "dedupe_digest",
                "beta6_route_stress_scope": "full_market",
                "beta6_route_notify_wecom": False,
                "beta6_route_allow_wecom_external": False,
                "epsilon6_sla_automation": True,
                "epsilon6_hash_verify": True,
                "epsilon6_recovery_drill": "hash_chain_verify",
                "epsilon6_requested_by": "epsilon6",
                "epsilon6_environment": "local",
                "epsilon6_sla_limit": 100,
                "epsilon6_audit_verify_limit": 1000,
                "zeta6_environment": "local",
                "zeta6_release_version": "zeta6-local",
                "zeta6_requested_by": "zeta6",
                "zeta6_require_dual_secret": False,
                "zeta6_export_audit": True,
                "zeta6_export_chain_scope": "route-approval:control_code:omega5-route-control-demo",
                "zeta6_export_control_code": "omega5-route-control-demo",
                "zeta6_export_limit": 1000,
                "eta6_source_code": "vendor_http",
                "eta6_primary_source_code": "csv",
                "eta6_dataset_codes": ["daily_bar", "security_master"],
                "eta6_environment": "local",
                "eta6_closure_scope": "production_primary",
                "eta6_closure_mode": "review_only",
                "eta6_requested_by": "eta6",
                "eta6_require_real_vendor_env": True,
                "eta6_external_probe_allowed": False,
                "eta6_min_stability_score": 70,
                "eta6_allow_cost_watch": False,
                "ignored": "value",
            },
        }

        kwargs = build_worker_kwargs(schedule, dry_run=True, trade_date="2026-07-24")

        self.assertEqual(kwargs["trade_date"], "2026-07-24")
        self.assertNotIn("start_date", kwargs)
        self.assertNotIn("ignored", kwargs)
        self.assertEqual(kwargs["alert_limit"], 10)
        self.assertEqual(kwargs["free_source_lookback_hours"], 72)
        self.assertEqual(kwargs["free_source_max_actions"], 20)
        self.assertEqual(kwargs["mu5_max_actions"], 5)
        self.assertEqual(kwargs["mu5_start_date"], "2024-01-04")
        self.assertEqual(kwargs["nu5_lookback_hours"], 24)
        self.assertEqual(kwargs["nu5_approval_sla_hours"], 4)
        self.assertEqual(kwargs["nu5_max_backlog_actions"], 50)
        self.assertEqual(kwargs["nu5_max_failure_rate"], 0.5)
        self.assertEqual(kwargs["nu5_max_stale_minutes"], 90)
        self.assertEqual(kwargs["xi5_lookback_days"], 30)
        self.assertEqual(kwargs["xi5_min_validator_score"], 55)
        self.assertEqual(kwargs["xi5_min_backup_score"], 75)
        self.assertEqual(kwargs["xi5_min_primary_score"], 90)
        self.assertEqual(kwargs["xi5_min_coverage_rate"], 0.95)
        self.assertEqual(kwargs["xi5_max_conflict_rate_bps"], 5)
        self.assertEqual(kwargs["omicron5_min_sla_uptime_pct"], 99.5)
        self.assertEqual(kwargs["omicron5_min_rate_limit_per_min"], 60)
        self.assertFalse(kwargs["omicron5_require_live_evidence"])
        self.assertEqual(kwargs["pi5_promotion_scope"], "full_market")
        self.assertTrue(kwargs["pi5_require_full_market"])
        self.assertTrue(kwargs["pi5_require_signoff"])
        self.assertFalse(kwargs["pi5_apply_routing"])
        self.assertEqual(kwargs["pi5_target_priority"], 0)
        self.assertEqual(kwargs["rho5_monitor_scope"], "post_promotion")
        self.assertTrue(kwargs["rho5_require_applied_promotion"])
        self.assertFalse(kwargs["rho5_apply_rollback"])
        self.assertEqual(kwargs["rho5_shadow_window_hours"], 24)
        self.assertEqual(kwargs["rho5_max_conflict_rate_bps"], 5)
        self.assertEqual(kwargs["rho5_max_failure_rate"], 0.01)
        self.assertEqual(kwargs["rho5_max_stale_minutes"], 90)
        self.assertEqual(kwargs["sigma5_monitor_scope"], "primary_source")
        self.assertEqual(kwargs["sigma5_lookback_hours"], 24)
        self.assertEqual(kwargs["sigma5_capacity_window_days"], 7)
        self.assertEqual(kwargs["sigma5_min_success_rate"], 0.995)
        self.assertEqual(kwargs["sigma5_max_error_rate"], 0.005)
        self.assertEqual(kwargs["sigma5_max_latency_p95_ms"], 2000)
        self.assertEqual(kwargs["sigma5_max_timeout_rate"], 0.01)
        self.assertEqual(kwargs["sigma5_max_cost_units"], 500)
        self.assertEqual(kwargs["sigma5_max_scheduler_lag_minutes"], 90)
        self.assertEqual(kwargs["sigma5_max_backlog_count"], 50)
        self.assertEqual(kwargs["sigma5_max_post_promotion_no_applied_count"], 0)
        self.assertEqual(kwargs["tau5_optimization_scope"], "primary_source")
        self.assertEqual(kwargs["tau5_lookback_hours"], 24)
        self.assertEqual(kwargs["tau5_forecast_window_days"], 30)
        self.assertEqual(kwargs["tau5_monthly_budget_amount"], 10000)
        self.assertEqual(kwargs["tau5_max_budget_usage_pct"], 0.85)
        self.assertEqual(kwargs["tau5_max_daily_quota_usage_pct"], 0.85)
        self.assertEqual(kwargs["tau5_max_monthly_quota_usage_pct"], 0.85)
        self.assertEqual(kwargs["tau5_min_stability_score"], 70)
        self.assertEqual(kwargs["tau5_cost_safety_margin_pct"], 0.15)
        self.assertEqual(kwargs["tau5_default_unit_cost"], 0.01)
        self.assertEqual(kwargs["tau5_stress_multipliers"], [1, 5, 10])
        self.assertEqual(kwargs["upsilon5_execution_scope"], "primary_source")
        self.assertEqual(kwargs["upsilon5_execution_mode"], "review_only")
        self.assertEqual(kwargs["upsilon5_approval_policy"], "manual_required")
        self.assertEqual(kwargs["upsilon5_approval_status"], "pending")
        self.assertEqual(kwargs["upsilon5_rollout_policy"], "gradual")
        self.assertEqual(kwargs["upsilon5_rollout_stages"], [10, 30, 60, 90])
        self.assertEqual(kwargs["upsilon5_current_stage_sequence"], 1)
        self.assertEqual(kwargs["upsilon5_max_initial_primary_weight_pct"], 10)
        self.assertFalse(kwargs["upsilon5_allow_over_budget"])
        self.assertFalse(kwargs["upsilon5_allow_quota_risk"])
        self.assertFalse(kwargs["upsilon5_rollback_requested"])
        self.assertEqual(kwargs["chi5_lookback_hours"], 24)
        self.assertEqual(kwargs["chi5_min_request_count"], 1)
        self.assertEqual(kwargs["chi5_min_success_rate"], 0.95)
        self.assertEqual(kwargs["chi5_max_failure_rate"], 0.1)
        self.assertEqual(kwargs["chi5_max_fallback_rate"], 0.2)
        self.assertEqual(kwargs["chi5_max_empty_rate"], 0.2)
        self.assertEqual(kwargs["chi5_max_latency_p95_ms"], 2000)
        self.assertEqual(kwargs["chi5_circuit_open_minutes"], 30)
        self.assertEqual(kwargs["chi5_recovery_probe_min_success_rate"], 1.0)
        self.assertEqual(kwargs["psi5_route_lookback_hours"], 24)
        self.assertEqual(kwargs["psi5_route_max_actions"], 50)
        self.assertEqual(kwargs["psi5_route_execution_mode"], "execute")
        self.assertFalse(kwargs["psi5_route_approve_high_risk"])
        self.assertEqual(kwargs["psi5_route_approved_by"], "route-ops")
        self.assertEqual(kwargs["psi5_route_owner"], "platform-ops")
        self.assertTrue(kwargs["psi5_route_include_recovered"])
        self.assertEqual(kwargs["omega5_route_lookback_hours"], 24)
        self.assertEqual(kwargs["omega5_route_max_controls"], 50)
        self.assertEqual(kwargs["omega5_route_execution_mode"], "review_only")
        self.assertFalse(kwargs["omega5_route_auto_approve"])
        self.assertEqual(kwargs["omega5_route_approved_by"], "route-control-ops")
        self.assertEqual(kwargs["omega5_route_requested_by"], "omega5")
        self.assertEqual(kwargs["omega5_route_approval_sla_hours"], 4)
        self.assertTrue(kwargs["omega5_route_notify_wecom"])
        self.assertFalse(kwargs["omega5_route_allow_wecom_external"])
        self.assertTrue(kwargs["omega5_route_create_rollback"])
        self.assertEqual(kwargs["alpha6_route_lookback_hours"], 24)
        self.assertEqual(kwargs["alpha6_route_approval_sla_hours"], 4)
        self.assertEqual(kwargs["alpha6_route_max_pending_controls"], 50)
        self.assertEqual(kwargs["alpha6_route_max_failed_execution_rate"], 0.1)
        self.assertEqual(kwargs["alpha6_route_max_blocked_receipt_rate"], 0.8)
        self.assertEqual(kwargs["alpha6_route_max_stale_minutes"], 90)
        self.assertEqual(kwargs["alpha6_route_requested_by"], "alpha6")
        self.assertEqual(kwargs["alpha6_route_environment"], "local")
        self.assertEqual(kwargs["alpha6_route_control_schedule_code"], "omega5_route_incident_control_15m")
        self.assertEqual(kwargs["beta6_route_lookback_hours"], 24)
        self.assertEqual(kwargs["beta6_route_max_controls"], 100)
        self.assertEqual(kwargs["beta6_route_approval_decision"], "hold")
        self.assertFalse(kwargs["beta6_route_apply_decisions"])
        self.assertEqual(kwargs["beta6_route_requested_by"], "beta6")
        self.assertEqual(kwargs["beta6_route_environment"], "local")
        self.assertEqual(kwargs["beta6_route_notification_policy"], "dedupe_digest")
        self.assertEqual(kwargs["beta6_route_stress_scope"], "full_market")
        self.assertFalse(kwargs["beta6_route_notify_wecom"])
        self.assertFalse(kwargs["beta6_route_allow_wecom_external"])
        self.assertTrue(kwargs["epsilon6_sla_automation"])
        self.assertTrue(kwargs["epsilon6_hash_verify"])
        self.assertEqual(kwargs["epsilon6_recovery_drill"], "hash_chain_verify")
        self.assertEqual(kwargs["epsilon6_requested_by"], "epsilon6")
        self.assertEqual(kwargs["epsilon6_environment"], "local")
        self.assertEqual(kwargs["epsilon6_sla_limit"], 100)
        self.assertEqual(kwargs["epsilon6_audit_verify_limit"], 1000)
        self.assertEqual(kwargs["zeta6_environment"], "local")
        self.assertEqual(kwargs["zeta6_release_version"], "zeta6-local")
        self.assertEqual(kwargs["zeta6_requested_by"], "zeta6")
        self.assertFalse(kwargs["zeta6_require_dual_secret"])
        self.assertTrue(kwargs["zeta6_export_audit"])
        self.assertEqual(kwargs["zeta6_export_chain_scope"], "route-approval:control_code:omega5-route-control-demo")
        self.assertEqual(kwargs["zeta6_export_control_code"], "omega5-route-control-demo")
        self.assertEqual(kwargs["zeta6_export_limit"], 1000)
        self.assertEqual(kwargs["eta6_source_code"], "vendor_http")
        self.assertEqual(kwargs["eta6_primary_source_code"], "csv")
        self.assertEqual(kwargs["eta6_dataset_codes"], ["daily_bar", "security_master"])
        self.assertEqual(kwargs["eta6_environment"], "local")
        self.assertEqual(kwargs["eta6_closure_scope"], "production_primary")
        self.assertEqual(kwargs["eta6_closure_mode"], "review_only")
        self.assertEqual(kwargs["eta6_requested_by"], "eta6")
        self.assertTrue(kwargs["eta6_require_real_vendor_env"])
        self.assertFalse(kwargs["eta6_external_probe_allowed"])
        self.assertEqual(kwargs["eta6_min_stability_score"], 70)
        self.assertFalse(kwargs["eta6_allow_cost_watch"])
        self.assertTrue(kwargs["dry_run"])

    def test_build_worker_kwargs_requires_complete_window(self) -> None:
        with self.assertRaises(QDataValidationError):
            build_worker_kwargs({"dry_run": False, "task_args": {"start_date": "2026-07-01"}})

    def test_compute_next_run_at(self) -> None:
        started_at = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)

        self.assertEqual(compute_next_run_at(started_at, 300).isoformat(), "2026-07-24T08:05:00+00:00")
        with self.assertRaises(QDataValidationError):
            compute_next_run_at(started_at, 0)

    def test_format_scheduler_report(self) -> None:
        result = MuSchedulerResult(
            scheduler_id="mu-test",
            status="success",
            scan_count=1,
            duration_ms=12,
            tick_results=[
                MuTickResult(
                    schedule_code="mu_usage_rollup_5m",
                    task_name="usage_rollup",
                    status="success",
                    worker_run_id=7,
                    lock_acquired=True,
                )
            ],
        )

        report = format_scheduler_report(result)

        self.assertIn("mu_scheduler scheduler_id=mu-test status=success", report)
        self.assertIn("tick schedule=mu_usage_rollup_5m", report)
        self.assertIn("worker_run_id=7", report)


if __name__ == "__main__":
    unittest.main()
