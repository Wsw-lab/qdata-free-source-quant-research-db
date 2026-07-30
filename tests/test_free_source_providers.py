import json
import unittest

from qdata.exceptions import QDataValidationError
from qdata.sources.providers.baostock_provider import BaoStockProvider
from qdata.sources.providers.official_public_provider import OfficialPublicProvider
from qdata.sources.providers.tushare_provider import TushareFreeProvider
from qdata.sources.registry import create_provider


class FreeSourceProviderTest(unittest.TestCase):
    def test_registry_creates_iota5_free_source_providers(self) -> None:
        self.assertIsInstance(create_provider("baostock", baostock_module=FakeBaoStock()), BaoStockProvider)
        self.assertIsInstance(create_provider("tushare_free", token="token", request_func=fake_tushare_request), TushareFreeProvider)
        self.assertIsInstance(create_provider("sse_public"), OfficialPublicProvider)

    def test_baostock_provider_maps_daily_bundle(self) -> None:
        provider = BaoStockProvider(baostock_module=FakeBaoStock())

        bundle = provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

        self.assertEqual(bundle.provider, "baostock")
        self.assertEqual(bundle.securities[0].name, "贵州茅台")
        self.assertEqual(bundle.calendars[0].exchange, "SH")
        self.assertTrue(bundle.calendars[0].is_open)
        self.assertEqual(bundle.daily_bars[0].symbol, "600519.SH")
        self.assertEqual(bundle.daily_bars[0].trade_date, "2024-01-04")
        self.assertEqual(bundle.daily_bars[0].pre_close, 1705.0)
        self.assertAlmostEqual(bundle.daily_bars[0].turnover_rate, 0.0034)

    def test_tushare_provider_requires_token(self) -> None:
        provider = TushareFreeProvider(token="", token_env="QDATA_TUSHARE_TOKEN_MISSING")

        with self.assertRaises(QDataValidationError):
            provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

    def test_tushare_provider_maps_http_rows(self) -> None:
        provider = TushareFreeProvider(token="token", request_func=fake_tushare_request)

        bundle = provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

        self.assertEqual(bundle.provider, "tushare_free")
        self.assertEqual(bundle.daily_bars[0].trade_date, "2024-01-04")
        self.assertEqual(bundle.daily_bars[0].volume, 12300.0)
        self.assertEqual(bundle.daily_bars[0].amount, 171500000.0)
        self.assertEqual(bundle.calendars[0].exchange, "SH")
        self.assertTrue(bundle.calendars[0].is_open)

    def test_official_public_provider_scaffold_is_explicit(self) -> None:
        provider = OfficialPublicProvider("sse_public")

        with self.assertRaisesRegex(QDataValidationError, "official_public_adapter_scaffold_only:sse_public"):
            provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])


class FakeBaoStock:
    def __init__(self) -> None:
        self.logged_out = False

    def login(self):
        return FakeResultStatus("0", "success")

    def logout(self):
        self.logged_out = True

    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        return FakeBaoStockResult(
            fields.split(","),
            [
                [
                    "2024-01-04",
                    code,
                    "1700.00",
                    "1720.00",
                    "1690.00",
                    "1715.00",
                    "1705.00",
                    "12300",
                    "171500000",
                    "0.34",
                    "0.58",
                    "0",
                ]
            ],
        )

    def query_stock_basic(self, code):
        return FakeBaoStockResult(
            ["code", "code_name", "ipoDate", "outDate", "type", "status"],
            [[code, "贵州茅台", "2001-08-27", "", "1", "1"]],
        )

    def query_trade_dates(self, start_date, end_date):
        return FakeBaoStockResult(["calendar_date", "is_trading_day"], [[start_date, "1"]])


class FakeResultStatus:
    def __init__(self, error_code, error_msg):
        self.error_code = error_code
        self.error_msg = error_msg


class FakeBaoStockResult:
    def __init__(self, fields, rows):
        self.error_code = "0"
        self.error_msg = "success"
        self.fields = fields
        self.rows = rows
        self.index = -1

    def next(self):
        self.index += 1
        return self.index < len(self.rows)

    def get_row_data(self):
        return self.rows[self.index]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def fake_tushare_request(http_request, timeout):
    payload = json.loads(http_request.data.decode("utf-8"))
    if payload["api_name"] == "daily":
        return FakeResponse(
            {
                "code": 0,
                "msg": None,
                "data": {
                    "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"],
                    "items": [["600519.SH", "20240104", 1700, 1720, 1690, 1715, 1705, 123, 171500]],
                },
            }
        )
    return FakeResponse(
        {
            "code": 0,
            "msg": None,
            "data": {
                "fields": ["exchange", "cal_date", "is_open", "pretrade_date"],
                "items": [["SSE", "20240104", 1, "20240103"]],
            },
        }
    )


if __name__ == "__main__":
    unittest.main()
