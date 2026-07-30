import unittest

from qdata.omega5_route_incident_control import (
    build_route_incident_control_plan,
    format_omega5_report,
    format_omega5_rows,
    summarize_control_results,
)


class Omega5RouteIncidentControlTest(unittest.TestCase):
    def test_build_control_plan_requests_approval_notification_and_rollback(self) -> None:
        plan = build_route_incident_control_plan(
            {
                "incident_action_code": "psi5-route-incident-demo",
                "action_code": "psi-action-route-demo",
                "dataset_code": "daily_bar",
                "source_code": "baostock",
                "source_signal_type": "circuit_open",
                "action_type": "degrade_vendor",
                "safety_level": "high",
                "status": "approval_required",
                "approval_required": True,
                "action_execution_mode": "execute",
                "reason": "route circuit opened",
            },
            execution_mode="execute",
            auto_approve=True,
            requested_by="omega5-smoke",
            notify_wecom=True,
            create_rollback=True,
        )

        self.assertTrue(plan["approval_required"])
        self.assertTrue(plan["notify_wecom"])
        self.assertEqual(plan["execution_mode"], "execute")
        self.assertIn("request_approval", plan["commands"])
        self.assertIn("record_wecom_notification", plan["commands"])
        self.assertIn("approve_action", plan["commands"])
        self.assertIn("execute_action", plan["commands"])
        self.assertIn("plan_rollback", plan["commands"])

    def test_summarize_control_results_maps_pending_warning_and_execution(self) -> None:
        summary = summarize_control_results(
            [
                {"control_stage": "rollback_planned", "approval_status": "pending", "dispatch_status": "acknowledged", "receipt_status": "blocked", "rollback_status": "planned"},
                {"control_stage": "executed", "approval_status": "approved", "attempt_status": "success", "rollback_status": "planned"},
            ]
        )

        self.assertEqual(summary["status"], "warning")
        self.assertEqual(summary["approval_requested_count"], 1)
        self.assertEqual(summary["approved_count"], 1)
        self.assertEqual(summary["notification_recorded_count"], 1)
        self.assertEqual(summary["executed_count"], 1)
        self.assertEqual(summary["rollback_planned_count"], 2)

    def test_format_reports_include_control_statuses(self) -> None:
        payload = {
            "status": "warning",
            "control_count": 1,
            "approval_requested_count": 1,
            "approved_count": 0,
            "notification_recorded_count": 1,
            "executed_count": 0,
            "rollback_planned_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
            "controls": [
                {
                    "control_code": "omega5-route-control-demo",
                    "incident_action_code": "psi5-route-incident-demo",
                    "action_code": "psi-action-route-demo",
                    "source_signal_type": "circuit_open",
                    "control_stage": "rollback_planned",
                    "approval_status": "pending",
                    "dispatch_status": "acknowledged",
                    "receipt_status": "blocked",
                    "rollback_status": "planned",
                }
            ],
        }

        report = format_omega5_report(payload)
        rows_report = format_omega5_rows("controls", payload["controls"])

        self.assertIn("omega5_route_incident_control status=warning", report)
        self.assertIn("approval_status=pending", report)
        self.assertIn("omega5 resource=controls rows=1", rows_report)
        self.assertIn("control_stage=rollback_planned", rows_report)


if __name__ == "__main__":
    unittest.main()
