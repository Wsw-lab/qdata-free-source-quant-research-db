from decimal import Decimal
import unittest

from qdata.iota4_external_free_source_canary import (
    default_min_source_count,
    default_source_codes,
    evaluate_external_free_source_canary,
    format_iota4_canary,
    with_iota4_evaluation,
)


class Iota4ExternalFreeSourceCanaryTest(unittest.TestCase):
    def test_warning_research_only_fabric_still_passes_external_canary(self) -> None:
        row = {
            "fabric_code": "iota3-free-source-fabric-warning-demo",
            "status": "warning",
            "dataset_codes": ["daily_bar", "security_master", "trading_calendar"],
            "dataset_result_count": 3,
            "source_count": 1,
            "coverage_rate": Decimal("1.000000"),
            "baseline_source_code": "akshare",
            "recommendation": "research_only",
            "risk_level": "medium",
            "license_review_required_count": 3,
            "commercial_blocker_count": 3,
            "evidence": {"source_summary": {"external_executed_source_count": 1}},
        }

        evaluation = evaluate_external_free_source_canary(row)

        self.assertEqual(evaluation["status"], "ok")
        self.assertEqual(evaluation["external_executed_source_count"], 1)
        self.assertEqual(evaluation["commercial_clearance"], "blocked")
        self.assertIn("free_source_requires_license_review_before_commercial_use", evaluation["warnings"])

    def test_missing_external_execution_fails_canary(self) -> None:
        row = {
            "status": "success",
            "dataset_codes": ["daily_bar", "security_master", "trading_calendar"],
            "coverage_rate": 1.0,
            "evidence": {"source_summary": {"external_executed_source_count": 0}},
        }

        evaluation = evaluate_external_free_source_canary(row)

        self.assertEqual(evaluation["status"], "failed")
        self.assertIn("external_free_source_not_executed", evaluation["blocking_issues"])

    def test_blocked_fabric_fails_even_with_external_summary(self) -> None:
        row = {
            "status": "blocked",
            "dataset_codes": ["daily_bar", "security_master", "trading_calendar"],
            "coverage_rate": 1.0,
            "evidence": {"source_summary": {"external_executed_source_count": 1}},
        }

        evaluation = evaluate_external_free_source_canary(row)

        self.assertEqual(evaluation["status"], "failed")
        self.assertIn("fabric_status_not_pass:blocked", evaluation["blocking_issues"])

    def test_default_modes_pick_expected_sources_and_thresholds(self) -> None:
        self.assertEqual(default_source_codes("live-only"), ["akshare"])
        self.assertEqual(default_source_codes("compare_local"), ["csv", "csv_mirror", "akshare"])
        self.assertEqual(default_min_source_count("live-only"), 1)
        self.assertEqual(default_min_source_count("compare-local"), 2)

    def test_formatter_prioritizes_canary_status(self) -> None:
        row = with_iota4_evaluation(
            {
                "fabric_code": "iota3-free-source-fabric-warning-demo",
                "status": "warning",
                "dataset_codes": ["daily_bar", "security_master", "trading_calendar"],
                "dataset_result_count": 3,
                "source_count": 1,
                "coverage_rate": 1.0,
                "baseline_source_code": "akshare",
                "recommendation": "research_only",
                "risk_level": "medium",
                "evidence": {"source_summary": {"external_executed_source_count": 1}},
            }
        )

        report = format_iota4_canary(row)

        self.assertIn("iota4_external_free_source_canary=ok", report)
        self.assertIn("fabric_status=warning", report)
        self.assertIn("external_executed=1", report)


if __name__ == "__main__":
    unittest.main()
