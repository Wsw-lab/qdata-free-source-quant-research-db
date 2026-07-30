import unittest

from qdata.pi5_vendor_primary_promotion import (
    build_vendor_primary_promotion_results,
    build_vendor_primary_promotion_run,
    evaluate_vendor_primary_promotion,
    format_pi5_rows,
)


def _row(**overrides):
    row = {
        "source_id": 2,
        "source_code": "vendor_http",
        "primary_source_id": 1,
        "primary_source_code": "csv",
        "dataset_id": 10,
        "dataset_code": "daily_bar",
        "procurement_snapshot_id": 100,
        "procurement_snapshot_code": "omicron5-procurement-ready",
        "procurement_status": "ready",
        "procurement_role": "primary_candidate",
        "readiness_review_id": 200,
        "readiness_review_code": "pi-readiness-ready",
        "readiness_status": "ready",
        "readiness_recommendation": "approve_primary",
        "readiness_recommended_role": "primary",
        "readiness_required_windows": [5, 20, 60],
        "readiness_missing_window_count": 0,
        "readiness_failed_window_count": 0,
        "canary_pilot_id": 300,
        "canary_pilot_code": "theta3-canary-ready",
        "canary_status": "success",
        "canary_signoff_status": "approved",
        "canary_recommendation": "primary_candidate",
        "canary_risk_level": "low",
        "full_market_pilot_id": 400,
        "full_market_pilot_code": "theta3-full-market-ready",
        "full_market_status": "success",
        "full_market_signoff_status": "approved",
        "full_market_recommendation": "primary_candidate",
        "full_market_risk_level": "medium",
        "current_priority_id": 500,
        "current_primary_source_code": "csv",
        "current_priority": 0,
    }
    row.update(overrides)
    return row


class Pi5VendorPrimaryPromotionTest(unittest.TestCase):
    def test_evaluate_approves_all_evidence_ready(self) -> None:
        result = evaluate_vendor_primary_promotion(_row())

        self.assertEqual(result["status"], "approved_for_primary")
        self.assertEqual(result["promotion_role"], "primary")
        self.assertTrue(result["routing_change_allowed"])
        self.assertEqual(result["promotion_score"], 100.0)

    def test_evaluate_marks_already_primary_as_applied(self) -> None:
        result = evaluate_vendor_primary_promotion(_row(current_primary_source_code="vendor_http", current_priority=0))

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["promotion_role"], "primary")
        self.assertFalse(result["routing_change_allowed"])

    def test_evaluate_blocks_without_primary_candidate_procurement(self) -> None:
        result = evaluate_vendor_primary_promotion(_row(procurement_status="review_required", procurement_role="validator"))

        self.assertEqual(result["status"], "blocked")
        self.assertIn("omicron5_procurement_not_primary_candidate:review_required/validator", result["blocking_issues"])

    def test_evaluate_requires_full_market_when_policy_requires_it(self) -> None:
        result = evaluate_vendor_primary_promotion(_row(full_market_pilot_id=None))

        self.assertEqual(result["status"], "full_market_required")
        self.assertIn("theta3_full_market_pilot_missing", result["blocking_issues"])

    def test_evaluate_pending_signoff_after_evidence_ready(self) -> None:
        result = evaluate_vendor_primary_promotion(_row(canary_signoff_status="pending"))

        self.assertEqual(result["status"], "pending_signoff")
        self.assertIn("promotion_signoff_not_approved", result["blocking_issues"])

    def test_build_results_and_run_aggregate_counts(self) -> None:
        results = build_vendor_primary_promotion_results(
            [_row(dataset_code="daily_bar"), _row(dataset_id=11, dataset_code="security_master", procurement_status="blocked")],
            as_of_date="2026-07-28",
        )
        run = build_vendor_primary_promotion_run(
            results,
            source_code="vendor_http",
            primary_source_code="csv",
            as_of_date="2026-07-28",
        )
        report = format_pi5_rows("runs", [run])

        self.assertEqual(run["status"], "blocked")
        self.assertEqual(run["dataset_count"], 2)
        self.assertEqual(run["approved_dataset_count"], 1)
        self.assertEqual(run["blocked_dataset_count"], 1)
        self.assertIn("pi5 resource=runs rows=1", report)
        self.assertIn("source_code=vendor_http", report)
        self.assertEqual(results[0]["evidence"]["routing"]["target_priority"], 0)


if __name__ == "__main__":
    unittest.main()
