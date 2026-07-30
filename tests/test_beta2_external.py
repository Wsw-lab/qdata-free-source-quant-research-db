from __future__ import annotations

import unittest

from qdata.beta2_external import _dispatch_status, _idempotency_key, format_beta2_rows


class Beta2ExternalTest(unittest.TestCase):
    def test_dispatch_status_acknowledges_success(self) -> None:
        status, next_retry_at = _dispatch_status("success", {"max_retry_count": 2}, 0)

        self.assertEqual(status, "acknowledged")
        self.assertIsNone(next_retry_at)

    def test_dispatch_status_schedules_retry_before_dead_letter(self) -> None:
        status, next_retry_at = _dispatch_status("failed", {"max_retry_count": 2, "retry_backoff_seconds": 30}, 0)

        self.assertEqual(status, "retry_scheduled")
        self.assertIsNotNone(next_retry_at)

    def test_dispatch_status_dead_letters_after_retry_budget(self) -> None:
        status, next_retry_at = _dispatch_status("failed", {"max_retry_count": 0, "retry_backoff_seconds": 30}, 0)

        self.assertEqual(status, "dead_letter")
        self.assertIsNone(next_retry_at)

    def test_idempotency_key_scopes_action_channel_and_dispatch_type(self) -> None:
        key = _idempotency_key({"automation_action_id": 7}, {"channel_id": 3}, "approval_request")

        self.assertEqual(key, "7:3:approval_request")

    def test_format_beta2_rows_prefers_dispatch_fields(self) -> None:
        report = format_beta2_rows(
            "dispatches",
            [
                {
                    "dispatch_code": "beta2-dispatch-demo",
                    "action_code": "omega-smoke-retry-action",
                    "channel_code": "beta2-local-approval-webhook",
                    "dispatch_type": "approval_request",
                    "status": "suppressed",
                    "retry_count": 0,
                }
            ],
        )

        self.assertIn("beta2 resource=dispatches rows=1", report)
        self.assertIn("dispatch_code=beta2-dispatch-demo", report)
        self.assertIn("status=suppressed", report)


if __name__ == "__main__":
    unittest.main()
