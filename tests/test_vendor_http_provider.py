import json
import unittest
from urllib.error import HTTPError

from qdata.exceptions import QDataProviderError
from qdata.sources.providers.vendor_http_provider import VendorHttpProvider
from qdata.sources.registry import create_provider


class VendorHttpProviderTest(unittest.TestCase):
    def test_fixture_mode_returns_vendor_named_bundle(self) -> None:
        provider = create_provider(
            "vendor_http",
            fixture_daily_bar_path="raw/samples/daily_bar.csv",
            close_offset_bps=10,
        )

        bundle = provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

        self.assertEqual(bundle.provider, "vendor_http")
        self.assertEqual(len(bundle.daily_bars), 1)
        self.assertAlmostEqual(bundle.daily_bars[0].close, 1716.715)

    def test_http_mode_maps_json_rows_to_daily_bars_and_sets_auth_header(self) -> None:
        captured = {}

        def fake_request(request, timeout):
            captured["url"] = request.full_url
            captured["auth"] = request.headers["Authorization"]
            return FakeResponse(
                {
                    "data": [
                        {
                            "symbol": "600519.SH",
                            "trade_date": "2024-01-04",
                            "open": 1700,
                            "high": 1720,
                            "low": 1690,
                            "close": 1715,
                            "pre_close": 1705,
                            "volume": 100,
                            "amount": 171500,
                        }
                    ]
                }
            )

        provider = VendorHttpProvider(
            base_url="https://vendor.example",
            token="secret",
            auth_mode="bearer",
            request_func=fake_request,
        )

        bundle = provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

        self.assertIn("trade_date=2024-01-04", captured["url"])
        self.assertEqual(captured["auth"], "Bearer secret")
        self.assertEqual(bundle.daily_bars[0].close, 1715.0)
        self.assertEqual(provider.request_count, 1)

    def test_http_mode_preserves_zero_values_during_field_fallback(self) -> None:
        def fake_request(request, timeout):
            return FakeResponse(
                {
                    "rows": [
                        {
                            "code": "000001.SZ",
                            "date": "2024-01-04",
                            "open": 0,
                            "high": 0,
                            "low": 0,
                            "close": 0,
                            "previous_close": 0,
                            "vol": 0,
                            "amount": 0,
                            "turnover": 0.0123,
                        }
                    ]
                }
            )

        provider = VendorHttpProvider(
            base_url="https://vendor.example",
            request_func=fake_request,
        )

        bar = provider.fetch_daily_market("2024-01-04", symbols=["000001.SZ"]).daily_bars[0]

        self.assertEqual(bar.open, 0)
        self.assertEqual(bar.pre_close, 0)
        self.assertEqual(bar.volume, 0)
        self.assertEqual(bar.amount, 0)
        self.assertEqual(bar.turnover_rate, 0.0123)

    def test_http_mode_applies_vendor_field_mapping_and_transforms(self) -> None:
        def fake_request(request, timeout):
            return FakeResponse(
                {
                    "data": [
                        {
                            "ts_code": "000001.SZ",
                            "date": "20240104",
                            "open_px": 10,
                            "close_px": 11,
                            "vol": 2,
                            "amount_thousand": 3,
                            "turnover_pct": 1.23,
                        }
                    ]
                }
            )

        provider = VendorHttpProvider(
            base_url="https://vendor.example",
            field_mapping={
                "date": "trade_date",
                "open_px": "open",
                "close_px": "close",
                "vol": "volume",
                "amount_thousand": "amount",
                "turnover_pct": "turnover_rate",
            },
            field_transforms={
                "date": "date_yyyymmdd",
                "vol": "volume_hand_to_share",
                "amount_thousand": "amount_thousand_to_yuan",
                "turnover_pct": "pct_to_ratio",
            },
            request_func=fake_request,
        )

        bar = provider.fetch_daily_market("2024-01-04", symbols=["000001.SZ"]).daily_bars[0]

        self.assertEqual(bar.trade_date, "2024-01-04")
        self.assertEqual(bar.open, 10)
        self.assertEqual(bar.close, 11)
        self.assertEqual(bar.volume, 200)
        self.assertEqual(bar.amount, 3000)
        self.assertEqual(bar.turnover_rate, 0.0123)

    def test_http_mode_records_retryable_error_events(self) -> None:
        calls = {"count": 0}

        def failing_request(request, timeout):
            calls["count"] += 1
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)

        provider = VendorHttpProvider(
            base_url="https://vendor.example",
            retry_limit=1,
            request_func=failing_request,
        )

        with self.assertRaises(QDataProviderError):
            provider.fetch_daily_market("2024-01-04", symbols=["600519.SH"])

        self.assertEqual(calls["count"], 2)
        self.assertEqual(len(provider.error_events), 2)
        self.assertTrue(all(event.retryable for event in provider.error_events))
        self.assertEqual({event.error_type for event in provider.error_events}, {"rate_limit"})


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
