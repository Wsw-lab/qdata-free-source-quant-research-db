from argparse import Namespace
from datetime import datetime, timezone
import unittest

from qdata.eta3_vendor_live_closure import (
    _contract_issues,
    _profile_issues,
    _run_endpoint_probe,
    format_eta3_rows,
)
from qdata.theta import VendorRuntimeConfig
from scripts.run_eta3_vendor_live_closure import _params


class Eta3VendorLiveClosureTest(unittest.TestCase):
    def test_profile_and_contract_preflight_detects_live_blockers(self) -> None:
        profile = {
            "profile_id": 1,
            "profile_status": "testing",
            "enabled_datasets": ["daily_bar"],
            "commercial_contract_ref": None,
            "redistribution_allowed": None,
            "rate_limit_per_min": None,
        }

        profile_issues = _profile_issues(profile, ["daily_bar", "security_master"], require_active_profile=True)
        contract_issues = _contract_issues(profile, require_contract=True)

        self.assertIn("profile_not_active:testing", profile_issues)
        self.assertIn("dataset_not_enabled:security_master", profile_issues)
        self.assertIn("missing_rate_limit_per_min", profile_issues)
        self.assertIn("missing_commercial_contract_ref", contract_issues)
        self.assertIn("redistribution_policy_unknown", contract_issues)

    def test_endpoint_probe_blocks_without_external_call(self) -> None:
        config = VendorRuntimeConfig(auth_mode="bearer", base_url=None, token=None)

        probe = _run_endpoint_probe(
            "postgresql://unused",
            source_code="vendor_http",
            dataset_code="daily_bar",
            config=config,
            start_date="2024-01-04",
            end_date="2024-01-04",
            symbols=["600519.SH"],
            allow_live=False,
            requested_allow_live=False,
            live_issues=["missing_env:QDATA_VENDOR_BASE_URL", "missing_env:QDATA_VENDOR_TOKEN"],
            dataset_enabled=True,
        )

        self.assertEqual(probe["status"], "blocked")
        self.assertFalse(probe["live_executed"])
        self.assertIn("external_vendor_live_disabled", probe["error_message"])

    def test_format_eta3_rows_prioritizes_closure_fields(self) -> None:
        report = format_eta3_rows(
            "runs",
            [
                {
                    "closure_code": "eta3-live-closure-demo",
                    "source_code": "vendor_http",
                    "status": "blocked",
                    "config_status": "blocked",
                    "endpoint_status": "blocked",
                    "recommendation": "research_only",
                }
            ],
        )

        self.assertIn("closure_code=eta3-live-closure-demo", report)
        self.assertIn("config_status=blocked", report)
        self.assertIn("recommendation=research_only", report)

    def test_query_params_can_skip_run_defaults(self) -> None:
        args = Namespace(
            limit=5,
            offset=0,
            closure_code="",
            run_code="",
            probe_code="",
            dataset_code="",
            source_code="vendor_http",
            primary_source_code="csv",
            status="",
            config_status="",
            profile_check_status="",
            profile_update_status="",
            contract_status="",
            endpoint_status="",
            onboarding_status="",
            promotion_status="",
            auth_status="",
            schema_status="",
            recommendation="",
            recommended_role="",
            requested_by="eta3",
            trigger_mode="manual",
            environment="local",
            start_date="2024-01-04",
            end_date="2024-01-04",
        )

        params = _params(args, include_run_defaults=False)

        self.assertNotIn("source_code", params)
        self.assertNotIn("primary_source_code", params)
        self.assertNotIn("requested_by", params)
        self.assertNotIn("trigger_mode", params)
        self.assertNotIn("environment", params)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)


if __name__ == "__main__":
    unittest.main()
