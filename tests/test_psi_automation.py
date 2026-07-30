import unittest

from qdata.psi_automation import build_automation_actions, format_psi_report, format_psi_rows


class PsiAutomationTest(unittest.TestCase):
    def test_build_automation_actions_maps_phi_and_chi_sources(self) -> None:
        actions = build_automation_actions(
            [
                {
                    "decision_id": 7,
                    "decision_code": "phi-decision-commercial",
                    "run_code": "phi-local-20260727",
                    "policy_code": "phi-commercial-risk-gate",
                    "domain": "commercial",
                    "subject_type": "project",
                    "subject_code": "quant-research",
                    "action": "open_review",
                    "status": "escalate",
                    "severity": "high",
                    "priority_score": 31,
                    "recommended_owner": "commercial-ops",
                    "reason": "budget risk requires review",
                }
            ],
            [
                {
                    "action_id": 11,
                    "action_code": "chi-action-demo-review-budget",
                    "tenant_id": 1,
                    "project_id": 2,
                    "tenant_code": "demo",
                    "project_code": "quant-research",
                    "action_type": "review_budget",
                    "severity": "high",
                    "status": "open",
                    "owner": "platform-governance",
                    "reason": "project budget exceeded",
                }
            ],
            run_code="psi-local-20260727-dry-run",
            execution_mode="dry_run",
        )

        action_types = {row["action_type"] for row in actions}
        self.assertIn("escalate_commercial", action_types)
        self.assertIn("freeze_budget", action_types)
        freeze = next(row for row in actions if row["action_type"] == "freeze_budget")
        self.assertEqual(freeze["source_type"], "chi_governance_action")
        self.assertEqual(freeze["safety_level"], "high")
        self.assertTrue(freeze["approval_required"])

    def test_build_automation_actions_maps_route_incident_signals(self) -> None:
        actions = build_automation_actions(
            [],
            [],
            [
                {
                    "source_signal_type": "circuit_open",
                    "breaker_id": 3,
                    "breaker_code": "chi5-breaker-demo",
                    "snapshot_id": 4,
                    "snapshot_code": "chi5-route-health-demo",
                    "dataset_id": 10,
                    "dataset_code": "daily_bar",
                    "source_id": 20,
                    "source_code": "baostock",
                    "route_status": "circuit_open",
                    "circuit_status": "open",
                    "open_until": "2026-07-29T10:00:00+08:00",
                    "failure_rate": "1.000000",
                    "health_issues": ["failure_rate_high"],
                },
                {
                    "source_signal_type": "recovered",
                    "probe_id": 5,
                    "probe_code": "chi5-probe-demo",
                    "dataset_id": 10,
                    "dataset_code": "daily_bar",
                    "source_id": 20,
                    "source_code": "baostock",
                    "route_status": "healthy",
                    "circuit_status": "closed",
                    "probe_status": "recovered",
                },
            ],
            run_code="psi5-route-smoke",
            execution_mode="execute",
            route_owner="platform-ops",
        )

        circuit = next(row for row in actions if row["source_type"] == "route_circuit_breaker")
        self.assertEqual(circuit["action_type"], "degrade_vendor")
        self.assertEqual(circuit["safety_level"], "high")
        self.assertTrue(circuit["approval_required"])
        self.assertEqual(circuit["dataset_id"], 10)
        self.assertEqual(circuit["planned_effect"]["notification_channel"], "wecom")
        self.assertEqual(circuit["details"]["route"]["source_code"], "baostock")

        recovered = next(row for row in actions if row["source_type"] == "route_recovery_probe")
        self.assertEqual(recovered["action_type"], "monitor")
        self.assertEqual(recovered["safety_level"], "low")
        self.assertFalse(recovered["approval_required"])

    def test_format_psi_report_summarizes_actions(self) -> None:
        report = format_psi_report(
            {
                "run_code": "psi-local-20260727-dry-run",
                "status": "success",
                "execution_mode": "dry_run",
                "action_count": 1,
                "executed_count": 0,
                "approval_required_count": 0,
                "skipped_count": 1,
                "failed_count": 0,
                "actions": [
                    {
                        "action_code": "psi-action-demo",
                        "source_type": "phi_decision",
                        "source_code": "phi-decision-demo",
                        "action_type": "escalate_commercial",
                        "safety_level": "medium",
                        "status": "skipped",
                        "owner": "commercial-ops",
                        "reason": "dry run",
                    }
                ],
            }
        )

        self.assertIn("psi_automation run=psi-local-20260727-dry-run", report)
        self.assertIn("actions=1", report)
        self.assertIn("action_type=escalate_commercial", report)

    def test_format_psi_rows_summarizes_route_actions(self) -> None:
        report = format_psi_rows(
            "route-actions",
            [
                {
                    "incident_action_code": "psi5-route-incident-demo",
                    "run_code": "psi5-route-smoke",
                    "action_code": "psi-action-route",
                    "source_signal_type": "circuit_open",
                    "dataset_code": "daily_bar",
                    "source_code": "baostock",
                    "action_type": "degrade_vendor",
                    "safety_level": "high",
                    "execution_mode": "execute",
                    "status": "approval_required",
                    "approval_required": True,
                    "owner": "platform-ops",
                    "circuit_status": "open",
                }
            ],
        )

        self.assertIn("psi resource=route-actions rows=1", report)
        self.assertIn("source_signal_type=circuit_open", report)
        self.assertIn("status=approval_required", report)


if __name__ == "__main__":
    unittest.main()
