from __future__ import annotations

import unittest

from qdata.phi_strategy import build_strategy_evaluation, format_strategy_evaluation


class PhiStrategyTest(unittest.TestCase):
    def test_clear_snapshot_allows_core_gates(self) -> None:
        payload = build_strategy_evaluation(
            {
                "quality": {"dataset_code": "daily_bar", "open_repair_count": 0, "open_quality_alert_count": 0, "max_conflict_rate": 0},
                "vendor_readiness": [
                    {
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "status": "ready",
                        "recommendation": "approve_primary",
                        "recommended_role": "primary",
                        "missing_window_count": 0,
                        "failed_window_count": 0,
                        "review_code": "pi-ready",
                    }
                ],
                "deployment_health": [{"status": "success", "snapshot_code": "nu-ok", "failed_count": 0}],
                "runtime_daily_reports": [{"status": "success", "report_code": "sigma-ok", "open_capacity_alert_count": 0}],
                "capacity_alerts": [],
                "budget_usage": [{"project_code": "quant-research", "status": "normal", "usage_pct": "0.25"}],
                "budget_alerts": [],
                "ar_aging": [{"project_code": "quant-research", "status": "current", "outstanding_amount": 0}],
                "customer_health": [{"project_code": "quant-research", "status": "active", "health_score": 95}],
                "payments": [],
                "payment_batches": [{"batch_code": "tau-ok", "status": "matched", "unmatched_count": 0}],
                "reconciliation": [{"reconciliation_code": "rho-ok", "status": "matched", "amount_delta": 0}],
            },
            as_of_date="2026-07-27",
            environment="local",
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["highest_severity"], "low")
        self.assertEqual(payload["policy_count"], 5)
        self.assertEqual(payload["escalation_count"], 0)
        actions = {decision["domain"]: decision["action"] for decision in payload["decisions"]}
        self.assertEqual(actions["data_quality"], "allow_production")
        self.assertEqual(actions["vendor"], "approve_primary")
        self.assertEqual(actions["runtime"], "allow_production")
        self.assertEqual(actions["payment"], "monitor")

    def test_risky_snapshot_creates_signals_decisions_and_escalations(self) -> None:
        payload = build_strategy_evaluation(
            {
                "quality": {
                    "dataset_code": "daily_bar",
                    "open_repair_count": 1,
                    "open_quality_alert_count": 1,
                    "max_conflict_rate": "0.01000000",
                    "latest_quality_status": "warning",
                },
                "vendor_readiness": [
                    {
                        "source_code": "vendor_http",
                        "dataset_code": "daily_bar",
                        "status": "rejected",
                        "recommendation": "reject",
                        "failed_window_count": 1,
                        "missing_window_count": 0,
                        "review_code": "pi-reject",
                    }
                ],
                "deployment_health": [{"status": "failed", "snapshot_code": "nu-failed", "failed_count": 1}],
                "runtime_daily_reports": [{"status": "critical", "report_code": "sigma-critical", "open_capacity_alert_count": 1}],
                "capacity_alerts": [
                    {
                        "alert_key": "cap-api",
                        "severity": "critical",
                        "metric_name": "api_slowest_duration_ms",
                        "metric_value": "6000",
                        "threshold_value": "5000",
                        "message": "api too slow",
                    }
                ],
                "budget_usage": [{"project_code": "quant-research", "status": "blocked", "usage_pct": "1.20", "snapshot_code": "budget-block"}],
                "budget_alerts": [{"project_code": "quant-research", "severity": "critical", "usage_pct": "1.20", "alert_key": "budget-alert"}],
                "ar_aging": [{"project_code": "quant-research", "status": "critical", "outstanding_amount": "1000", "aging_code": "ar-critical"}],
                "customer_health": [{"project_code": "quant-research", "status": "at_risk", "health_score": 50, "health_code": "health-risk"}],
                "payments": [{"transaction_code": "pay-unmatched", "status": "unmatched"}],
                "payment_batches": [{"batch_code": "tau-partial", "status": "partially_matched", "unmatched_count": 1}],
                "reconciliation": [{"reconciliation_code": "rho-mismatch", "status": "mismatch", "amount_delta": "10"}],
            },
            as_of_date="2026-07-27",
            environment="local",
        )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["highest_severity"], "critical")
        self.assertGreaterEqual(payload["signal_count"], 10)
        self.assertGreaterEqual(payload["escalation_count"], 5)
        decisions = {decision["domain"]: decision for decision in payload["decisions"]}
        self.assertEqual(decisions["data_quality"]["status"], "block")
        self.assertEqual(decisions["runtime"]["action"], "investigate_runtime")
        self.assertEqual(decisions["commercial"]["action"], "limit_usage")
        self.assertEqual(decisions["payment"]["action"], "reconcile_payment")

        text = format_strategy_evaluation(payload)
        self.assertIn("phi_strategy run=phi-local-20260727", text)
        self.assertIn("highest=critical", text)
        self.assertIn("escalation", text)


if __name__ == "__main__":
    unittest.main()
