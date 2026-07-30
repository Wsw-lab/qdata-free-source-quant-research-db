from datetime import datetime, timedelta, timezone
import unittest

from qdata.chi5_route_feedback import (
    build_route_health_runbook,
    evaluate_route_health,
    filter_route_candidates_by_circuit,
)


class Chi5RouteFeedbackTest(unittest.TestCase):
    def test_evaluate_route_health_opens_circuit_for_failed_source(self) -> None:
        now = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)

        result = evaluate_route_health(
            {
                "request_count": 10,
                "success_rate": 0.7,
                "failure_rate": 0.3,
                "fallback_rate": 0.4,
                "empty_rate": 0.1,
                "latency_p95_ms": 100,
            },
            thresholds={"min_success_rate": 0.95, "max_failure_rate": 0.1, "max_fallback_rate": 0.2, "circuit_open_minutes": 30},
            as_of_at=now,
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["circuit_status"], "open")
        self.assertEqual(result["circuit_action"], "open_circuit")
        self.assertEqual(result["open_until"], now + timedelta(minutes=30))
        self.assertIn("route_failure_rate_high", result["health_issues"])

    def test_evaluate_route_health_closes_expired_open_circuit_after_recovery(self) -> None:
        now = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)

        result = evaluate_route_health(
            {
                "request_count": 3,
                "success_rate": 1.0,
                "failure_rate": 0.0,
                "fallback_rate": 0.0,
                "empty_rate": 0.0,
                "latency_p95_ms": 10,
            },
            previous_state={"status": "open", "open_until": now - timedelta(minutes=1)},
            thresholds={"min_success_rate": 1.0, "max_failure_rate": 0.0, "circuit_open_minutes": 30},
            as_of_at=now,
        )

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["circuit_status"], "closed")
        self.assertEqual(result["circuit_action"], "close_circuit")

    def test_filter_route_candidates_skips_open_circuit(self) -> None:
        now = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
        candidates = [
            {"source_code": "vendor_http", "role": "primary", "weight_pct": 80},
            {"source_code": "csv", "role": "backup", "weight_pct": 20},
        ]

        filtered, skipped = filter_route_candidates_by_circuit(
            candidates,
            {("daily_bar", "vendor_http"): {"status": "open", "open_until": now + timedelta(minutes=5)}},
            dataset_code="daily_bar",
            now=now,
        )

        self.assertEqual([item["source_code"] for item in filtered], ["csv"])
        self.assertEqual(skipped, ["vendor_http"])

    def test_runbook_mentions_circuit_action(self) -> None:
        actions = build_route_health_runbook(
            {"source_code": "vendor_http", "dataset_code": "daily_bar", "success_rate": 0.7, "fallback_rate": 0.5},
            ["route_failure_rate_high", "route_fallback_rate_high"],
            "open_circuit",
        )

        self.assertTrue(any("Circuit opened" in action for action in actions))


if __name__ == "__main__":
    unittest.main()
