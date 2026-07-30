from __future__ import annotations

import unittest

from qdata.upsilon5_route_weight_execution import (
    build_route_weight_execution_datasets,
    build_route_weight_execution_run,
    build_route_weight_rollout_stages,
    evaluate_route_weight_execution_dataset,
    format_upsilon5_rows,
)


def _base_row(**overrides):
    row = {
        "optimization_id": 1,
        "optimization_code": "tau5-cost-optimization-demo",
        "plan_id": 2,
        "plan_code": "tau5-route-weight-demo",
        "source_id": 10,
        "source_code": "vendor_http",
        "dataset_id": 20,
        "dataset_code": "daily_bar",
        "primary_source_id": 30,
        "primary_source_code": "csv",
        "backup_source_id": 40,
        "backup_source_code": "akshare",
        "current_priority_id": 50,
        "current_primary_source_code": "vendor_http",
        "current_priority": 0,
        "is_primary_route": True,
        "stability_snapshot_id": 60,
        "stability_snapshot_code": "sigma5-primary-stability-demo",
        "tau5_status": "optimized",
        "tau5_plan_role": "primary",
        "stability_status": "healthy",
        "stability_score": 95.0,
        "contract_status": "active",
        "entitlement_status": "active",
        "recommended_primary_weight_pct": 90.0,
        "recommended_backup_weight_pct": 10.0,
        "recommended_free_source_weight_pct": 0.0,
        "projected_budget_usage_pct": 0.2,
        "projected_monthly_quota_usage_pct": 0.3,
    }
    row.update(overrides)
    return row


class Upsilon5RouteWeightExecutionTest(unittest.TestCase):
    def test_no_primary_blocks_execution_and_keeps_primary_weight_zero(self) -> None:
        datasets = build_route_weight_execution_datasets(
            [
                _base_row(
                    current_primary_source_code="csv",
                    is_primary_route=False,
                    tau5_status="no_primary_promotion",
                    recommended_primary_weight_pct=0.0,
                    recommended_backup_weight_pct=100.0,
                )
            ],
            as_of_date="2026-07-29",
        )

        self.assertEqual(datasets[0]["status"], "no_primary_promotion")
        self.assertFalse(datasets[0]["routing_change_allowed"])
        self.assertEqual(datasets[0]["applied_primary_weight_pct"], 0.0)
        self.assertEqual(datasets[0]["applied_backup_weight_pct"], 100.0)
        self.assertIn("tau5_primary_weight_not_executable", datasets[0]["blocking_issues"][0])

    def test_pending_approval_for_optimized_plan(self) -> None:
        result = evaluate_route_weight_execution_dataset(_base_row(), approval_status="pending")

        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(result["approval_status"], "pending")
        self.assertFalse(result["routing_change_allowed"])
        self.assertIn("manual_approval_pending", result["blocking_issues"])

    def test_approved_apply_stages_initial_weight(self) -> None:
        result = evaluate_route_weight_execution_dataset(
            _base_row(),
            execution_mode="apply",
            approval_status="approved",
            rollout_policy="gradual",
            rollout_stages=[10, 30, 60, 90],
            current_stage_sequence=1,
            max_initial_primary_weight_pct=10,
        )

        self.assertEqual(result["status"], "staged")
        self.assertEqual(result["current_stage_sequence"], 1)
        self.assertEqual(result["stage_count"], 4)
        self.assertTrue(result["routing_change_allowed"])
        self.assertTrue(result["routing_change_applied"])
        self.assertEqual(result["applied_primary_weight_pct"], 10.0)
        self.assertEqual(result["applied_backup_weight_pct"], 90.0)

    def test_over_budget_requires_review_unless_allowed(self) -> None:
        review = evaluate_route_weight_execution_dataset(_base_row(tau5_status="over_budget"), approval_status="pending")
        allowed = evaluate_route_weight_execution_dataset(
            _base_row(tau5_status="over_budget"),
            approval_policy="auto_if_optimized",
            approval_status="approved",
            allow_over_budget=True,
        )

        self.assertEqual(review["status"], "review_required")
        self.assertFalse(review["routing_change_allowed"])
        self.assertEqual(allowed["status"], "approved")
        self.assertTrue(allowed["routing_change_allowed"])

    def test_snapshot_and_stages_report(self) -> None:
        datasets = build_route_weight_execution_datasets(
            [_base_row(dataset_id=20, dataset_code="daily_bar"), _base_row(dataset_id=21, dataset_code="security_master")],
            as_of_date="2026-07-29",
            approval_status="approved",
            execution_mode="dry_run",
        )
        stages = build_route_weight_rollout_stages(
            datasets,
            as_of_date="2026-07-29",
            rollout_stages=[10, 30, 60, 90],
            current_stage_sequence=1,
            execution_mode="dry_run",
        )
        run = build_route_weight_execution_run(
            datasets,
            stages,
            source_code="vendor_http",
            primary_source_code="csv",
            as_of_date="2026-07-29",
            approval_status="approved",
            execution_mode="dry_run",
        )
        report = format_upsilon5_rows("executions", [run])

        self.assertEqual(run["status"], "staged")
        self.assertEqual(run["dataset_count"], 2)
        self.assertEqual(run["staged_dataset_count"], 2)
        self.assertEqual(run["current_stage_sequence"], 1)
        self.assertEqual(run["applied_primary_weight_pct"], 10.0)
        self.assertEqual(len(stages), 8)
        self.assertIn("upsilon5 resource=executions rows=1", report)
        self.assertIn("status=staged", report)


if __name__ == "__main__":
    unittest.main()
