import unittest

from qdata.fusion import compare_provider_daily, select_daily_bundle_with_fallback
from qdata.sources.registry import create_provider


class FusionTest(unittest.TestCase):
    def test_csv_mirror_provider_can_create_deterministic_field_conflict(self) -> None:
        provider = create_provider("csv_mirror", close_offset_bps=10)

        bundle = provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

        self.assertEqual(bundle.provider, "csv_mirror")
        self.assertAlmostEqual(bundle.daily_bars[0].close, 1716.715)

    def test_compare_provider_daily_reports_field_level_conflicts(self) -> None:
        report = compare_provider_daily(
            "csv",
            "csv_mirror",
            trade_date="2024-01-04",
            symbols=["600519.SH", "000001.SZ"],
            fields=["open", "close"],
            secondary_kwargs={"close_offset_bps": 10},
        )

        self.assertEqual(report.primary_count, 2)
        self.assertEqual(report.secondary_count, 2)
        self.assertEqual(report.matched_count, 2)
        self.assertEqual(report.conflict_count, 2)
        self.assertEqual({conflict.field_name for conflict in report.conflicts}, {"close"})
        self.assertEqual(report.status, "warning")

    def test_select_daily_bundle_uses_fallback_after_primary_failure(self) -> None:
        selection = select_daily_bundle_with_fallback(
            [
                {"provider": "csv", "priority": 0, "kwargs": {"fail_daily": True}},
                {"provider": "csv_mirror", "priority": 10},
            ],
            trade_date="2024-01-04",
            symbols=["600519.SH"],
        )

        self.assertEqual(selection.source_code, "csv_mirror")
        self.assertEqual([attempt.status for attempt in selection.attempts], ["failed", "success"])
        self.assertEqual(len(selection.bundle.daily_bars), 1)


if __name__ == "__main__":
    unittest.main()
