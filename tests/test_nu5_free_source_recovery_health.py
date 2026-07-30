import unittest

from qdata.nu5_free_source_recovery_health import (
    build_recovery_runbook,
    evaluate_recovery_health,
    format_nu5_rows,
)


def _metrics(**overrides):
    values = {
        "pending_action_count": 0,
        "pending_retry_count": 0,
        "pending_manual_review_count": 0,
        "execution_count": 3,
        "recovered_count": 3,
        "failed_count": 0,
        "suppressed_count": 0,
        "review_requested_count": 0,
        "blocked_count": 0,
        "failure_rate": 0,
        "approval_pending_count": 0,
        "approval_overdue_count": 0,
        "backlog_count": 0,
        "stale_schedule_count": 0,
        "recent_worker_run_count": 1,
        "latest_worker_status": "success",
        "latest_schedule_status": "success",
        "latest_execution_status": "recovered",
    }
    values.update(overrides)
    return values


class Nu5FreeSourceRecoveryHealthTest(unittest.TestCase):
    def test_evaluate_recovery_health_marks_healthy_when_clear(self) -> None:
        result = evaluate_recovery_health(_metrics(), {"max_backlog_actions": 50, "max_failure_rate": 0.5})

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["health_issues"], [])

    def test_evaluate_recovery_health_marks_warning_for_pending_work(self) -> None:
        result = evaluate_recovery_health(
            _metrics(backlog_count=3, approval_pending_count=1, review_requested_count=1),
            {"max_backlog_actions": 50, "max_failure_rate": 0.5},
        )

        self.assertEqual(result["status"], "warning")
        self.assertIn("recovery_backlog_pending", result["health_issues"])
        self.assertIn("manual_review_approval_pending", result["health_issues"])

    def test_evaluate_recovery_health_marks_critical_for_sla_and_stale_schedule(self) -> None:
        result = evaluate_recovery_health(
            _metrics(
                execution_count=4,
                failed_count=3,
                failure_rate=0.75,
                approval_overdue_count=2,
                backlog_count=80,
                stale_schedule_count=1,
                latest_worker_status="failed",
            ),
            {"max_backlog_actions": 50, "max_failure_rate": 0.5},
        )

        self.assertEqual(result["status"], "critical")
        self.assertIn("approval_sla_overdue", result["health_issues"])
        self.assertIn("recovery_backlog_exceeds_limit", result["health_issues"])
        self.assertIn("recovery_execution_failure_rate_high", result["health_issues"])
        self.assertIn("recovery_schedule_stale", result["health_issues"])
        self.assertIn("recovery_worker_failed", result["health_issues"])

    def test_runbook_names_recovery_actions(self) -> None:
        actions = build_recovery_runbook(
            _metrics(backlog_count=80, approval_pending_count=2, failed_count=3),
            [
                "approval_sla_overdue",
                "recovery_backlog_exceeds_limit",
                "recovery_execution_failure_rate_high",
                "recovery_schedule_stale",
            ],
        )

        joined = " ".join(actions)
        self.assertIn("overdue Mu-5", joined)
        self.assertIn("Mu-5 recovery executor", joined)
        self.assertIn("Iota-5 adapter pool", joined)
        self.assertIn("restart the Mu scheduler", joined)
        self.assertIn("Current backlog=80", joined)

    def test_format_nu5_rows_prefers_health_fields(self) -> None:
        report = format_nu5_rows(
            "snapshots",
            [
                {
                    "snapshot_code": "nu5-recovery-health-demo",
                    "status": "warning",
                    "backlog_count": 3,
                    "approval_pending_count": 1,
                    "health_issues": ["recovery_backlog_pending"],
                }
            ],
        )

        self.assertIn("nu5 resource=snapshots rows=1", report)
        self.assertIn("snapshot_code=nu5-recovery-health-demo", report)
        self.assertIn("backlog_count=3", report)
        self.assertIn("health_issues=['recovery_backlog_pending']", report)


if __name__ == "__main__":
    unittest.main()
