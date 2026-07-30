import unittest

from qdata.beta6_route_incident_ops import (
    build_approval_queue_items,
    build_notification_dedupe_plan,
    build_operation_required_actions,
    build_route_incident_pressure_plan,
    format_beta6_rows,
    summarize_route_incident_operations,
)


def _control(**overrides):
    values = {
        "control_id": 1,
        "approval_id": 10,
        "control_code": "omega5-route-control-demo",
        "approval_code": "omega-approval-demo",
        "incident_action_code": "psi5-route-incident-demo",
        "dataset_code": "daily_bar",
        "source_code": "baostock",
        "source_signal_type": "circuit_open",
        "safety_level": "high",
        "control_stage": "rollback_planned",
        "approval_status": "pending",
        "receipt_status": "blocked",
        "rollback_status": "planned",
        "approval_overdue": False,
        "age_hours": 2,
    }
    values.update(overrides)
    return values


class Beta6RouteIncidentOpsTest(unittest.TestCase):
    def test_build_approval_queue_prioritizes_critical_overdue(self) -> None:
        items = build_approval_queue_items(
            [
                _control(control_id=1, control_code="low", safety_level="low", age_hours=1),
                _control(control_id=2, control_code="critical", safety_level="critical", approval_overdue=True, age_hours=5),
            ],
            approval_decision="approve",
            max_controls=10,
        )

        self.assertEqual(items[0]["control_code"], "critical")
        self.assertEqual(items[0]["operation_decision"], "approve")
        self.assertGreater(items[0]["priority_score"], items[1]["priority_score"])

    def test_notification_dedupe_suppresses_duplicate_noncritical(self) -> None:
        items = build_approval_queue_items(
            [
                _control(control_id=1, control_code="a", safety_level="high"),
                _control(control_id=2, control_code="b", safety_level="high"),
                _control(control_id=3, control_code="c", safety_level="critical"),
            ],
            approval_decision="approve",
            max_controls=10,
        )
        plan = build_notification_dedupe_plan(items, notification_policy="dedupe_digest")

        self.assertEqual(plan["summary"]["notification_group_count"], 2)
        self.assertEqual(plan["summary"]["deduped_notification_count"], 1)
        self.assertEqual(plan["summary"]["suppressed_notification_count"], 1)
        self.assertEqual(plan["summary"]["critical_notification_count"], 1)

    def test_pressure_plan_counts_smoke_scope_and_caps_full_market(self) -> None:
        smoke = build_route_incident_pressure_plan({"dataset_count": 7, "source_count": 8, "active_source_count": 6}, stress_scope="smoke", max_controls=20)
        full = build_route_incident_pressure_plan({"dataset_count": 10, "source_count": 10, "active_source_count": 8}, stress_scope="full_market", max_controls=5)

        self.assertEqual(smoke["dataset_count"], 2)
        self.assertEqual(smoke["source_count"], 2)
        self.assertEqual(smoke["scenario_count"], 16)
        self.assertIn("pressure_test_scenarios_capped", full["issues"])
        self.assertEqual(full["scenario_count"], 20)

    def test_summarize_marks_warning_for_preview_and_dedupe(self) -> None:
        items = build_approval_queue_items([_control()], approval_decision="hold", max_controls=10)
        notification = build_notification_dedupe_plan(items, notification_policy="none")
        pressure = build_route_incident_pressure_plan({"dataset_count": 1, "source_count": 1, "active_source_count": 1}, stress_scope="smoke", max_controls=10)
        summary = summarize_route_incident_operations(
            notification["items"],
            notification_summary=notification["summary"],
            pressure_plan=pressure,
            dry_run=True,
            apply_decisions=False,
        )

        self.assertEqual(summary["status"], "warning")
        self.assertIn("operation_preview_only", summary["operation_issues"])
        self.assertIn("notification_dedupe_active", summary["operation_issues"])
        self.assertEqual(summary["counts"]["eligible_count"], 1)

    def test_required_actions_and_rows_report(self) -> None:
        actions = build_operation_required_actions(
            ["approval_queue_waiting_for_operator", "pressure_test_scenarios_capped"],
            eligible_count=3,
            pressure_plan={"scenario_count": 20, "stress_scope": "full_market"},
        )
        report = format_beta6_rows(
            "batches",
            [
                {
                    "batch_code": "beta6-route-ops-demo",
                    "status": "warning",
                    "eligible_count": 3,
                    "suppressed_notification_count": 2,
                    "stress_scenario_count": 20,
                }
            ],
        )

        self.assertIn("approve, reject or hold", " ".join(actions))
        self.assertIn("beta6 resource=batches rows=1", report)
        self.assertIn("batch_code=beta6-route-ops-demo", report)
        self.assertIn("stress_scenario_count=20", report)


if __name__ == "__main__":
    unittest.main()
