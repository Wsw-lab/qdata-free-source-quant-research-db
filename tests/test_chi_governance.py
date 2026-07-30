import unittest

from qdata.chi_governance import format_chi_report, score_project_governance


class ChiGovernanceTest(unittest.TestCase):
    def test_score_project_governance_flags_budget_and_access_risk(self) -> None:
        status, risk_score, action, details = score_project_governance(
            {
                "request_count_7d": 100,
                "failed_count_7d": 3,
                "denied_access_7d_count": 6,
                "budget_status": "exceeded",
                "budget_usage_pct": 108,
                "open_budget_alert_count": 1,
                "unpaid_invoice_count": 0,
                "overdue_invoice_count": 0,
                "open_governance_action_count": 0,
            }
        )

        self.assertEqual(status, "critical")
        self.assertGreaterEqual(risk_score, 70)
        self.assertEqual(action, "review_budget")
        self.assertEqual(details["risk_drivers"]["denied_access_7d_count"], 6)

    def test_score_project_governance_marks_clear_project_healthy(self) -> None:
        status, risk_score, action, _ = score_project_governance(
            {
                "request_count_7d": 12,
                "failed_count_7d": 0,
                "denied_access_7d_count": 0,
                "budget_status": "ok",
                "budget_usage_pct": 25,
                "open_budget_alert_count": 0,
                "unpaid_invoice_count": 0,
                "overdue_invoice_count": 0,
                "open_governance_action_count": 0,
            }
        )

        self.assertEqual(status, "healthy")
        self.assertEqual(risk_score, 0)
        self.assertEqual(action, "monitor")

    def test_score_project_governance_accepts_budget_ratio(self) -> None:
        status, risk_score, action, details = score_project_governance(
            {
                "request_count_7d": 12,
                "failed_count_7d": 0,
                "denied_access_7d_count": 0,
                "budget_status": "ok",
                "budget_usage_pct": 1.05,
                "open_budget_alert_count": 0,
                "unpaid_invoice_count": 0,
                "overdue_invoice_count": 0,
                "open_governance_action_count": 0,
            }
        )

        self.assertEqual(status, "warning")
        self.assertEqual(risk_score, 35)
        self.assertEqual(action, "review_budget")
        self.assertEqual(details["risk_drivers"]["budget_usage_threshold_pct"], 105.0)

    def test_format_chi_report_prefers_project_governance_fields(self) -> None:
        report = format_chi_report(
            "project-governance",
            [
                {
                    "snapshot_code": "chi-gov-demo-quant-20260727",
                    "tenant_code": "demo",
                    "project_code": "quant-research",
                    "status": "warning",
                    "risk_score": 42,
                    "recommended_action": "review_access_policy",
                    "denied_access_7d_count": 2,
                }
            ],
        )

        self.assertIn("chi resource=project-governance rows=1", report)
        self.assertIn("project_code=quant-research", report)
        self.assertIn("recommended_action=review_access_policy", report)


if __name__ == "__main__":
    unittest.main()
