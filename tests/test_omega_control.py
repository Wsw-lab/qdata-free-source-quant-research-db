import unittest

from qdata.omega_control import _hmac_signature, _redact_rows, build_rollback_plan, format_omega_report, simulate_executor


class OmegaControlTest(unittest.TestCase):
    def test_build_rollback_plan_uses_action_hint(self) -> None:
        plan = build_rollback_plan(
            {
                "action_code": "psi-action-freeze-budget",
                "action_type": "freeze_budget",
                "source_code": "chi-action-demo",
                "safety_level": "high",
                "rollback_hint": "Unfreeze after approval.",
            }
        )

        self.assertEqual(plan["action_code"], "psi-action-freeze-budget")
        self.assertEqual(plan["rollback_hint"], "Unfreeze after approval.")
        self.assertEqual(plan["safety_level"], "high")

    def test_simulate_noop_executor_has_no_external_side_effect(self) -> None:
        status, payload, error = simulate_executor(
            {"action_code": "psi-action-notify", "action_type": "notify_owner", "planned_effect": {"operation": "notify_owner"}},
            {"executor_code": "omega-noop-notify-owner", "executor_type": "noop", "config": {"operation": "notify_owner"}},
        )

        self.assertEqual(status, "success")
        self.assertIsNone(error)
        self.assertFalse(payload["external_side_effect"])

    def test_external_executor_is_blocked_without_explicit_permission(self) -> None:
        status, payload, error = simulate_executor(
            {"action_code": "psi-action-webhook", "action_type": "notify_owner"},
            {"executor_code": "omega-webhook", "executor_type": "webhook", "config": {"operation": "notify_owner"}},
            allow_external=False,
        )

        self.assertEqual(status, "failed")
        self.assertEqual(error, "external executor disabled")
        self.assertEqual(payload["blocked_by"], "external_executor_disabled")

    def test_script_executor_runs_only_through_sandbox_allowlist(self) -> None:
        status, payload, error = simulate_executor(
            {"action_code": "alpha2-action-script", "action_type": "notify_owner", "planned_effect": {"operation": "notify_owner"}},
            {
                "executor_code": "alpha2-script-notify-owner",
                "executor_type": "script",
                "sandbox_mode": True,
                "allowlist_code": "alpha2-script-reporter",
                "command_name": "scripts/alpha2_executor_sandbox.py",
                "allowed_target": "scripts/alpha2_executor_sandbox.py",
                "timeout_seconds": 5,
                "config": {"operation": "notify_owner"},
            },
            allow_external=True,
            allowlist={
                "allowlist_code": "alpha2-script-reporter",
                "executor_type": "script",
                "target_pattern": "scripts/alpha2_executor_sandbox.py",
                "status": "active",
                "sandbox_only": True,
                "max_timeout_seconds": 5,
            },
        )

        self.assertEqual(status, "success")
        self.assertIsNone(error)
        self.assertTrue(payload["sandbox_dispatch"])
        self.assertFalse(payload["external_side_effect"])
        self.assertIn('"status": "ok"', payload["stdout"])

    def test_external_executor_rejects_non_allowlisted_target(self) -> None:
        status, payload, error = simulate_executor(
            {"action_code": "alpha2-action-script", "action_type": "notify_owner"},
            {
                "executor_code": "alpha2-script-notify-owner",
                "executor_type": "script",
                "sandbox_mode": True,
                "command_name": "scripts/alpha2_executor_sandbox.py",
                "allowed_target": "scripts/alpha2_executor_sandbox.py",
            },
            allow_external=True,
            allowlist={
                "allowlist_code": "alpha2-script-wrong",
                "executor_type": "script",
                "target_pattern": "scripts/not-this.py",
                "status": "active",
                "sandbox_only": True,
            },
        )

        self.assertEqual(status, "failed")
        self.assertEqual(error, "target_not_allowlisted")
        self.assertEqual(payload["blocked_by"], "target_not_allowlisted")

    def test_hmac_signature_uses_sha256_prefix(self) -> None:
        self.assertEqual(
            _hmac_signature(b'{"a":1}', "secret"),
            "sha256=aa9e2e3575f5d7098b6caccd790888c36d5fdb63342a73bada2d6a51747a8494",
        )

    def test_format_omega_report_summarizes_attempts(self) -> None:
        report = format_omega_report(
            {
                "status": "warning",
                "action_count": 1,
                "attempt_count": 1,
                "success_count": 0,
                "approval_required_count": 1,
                "retry_scheduled_count": 0,
                "failed_count": 0,
                "attempts": [
                    {
                        "attempt_code": "omega-attempt-demo",
                        "action_code": "psi-action-demo",
                        "action_type": "freeze_budget",
                        "status": "approval_required",
                    }
                ],
            }
        )

        self.assertIn("omega_control status=warning", report)
        self.assertIn("approval_required=1", report)
        self.assertIn("action_type=freeze_budget", report)

    def test_redacts_nested_sensitive_fields(self) -> None:
        rows = _redact_rows(
            [
                {
                    "executor_code": "omega-webhook",
                    "config": {"endpoint": "https://example.test", "token": "secret-token", "nested": {"password": "pw"}},
                }
            ]
        )

        self.assertEqual(rows[0]["config"]["token"], "<redacted>")
        self.assertEqual(rows[0]["config"]["nested"]["password"], "<redacted>")
        self.assertEqual(rows[0]["config"]["endpoint"], "https://example.test")


if __name__ == "__main__":
    unittest.main()
