from __future__ import annotations

import os
import unittest

from qdata.gamma2_external import (
    _profile_blocked_reason,
    _readiness_after_validation,
    _secret_env_evidence,
    _validation_status_from_dispatch,
    format_gamma2_rows,
)


class Gamma2ExternalTest(unittest.TestCase):
    def test_validation_status_from_dispatch(self) -> None:
        self.assertEqual(_validation_status_from_dispatch({"status": "acknowledged"}), "success")
        self.assertEqual(_validation_status_from_dispatch({"status": "suppressed"}), "skipped")
        self.assertEqual(_validation_status_from_dispatch({"status": "dead_letter"}), "failed")

    def test_readiness_after_validation(self) -> None:
        profile = {"readiness_status": "not_configured"}

        self.assertEqual(_readiness_after_validation(profile, "dry_run_dispatch", "success"), "dry_run_ready")
        self.assertEqual(_readiness_after_validation(profile, "live_dispatch", "success"), "live_ready")
        self.assertEqual(_readiness_after_validation(profile, "dry_run_dispatch", "blocked"), "blocked")
        self.assertEqual(_readiness_after_validation(profile, "dry_run_dispatch", "failed"), "failed")

    def test_profile_blocked_reason_guards_live_dispatch(self) -> None:
        profile = {
            "profile_status": "active",
            "channel_status": "active",
            "dry_run_only": True,
            "endpoint_url": "http://127.0.0.1:18102/gamma2/feishu",
        }

        self.assertIsNone(_profile_blocked_reason(profile, "dry_run_dispatch"))
        self.assertEqual(_profile_blocked_reason(profile, "live_dispatch"), "profile_dry_run_only")

    def test_secret_env_evidence_does_not_expose_secret_value(self) -> None:
        old_value = os.environ.get("QDATA_GAMMA2_TEST_SECRET")
        os.environ["QDATA_GAMMA2_TEST_SECRET"] = "gamma2-secret-value"
        try:
            evidence = _secret_env_evidence(
                {
                    "secret_ref": "gamma2-test-secret",
                    "metadata": {"env_var": "QDATA_GAMMA2_TEST_SECRET"},
                }
            )
        finally:
            if old_value is None:
                os.environ.pop("QDATA_GAMMA2_TEST_SECRET", None)
            else:
                os.environ["QDATA_GAMMA2_TEST_SECRET"] = old_value

        self.assertTrue(evidence["env_present"])
        self.assertEqual(evidence["env_var"], "QDATA_GAMMA2_TEST_SECRET")
        self.assertNotEqual(evidence["fingerprint"], "gamma2-secret-value")

    def test_format_gamma2_rows_prefers_profile_fields(self) -> None:
        report = format_gamma2_rows(
            "profiles",
            [
                {
                    "profile_code": "gamma2-local-feishu-profile",
                    "channel_code": "gamma2-local-feishu-dryrun",
                    "provider_code": "feishu",
                    "environment": "local",
                    "profile_status": "active",
                    "readiness_status": "dry_run_ready",
                }
            ],
        )

        self.assertIn("gamma2 resource=profiles rows=1", report)
        self.assertIn("profile_code=gamma2-local-feishu-profile", report)
        self.assertIn("readiness_status=dry_run_ready", report)


if __name__ == "__main__":
    unittest.main()
