from argparse import Namespace
from datetime import datetime, timezone
import unittest

from qdata.theta import VendorRuntimeConfig
from qdata.zeta3_vendor_onboarding import (
    _aggregate_status,
    _dataset_result,
    _preflight_issues,
    format_zeta3_rows,
)
from scripts.run_zeta3_vendor_onboarding import _params


class Zeta3VendorOnboardingTest(unittest.TestCase):
    def test_preflight_blocks_missing_live_env_contract_and_policy(self) -> None:
        profile = {
            "profile_id": 1,
            "profile_status": "active",
            "enabled_datasets": ["daily_bar"],
            "commercial_contract_ref": None,
            "redistribution_allowed": None,
            "rate_limit_per_min": 120,
        }
        config = VendorRuntimeConfig(auth_mode="bearer", base_url=None, token=None)

        issues = _preflight_issues(
            profile,
            config,
            dataset_codes=["daily_bar", "security_master"],
            live_issues=["missing_env:QDATA_VENDOR_BASE_URL", "missing_env:QDATA_VENDOR_TOKEN"],
            allow_live=False,
            require_active_profile=True,
            require_contract=True,
        )

        self.assertIn("external_vendor_live_disabled", issues)
        self.assertIn("missing_env:QDATA_VENDOR_BASE_URL", issues)
        self.assertIn("missing_env:QDATA_VENDOR_TOKEN", issues)
        self.assertIn("dataset_not_enabled:security_master", issues)
        self.assertIn("missing_commercial_contract_ref", issues)
        self.assertIn("redistribution_policy_unknown", issues)

    def test_dataset_result_keeps_blocked_gate_research_only(self) -> None:
        started = datetime.now(timezone.utc)
        gate = {
            "gate_id": 10,
            "gate_code": "epsilon3-live-gate-demo",
            "status": "blocked",
            "run_mode": "blocked",
            "executed_windows": [],
            "blocking_issues": ["external_vendor_live_disabled"],
        }

        result = _dataset_result(
            dataset_code="daily_bar",
            source_code="vendor_http",
            primary_source_code="csv",
            gate=gate,
            issues=["external_vendor_live_disabled"],
            gate_error=None,
            windows=[5, 20, 60],
            symbols=["600519.SH"],
            shard_size=500,
            max_symbols=10,
            allow_live=False,
            run_canary=True,
            run_benchmarks=False,
            full_market=False,
            started_at=started,
            finished_at=started,
        )

        self.assertEqual(result["stage_status"], "blocked")
        self.assertEqual(result["recommendation"], "research_only")
        self.assertFalse(result["live_executed"])
        self.assertEqual(_aggregate_status(["external_vendor_live_disabled"], [result]), "blocked")

    def test_format_zeta3_rows_prioritizes_onboarding_fields(self) -> None:
        report = format_zeta3_rows(
            "runs",
            [
                {
                    "run_code": "zeta3-onboarding-demo",
                    "source_code": "vendor_http",
                    "status": "blocked",
                    "preflight_status": "blocked",
                    "recommendation": "research_only",
                    "live_base_url_present": False,
                    "live_token_present": False,
                }
            ],
        )

        self.assertIn("run_code=zeta3-onboarding-demo", report)
        self.assertIn("preflight_status=blocked", report)
        self.assertIn("recommendation=research_only", report)

    def test_runs_params_can_skip_run_defaults(self) -> None:
        args = Namespace(
            limit=5,
            offset=0,
            run_code="",
            onboarding_code="",
            gate_code="",
            dataset_code="",
            source_code="vendor_http",
            primary_source_code="csv",
            status="",
            preflight_status="",
            canary_status="",
            gate_status="",
            recommendation="",
            recommended_role="",
            requested_by="zeta3",
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
