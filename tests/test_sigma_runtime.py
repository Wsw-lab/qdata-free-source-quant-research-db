from datetime import datetime, timezone
from decimal import Decimal
import unittest

from qdata.exceptions import QDataValidationError
from qdata.sigma_runtime import (
    capacity_alert_payload,
    daily_report_status,
    format_capacity_alerts,
    format_runtime_collection,
    runtime_metric_status,
)


class SigmaRuntimeTest(unittest.TestCase):
    def test_runtime_metric_status_uses_warning_and_critical_thresholds(self) -> None:
        self.assertEqual(runtime_metric_status("9", warning_threshold="10", critical_threshold="20"), "normal")
        self.assertEqual(runtime_metric_status("10", warning_threshold="10", critical_threshold="20"), "warning")
        self.assertEqual(runtime_metric_status("20", warning_threshold="10", critical_threshold="20"), "critical")
        with self.assertRaises(QDataValidationError):
            runtime_metric_status("15", warning_threshold="20", critical_threshold="10")

    def test_daily_report_status_prioritizes_critical_inputs(self) -> None:
        self.assertEqual(daily_report_status(api_error_rate=0), "success")
        self.assertEqual(daily_report_status(api_error_rate=Decimal("0.001")), "warning")
        self.assertEqual(daily_report_status(api_error_rate=Decimal("0.05")), "critical")
        self.assertEqual(daily_report_status(api_error_rate=0, deployment_health_status="warning"), "warning")
        self.assertEqual(daily_report_status(api_error_rate=0, worker_failed_count=1), "critical")
        self.assertEqual(daily_report_status(api_error_rate=0, open_critical_capacity_alert_count=1), "critical")

    def test_capacity_alert_payload_maps_metric_status_to_alert(self) -> None:
        payload = capacity_alert_payload(
            {
                "environment": "local",
                "component": "api",
                "metric_name": "api_request_count_7d",
                "metric_time": datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
                "metric_value": "227",
                "unit": "requests",
                "status": "warning",
                "warning_threshold": "200",
                "critical_threshold": "1000",
            }
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["alert_key"], "sigma-capacity-local-api-api-request-count-7d")
        self.assertEqual(payload["severity"], "medium")
        self.assertEqual(payload["alert_type"], "runtime_capacity_warning")
        self.assertEqual(payload["metric_value"], Decimal("227.000000000000"))

    def test_capacity_alert_payload_ignores_normal_metrics_and_formatters_are_readable(self) -> None:
        self.assertIsNone(capacity_alert_payload({"status": "normal"}))
        alerts = [
            {
                "alert_key": "sigma-capacity-local-api-api-request-count-7d",
                "environment": "local",
                "component": "api",
                "metric_name": "api_request_count_7d",
                "severity": "medium",
                "status": "open",
                "metric_value": "227.000000000000",
                "threshold_value": "200.000000000000",
            }
        ]
        collection = format_runtime_collection(
            {
                "environment": "local",
                "report_date": "2026-07-26",
                "metrics": [{"component": "api", "metric_name": "api_request_count_7d", "metric_value": "227", "unit": "requests", "status": "warning", "warning_threshold": "200"}],
                "capacity_alerts": alerts,
                "daily_report": {"status": "warning"},
            }
        )

        self.assertIn("sigma_runtime environment=local", collection)
        self.assertIn("capacity_alerts=1", collection)
        self.assertIn("sigma_capacity_alerts rows=1", format_capacity_alerts(alerts))


if __name__ == "__main__":
    unittest.main()
