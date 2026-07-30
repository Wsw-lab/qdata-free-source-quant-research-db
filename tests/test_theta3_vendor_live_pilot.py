from argparse import Namespace
import unittest

from qdata.theta3_vendor_live_pilot import (
    _build_dataset_results,
    _dataset_status,
    format_theta3_rows,
)
from scripts.run_theta3_vendor_live_pilot import _params


class Theta3VendorLivePilotTest(unittest.TestCase):
    def test_dataset_status_aggregates_blocked_failed_and_success_inputs(self) -> None:
        self.assertEqual(
            _dataset_status(
                closure_status="blocked",
                probe_status="success",
                schema_status="success",
                onboarding_status="success",
            ),
            "blocked",
        )
        self.assertEqual(
            _dataset_status(
                closure_status="success",
                probe_status="failed",
                schema_status="success",
                onboarding_status="success",
            ),
            "failed",
        )
        self.assertEqual(
            _dataset_status(
                closure_status="success",
                probe_status="skipped",
                schema_status="success",
                onboarding_status="success",
            ),
            "success",
        )

    def test_build_dataset_results_keeps_blocking_evidence_without_live_call(self) -> None:
        results = _build_dataset_results(
            closure={
                "status": "blocked",
                "source_code": "vendor_http",
                "closure_code": "eta3-live-closure-demo",
                "endpoint_status": "blocked",
                "onboarding_status": "blocked",
                "recommendation": "research_only",
                "gate_codes": ["epsilon3-live-gate-vendor_http-daily_bar-blocked-demo"],
                "blocking_issues": [
                    "external_vendor_live_disabled",
                    "dataset_not_enabled:security_master",
                ],
            },
            probes=[
                {
                    "dataset_code": "daily_bar",
                    "probe_code": "eta3-live-probe-demo",
                    "status": "blocked",
                    "schema_status": "skipped",
                    "live_requested": False,
                    "live_executed": False,
                    "missing_fields": ["close", "symbol", "trade_date"],
                    "error_message": "external_vendor_live_disabled",
                }
            ],
            dataset_codes=["daily_bar", "security_master"],
            run_benchmarks=False,
        )

        daily_bar = results[0]
        security_master = results[1]

        self.assertEqual(daily_bar["status"], "blocked")
        self.assertEqual(daily_bar["gate_code"], "epsilon3-live-gate-vendor_http-daily_bar-blocked-demo")
        self.assertFalse(daily_bar["live_executed"])
        self.assertIn("close", daily_bar["missing_fields"])
        self.assertEqual(daily_bar["recommendation"], "research_only")
        self.assertIn("dataset_not_enabled:security_master", security_master["blocking_issues"])

    def test_format_theta3_rows_prioritizes_pilot_fields(self) -> None:
        report = format_theta3_rows(
            "runs",
            [
                {
                    "pilot_code": "theta3-live-pilot-demo",
                    "source_code": "vendor_http",
                    "status": "blocked",
                    "signoff_status": "not_ready",
                    "risk_level": "high",
                    "recommendation": "research_only",
                }
            ],
        )

        self.assertIn("pilot_code=theta3-live-pilot-demo", report)
        self.assertIn("signoff_status=not_ready", report)
        self.assertIn("risk_level=high", report)

    def test_query_params_can_skip_run_defaults(self) -> None:
        args = Namespace(
            limit=5,
            offset=0,
            pilot_code="",
            run_code="",
            result_code="",
            closure_code="",
            probe_code="",
            gate_code="",
            dataset_code="",
            source_code="vendor_http",
            primary_source_code="csv",
            status="",
            closure_status="",
            endpoint_status="",
            schema_status="",
            onboarding_status="",
            gate_status="",
            benchmark_status="",
            signoff_status="",
            recommendation="",
            recommended_role="",
            risk_level="",
            pilot_scope="canary",
            requested_by="theta3",
            trigger_mode="manual",
            environment="local",
            start_date="2024-01-04",
            end_date="2024-01-04",
        )

        params = _params(args, include_run_defaults=False)

        self.assertNotIn("source_code", params)
        self.assertNotIn("primary_source_code", params)
        self.assertNotIn("pilot_scope", params)
        self.assertNotIn("requested_by", params)
        self.assertNotIn("trigger_mode", params)
        self.assertNotIn("environment", params)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)


if __name__ == "__main__":
    unittest.main()
