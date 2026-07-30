from argparse import Namespace
from datetime import date, datetime, timezone
import unittest

from qdata.iota3_free_source_fabric import (
    _build_dataset_result,
    format_iota3_rows,
    free_source_catalog,
)
from scripts.run_iota3_free_source_fabric import _params


class Iota3FreeSourceFabricTest(unittest.TestCase):
    def test_local_csv_fabric_successfully_cross_checks_daily_bar(self) -> None:
        result = _build_dataset_result(
            dataset_code="daily_bar",
            source_codes=["csv", "csv_mirror"],
            start=date.fromisoformat("2024-01-04"),
            end=date.fromisoformat("2024-01-04"),
            symbols=["600519.SH", "000001.SZ"],
            allow_external=False,
            require_commercial_clearance=False,
            min_source_count=2,
            min_coverage_rate=0.95,
            max_conflict_rate_bps=5.0,
            provider_kwargs_by_source={},
            started_at=datetime.now(timezone.utc),
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["coverage_status"], "success")
        self.assertEqual(result["consistency_status"], "success")
        self.assertEqual(result["license_status"], "local_smoke")
        self.assertEqual(result["usable_source_count"], 2)
        self.assertEqual(result["coverage_rate"], 1.0)
        self.assertEqual(result["conflict_rate_bps"], 0.0)

    def test_price_offset_becomes_consistency_warning(self) -> None:
        result = _build_dataset_result(
            dataset_code="daily_bar",
            source_codes=["csv", "csv_mirror"],
            start=date.fromisoformat("2024-01-04"),
            end=date.fromisoformat("2024-01-04"),
            symbols=["600519.SH", "000001.SZ"],
            allow_external=False,
            require_commercial_clearance=False,
            min_source_count=2,
            min_coverage_rate=0.95,
            max_conflict_rate_bps=5.0,
            provider_kwargs_by_source={"csv_mirror": {"close_offset_bps": 10}},
            started_at=datetime.now(timezone.utc),
        )

        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["consistency_status"], "warning")
        self.assertGreater(result["conflict_rate_bps"], 5.0)
        self.assertIn("conflict_rate_above_threshold:5.0", result["blocking_issues"])

    def test_external_free_source_is_blocked_until_explicitly_allowed(self) -> None:
        result = _build_dataset_result(
            dataset_code="daily_bar",
            source_codes=["akshare"],
            start=date.fromisoformat("2024-01-04"),
            end=date.fromisoformat("2024-01-04"),
            symbols=["600519.SH"],
            allow_external=False,
            require_commercial_clearance=False,
            min_source_count=1,
            min_coverage_rate=0.95,
            max_conflict_rate_bps=5.0,
            provider_kwargs_by_source={},
            started_at=datetime.now(timezone.utc),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("akshare:external_free_source_disabled", result["blocking_issues"])

    def test_catalog_exposes_free_source_candidates(self) -> None:
        catalog = free_source_catalog()
        source_codes = {row["source_code"] for row in catalog}

        self.assertIn("akshare", source_codes)
        self.assertIn("baostock", source_codes)
        self.assertIn("tushare_free", source_codes)
        self.assertIn("cninfo_public", source_codes)

    def test_format_iota3_rows_prioritizes_fabric_fields(self) -> None:
        report = format_iota3_rows(
            "runs",
            [
                {
                    "fabric_code": "iota3-free-source-fabric-demo",
                    "status": "success",
                    "recommendation": "backup",
                    "risk_level": "low",
                    "coverage_rate": 1.0,
                    "conflict_rate_bps": 0.0,
                }
            ],
        )

        self.assertIn("fabric_code=iota3-free-source-fabric-demo", report)
        self.assertIn("recommendation=backup", report)
        self.assertIn("risk_level=low", report)

    def test_query_params_can_skip_run_defaults(self) -> None:
        args = Namespace(
            limit=5,
            offset=0,
            fabric_code="",
            run_code="",
            result_code="",
            dataset_code="",
            source_code="",
            status="",
            coverage_status="",
            consistency_status="",
            license_status="",
            freshness_status="",
            recommendation="",
            recommended_role="",
            risk_level="",
            baseline_source_code="",
            requested_by="iota3",
            trigger_mode="manual",
            environment="local",
            fabric_scope="canary",
            start_date="2024-01-04",
            end_date="2024-01-04",
        )

        params = _params(args, include_run_defaults=False)

        self.assertNotIn("requested_by", params)
        self.assertNotIn("trigger_mode", params)
        self.assertNotIn("environment", params)
        self.assertNotIn("fabric_scope", params)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)


if __name__ == "__main__":
    unittest.main()
