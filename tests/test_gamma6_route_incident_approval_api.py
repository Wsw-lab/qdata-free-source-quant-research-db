import unittest

from qdata.exceptions import QDataValidationError
from qdata.gamma6_route_incident_approval_api import (
    build_approval_command_item,
    command_issues,
    command_status,
    evaluate_approval_quorum,
    submit_route_incident_approval_command,
)


class Gamma6RouteIncidentApprovalApiTest(unittest.TestCase):
    def test_quorum_evaluation_tracks_remaining_signatures(self) -> None:
        pending = evaluate_approval_quorum(1, 2)
        self.assertFalse(pending["quorum_met"])
        self.assertEqual(pending["quorum_status"], "pending")
        self.assertEqual(pending["remaining_approvals"], 1)

        met = evaluate_approval_quorum(2, 2)
        self.assertTrue(met["quorum_met"])
        self.assertEqual(met["quorum_status"], "met")
        self.assertEqual(met["remaining_approvals"], 0)

    def test_command_status_keeps_pending_quorum_until_threshold_met(self) -> None:
        summary = {
            "target_count": 1,
            "applied_count": 0,
            "held_count": 0,
            "rejected_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "approval_count": 1,
            "duplicate_count": 0,
            "quorum_status": "pending",
        }
        self.assertEqual(command_status(summary, decision="approve"), "pending_quorum")
        summary["quorum_status"] = "met"
        summary["applied_count"] = 1
        self.assertEqual(command_status(summary, decision="approve"), "applied")

    def test_command_issues_collects_quorum_skip_failure_and_duplicates(self) -> None:
        items = [
            {"item_status": "pending_quorum", "evidence": {}},
            {"item_status": "skipped", "evidence": {"duplicate_signature": True}},
            {"item_status": "failed", "evidence": {}},
        ]
        issues = command_issues(items, [{"control_code": "ctrl"}])
        self.assertEqual(
            issues,
            [
                "approval_quorum_pending",
                "approval_item_skipped",
                "approval_item_failed",
                "approval_signature_duplicate",
            ],
        )

    def test_build_command_item_preserves_before_state_and_signer(self) -> None:
        item = build_approval_command_item(
            {
                "control_id": 7,
                "approval_id": 8,
                "control_code": "omega5-route-control-demo",
                "approval_code": "omega-approval-demo",
                "dataset_code": "daily_bar",
                "source_code": "baostock",
                "approval_status": "pending",
                "control_stage": "approval_requested",
            },
            decision="approve",
            signer_code="alice",
            required_approvals=2,
            idempotency_key="gamma6-test",
            item_status="pending_quorum",
            signature_count=1,
        )
        self.assertEqual(item["control_code"], "omega5-route-control-demo")
        self.assertEqual(item["approval_status_before"], "pending")
        self.assertEqual(item["control_stage_before"], "approval_requested")
        self.assertEqual(item["signer_code"], "alice")
        self.assertEqual(item["signature_count"], 1)

    def test_submit_validates_selector_and_quorum_before_db_access(self) -> None:
        with self.assertRaises(QDataValidationError):
            submit_route_incident_approval_command(
                "postgresql://unused",
                decision="approve",
                requested_by="alice",
                required_approvals=6,
                control_code="ctrl",
            )
        with self.assertRaises(QDataValidationError):
            submit_route_incident_approval_command(
                "postgresql://unused",
                decision="approve",
                requested_by="alice",
                control_code="ctrl",
                approval_code="approval",
            )


if __name__ == "__main__":
    unittest.main()

