import unittest

from qdata.sigma5_vendor_primary_stability import (
    build_vendor_primary_stability_dataset_snapshots,
    build_vendor_primary_stability_snapshot,
    evaluate_vendor_primary_stability_dataset,
    format_sigma5_rows,
)


def _row(**overrides):
    row = {
        "source_id": 2,
        "source_code": "vendor_http",
        "primary_source_id": 1,
        "primary_source_code": "csv",
        "dataset_id": 10,
        "dataset_code": "daily_bar",
        "entitlement_status": "active",
        "allowed_role": "primary_candidate",
        "production_use_allowed": True,
        "schema_status": "validated",
        "promotion_id": 700,
        "promotion_code": "pi5-primary-promotion-applied",
        "promotion_status": "applied",
        "promotion_result_status": "applied",
        "current_priority_id": 500,
        "current_primary_source_code": "vendor_http",
        "current_priority": 0,
        "post_promotion_status": "healthy",
    }
    row.update(overrides)
    return row


class Sigma5VendorPrimaryStabilityTest(unittest.TestCase):
    def test_evaluate_healthy_primary_route_with_sla(self) -> None:
        result = evaluate_vendor_primary_stability_dataset(
            _row(api_request_count=1000, api_failed_count=1, api_latency_p95_ms=42.0, cost_units=20.0)
        )

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["stability_role"], "primary")
        self.assertTrue(result["is_primary_route"])
        self.assertEqual(result["stability_score"], 100.0)

    def test_evaluate_waits_for_applied_primary_promotion(self) -> None:
        result = evaluate_vendor_primary_stability_dataset(
            _row(promotion_status="blocked", promotion_result_status="blocked", current_primary_source_code="csv")
        )

        self.assertEqual(result["status"], "no_primary_promotion")
        self.assertEqual(result["stability_role"], "watch")
        self.assertIn("pi5_applied_promotion_missing:blocked", result["blocking_issues"])
        self.assertIn("primary_route_not_active:csv/0", result["blocking_issues"])

    def test_evaluate_critical_on_sla_breach(self) -> None:
        result = evaluate_vendor_primary_stability_dataset(
            _row(api_request_count=1000, api_failed_count=30, api_timeout_count=20, api_latency_p95_ms=3000.0)
        )

        self.assertEqual(result["status"], "critical")
        self.assertEqual(result["stability_role"], "degraded")
        self.assertIn("error_rate_high:0.03", result["blocking_issues"])
        self.assertIn("timeout_rate_high:0.02", result["blocking_issues"])
        self.assertIn("latency_p95_high:3000.0", result["blocking_issues"])

    def test_build_dataset_and_snapshot_aggregate_no_primary(self) -> None:
        results = build_vendor_primary_stability_dataset_snapshots(
            [_row(promotion_status="blocked", promotion_result_status="blocked", current_primary_source_code="csv"), _row(dataset_id=11, dataset_code="security_master", promotion_status="blocked", promotion_result_status="blocked", current_primary_source_code="csv")],
            dataset_api_metrics={},
            as_of_date="2026-07-28",
        )
        snapshot = build_vendor_primary_stability_snapshot(
            results,
            source_code="vendor_http",
            primary_source_code="csv",
            as_of_date="2026-07-28",
            post_metrics={"post_promotion_no_applied_count": 2},
        )
        report = format_sigma5_rows("snapshots", [snapshot])

        self.assertEqual(snapshot["status"], "no_primary_promotion")
        self.assertEqual(snapshot["stability_role"], "watch")
        self.assertEqual(snapshot["dataset_count"], 2)
        self.assertEqual(snapshot["no_primary_dataset_count"], 2)
        self.assertEqual(snapshot["primary_dataset_count"], 0)
        self.assertIn("rho5_no_applied_promotion_pending:2", snapshot["blocking_issues"])
        self.assertIn("sigma5 resource=snapshots rows=1", report)
        self.assertIn("status=no_primary_promotion", report)


if __name__ == "__main__":
    unittest.main()
