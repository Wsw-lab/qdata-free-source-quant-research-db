from __future__ import annotations

from datetime import datetime, timezone
import unittest

from qdata.exceptions import QDataValidationError
from qdata.lambda5_free_source_recovery import (
    build_recovery_actions_from_snapshots,
    format_lambda5_rows,
    summarize_recovery_actions,
)


class Lambda5FreeSourceRecoveryTest(unittest.TestCase):
    def test_rejected_snapshot_requires_manual_review_and_alert(self) -> None:
        actions = build_recovery_actions_from_snapshots(
            [
                _snapshot(
                    status="rejected",
                    source_code="tushare_free",
                    reliability_score="0.0000",
                    commercial_clearance="blocked",
                    license_status="blocked",
                    degradation_reasons=["token_missing:tushare_free", "commercial_clearance_blocked"],
                )
            ],
            now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_type"], "manual_review")
        self.assertEqual(actions[0]["severity"], "critical")
        self.assertEqual(actions[0]["reason_code"], "commercial_clearance_blocked")
        self.assertTrue(actions[0]["should_alert"])

        summary = summarize_recovery_actions([], actions)
        self.assertEqual(summary["status"], "warning")
        self.assertEqual(summary["manual_review_action_count"], 1)
        self.assertEqual(summary["alert_action_count"], 1)

    def test_degraded_snapshot_schedules_retry(self) -> None:
        actions = build_recovery_actions_from_snapshots(
            [
                _snapshot(
                    status="degraded",
                    source_code="akshare",
                    reliability_score="48.0000",
                    commercial_clearance="clear",
                    license_status="local_smoke",
                    degradation_reasons=["failed_observations:1", "akshare:timed out"],
                    consecutive_failure_count=1,
                )
            ],
            now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(actions[0]["action_type"], "retry_canary")
        self.assertEqual(actions[0]["status"], "scheduled")
        self.assertEqual(actions[0]["severity"], "high")
        self.assertEqual(actions[0]["retry_after_minutes"], 60)
        self.assertTrue(actions[0]["should_alert"])

    def test_watch_snapshot_only_observes_and_dry_run_plans(self) -> None:
        actions = build_recovery_actions_from_snapshots(
            [_snapshot(status="watch", reliability_score="62.0000")],
            dry_run=True,
            now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(actions[0]["action_type"], "observe")
        self.assertEqual(actions[0]["status"], "planned")
        self.assertFalse(actions[0]["should_alert"])

    def test_validation_and_report_format(self) -> None:
        with self.assertRaises(QDataValidationError):
            build_recovery_actions_from_snapshots([], max_actions=0)

        report = format_lambda5_rows(
            "actions",
            [
                {
                    "action_code": "lambda5-demo",
                    "source_code": "akshare",
                    "dataset_code": "daily_bar",
                    "action_type": "retry_canary",
                    "status": "scheduled",
                    "severity": "high",
                }
            ],
        )

        self.assertIn("lambda5 resource=actions rows=1", report)
        self.assertIn("action_code=lambda5-demo", report)
        self.assertIn("action_type=retry_canary", report)


def _snapshot(
    *,
    status: str,
    source_code: str = "sse_public",
    dataset_code: str = "daily_bar",
    reliability_score: str = "50.0000",
    commercial_clearance: str = "review_required",
    license_status: str = "official_public",
    degradation_reasons: list[str] | None = None,
    consecutive_failure_count: int = 0,
) -> dict[str, object]:
    return {
        "snapshot_id": 1,
        "snapshot_code": "kappa5-free-source-demo",
        "source_id": 10,
        "dataset_id": 20,
        "source_code": source_code,
        "dataset_code": dataset_code,
        "status": status,
        "recommended_role": "research_only",
        "reliability_score": reliability_score,
        "consecutive_failure_count": consecutive_failure_count,
        "license_status": license_status,
        "commercial_clearance": commercial_clearance,
        "degradation_reasons": degradation_reasons or ["score_watch"],
        "recovery_actions": ["keep source under observation"],
    }


if __name__ == "__main__":
    unittest.main()
