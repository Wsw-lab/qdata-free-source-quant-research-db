import unittest

from qdata.ops.dashboard import (
    build_api_summary,
    build_pipeline_summary,
    build_quality_summary,
    evaluate_sla_records,
)


class OpsDashboardTest(unittest.TestCase):
    def test_pipeline_summary_counts_runs_missing_and_repairs(self) -> None:
        summary = build_pipeline_summary(
            runs=[
                {
                    "status": "partial_success",
                    "missing_count": 1,
                    "completeness_rate": 0.66666667,
                    "duration_ms": 120,
                },
                {
                    "status": "success",
                    "missing_count": 0,
                    "completeness_rate": 1.0,
                    "duration_ms": 80,
                },
            ],
            repairs=[
                {"status": "open"},
                {"status": "resolved"},
            ],
        )

        self.assertEqual(summary["status_counts"], {"partial_success": 1, "success": 1})
        self.assertEqual(summary["missing_total"], 1)
        self.assertEqual(summary["open_repair_count"], 1)
        self.assertEqual(summary["min_completeness"], 0.66666667)
        self.assertEqual(summary["median_duration_ms"], 100)

    def test_quality_and_api_summaries_roll_up_core_metrics(self) -> None:
        quality = build_quality_summary(
            quality_checks=[
                {"status": "warning", "severity": "medium"},
                {"status": "pass", "severity": "info"},
            ],
            multi_source=[
                {
                    "trade_date": "2024-01-04",
                    "status": "warning",
                    "coverage_rate": 1.0,
                    "conflict_rate": 0.16666667,
                }
            ],
            conflicts=[
                {"status": "open", "severity": "high", "count": 2},
            ],
        )
        api = build_api_summary(
            [
                {
                    "api_name": "price",
                    "status": "success",
                    "count": 9,
                    "max_duration_ms": 12,
                    "request_date": "2024-01-04",
                },
                {
                    "api_name": "price",
                    "status": "failed",
                    "count": 1,
                    "max_duration_ms": 20,
                    "request_date": "2024-01-04",
                },
            ]
        )

        self.assertEqual(quality["conflict_count"], 2)
        self.assertEqual(quality["conflict_severity_counts"], {"high": 2})
        self.assertEqual(quality["max_conflict_rate"], 0.16666667)
        self.assertEqual(api["request_count"], 10)
        self.assertEqual(api["failed_count"], 1)
        self.assertEqual(api["error_rate"], 0.1)

    def test_evaluate_sla_records_generates_pipeline_quality_and_api_alerts(self) -> None:
        policies = [
            {
                "policy_id": 1,
                "policy_code": "daily_sla",
                "job_id": 10,
                "job_code": "daily_market_csv_all",
                "dataset_id": 7,
                "min_completeness": 0.99,
                "max_conflict_rate": 0.001,
                "max_api_error_rate": 0.05,
                "alert_severity": "high",
                "is_active": True,
            }
        ]
        alerts = evaluate_sla_records(
            policies=policies,
            pipeline_runs=[
                {
                    "job_id": 10,
                    "run_id": 100,
                    "trade_date": "2024-01-04",
                    "status": "partial_success",
                    "completeness_rate": 0.66666667,
                    "missing_symbols": ["300750.SZ"],
                }
            ],
            multi_source_quality=[
                {
                    "dataset_id": 7,
                    "trade_date": "2024-01-04",
                    "conflict_rate": 0.16666667,
                    "conflict_count": 2,
                }
            ],
            api_summary_by_date=[
                {"request_date": "2024-01-04", "request_count": 10, "failed_count": 1}
            ],
            start_date="2024-01-04",
            end_date="2024-01-04",
        )

        self.assertEqual(
            {alert["alert_type"] for alert in alerts},
            {
                "pipeline_status",
                "completeness_below_sla",
                "conflict_rate_above_sla",
                "api_error_rate_above_sla",
            },
        )
        self.assertTrue(all(alert["alert_key"].startswith("daily_sla:") for alert in alerts))

    def test_evaluate_sla_records_detects_missing_run(self) -> None:
        alerts = evaluate_sla_records(
            policies=[
                {
                    "policy_id": 1,
                    "policy_code": "daily_sla",
                    "job_id": 10,
                    "dataset_id": 7,
                    "alert_severity": "critical",
                    "is_active": True,
                }
            ],
            pipeline_runs=[],
            multi_source_quality=[],
            api_summary_by_date=[],
            start_date="2024-01-04",
            end_date="2024-01-04",
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_type"], "missing_run")
        self.assertEqual(alerts[0]["severity"], "critical")

    def test_evaluate_sla_records_generates_provider_sla_alerts(self) -> None:
        alerts = evaluate_sla_records(
            policies=[
                {
                    "policy_id": 2,
                    "policy_code": "vendor_sla",
                    "dataset_id": 7,
                    "source_id": 3,
                    "min_vendor_score": 90,
                    "max_vendor_conflict_rate": 0.005,
                    "max_vendor_failure_rate": 0.01,
                    "max_vendor_latency_ms": 5000,
                    "max_provider_error_count": 0,
                    "alert_severity": "high",
                    "is_active": True,
                }
            ],
            pipeline_runs=[],
            multi_source_quality=[],
            api_summary_by_date=[],
            start_date="2024-01-04",
            end_date="2024-01-04",
            vendor_quality_scores=[
                {
                    "source_id": 3,
                    "source_code": "akshare",
                    "dataset_id": 7,
                    "score_date": "2024-01-04",
                    "total_score": 63,
                    "rating": "C",
                    "conflict_rate": 1.0,
                    "failure_rate": 0.02,
                    "latency_ms": 6020,
                }
            ],
            provider_error_counts=[
                {
                    "source_id": 3,
                    "source_code": "akshare",
                    "dataset_id": 7,
                    "trade_date": "2024-01-04",
                    "error_count": 2,
                    "error_type_counts": {"network": 2},
                }
            ],
        )

        self.assertEqual(
            {alert["alert_type"] for alert in alerts},
            {
                "vendor_score_below_sla",
                "vendor_conflict_rate_above_sla",
                "vendor_failure_rate_above_sla",
                "vendor_latency_above_sla",
                "provider_error_count_above_sla",
            },
        )


if __name__ == "__main__":
    unittest.main()
