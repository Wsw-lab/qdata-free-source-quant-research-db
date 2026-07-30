import unittest

from qdata.rho5_post_promotion_monitor import (
    build_post_promotion_dataset_results,
    build_post_promotion_run,
    evaluate_post_promotion_dataset,
    format_rho5_rows,
    mark_rolled_back_results,
)


def _row(**overrides):
    row = {
        "promotion_id": 700,
        "promotion_code": "pi5-primary-promotion-applied",
        "promotion_status": "applied",
        "promotion_routing_change_applied": True,
        "promotion_result_id": 701,
        "promotion_result_code": "pi5-primary-promotion-result-applied",
        "promotion_result_status": "applied",
        "promotion_role": "primary",
        "result_routing_change_applied": True,
        "source_id": 2,
        "source_code": "vendor_http",
        "primary_source_id": 1,
        "primary_source_code": "csv",
        "previous_primary_source_id": 1,
        "previous_primary_source_code": "csv",
        "dataset_id": 10,
        "dataset_code": "daily_bar",
        "current_priority_id": 500,
        "previous_priority_id": 490,
        "current_primary_source_code": "vendor_http",
        "current_priority": 0,
        "previous_priority": 0,
        "target_priority": 0,
        "shadow_status": "healthy",
        "shadow_conflict_rate_bps": 1.0,
        "shadow_failure_rate": 0.001,
        "shadow_latency_p95_ms": 42.0,
        "stale_minutes": 10,
    }
    row.update(overrides)
    return row


class Rho5PostPromotionMonitorTest(unittest.TestCase):
    def test_evaluate_waits_for_applied_pi5_promotion(self) -> None:
        result = evaluate_post_promotion_dataset(_row(promotion_status="blocked", promotion_routing_change_applied=False, promotion_result_status="blocked"))

        self.assertEqual(result["status"], "no_applied_promotion")
        self.assertFalse(result["rollback_allowed"])
        self.assertIn("pi5_promotion_not_applied:blocked", result["blocking_issues"])

    def test_evaluate_healthy_after_applied_route_and_shadow_metrics(self) -> None:
        result = evaluate_post_promotion_dataset(_row())

        self.assertEqual(result["status"], "healthy")
        self.assertFalse(result["rollback_allowed"])
        self.assertEqual(result["monitor_score"], 100.0)

    def test_evaluate_recommends_rollback_on_high_conflict(self) -> None:
        result = evaluate_post_promotion_dataset(_row(shadow_conflict_rate_bps=12.5))

        self.assertEqual(result["status"], "rollback_recommended")
        self.assertTrue(result["rollback_allowed"])
        self.assertIn("shadow_conflict_rate_high:12.5", result["blocking_issues"])

    def test_evaluate_blocks_when_routing_is_not_current(self) -> None:
        result = evaluate_post_promotion_dataset(_row(current_primary_source_code="csv"))

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["rollback_allowed"])
        self.assertIn("routing_not_current:csv/0", result["blocking_issues"])

    def test_build_results_run_and_rollback_aggregate_counts(self) -> None:
        results = build_post_promotion_dataset_results(
            [_row(dataset_code="daily_bar", shadow_conflict_rate_bps=8.0), _row(dataset_id=11, dataset_code="security_master")],
            as_of_date="2026-07-28",
            rollback_mode="apply",
        )
        mark_rolled_back_results(results)
        run = build_post_promotion_run(
            results,
            source_code="vendor_http",
            primary_source_code="csv",
            as_of_date="2026-07-28",
            rollback_mode="apply",
            promotion_id=700,
            promotion_code="pi5-primary-promotion-applied",
        )
        report = format_rho5_rows("runs", [run])

        self.assertEqual(run["status"], "rolled_back")
        self.assertEqual(run["dataset_count"], 2)
        self.assertEqual(run["healthy_dataset_count"], 1)
        self.assertEqual(run["rolled_back_dataset_count"], 1)
        self.assertTrue(run["rollback_allowed"])
        self.assertTrue(run["rollback_applied"])
        self.assertIn("rho5 resource=runs rows=1", report)
        self.assertIn("monitor_scope=post_promotion", report)
        self.assertEqual(results[0]["evidence"]["shadow_policy"]["max_conflict_rate_bps"], 5.0)


if __name__ == "__main__":
    unittest.main()
