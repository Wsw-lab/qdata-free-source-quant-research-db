from __future__ import annotations

import unittest

from qdata.tau5_vendor_cost_optimization import (
    build_vendor_budget_stress_snapshots,
    build_vendor_cost_optimization_snapshot,
    build_vendor_route_weight_plans,
    evaluate_vendor_route_weight,
    format_tau5_rows,
)


def _base_row(**overrides):
    row = {
        "source_id": 1,
        "source_code": "vendor_http",
        "dataset_id": 10,
        "dataset_code": "daily_bar",
        "primary_source_id": 2,
        "primary_source_code": "csv",
        "backup_source_id": 3,
        "backup_source_code": "akshare",
        "current_priority_id": 4,
        "current_primary_source_code": "vendor_http",
        "current_priority": 0,
        "stability_snapshot_id": 5,
        "stability_snapshot_code": "sigma5-primary-stability-ok",
        "stability_status": "healthy",
        "stability_score": 95.0,
        "procurement_status": "active",
        "contract_status": "active",
        "contract_production_use_allowed": True,
        "entitlement_status": "active",
        "allowed_role": "primary_candidate",
        "production_use_allowed": True,
        "billing_model": "per_request",
        "billing_currency": "CNY",
        "unit_cost": 0.001,
        "monthly_fee": 0.0,
        "entitlement_daily_quota": 100000,
        "contract_daily_quota": 100000,
        "contract_monthly_quota": 3000000,
        "api_request_count": 100,
        "api_row_count": 1000,
        "api_cost_units": 0.1,
    }
    row.update(overrides)
    return row


class Tau5VendorCostOptimizationTest(unittest.TestCase):
    def test_evaluate_optimized_primary_route(self) -> None:
        evaluation = evaluate_vendor_route_weight(
            _base_row(),
            allocated_budget_amount=1000,
            lookback_hours=24,
            forecast_window_days=30,
            default_unit_cost=0.001,
        )

        self.assertEqual(evaluation["status"], "optimized")
        self.assertEqual(evaluation["plan_role"], "primary")
        self.assertTrue(evaluation["is_primary_route"])
        self.assertTrue(evaluation["routing_change_allowed"])
        self.assertEqual(evaluation["recommended_primary_weight_pct"], 90.0)
        self.assertEqual(evaluation["recommended_backup_weight_pct"], 10.0)

    def test_no_primary_promotion_never_assigns_vendor_primary_weight(self) -> None:
        plans = build_vendor_route_weight_plans(
            [
                _base_row(
                    current_primary_source_code="csv",
                    stability_status="no_primary_promotion",
                    stability_score=0.0,
                )
            ],
            dataset_api_metrics={"daily_bar": {"api_request_count": 100, "row_count": 1000, "cost_units": 0.1}},
            as_of_date="2026-07-29",
            monthly_budget_amount=1000,
        )

        self.assertEqual(plans[0]["status"], "no_primary_promotion")
        self.assertEqual(plans[0]["plan_role"], "watch")
        self.assertFalse(plans[0]["is_primary_route"])
        self.assertFalse(plans[0]["routing_change_allowed"])
        self.assertEqual(plans[0]["recommended_primary_weight_pct"], 0.0)
        self.assertEqual(plans[0]["recommended_backup_weight_pct"], 100.0)
        self.assertTrue(any(issue.startswith("sigma5_primary_route_not_active") for issue in plans[0]["blocking_issues"]))
        self.assertIn("Wait for an applied Pi-5 promotion", plans[0]["required_actions"][0])

    def test_budget_and_quota_risks_get_distinct_statuses(self) -> None:
        over_budget = evaluate_vendor_route_weight(
            _base_row(unit_cost=1.0),
            allocated_budget_amount=1,
            lookback_hours=24,
            forecast_window_days=30,
            default_unit_cost=0.001,
        )
        quota_risk = evaluate_vendor_route_weight(
            _base_row(entitlement_daily_quota=100, contract_daily_quota=100, contract_monthly_quota=100000, unit_cost=0.0001),
            allocated_budget_amount=10000,
            lookback_hours=24,
            forecast_window_days=30,
            default_unit_cost=0.001,
        )

        self.assertEqual(over_budget["status"], "over_budget")
        self.assertEqual(over_budget["recommended_primary_weight_pct"], 40.0)
        self.assertEqual(quota_risk["status"], "quota_risk")
        self.assertEqual(quota_risk["recommended_primary_weight_pct"], 60.0)
        self.assertEqual(quota_risk["recommended_free_source_weight_pct"], 10.0)

    def test_snapshot_stress_and_report_keep_no_primary_explainable(self) -> None:
        rows = [
            _base_row(dataset_id=10, dataset_code="daily_bar", current_primary_source_code="csv", stability_status="no_primary_promotion", stability_score=0.0),
            _base_row(dataset_id=11, dataset_code="security_master", current_primary_source_code="csv", stability_status="no_primary_promotion", stability_score=0.0),
        ]
        plans = build_vendor_route_weight_plans(
            rows,
            dataset_api_metrics={
                "daily_bar": {"api_request_count": 100, "row_count": 1000, "cost_units": 0.1},
                "security_master": {"api_request_count": 10, "row_count": 100, "cost_units": 0.01},
            },
            as_of_date="2026-07-29",
            monthly_budget_amount=1000,
        )
        snapshot = build_vendor_cost_optimization_snapshot(
            plans,
            source_code="vendor_http",
            primary_source_code="csv",
            as_of_date="2026-07-29",
            monthly_budget_amount=1000,
            stress_multipliers=[1, 5, 10],
        )
        stress_rows = build_vendor_budget_stress_snapshots(
            plans,
            as_of_date="2026-07-29",
            stress_multipliers=[1, 5, 10],
        )
        report = format_tau5_rows("optimizations", [snapshot])

        self.assertEqual(snapshot["status"], "no_primary_promotion")
        self.assertEqual(snapshot["optimization_role"], "watch")
        self.assertEqual(snapshot["dataset_count"], 2)
        self.assertEqual(snapshot["no_primary_dataset_count"], 2)
        self.assertEqual(snapshot["recommended_primary_weight_pct"], 0.0)
        self.assertEqual(snapshot["recommended_backup_weight_pct"], 100.0)
        self.assertEqual(len(stress_rows), 6)
        self.assertIn("tau5 resource=optimizations rows=1", report)
        self.assertIn("status=no_primary_promotion", report)


if __name__ == "__main__":
    unittest.main()
