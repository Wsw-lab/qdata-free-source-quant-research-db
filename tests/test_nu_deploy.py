from datetime import datetime, timezone
import unittest

from qdata.exceptions import QDataValidationError
from qdata.nu_deploy import (
    NuHealthCheckResult,
    NuHealthReport,
    format_nu_health_report,
    normalize_check_names,
    overall_health_status,
    report_to_dict,
)


class NuDeployTest(unittest.TestCase):
    def test_normalize_check_names_defaults_dedupes_and_validates(self) -> None:
        self.assertIn("postgres", normalize_check_names(None))
        self.assertEqual(normalize_check_names(["postgres", "postgres", "api"]), ["postgres", "api"])
        with self.assertRaises(QDataValidationError):
            normalize_check_names(["unknown"])

    def test_overall_health_status(self) -> None:
        self.assertEqual(overall_health_status([NuHealthCheckResult("pg", "postgres", "success", 1, {})]), "success")
        self.assertEqual(overall_health_status([NuHealthCheckResult("api", "api", "skipped", 1, {})]), "warning")
        self.assertEqual(overall_health_status([NuHealthCheckResult("pg", "postgres", "failed", 1, {})]), "failed")

    def test_report_counts_and_serialization(self) -> None:
        report = NuHealthReport(
            snapshot_code="nu-health-test",
            environment="local",
            status="warning",
            checked_at=datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc),
            duration_ms=12,
            checks=[
                NuHealthCheckResult("postgres", "postgres", "success", 3, {"ok": True}),
                NuHealthCheckResult("api_health", "api", "skipped", 1, {"reason": "not provided"}),
            ],
        )

        payload = report_to_dict(report)
        text = format_nu_health_report(report)

        self.assertEqual(report.success_count, 1)
        self.assertEqual(report.warning_count, 1)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(payload["check_count"], 2)
        self.assertIn("nu_health snapshot_code=nu-health-test", text)
        self.assertIn("check name=api_health", text)


if __name__ == "__main__":
    unittest.main()
