import unittest

from qdata.mu5_free_source_recovery_executor import (
    build_manual_review_message,
    classify_retry_execution_result,
    format_mu5_rows,
)


class Mu5FreeSourceRecoveryExecutorTest(unittest.TestCase):
    def test_classify_retry_execution_result_is_conservative(self) -> None:
        self.assertEqual(classify_retry_execution_result({"iota5_pool_status": "ok"}), "recovered")
        self.assertEqual(classify_retry_execution_result({"iota5_pool_status": "degraded"}), "failed")
        self.assertEqual(classify_retry_execution_result({"iota5_pool_status": "failed"}), "failed")

    def test_build_manual_review_message_contains_policy_boundary(self) -> None:
        message = build_manual_review_message(
            {
                "action_code": "lambda5-tushare-free-daily-bar-review",
                "source_code": "tushare_free",
                "dataset_code": "daily_bar",
                "severity": "critical",
                "reason_code": "token_missing",
                "reliability_score": 0,
                "recovery_actions": ["review token and license", "keep source as research evidence only"],
            }
        )

        self.assertIn("tushare_free/daily_bar", message)
        self.assertIn("reason_code: token_missing", message)
        self.assertIn("research/validation/backup evidence only", message)

    def test_format_mu5_rows_prefers_execution_fields(self) -> None:
        report = format_mu5_rows(
            "executions",
            [
                {
                    "execution_code": "mu5-manual-review-demo",
                    "action_code": "lambda5-akshare-daily-bar-review",
                    "source_code": "akshare",
                    "dataset_code": "daily_bar",
                    "execution_type": "manual_review",
                    "status": "review_requested",
                    "approval_code": "omega-approval-demo",
                    "wecom_receipt_code": "delta2-wecom-receipt-demo",
                }
            ],
        )

        self.assertIn("mu5 resource=executions rows=1", report)
        self.assertIn("execution_code=mu5-manual-review-demo", report)
        self.assertIn("approval_code=omega-approval-demo", report)


if __name__ == "__main__":
    unittest.main()
