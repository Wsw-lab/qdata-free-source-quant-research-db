import unittest

from qdata.exceptions import QDataValidationError
from qdata.lambda_worker import (
    LambdaTaskResult,
    format_worker_report,
    normalize_task_names,
    run_lambda_worker,
)


class LambdaWorkerTest(unittest.TestCase):
    def test_normalize_task_names_defaults_and_dedupes(self) -> None:
        self.assertEqual(
            normalize_task_names(None),
            [
                "usage_rollup",
                "alert_dispatch",
                "vendor_benchmark_schedule",
                "free_source_recovery",
                "free_source_recovery_execute",
                "free_source_recovery_health",
                "free_source_admission_review",
                "vendor_contract_readiness_review",
                "vendor_primary_promotion_review",
                "vendor_post_promotion_monitor",
                "vendor_primary_stability_monitor",
                "vendor_cost_optimizer",
                "vendor_route_weight_executor",
                "vendor_production_source_closure",
                "source_route_feedback_monitor",
                "route_incident_automation",
                "route_incident_control",
                "route_incident_control_health",
                "route_incident_operations",
                "route_incident_approval_resilience",
                "route_incident_approval_release",
            ],
        )
        self.assertEqual(
            normalize_task_names(["usage_rollup", "usage_rollup", "alert_dispatch"]),
            ["usage_rollup", "alert_dispatch"],
        )
        with self.assertRaises(QDataValidationError):
            normalize_task_names(["unknown"])

    def test_run_worker_without_db_aggregates_custom_task_results(self) -> None:
        result = run_lambda_worker(
            None,
            task_names=["usage_rollup", "alert_dispatch"],
            trade_date="2026-07-24",
            dry_run=True,
            write_db=False,
            task_handlers={
                "usage_rollup": lambda context: LambdaTaskResult("usage_rollup", "success", 2, success_count=2),
                "alert_dispatch": lambda context: LambdaTaskResult("alert_dispatch", "warning", 1, warning_count=1),
            },
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.processed_count, 3)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.warning_count, 1)
        self.assertTrue(result.dry_run)
        self.assertIsNone(result.worker_run_id)

    def test_run_worker_captures_task_exception(self) -> None:
        def boom(context):
            raise RuntimeError("task exploded")

        result = run_lambda_worker(
            None,
            task_names=["usage_rollup"],
            trade_date="2026-07-24",
            write_db=False,
            task_handlers={"usage_rollup": boom},
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.task_results[0].error_message, "task exploded")

    def test_format_worker_report(self) -> None:
        result = run_lambda_worker(
            None,
            task_names=["usage_rollup"],
            trade_date="2026-07-24",
            write_db=False,
            task_handlers={"usage_rollup": lambda context: LambdaTaskResult("usage_rollup", "success", 1, success_count=1)},
        )

        report = format_worker_report(result)

        self.assertIn("lambda_worker run_code=", report)
        self.assertIn("status=success", report)
        self.assertIn("task name=usage_rollup", report)


if __name__ == "__main__":
    unittest.main()
