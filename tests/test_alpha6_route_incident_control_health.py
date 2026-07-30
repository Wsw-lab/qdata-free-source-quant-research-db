import unittest

from qdata.alpha6_route_incident_control_health import (
    build_route_incident_control_runbook,
    evaluate_route_incident_control_health,
    format_alpha6_rows,
)


def _metrics(**overrides):
    values = {
        "control_count": 3,
        "pending_control_count": 0,
        "approval_pending_count": 0,
        "approval_overdue_count": 0,
        "notification_blocked_count": 0,
        "notification_success_count": 1,
        "blocked_receipt_rate": 0,
        "dispatch_failed_count": 0,
        "execution_count": 2,
        "executed_count": 2,
        "failed_execution_count": 0,
        "execution_failure_rate": 0,
        "rollback_planned_count": 0,
        "missing_rollback_count": 0,
        "stale_schedule_count": 0,
        "recent_worker_run_count": 1,
        "latest_worker_status": "success",
        "latest_schedule_status": "success",
        "latest_control_stage": "executed",
    }
    values.update(overrides)
    return values


class Alpha6RouteIncidentControlHealthTest(unittest.TestCase):
    def test_evaluate_marks_healthy_when_clear(self) -> None:
        result = evaluate_route_incident_control_health(
            _metrics(),
            {"max_pending_controls": 50, "max_failed_execution_rate": 0.1, "max_blocked_receipt_rate": 0.8},
        )

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["health_issues"], [])

    def test_evaluate_marks_warning_for_pending_and_blocked_wecom(self) -> None:
        result = evaluate_route_incident_control_health(
            _metrics(pending_control_count=2, approval_pending_count=1, notification_blocked_count=3, blocked_receipt_rate=1),
            {"max_pending_controls": 50, "max_failed_execution_rate": 0.1, "max_blocked_receipt_rate": 0.8},
        )

        self.assertEqual(result["status"], "warning")
        self.assertIn("route_control_pending", result["health_issues"])
        self.assertIn("route_control_approval_pending", result["health_issues"])
        self.assertIn("route_control_wecom_blocked_rate_high", result["health_issues"])

    def test_evaluate_marks_critical_for_sla_failures_and_stale_schedule(self) -> None:
        result = evaluate_route_incident_control_health(
            _metrics(
                pending_control_count=80,
                approval_overdue_count=2,
                execution_count=5,
                failed_execution_count=2,
                execution_failure_rate=0.4,
                dispatch_failed_count=1,
                missing_rollback_count=1,
                stale_schedule_count=1,
                latest_worker_status="failed",
            ),
            {"max_pending_controls": 50, "max_failed_execution_rate": 0.1, "max_blocked_receipt_rate": 0.8},
        )

        self.assertEqual(result["status"], "critical")
        self.assertIn("route_control_approval_sla_overdue", result["health_issues"])
        self.assertIn("route_control_backlog_exceeds_limit", result["health_issues"])
        self.assertIn("route_control_execution_failure_rate_high", result["health_issues"])
        self.assertIn("route_control_dispatch_failed", result["health_issues"])
        self.assertIn("route_control_rollback_missing", result["health_issues"])
        self.assertIn("route_control_schedule_stale", result["health_issues"])
        self.assertIn("route_control_worker_failed", result["health_issues"])

    def test_runbook_names_control_actions(self) -> None:
        actions = build_route_incident_control_runbook(
            _metrics(pending_control_count=80, approval_pending_count=2, notification_blocked_count=3, missing_rollback_count=1),
            [
                "route_control_approval_sla_overdue",
                "route_control_backlog_exceeds_limit",
                "route_control_wecom_blocked",
                "route_control_rollback_missing",
                "route_control_schedule_stale",
            ],
        )

        joined = " ".join(actions)
        self.assertIn("overdue Omega-5", joined)
        self.assertIn("bounded Omega-5 control run", joined)
        self.assertIn("QDATA_DELTA2_WECOM_WEBHOOK_URL", joined)
        self.assertIn("rollback planning enabled", joined)
        self.assertIn("Force the Omega-5", joined)
        self.assertIn("Current controls=3", joined)

    def test_format_alpha6_rows_prefers_health_fields(self) -> None:
        report = format_alpha6_rows(
            "health",
            [
                {
                    "snapshot_code": "alpha6-route-control-health-demo",
                    "status": "warning",
                    "pending_control_count": 3,
                    "approval_pending_count": 1,
                    "health_issues": ["route_control_pending"],
                }
            ],
        )

        self.assertIn("alpha6 resource=health rows=1", report)
        self.assertIn("snapshot_code=alpha6-route-control-health-demo", report)
        self.assertIn("pending_control_count=3", report)
        self.assertIn("health_issues=['route_control_pending']", report)


if __name__ == "__main__":
    unittest.main()
