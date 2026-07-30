import tempfile
import unittest
from pathlib import Path

from qdata.sources.export import export_daily_market_bundle
from qdata.sources.providers.akshare_provider import AkShareProvider
from qdata.sources.providers.csv_provider import CsvProvider
from qdata.sources.sync import sync_daily_market
from qdata.sources.sync_delta import sync_market_constraints, sync_minute_market


class SourceSyncTest(unittest.TestCase):
    def test_csv_provider_filters_trade_date_and_symbols(self) -> None:
        provider = CsvProvider()

        bundle = provider.fetch_daily_market(
            trade_date="2024-01-04",
            symbols=["600519.SH"],
        )

        self.assertEqual(bundle.provider, "csv")
        self.assertEqual(len(bundle.securities), 1)
        self.assertEqual(len(bundle.daily_bars), 1)
        self.assertEqual(bundle.daily_bars[0].symbol, "600519.SH")
        self.assertEqual(bundle.calendars[0].trade_date, "2024-01-04")

    def test_csv_provider_lists_symbols_and_trade_dates(self) -> None:
        provider = CsvProvider()

        self.assertEqual(provider.list_symbols(), ["600519.SH", "000001.SZ", "300750.SZ"])
        self.assertTrue(provider.is_trade_date("2024-01-04"))
        self.assertFalse(provider.is_trade_date("2024-01-05"))

    def test_csv_provider_derives_constraints_and_minute_bars(self) -> None:
        provider = CsvProvider()

        constraints = provider.fetch_market_constraints("2024-01-04", symbols=["600519.SH", "000001.SZ"])
        minutes = provider.fetch_minute_market("2024-01-04", symbols=["600519.SH"])

        self.assertEqual(len(constraints.adjustment_factors), 2)
        self.assertEqual(len(constraints.limit_prices), 2)
        self.assertEqual(constraints.limit_prices[0].limit_rule, "main_10pct")
        self.assertEqual(len(minutes.minute_bars), 1)
        self.assertEqual(minutes.minute_bars[0].bar_time, "2024-01-04 09:31:00")

    def test_export_daily_market_bundle_writes_three_csv_files(self) -> None:
        provider = CsvProvider()
        bundle = provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

        with tempfile.TemporaryDirectory() as directory:
            paths = export_daily_market_bundle(bundle, raw_root=directory)

            self.assertEqual(set(paths), {"security_master", "trading_calendar", "daily_bar"})
            for path in paths.values():
                self.assertTrue(Path(path).exists())
                self.assertIn("trade_date=2024-01-04", path)

    def test_sync_daily_market_dry_run_exports_provider_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = sync_daily_market(
                provider_name="csv",
                trade_date="2024-01-04",
                symbols=["600519.SH"],
                postgres_dsn="postgresql://unused",
                clickhouse_dsn="http://unused",
                raw_root=directory,
                dry_run=True,
                provider_kwargs={
                    "security_master_path": "raw/samples/security_master.csv",
                    "trading_calendar_path": "raw/samples/trading_calendar.csv",
                    "daily_bar_path": "raw/samples/daily_bar.csv",
                },
            )

            self.assertIsNone(result["summary"])
            self.assertEqual(len(result["bundle"].daily_bars), 1)
            self.assertTrue(Path(result["paths"]["daily_bar"]).exists())

    def test_sync_daily_market_batch_dry_run_reports_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = sync_daily_market(
                provider_name="csv",
                trade_date="2024-01-04",
                symbols=["600519.SH", "000001.SZ", "300750.SZ"],
                postgres_dsn="postgresql://unused",
                clickhouse_dsn="http://unused",
                raw_root=directory,
                dry_run=True,
                provider_kwargs={
                    "security_master_path": "raw/samples/security_master.csv",
                    "trading_calendar_path": "raw/samples/trading_calendar.csv",
                    "daily_bar_path": "raw/samples/daily_bar.csv",
                },
                expected_symbols=["600519.SH", "000001.SZ", "300750.SZ"],
                batch_size=1,
            )

            self.assertEqual(result["batch_count"], 3)
            self.assertEqual(result["completeness"]["expected_count"], 3)
            self.assertEqual(result["completeness"]["actual_count"], 2)
            self.assertEqual(result["completeness"]["missing_symbols"], ["300750.SZ"])
            self.assertEqual(result["completeness"]["missing_by_exchange"], {"SZ": ["300750.SZ"]})
            self.assertEqual(result["quality_report"].warning_count, 2)

    def test_delta_sync_dry_run_exports_constraints_and_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            constraints = sync_market_constraints(
                provider_name="csv",
                trade_date="2024-01-04",
                symbols=["600519.SH"],
                postgres_dsn="postgresql://unused",
                clickhouse_dsn="http://unused",
                raw_root=directory,
                dry_run=True,
                provider_kwargs={
                    "security_master_path": "raw/samples/security_master.csv",
                    "trading_calendar_path": "raw/samples/trading_calendar.csv",
                    "daily_bar_path": "raw/samples/daily_bar.csv",
                },
            )
            minutes = sync_minute_market(
                provider_name="csv",
                trade_date="2024-01-04",
                symbols=["600519.SH"],
                postgres_dsn="postgresql://unused",
                clickhouse_dsn="http://unused",
                raw_root=directory,
                dry_run=True,
                provider_kwargs={
                    "security_master_path": "raw/samples/security_master.csv",
                    "trading_calendar_path": "raw/samples/trading_calendar.csv",
                    "daily_bar_path": "raw/samples/daily_bar.csv",
                },
            )

            self.assertTrue(Path(constraints["paths"]["adjustment_factor"]).exists())
            self.assertTrue(Path(minutes["paths"]["minute_bar"]).exists())

    def test_akshare_hist_mapping(self) -> None:
        provider = AkShareProvider()
        hist_df = FakeDataFrame(
            [
                {
                    "日期": "2024-01-04",
                    "开盘": 10.0,
                    "最高": 11.0,
                    "最低": 9.8,
                    "收盘": 10.5,
                    "涨跌额": 0.2,
                    "成交量": 123,
                    "成交额": 129150.0,
                    "换手率": 1.5,
                }
            ],
            ["日期", "开盘", "最高", "最低", "收盘", "涨跌额", "成交量", "成交额", "换手率"],
        )

        bars = provider._hist_to_bars("000001.SZ", hist_df)

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].volume, 12300)
        self.assertAlmostEqual(bars[0].turnover_rate, 0.015)
        self.assertEqual(bars[0].pre_close, 10.3)

    def test_akshare_daily_fallback_mapping(self) -> None:
        provider = AkShareProvider()
        hist_df = FakeDataFrame(
            [
                {
                    "date": "2024-01-04",
                    "open": 9.19,
                    "high": 9.19,
                    "low": 9.08,
                    "close": 9.11,
                    "volume": 86419399.0,
                    "amount": 787470082.0,
                    "turnover": 0.004453,
                }
            ],
            ["date", "open", "high", "low", "close", "volume", "amount", "turnover"],
        )

        bars = provider._hist_to_bars("000001.SZ", hist_df)

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].volume, 86419399.0)
        self.assertAlmostEqual(bars[0].turnover_rate, 0.004453)
        self.assertIsNone(bars[0].pre_close)

    def test_akshare_daily_fallback_uses_previous_close(self) -> None:
        provider = AkShareProvider()
        hist_df = FakeDataFrame(
            [
                {
                    "date": "2024-01-03",
                    "open": 9.25,
                    "high": 9.3,
                    "low": 9.15,
                    "close": 9.2,
                    "volume": 100.0,
                    "amount": 920.0,
                    "turnover": 0.01,
                },
                {
                    "date": "2024-01-04",
                    "open": 9.19,
                    "high": 9.19,
                    "low": 9.08,
                    "close": 9.11,
                    "volume": 200.0,
                    "amount": 1822.0,
                    "turnover": 0.02,
                },
            ],
            ["date", "open", "high", "low", "close", "volume", "amount", "turnover"],
        )

        bars = provider._hist_to_bars("000001.SZ", hist_df)

        self.assertEqual(bars[1].pre_close, 9.2)
        self.assertEqual(bars[1].limit_up, 10.12)
        self.assertEqual(bars[1].limit_down, 8.28)

    def test_akshare_code_name_security_list_mapping(self) -> None:
        fake_ak = FakeAkShare(
            FakeDataFrame(
                [
                    {"code": "000001", "name": "平安银行"},
                    {"code": "600519", "name": "贵州茅台"},
                    {"code": "920001", "name": "纬达光电"},
                ],
                ["code", "name"],
            )
        )

        securities = AkShareProvider._list_securities_from_code_name(fake_ak)

        self.assertEqual([record.symbol for record in securities], ["000001.SZ", "600519.SH", "920001.BJ"])
        self.assertEqual(securities[1].name, "贵州茅台")


class FakeAkShare:
    def __init__(self, code_name_df) -> None:
        self._code_name_df = code_name_df

    def stock_info_a_code_name(self):
        return self._code_name_df


class FakeDataFrame:
    def __init__(self, rows, columns) -> None:
        self._rows = rows
        self.columns = columns
        self.empty = not rows

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row

    def __getitem__(self, columns):
        return FakeDataFrame(
            [{column: row[column] for column in columns} for row in self._rows],
            columns,
        )


if __name__ == "__main__":
    unittest.main()
