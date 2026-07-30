import unittest
from types import SimpleNamespace

from qdata.exceptions import QDataValidationError
from qdata.pipeline import PipelineJobConfig, PipelineRunResult
from qdata.pipeline.production import format_results_report, resolve_production_window, summarize_results


class ProductionPipelineTest(unittest.TestCase):
    def test_resolve_window_from_watermark_with_lookback(self) -> None:
        store = FakeWatermarkStore("2024-01-04")
        config = PipelineJobConfig(job_code="daily_market_csv_all", provider="csv", all_market=True)

        start_date, end_date = resolve_production_window(
            store=store,
            config=config,
            start_date="2024-01-01",
            end_date="2024-01-10",
            from_watermark=True,
            watermark_lookback_days=1,
        )

        self.assertEqual((start_date, end_date), ("2024-01-04", "2024-01-10"))

    def test_resolve_window_requires_bootstrap_when_no_watermark(self) -> None:
        store = FakeWatermarkStore(None)
        config = PipelineJobConfig(job_code="daily_market_csv_all", provider="csv", all_market=True)

        with self.assertRaisesRegex(QDataValidationError, "bootstrap start_date"):
            resolve_production_window(
                store=store,
                config=config,
                start_date=None,
                end_date="2024-01-10",
                from_watermark=True,
            )

    def test_summarize_and_format_report(self) -> None:
        results = [
            PipelineRunResult(
                job_code="daily_market_csv_all",
                run_id=1,
                trade_date="2024-01-04",
                attempt=1,
                status="partial_success",
                row_count=2,
                expected_row_count=3,
                missing_count=1,
                completeness_rate=2 / 3,
                repair_status="queued",
            ),
            PipelineRunResult(
                job_code="daily_market_csv_all",
                run_id=2,
                trade_date="2024-01-05",
                attempt=1,
                status="skipped",
            ),
        ]

        summary = summarize_results(results)
        report = format_results_report("daily_market_csv_all", "2024-01-04", "2024-01-05", results)

        self.assertEqual(summary["statuses"], {"partial_success": 1, "skipped": 1})
        self.assertEqual(summary["missing_total"], 1)
        self.assertIn("repair_queued=1", report)


class FakeWatermarkStore:
    def __init__(self, last_success_trade_date):
        self.last_success_trade_date = last_success_trade_date

    def ensure_job(self, config):
        return SimpleNamespace(job_id=1)

    def get_watermark(self, job_id):
        if self.last_success_trade_date is None:
            return None
        return {"last_success_trade_date": self.last_success_trade_date}


if __name__ == "__main__":
    unittest.main()
