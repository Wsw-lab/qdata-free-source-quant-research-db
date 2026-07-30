import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone

from qdata.zeta6_route_incident_approval_release import (
    configured_wecom_secrets,
    format_zeta6_rows,
    record_concurrency_test_result,
    record_secret_rotation_check,
    verify_wecom_callback_signature_rotating,
)


class Zeta6RouteIncidentApprovalReleaseTest(unittest.TestCase):
    def test_configured_wecom_secrets_detects_dual_accept_phase(self) -> None:
        result = configured_wecom_secrets("current-secret", "next-secret")

        self.assertEqual(result["rotation_phase"], "dual_accept")
        self.assertEqual(result["active_secret_label"], "current")
        self.assertEqual(result["accepted_secret_labels"], ["current", "next"])
        self.assertTrue(result["dual_secret_enabled"])

    def test_rotating_signature_accepts_next_secret_without_exposing_material(self) -> None:
        payload = {"decision": "approve", "control_code": "omega5-route-control-demo", "signer_code": "approver-a"}
        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        nonce = "zeta6-rotation-test"
        digest = hmac.new(b"next-secret", f"{timestamp}\n{nonce}\n".encode("utf-8") + raw, hashlib.sha256).hexdigest()

        result = verify_wecom_callback_signature_rotating(
            raw,
            {
                "X-QData-Timestamp": timestamp,
                "X-QData-Nonce": nonce,
                "X-QData-Signature": f"sha256={digest}",
            },
            payload=payload,
            current_secret="current-secret",
            next_secret="next-secret",
        )

        self.assertTrue(result["verified"])
        self.assertEqual(result["verified_secret_label"], "next")
        self.assertNotIn("current-secret", json.dumps(result, sort_keys=True))
        self.assertNotIn("next-secret", json.dumps(result, sort_keys=True))

    def test_record_secret_rotation_check_dry_record(self) -> None:
        result = {
            "verified": True,
            "rotation_phase": "dual_accept",
            "active_secret_label": "current",
            "accepted_secret_labels": ["current", "next"],
            "verified_secret_label": "next",
            "timestamp_seconds": 1785312000,
            "nonce": "nonce",
            "request_hash": "abc123",
            "signature_digest": "def456",
            "max_clock_skew_seconds": 300,
            "evidence": {"secret_label": "next", "raw_secret": "do-not-store"},
        }

        record = record_secret_rotation_check("postgresql://unused", result, write_db=False)

        self.assertEqual(record["status"], "success")
        self.assertEqual(record["verified_secret_label"], "next")
        self.assertEqual(record["evidence"]["secret_label"], "next")
        self.assertEqual(record["evidence"]["raw_secret"], "<redacted>")

    def test_record_concurrency_test_result_dry_record(self) -> None:
        record = record_concurrency_test_result(
            "postgresql://unused",
            target_scope="route-approval:control_code:omega5-route-control-demo",
            callback_count=8,
            expected_success_count=1,
            success_count=1,
            replay_rejected_count=7,
            failed_count=0,
            max_worker_threads=4,
            write_db=False,
        )

        self.assertEqual(record["status"], "success")
        self.assertEqual(record["callback_count"], 8)
        self.assertEqual(record["replay_rejected_count"], 7)

    def test_format_zeta6_rows(self) -> None:
        report = format_zeta6_rows(
            "release_preflights",
            [{"preflight_code": "zeta6-preflight-demo", "status": "success", "check_count": 5}],
        )

        self.assertIn("zeta6 resource=release_preflights rows=1", report)
        self.assertIn("preflight_code=zeta6-preflight-demo", report)


if __name__ == "__main__":
    unittest.main()
