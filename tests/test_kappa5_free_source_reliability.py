from __future__ import annotations

from datetime import datetime, timezone
import unittest

from qdata.exceptions import QDataValidationError
from qdata.kappa5_free_source_reliability import (
    build_reliability_snapshots_from_rows,
    format_kappa5_rows,
)


class Kappa5FreeSourceReliabilityTest(unittest.TestCase):
    def test_ready_backup_for_stable_official_public_source(self) -> None:
        rows = [
            {
                "fabric_code": "iota3-free-source-fabric-demo",
                "result_code": "iota3-free-source-result-demo",
                "dataset_code": "daily_bar",
                "status": "success",
                "coverage_status": "success",
                "consistency_status": "success",
                "source_codes": ["sse_public"],
                "executed_sources": ["sse_public"],
                "blocked_sources": [],
                "missing_sources": [],
                "license_blocking_sources": [],
                "coverage_rate": "1.000000",
                "conflict_rate_bps": "0.000000",
                "blocking_issues": [],
                "next_actions": [],
                "started_at": datetime(2026, 7, 28, 9, 30, tzinfo=timezone.utc),
            }
        ]

        snapshots = build_reliability_snapshots_from_rows(rows, as_of_date="2026-07-28")

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["source_code"], "sse_public")
        self.assertEqual(snapshots[0]["status"], "ready")
        self.assertEqual(snapshots[0]["recommended_role"], "backup")
        self.assertGreaterEqual(float(snapshots[0]["reliability_score"]), 75.0)
        self.assertIn("commercial_clearance_review_required", snapshots[0]["degradation_reasons"])

    def test_rejected_after_consecutive_source_failures(self) -> None:
        rows = [
            _failed_baostock_row("iota3-free-source-result-new", datetime(2026, 7, 28, 11, 0, tzinfo=timezone.utc)),
            _failed_baostock_row("iota3-free-source-result-old", datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)),
        ]

        snapshots = build_reliability_snapshots_from_rows(rows, as_of_date="2026-07-28")

        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertEqual(snapshot["source_code"], "baostock")
        self.assertEqual(snapshot["status"], "rejected")
        self.assertEqual(snapshot["recommended_role"], "reject")
        self.assertEqual(snapshot["consecutive_failure_count"], 2)
        self.assertIn("source_failed:baostock", snapshot["degradation_reasons"])
        self.assertIn("exclude from automatic production fallback until the next successful snapshot", snapshot["recovery_actions"])

    def test_explicit_filter_without_rows_creates_no_data_snapshot(self) -> None:
        snapshots = build_reliability_snapshots_from_rows(
            [],
            as_of_date="2026-07-28",
            source_codes=["tushare_free"],
            dataset_codes=["daily_bar"],
        )

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["source_code"], "tushare_free")
        self.assertEqual(snapshots[0]["status"], "no_data")
        self.assertEqual(snapshots[0]["recommended_role"], "research_only")
        self.assertIn("no_recent_fabric_observations", snapshots[0]["degradation_reasons"])

    def test_validation_and_report_format(self) -> None:
        with self.assertRaises(QDataValidationError):
            build_reliability_snapshots_from_rows([], lookback_hours=0)

        report = format_kappa5_rows(
            "snapshots",
            [
                {
                    "snapshot_code": "kappa5-free-source-demo",
                    "source_code": "sse_public",
                    "dataset_code": "daily_bar",
                    "status": "ready",
                    "recommended_role": "backup",
                    "reliability_score": "82.0000",
                }
            ],
        )

        self.assertIn("kappa5 resource=snapshots rows=1", report)
        self.assertIn("snapshot_code=kappa5-free-source-demo", report)
        self.assertIn("recommended_role=backup", report)


def _failed_baostock_row(result_code: str, started_at: datetime) -> dict[str, object]:
    return {
        "fabric_code": "iota3-free-source-fabric-failed",
        "result_code": result_code,
        "dataset_code": "daily_bar",
        "status": "failed",
        "coverage_status": "blocked",
        "consistency_status": "skipped",
        "source_codes": ["baostock"],
        "executed_sources": [],
        "blocked_sources": ["baostock"],
        "missing_sources": ["baostock"],
        "license_blocking_sources": ["baostock"],
        "coverage_rate": "0.000000",
        "conflict_rate_bps": "0.000000",
        "blocking_issues": ["source_failed:baostock", "baostock:timed out"],
        "next_actions": ["rerun baostock with timeout guard"],
        "error_message": "baostock:timed out",
        "started_at": started_at,
    }


if __name__ == "__main__":
    unittest.main()
