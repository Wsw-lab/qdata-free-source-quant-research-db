import unittest

from qdata.pi_readiness import ReadinessThresholds, build_readiness_review, evaluate_readiness_window


class PiReadinessTest(unittest.TestCase):
    def test_all_required_windows_pass_primary_readiness(self) -> None:
        suites = [
            _suite(1, 5, "suite-5", coverage_rate=0.99, conflict_rate=0, failure_rate=0),
            _suite(2, 20, "suite-20", coverage_rate=0.98, conflict_rate=0.001, failure_rate=0),
            _suite(3, 60, "suite-60", coverage_rate=0.97, conflict_rate=0.002, failure_rate=0.001),
        ]

        review = build_readiness_review(
            suites,
            dataset_code="daily_bar",
            source_code="vendor_http",
            primary_source_code="csv",
            required_windows=[5, 20, 60],
            profile={"profile_status": "active", "endpoint_base": "https://vendor.example", "auth_mode": "bearer"},
            require_live_endpoint=True,
            require_active_profile=True,
        )

        self.assertEqual(review["status"], "ready")
        self.assertEqual(review["recommendation"], "approve_primary")
        self.assertEqual(review["recommended_role"], "primary")
        self.assertEqual(review["missing_window_count"], 0)
        self.assertEqual(review["passed_window_count"], 3)

    def test_missing_window_keeps_vendor_in_watch_state(self) -> None:
        review = build_readiness_review(
            [_suite(1, 5, "suite-5", coverage_rate=1, conflict_rate=0, failure_rate=0)],
            dataset_code="daily_bar",
            source_code="vendor_http",
            required_windows=[5, 20],
        )

        self.assertEqual(review["status"], "incomplete")
        self.assertEqual(review["recommendation"], "watch")
        self.assertEqual(review["recommended_role"], "research_only")
        self.assertEqual(review["missing_window_count"], 1)
        self.assertIn("missing 20d benchmark suite", review["blocking_issues"])

    def test_window_thresholds_capture_failed_and_warning_conditions(self) -> None:
        failed = evaluate_readiness_window(
            20,
            _suite(2, 20, "suite-20", coverage_rate=0.90, conflict_rate=0, failure_rate=0),
            ReadinessThresholds(min_coverage_rate=0.95),
        )
        warning = evaluate_readiness_window(
            60,
            _suite(3, 60, "suite-60", coverage_rate=1, conflict_rate=0.01, failure_rate=0),
            ReadinessThresholds(max_conflict_rate=0.005),
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(warning["status"], "warning")


def _suite(suite_id: int, target_days: int, suite_code: str, **metrics):
    return {
        "suite_id": suite_id,
        "suite_code": suite_code,
        "target_trade_days": target_days,
        "status": "success",
        "symbol_count": 1000,
        "benchmark_count": target_days * 2,
        "p95_latency_ms": 100,
        "rows_per_second": 2000,
        "start_date": "2026-07-01",
        "end_date": "2026-07-26",
        **metrics,
    }


if __name__ == "__main__":
    unittest.main()
