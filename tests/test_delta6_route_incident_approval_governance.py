from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import unittest

from qdata.delta6_route_incident_approval_governance import (
    evaluate_approval_timeout,
    evaluate_route_approval_rbac,
    redact_callback_payload,
    verify_wecom_callback_signature,
)


class Delta6RouteIncidentApprovalGovernanceTest(unittest.TestCase):
    def test_wecom_signature_verification_uses_timestamp_nonce_and_raw_body(self) -> None:
        secret = "delta6-test-secret"
        body = json.dumps({"decision": "approve", "control_code": "ctrl"}, sort_keys=True).encode("utf-8")
        observed_at = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        timestamp = str(int(observed_at.timestamp()))
        nonce = "nonce-1"
        signature = hmac.new(secret.encode("utf-8"), f"{timestamp}\n{nonce}\n".encode("utf-8") + body, hashlib.sha256).hexdigest()

        result = verify_wecom_callback_signature(
            secret,
            timestamp,
            nonce,
            body,
            f"sha256={signature}",
            now=observed_at,
        )

        self.assertTrue(result["verified"])
        self.assertEqual(result["signature_status"], "verified")

        invalid = verify_wecom_callback_signature(secret, timestamp, nonce, body, "sha256=bad", now=observed_at)
        self.assertFalse(invalid["verified"])
        self.assertEqual(invalid["signature_status"], "invalid_signature")

    def test_rbac_denies_self_approval_before_role_lookup(self) -> None:
        result = evaluate_route_approval_rbac(
            signer_code="delta6-requester",
            requested_by="delta6-requester",
            role_bindings=[
                {
                    "binding_code": "delta6-role-demo",
                    "role_code": "route_approver",
                    "dataset_code": "*",
                    "source_code": "*",
                    "safety_level": "*",
                    "status": "active",
                }
            ],
            target={"dataset_code": "daily_bar", "source_code": "baostock", "safety_level": "high"},
            policy={"require_distinct_requester": True},
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason_code"], "policy_denied")

    def test_rbac_allows_scoped_route_approver_and_denies_missing_binding(self) -> None:
        target = {"dataset_code": "daily_bar", "source_code": "baostock", "safety_level": "high", "requested_by": "requester"}
        policy = {"require_distinct_requester": True, "require_risk_admin_for_high": False}

        allowed = evaluate_route_approval_rbac(
            signer_code="approver-a",
            requested_by="requester",
            role_bindings=[
                {
                    "binding_id": 7,
                    "binding_code": "delta6-role-a",
                    "role_code": "route_approver",
                    "dataset_code": "daily_bar",
                    "source_code": "*",
                    "safety_level": "*",
                    "status": "active",
                }
            ],
            target=target,
            policy=policy,
        )
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["binding_id"], 7)
        self.assertEqual(allowed["binding_code"], "delta6-role-a")

        denied = evaluate_route_approval_rbac(
            signer_code="viewer",
            requested_by="requester",
            role_bindings=[{"binding_code": "audit", "role_code": "route_audit_viewer", "dataset_code": "*", "source_code": "*", "safety_level": "*", "status": "active"}],
            target=target,
            policy=policy,
        )
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["reason_code"], "missing_binding")

    def test_timeout_evaluation_opens_after_policy_window(self) -> None:
        now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        result = evaluate_approval_timeout(
            {"started_at": (now - timedelta(minutes=12)).isoformat(), "command_code": "gamma6-demo"},
            now=now,
            policy={"timeout_minutes": 10},
        )

        self.assertTrue(result["overdue"])
        self.assertEqual(result["reason_code"], "approval_timeout")
        self.assertEqual(result["overdue_minutes"], 2)

    def test_callback_payload_redaction_handles_nested_sensitive_fields(self) -> None:
        redacted = redact_callback_payload(
            {
                "decision": "approve",
                "signature": "abc",
                "nested": {"access_token": "secret-token", "ok": "visible"},
            }
        )

        self.assertEqual(redacted["signature"], "<redacted>")
        self.assertEqual(redacted["nested"]["access_token"], "<redacted>")
        self.assertEqual(redacted["nested"]["ok"], "visible")


if __name__ == "__main__":
    unittest.main()
