from decimal import Decimal
import unittest

from qdata.iota5_free_source_adapter_pool import (
    evaluate_free_source_adapter_pool,
    format_iota5_pool,
    with_iota5_evaluation,
)


class Iota5FreeSourceAdapterPoolTest(unittest.TestCase):
    def test_two_external_sources_make_pool_ok_despite_license_warning(self) -> None:
        row = {
            "fabric_code": "iota5-free-source-pool-demo",
            "status": "warning",
            "dataset_codes": ["daily_bar", "security_master", "trading_calendar"],
            "dataset_result_count": 3,
            "source_count": 6,
            "usable_source_count": 2,
            "coverage_rate": Decimal("1.000000"),
            "conflict_rate_bps": Decimal("0.000000"),
            "recommendation": "research_only",
            "risk_level": "medium",
            "license_review_required_count": 3,
            "commercial_blocker_count": 3,
            "evidence": {"source_summary": {"external_executed_source_count": 2}},
        }

        evaluation = evaluate_free_source_adapter_pool(row)

        self.assertEqual(evaluation["status"], "ok")
        self.assertEqual(evaluation["commercial_clearance"], "blocked")
        self.assertEqual(evaluation["external_executed_source_count"], 2)

    def test_one_external_source_is_degraded_not_fake_ok(self) -> None:
        row = {
            "status": "warning",
            "dataset_codes": ["daily_bar", "security_master", "trading_calendar"],
            "coverage_rate": 1.0,
            "blocking_issues": ["daily_bar:baostock:baostock connection failed or timed out"],
            "evidence": {"source_summary": {"external_executed_source_count": 1}},
        }

        evaluation = evaluate_free_source_adapter_pool(row)

        self.assertEqual(evaluation["status"], "degraded")
        self.assertIn("external_successful_sources_below_target:1/2", evaluation["degraded_reasons"])
        self.assertIn("baostock_network_unreachable", evaluation["degraded_reasons"])

    def test_no_external_source_fails(self) -> None:
        row = {
            "status": "blocked",
            "dataset_codes": ["daily_bar"],
            "coverage_rate": 0.0,
            "evidence": {"source_summary": {"external_executed_source_count": 0}},
        }

        evaluation = evaluate_free_source_adapter_pool(row)

        self.assertEqual(evaluation["status"], "failed")
        self.assertIn("external_free_source_not_executed", evaluation["blocking_issues"])

    def test_formatter_includes_degraded_reasons(self) -> None:
        row = with_iota5_evaluation(
            {
                "fabric_code": "iota5-free-source-pool-demo",
                "status": "warning",
                "dataset_codes": ["daily_bar", "security_master", "trading_calendar"],
                "dataset_result_count": 3,
                "source_count": 6,
                "usable_source_count": 1,
                "coverage_rate": 1.0,
                "conflict_rate_bps": 0.0,
                "recommendation": "research_only",
                "risk_level": "medium",
                "evidence": {"source_summary": {"external_executed_source_count": 1}},
            }
        )

        report = format_iota5_pool(row)

        self.assertIn("iota5_free_source_adapter_pool=degraded", report)
        self.assertIn("external_executed=1", report)
        self.assertIn("degraded_reasons=external_successful_sources_below_target:1/2", report)


if __name__ == "__main__":
    unittest.main()
