import unittest

from qdata.epsilon6_route_incident_approval_resilience import (
    GENESIS_HASH,
    approval_lock_key,
    compute_audit_hash,
    evaluate_approval_state_transition,
    verify_audit_hash_entry,
)


class Epsilon6RouteIncidentApprovalResilienceTest(unittest.TestCase):
    def test_advisory_lock_key_is_deterministic_signed_bigint(self) -> None:
        key = approval_lock_key("route-approval:control_code:omega5-route-control-demo")

        self.assertEqual(key, approval_lock_key("route-approval:control_code:omega5-route-control-demo"))
        self.assertGreaterEqual(key, -(1 << 63))
        self.assertLess(key, 1 << 63)

    def test_state_machine_blocks_terminal_status(self) -> None:
        result = evaluate_approval_state_transition(
            approval_status="approved",
            control_stage="approved",
            decision="reject",
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["transition_status"], "blocked")
        self.assertEqual(result["reason_code"], "invalid_terminal_state")

    def test_state_machine_allows_pending_approve_and_hold(self) -> None:
        approve = evaluate_approval_state_transition(
            approval_status="pending",
            control_stage="rollback_planned",
            decision="approve",
        )
        hold = evaluate_approval_state_transition(
            approval_status="pending",
            control_stage="rollback_planned",
            decision="hold",
        )

        self.assertTrue(approve["allowed"])
        self.assertEqual(approve["expected_approval_status_after"], "approved")
        self.assertTrue(hold["allowed"])
        self.assertEqual(hold["reason_code"], "hold_keeps_pending")

    def test_audit_hash_entry_verification(self) -> None:
        payload = {"callback_code": "delta6-callback-demo", "governance_status": "applied"}
        hashes = compute_audit_hash(
            GENESIS_HASH,
            payload,
            chain_scope="route-approval:control_code:omega5-route-control-demo",
            sequence_no=1,
        )
        entry = {
            "chain_scope": "route-approval:control_code:omega5-route-control-demo",
            "sequence_no": 1,
            "canonical_payload": payload,
            "previous_hash": GENESIS_HASH,
            **hashes,
        }

        self.assertTrue(verify_audit_hash_entry(entry, GENESIS_HASH)["verified"])

    def test_audit_hash_entry_detects_tamper(self) -> None:
        payload = {"callback_code": "delta6-callback-demo", "governance_status": "applied"}
        hashes = compute_audit_hash(
            GENESIS_HASH,
            payload,
            chain_scope="route-approval:control_code:omega5-route-control-demo",
            sequence_no=1,
        )
        entry = {
            "chain_scope": "route-approval:control_code:omega5-route-control-demo",
            "sequence_no": 1,
            "canonical_payload": {"callback_code": "delta6-callback-demo", "governance_status": "denied"},
            "previous_hash": GENESIS_HASH,
            **hashes,
        }

        self.assertFalse(verify_audit_hash_entry(entry, GENESIS_HASH)["verified"])


if __name__ == "__main__":
    unittest.main()
