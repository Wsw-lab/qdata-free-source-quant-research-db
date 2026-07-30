import tempfile
import unittest
from pathlib import Path

from qdata.exceptions import QDataValidationError
from qdata.ingest import (
    check_daily_bundle_quality,
    daily_bar_completeness,
    ingest_daily_bundle,
    read_daily_bars,
    read_security_master,
    read_trading_calendar,
)


class FakeLoader:
    def __init__(self) -> None:
        self.securities = []
        self.calendars = []
        self.daily_bars = []
        self.quality_reports = []

    def load_security_master(self, records):
        self.securities.extend(records)

    def load_trading_calendar(self, records):
        self.calendars.extend(records)

    def load_daily_bars(self, records):
        self.daily_bars.extend(records)

    def write_quality_report(self, report, check_date=None, context=None):
        self.quality_reports.append((report, check_date, context or {}))


class IngestDailyBundleTest(unittest.TestCase):
    def test_sample_csv_quality_passes(self) -> None:
        securities = read_security_master("raw/samples/security_master.csv")
        calendars = read_trading_calendar("raw/samples/trading_calendar.csv")
        daily_bars = read_daily_bars("raw/samples/daily_bar.csv")

        report = check_daily_bundle_quality(securities, calendars, daily_bars)

        self.assertTrue(report.passed)
        self.assertEqual(len(securities), 3)
        self.assertEqual(len(calendars), 2)
        self.assertEqual(len(daily_bars), 2)
        self.assertEqual(daily_bars[0].vwap, 1710.0)

    def test_bad_ohlc_blocks_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            security_path = base / "security_master.csv"
            calendar_path = base / "calendar.csv"
            daily_path = base / "daily_bar.csv"
            security_path.write_text("symbol,name,list_date\n600519.SH,贵州茅台,2001-08-27\n", encoding="utf-8")
            calendar_path.write_text("exchange,trade_date,is_open\nSH,2024-01-04,true\n", encoding="utf-8")
            daily_path.write_text(
                "symbol,trade_date,open,high,low,close,pre_close,volume,amount\n"
                "600519.SH,2024-01-04,10,9,8,10,10,100,1000\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(QDataValidationError, "quality check failed"):
                ingest_daily_bundle(
                    security_path,
                    calendar_path,
                    daily_path,
                    loader=FakeLoader(),
                    raw_root=base / "raw",
                    strict_quality=True,
                )

    def test_pipeline_calls_loader_and_stores_raw_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loader = FakeLoader()
            summary = ingest_daily_bundle(
                "raw/samples/security_master.csv",
                "raw/samples/trading_calendar.csv",
                "raw/samples/daily_bar.csv",
                loader=loader,
                raw_root=directory,
            )

            self.assertTrue(summary.quality_report.passed)
            self.assertEqual(len(loader.securities), 3)
            self.assertEqual(len(loader.calendars), 2)
            self.assertEqual(len(loader.daily_bars), 2)
            self.assertEqual(len(loader.quality_reports), 1)
            self.assertEqual(len(summary.raw_paths), 3)
            for raw_path in summary.raw_paths:
                self.assertTrue(Path(raw_path).exists())

    def test_pipeline_passes_quality_context_to_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loader = FakeLoader()
            ingest_daily_bundle(
                "raw/samples/security_master.csv",
                "raw/samples/trading_calendar.csv",
                "raw/samples/daily_bar.csv",
                loader=loader,
                raw_root=directory,
                quality_context={"job_code": "daily_market_csv_all", "run_id": 42},
            )

            self.assertEqual(loader.quality_reports[0][2]["job_code"], "daily_market_csv_all")
            self.assertEqual(loader.quality_reports[0][2]["run_id"], 42)

    def test_vwap_outside_range_warns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            security_path = base / "security_master.csv"
            calendar_path = base / "calendar.csv"
            daily_path = base / "daily_bar.csv"
            security_path.write_text("symbol,name,list_date\n600519.SH,贵州茅台,2001-08-27\n", encoding="utf-8")
            calendar_path.write_text("exchange,trade_date,is_open\nSH,2024-01-04,true\n", encoding="utf-8")
            daily_path.write_text(
                "symbol,trade_date,open,high,low,close,pre_close,volume,amount,vwap\n"
                "600519.SH,2024-01-04,10,11,9,10.5,10.3,100,1200,12\n",
                encoding="utf-8",
            )

            securities = read_security_master(security_path)
            calendars = read_trading_calendar(calendar_path)
            daily_bars = read_daily_bars(daily_path)
            report = check_daily_bundle_quality(securities, calendars, daily_bars)

            self.assertTrue(report.passed)
            self.assertEqual(report.warning_count, 1)

    def test_completeness_breaks_down_by_exchange_and_explains_missing(self) -> None:
        securities = read_security_master("raw/samples/security_master.csv")
        daily_bars = read_daily_bars("raw/samples/daily_bar.csv")

        completeness = daily_bar_completeness(
            daily_bars,
            ["600519.SH", "000001.SZ", "300750.SZ", "688001.SH"],
            securities=securities,
            trade_date="2024-01-04",
        )

        self.assertEqual(completeness["expected_by_exchange"], {"SH": 2, "SZ": 2})
        self.assertEqual(completeness["actual_by_exchange"], {"SH": 1, "SZ": 1})
        self.assertEqual(completeness["missing_by_exchange"], {"SH": ["688001.SH"], "SZ": ["300750.SZ"]})
        self.assertEqual(completeness["missing_explanations"]["300750.SZ"]["reason"], "unexplained_missing")
        self.assertEqual(completeness["missing_explanations"]["688001.SH"]["reason"], "not_in_security_master")

    def test_completeness_excludes_not_yet_listed_symbols(self) -> None:
        securities = read_security_master("raw/samples/security_master.csv")
        daily_bars = read_daily_bars("raw/samples/daily_bar.csv")

        completeness = daily_bar_completeness(
            daily_bars,
            ["600519.SH", "000001.SZ", "300750.SZ"],
            securities=securities,
            trade_date="2010-01-04",
        )

        self.assertEqual(completeness["expected_count"], 2)
        self.assertEqual(completeness["excluded_symbols"], {"listed_after_trade_date": ["300750.SZ"]})


if __name__ == "__main__":
    unittest.main()
