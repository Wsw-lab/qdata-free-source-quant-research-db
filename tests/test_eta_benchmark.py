import unittest

from qdata.eta import run_provider_benchmark, score_vendor_quality


class EtaBenchmarkTest(unittest.TestCase):
    def test_run_provider_benchmark_scores_fixture_vendor(self) -> None:
        report = run_provider_benchmark(
            primary_provider="csv",
            secondary_provider="vendor_http",
            start_date="2024-01-04",
            end_date="2024-01-04",
            symbols=["600519.SH", "000001.SZ"],
            fields=["open", "close"],
            secondary_kwargs={
                "fixture_daily_bar_path": "raw/samples/daily_bar.csv",
                "close_offset_bps": 10,
            },
        )
        score = score_vendor_quality(report, cost_score=90, license_risk_score=70)

        self.assertEqual(report.primary_row_count, 2)
        self.assertEqual(report.secondary_row_count, 2)
        self.assertEqual(report.conflict_count, 2)
        self.assertEqual(report.status, "warning")
        self.assertEqual(score.source_code, "vendor_http")
        self.assertGreater(score.total_score, 70)
        self.assertIn(score.rating, {"A", "B", "C"})

    def test_benchmark_requires_symbols(self) -> None:
        with self.assertRaisesRegex(Exception, "symbols are required"):
            run_provider_benchmark(
                primary_provider="csv",
                secondary_provider="vendor_http",
                start_date="2024-01-04",
                end_date="2024-01-04",
                symbols=[],
            )


if __name__ == "__main__":
    unittest.main()
