import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qdata.exceptions import QDataProviderError
from qdata.pipeline import DailyPipelineRunner, PipelineJobConfig, PipelineJobRecord, iter_trade_dates


class DailyPipelineRunnerTest(unittest.TestCase):
    def test_iter_trade_dates_is_inclusive(self) -> None:
        dates = [date.isoformat() for date in iter_trade_dates("2024-01-02", "2024-01-04")]

        self.assertEqual(dates, ["2024-01-02", "2024-01-03", "2024-01-04"])

    def test_runner_records_success_then_skips_existing_success(self) -> None:
        store = FakeStore()
        runner = DailyPipelineRunner(
            store=store,
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            sync_func=sync_success,
        )
        config = PipelineJobConfig(job_code="daily_market_csv", provider="csv", symbols=["600519.SH"])

        first = runner.run(config, "2024-01-04", "2024-01-04")
        second = runner.run(config, "2024-01-04", "2024-01-04")

        self.assertEqual(first[0].status, "success")
        self.assertEqual(first[0].row_count, 2)
        self.assertEqual(second[0].status, "skipped")
        self.assertEqual(store.watermark_successes[-1], (1, "2024-01-04", first[0].run_id))

    def test_runner_retries_failed_run(self) -> None:
        store = FakeStore()
        calls = {"count": 0}

        def flaky_sync(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise QDataProviderError("temporary upstream outage")
            return sync_success(**kwargs)

        runner = DailyPipelineRunner(
            store=store,
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            sync_func=flaky_sync,
        )
        config = PipelineJobConfig(
            job_code="daily_market_akshare",
            provider="akshare",
            retry_limit=1,
            skip_closed_days=False,
        )

        results = runner.run(config, "2024-01-04", "2024-01-04")

        self.assertEqual([result.status for result in results], ["failed", "success"])
        self.assertEqual([result.attempt for result in results], [1, 2])
        self.assertEqual(len(store.watermark_failures), 1)
        self.assertEqual(len(store.watermark_successes), 1)

    def test_runner_skips_closed_market_date(self) -> None:
        store = FakeStore()
        runner = DailyPipelineRunner(
            store=store,
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            sync_func=sync_success,
        )
        config = PipelineJobConfig(job_code="daily_market_csv_all", provider="csv", all_market=True)

        with patch("qdata.pipeline.runner.is_provider_trade_date", return_value=False):
            results = runner.run(config, "2024-01-05", "2024-01-05")

        self.assertEqual(results[0].status, "skipped")
        self.assertIn("market is closed", results[0].skipped_reason)

    def test_runner_resolves_full_market_symbols(self) -> None:
        store = FakeStore()

        def sync_asserts(**kwargs):
            self.assertEqual(kwargs["symbols"], ["600519.SH", "000001.SZ", "300750.SZ"])
            self.assertEqual(kwargs["expected_symbols"], ["600519.SH", "000001.SZ", "300750.SZ"])
            self.assertEqual(kwargs["batch_size"], 2)
            self.assertAlmostEqual(kwargs["min_completeness"], 0.99)
            self.assertEqual(kwargs["quality_context"]["job_code"], "daily_market_csv_all")
            self.assertTrue(kwargs["quality_context"]["all_market"])
            return sync_success(**kwargs)

        runner = DailyPipelineRunner(
            store=store,
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            sync_func=sync_asserts,
        )
        config = PipelineJobConfig(
            job_code="daily_market_csv_all",
            provider="csv",
            all_market=True,
            batch_size=2,
            min_completeness=0.99,
        )

        with patch("qdata.pipeline.runner.is_provider_trade_date", return_value=True), patch(
            "qdata.pipeline.runner.list_provider_symbols",
            return_value=["600519.SH", "000001.SZ", "300750.SZ"],
        ):
            results = runner.run(config, "2024-01-04", "2024-01-04")

        self.assertEqual(results[0].status, "success")

    def test_runner_queues_partial_success_for_repair(self) -> None:
        store = FakeStore()
        runner = DailyPipelineRunner(
            store=store,
            postgres_dsn="postgresql://unused",
            clickhouse_dsn="http://unused",
            sync_func=sync_partial,
        )
        config = PipelineJobConfig(
            job_code="daily_market_csv_all",
            provider="csv",
            all_market=True,
            min_completeness=0.99,
        )

        with patch("qdata.pipeline.runner.is_provider_trade_date", return_value=True), patch(
            "qdata.pipeline.runner.list_provider_symbols",
            return_value=["600519.SH", "000001.SZ", "300750.SZ"],
        ):
            results = runner.run(config, "2024-01-04", "2024-01-04")

        self.assertEqual(results[0].status, "partial_success")
        self.assertEqual(results[0].repair_status, "queued")
        self.assertEqual(store.runs[0]["repair_reason"], "completeness_below_threshold")
        self.assertEqual(store.watermark_failures[-1], (1, "2024-01-04", results[0].run_id))


class FakeStore:
    def __init__(self) -> None:
        self.runs = []
        self.watermark_successes = []
        self.watermark_failures = []

    def ensure_job(self, config):
        return PipelineJobRecord(
            job_id=1,
            job_code=config.job_code,
            provider=config.provider,
            dataset_code=config.dataset_code,
            retry_limit=config.retry_limit,
        )

    def has_success(self, job_id, trade_date):
        return any(
            run["job_id"] == job_id and run["trade_date"] == trade_date and run["status"] == "success"
            for run in self.runs
        )

    def next_attempt(self, job_id, trade_date):
        attempts = [
            run["attempt"]
            for run in self.runs
            if run["job_id"] == job_id and run["trade_date"] == trade_date
        ]
        return max(attempts, default=0) + 1

    def start_run(self, job_id, trade_date, attempt, run_type, symbols, provider_config):
        run_id = len(self.runs) + 1
        self.runs.append(
            {
                "run_id": run_id,
                "job_id": job_id,
                "trade_date": trade_date,
                "attempt": attempt,
                "status": "running",
            }
        )
        return run_id

    def finish_run(
        self,
        run_id,
        status,
        duration_ms,
        row_count,
        quality_passed,
        error_count,
        warning_count,
        raw_paths=None,
        error_message=None,
        expected_row_count=None,
        missing_count=0,
        missing_symbols=None,
        completeness_rate=None,
        expected_by_exchange=None,
        actual_by_exchange=None,
        missing_by_exchange=None,
        missing_explanations=None,
        batch_count=1,
        all_market=False,
        repair_status="none",
    ):
        self.runs[run_id - 1].update(
            {
                "status": status,
                "row_count": row_count,
                "quality_passed": quality_passed,
                "error_count": error_count,
                "warning_count": warning_count,
                "raw_paths": raw_paths or {},
                "error_message": error_message,
                "expected_row_count": expected_row_count,
                "missing_count": missing_count,
                "missing_symbols": missing_symbols or [],
                "completeness_rate": completeness_rate,
                "expected_by_exchange": expected_by_exchange or {},
                "actual_by_exchange": actual_by_exchange or {},
                "missing_by_exchange": missing_by_exchange or {},
                "missing_explanations": missing_explanations or {},
                "batch_count": batch_count,
                "all_market": all_market,
                "repair_status": repair_status,
            }
        )

    def record_skipped(
        self,
        job_id,
        trade_date,
        attempt,
        run_type,
        symbols,
        provider_config,
        reason,
        expected_row_count=None,
        batch_count=0,
        all_market=False,
    ):
        run_id = len(self.runs) + 1
        self.runs.append(
            {
                "run_id": run_id,
                "job_id": job_id,
                "trade_date": trade_date,
                "attempt": attempt,
                "status": "skipped",
                "error_message": reason,
                "expected_row_count": expected_row_count,
                "batch_count": batch_count,
                "all_market": all_market,
            }
        )
        return run_id

    def update_watermark_success(self, job_id, trade_date, run_id):
        self.watermark_successes.append((job_id, trade_date, run_id))

    def update_watermark_failure(self, job_id, trade_date, run_id):
        self.watermark_failures.append((job_id, trade_date, run_id))

    def upsert_repair_item(
        self,
        job_id,
        run_id,
        trade_date,
        reason,
        expected_row_count,
        row_count,
        missing_count,
        missing_symbols,
        completeness_rate,
        details,
    ):
        self.runs[run_id - 1]["repair_reason"] = reason

    def resolve_repair_items(self, job_id, trade_date, run_id):
        self.runs[run_id - 1]["resolved_repairs"] = True


def sync_success(**kwargs):
    return {
        "bundle": SimpleNamespace(daily_bars=[object(), object()]),
        "paths": {"daily_bar": "raw/vendor/test/daily_bar.csv"},
        "completeness": {
            "expected_count": 2,
            "actual_count": 2,
            "missing_count": 0,
            "missing_symbols": [],
            "completeness_rate": 1.0,
            "expected_by_exchange": {"SH": 1, "SZ": 1},
            "actual_by_exchange": {"SH": 1, "SZ": 1},
            "missing_by_exchange": {},
            "missing_explanations": {},
        },
        "batch_count": 1,
        "summary": SimpleNamespace(
            quality_report=SimpleNamespace(passed=True, error_count=0, warning_count=0)
        ),
    }


def sync_partial(**kwargs):
    result = sync_success(**kwargs)
    result["bundle"] = SimpleNamespace(daily_bars=[object(), object()])
    result["completeness"] = {
        "expected_count": 3,
        "actual_count": 2,
        "missing_count": 1,
        "missing_symbols": ["300750.SZ"],
        "completeness_rate": 2 / 3,
        "expected_by_exchange": {"SH": 1, "SZ": 2},
        "actual_by_exchange": {"SH": 1, "SZ": 1},
        "missing_by_exchange": {"SZ": ["300750.SZ"]},
        "missing_explanations": {
            "300750.SZ": {
                "status": "missing",
                "reason": "unexplained_missing",
                "exchange": "SZ",
            }
        },
    }
    result["summary"] = SimpleNamespace(
        quality_report=SimpleNamespace(passed=True, error_count=0, warning_count=2)
    )
    return result


if __name__ == "__main__":
    unittest.main()
