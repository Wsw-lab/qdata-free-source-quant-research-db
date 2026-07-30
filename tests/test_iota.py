import json
import unittest

from qdata.iota import (
    DATASET_SCOPE_BY_ENDPOINT,
    _access_level_allows,
    _policy_scope,
    _send_notification,
    _severity_allows,
    authorize_dataset_access,
    format_usage_report,
)


class IotaTest(unittest.TestCase):
    def test_legacy_or_env_tokens_skip_acl_without_database_context(self) -> None:
        decision = authorize_dataset_access(
            None,
            tenant_id=None,
            project_id=None,
            principal_id=None,
            dataset_code="daily_bar",
            fields=["close"],
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.dataset_code, "daily_bar")
        self.assertEqual(DATASET_SCOPE_BY_ENDPOINT["price"], "daily_bar")

    def test_access_and_severity_levels_are_ordered(self) -> None:
        self.assertTrue(_access_level_allows("admin", "read"))
        self.assertTrue(_access_level_allows("write", "read"))
        self.assertFalse(_access_level_allows("read", "admin"))
        self.assertTrue(_severity_allows("critical", "high"))
        self.assertFalse(_severity_allows("medium", "high"))

    def test_access_policy_scope_is_strictly_hierarchical(self) -> None:
        self.assertEqual(_policy_scope({"tenant_id": 1, "project_id": 2, "principal_id": 3}, 1, 2, 3), "principal")
        self.assertEqual(_policy_scope({"tenant_id": 1, "project_id": 2, "principal_id": None}, 1, 2, 99), "project")
        self.assertEqual(_policy_scope({"tenant_id": 1, "project_id": None, "principal_id": None}, 1, 22, 99), "tenant")
        self.assertEqual(_policy_scope({"tenant_id": 1, "project_id": 2, "principal_id": 3}, 1, 2, 99), "none")

    def test_stdout_notification_returns_payload_without_network(self) -> None:
        status, response, error = _send_notification(
            {
                "channel_code": "stdout-high",
                "channel_type": "stdout",
                "endpoint": None,
            },
            {
                "alert_type": "coverage_drop",
                "severity": "high",
                "trade_date": "2024-01-04",
                "message": "coverage dropped",
                "metric_name": "coverage_rate",
                "metric_value": 0.92,
                "threshold_value": 0.98,
            },
            False,
            lambda request, timeout: None,
        )

        self.assertEqual(status, "sent")
        self.assertIsNone(error)
        payload = json.loads(response or "{}")
        self.assertEqual(payload["channel"], "stdout-high")
        self.assertEqual(payload["message"], "coverage dropped")

    def test_webhook_notification_builds_post_request(self) -> None:
        calls = []

        class Response:
            status = 204

        def fake_request(request, timeout):
            calls.append((request.full_url, request.data, timeout))
            return Response()

        status, response, error = _send_notification(
            {
                "channel_code": "webhook-high",
                "channel_type": "webhook",
                "endpoint": "https://ops.example/alert",
            },
            {
                "alert_type": "latency_spike",
                "severity": "critical",
                "trade_date": "2024-01-04",
                "message": "vendor latency spike",
            },
            False,
            fake_request,
        )

        self.assertEqual(status, "sent")
        self.assertEqual(response, "http_status=204")
        self.assertIsNone(error)
        self.assertEqual(calls[0][0], "https://ops.example/alert")
        self.assertIn(b"vendor latency spike", calls[0][1])
        self.assertEqual(calls[0][2], 10)

    def test_format_usage_report_is_human_readable(self) -> None:
        report = format_usage_report(
            [
                {
                    "usage_date": "2024-01-04",
                    "project_code": "quant-research",
                    "api_name": "price",
                    "request_count": 3,
                    "failed_count": 1,
                    "row_count": 2000,
                    "cost_units": 3.2,
                }
            ]
        )

        self.assertIn("api_usage rows=1", report)
        self.assertIn("project=quant-research", report)
        self.assertIn("requests=3", report)
        self.assertIn("cost=3.2", report)


if __name__ == "__main__":
    unittest.main()
