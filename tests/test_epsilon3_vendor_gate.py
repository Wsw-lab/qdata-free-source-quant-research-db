from argparse import Namespace
import unittest
from unittest.mock import patch

from qdata.epsilon3_vendor_gate import (
    _apply_profile_auth_default,
    _live_config_issues,
    _status_from_review,
    format_epsilon3_rows,
)
from qdata.theta import VendorRuntimeConfig
from scripts.run_epsilon3_vendor_live_gate import _params


class Epsilon3VendorGateTest(unittest.TestCase):
    def test_live_config_requires_base_url_and_token_for_bearer(self) -> None:
        config = VendorRuntimeConfig(auth_mode="bearer", base_url=None, token=None)

        issues = _live_config_issues(config)

        self.assertIn("missing_env:QDATA_VENDOR_BASE_URL", issues)
        self.assertIn("missing_env:QDATA_VENDOR_TOKEN", issues)

    def test_live_config_allows_none_auth_without_token(self) -> None:
        config = VendorRuntimeConfig(auth_mode="none", base_url="https://vendor.example", token=None)

        self.assertEqual(_live_config_issues(config), [])

    def test_gate_status_from_readiness_review(self) -> None:
        self.assertEqual(_status_from_review({"status": "ready", "recommendation": "approve_primary"}), "success")
        self.assertEqual(_status_from_review({"status": "watch", "recommendation": "approve_backup"}), "warning")
        self.assertEqual(_status_from_review({"status": "rejected", "recommendation": "reject"}), "failed")

    def test_profile_auth_mode_is_used_when_env_auth_mode_absent(self) -> None:
        config = VendorRuntimeConfig(auth_mode="none", base_url=None, token=None)

        with patch.dict("os.environ", {}, clear=True):
            merged = _apply_profile_auth_default(config, {"auth_mode": "bearer"})

        self.assertEqual(merged.auth_mode, "bearer")
        self.assertIn("missing_env:QDATA_VENDOR_TOKEN", _live_config_issues(merged))

    def test_format_epsilon3_rows_prioritizes_gate_fields(self) -> None:
        report = format_epsilon3_rows(
            "runs",
            [
                {
                    "gate_code": "epsilon3-live-gate-demo",
                    "source_code": "vendor_http",
                    "dataset_code": "daily_bar",
                    "run_mode": "blocked",
                    "status": "blocked",
                    "live_base_url_present": False,
                    "live_token_present": False,
                    "error_message": "external_vendor_live_disabled",
                }
            ],
        )

        self.assertIn("gate_code=epsilon3-live-gate-demo", report)
        self.assertIn("run_mode=blocked", report)
        self.assertIn("error_message=external_vendor_live_disabled", report)

    def test_runs_params_can_skip_run_defaults(self) -> None:
        args = Namespace(
            limit=5,
            offset=0,
            gate_code="",
            dataset_code="daily_bar",
            source_code="vendor_http",
            primary_source_code="csv",
            status="",
            run_mode="",
            requested_by="",
            trigger_mode="",
            review_code="",
            recommendation="",
            recommended_role="",
            start_date="2024-01-04",
            end_date="2024-01-04",
        )

        params = _params(args, include_run_defaults=False)

        self.assertNotIn("dataset_code", params)
        self.assertNotIn("source_code", params)
        self.assertNotIn("primary_source_code", params)
        self.assertNotIn("requested_by", params)
        self.assertNotIn("trigger_mode", params)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)


if __name__ == "__main__":
    unittest.main()
