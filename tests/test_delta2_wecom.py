from __future__ import annotations

import unittest

from qdata.delta2_wecom import (
    _blocked_reason,
    _valid_wecom_webhook_url,
    build_wecom_message_payload,
    format_delta2_rows,
)


class Delta2WeComTest(unittest.TestCase):
    def test_build_wecom_markdown_payload(self) -> None:
        payload = build_wecom_message_payload(
            title="Delta-2 Test",
            message="hello",
            profile={"profile_code": "delta2-wecom-live-profile", "environment": "live_test"},
            action_code="omega-smoke-retry-action",
        )

        self.assertEqual(payload["msgtype"], "markdown")
        content = payload["markdown"]["content"]
        self.assertIn("Delta-2 Test", content)
        self.assertIn("delta2-wecom-live-profile", content)
        self.assertIn("omega-smoke-retry-action", content)

    def test_wecom_webhook_url_validation(self) -> None:
        self.assertTrue(_valid_wecom_webhook_url("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"))
        self.assertFalse(_valid_wecom_webhook_url("https://example.com/cgi-bin/webhook/send?key=abc"))

    def test_blocked_reason_requires_allow_external_and_endpoint(self) -> None:
        profile = {"dry_run_only": False}

        self.assertEqual(_blocked_reason(profile=profile, endpoint=None, allow_external=True), "missing_wecom_webhook_env")
        self.assertEqual(_blocked_reason(profile=profile, endpoint="https://example.com/x", allow_external=True), "invalid_wecom_webhook_url")
        self.assertEqual(
            _blocked_reason(
                profile=profile,
                endpoint="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                allow_external=False,
            ),
            "external_live_dispatch_disabled",
        )
        self.assertIsNone(
            _blocked_reason(
                profile=profile,
                endpoint="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                allow_external=True,
            )
        )

    def test_format_delta2_rows_prefers_receipt_fields(self) -> None:
        report = format_delta2_rows(
            "receipts",
            [
                {
                    "receipt_code": "delta2-wecom-receipt-demo",
                    "validation_code": "delta2-wecom-validation-demo",
                    "profile_code": "delta2-wecom-live-profile",
                    "provider_code": "wecom",
                    "status": "success",
                    "provider_errcode": 0,
                }
            ],
        )

        self.assertIn("delta2 resource=receipts rows=1", report)
        self.assertIn("receipt_code=delta2-wecom-receipt-demo", report)
        self.assertIn("provider_errcode=0", report)


if __name__ == "__main__":
    unittest.main()
