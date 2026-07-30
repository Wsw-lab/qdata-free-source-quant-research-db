import unittest

from qdata import Client
from qdata.exceptions import QDataValidationError


class ClientTest(unittest.TestCase):
    def test_get_price_returns_forward_adjusted_records(self) -> None:
        client = Client(default_format="records")

        rows = client.get_price(
            symbols=["600519.SH"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            adjust="forward",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "600519.SH")
        self.assertEqual(rows[0]["close"], round(1698.00 * 0.5321, 6))

    def test_fundamental_asof_does_not_leak_future_report(self) -> None:
        client = Client(default_format="records")

        rows = client.get_fundamental_asof(
            symbols=["600519.SH"],
            fields=["revenue"],
            asof_date="2021-06-30",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["report_period"], "2021-03-31")
        self.assertEqual(rows[0]["field_value"], 27271000000.0)

    def test_universe_filters_and_factor_wide_format(self) -> None:
        client = Client(default_format="records")

        universe = client.get_universe(
            universe="hs300",
            asof_date="2024-01-02",
            filters={"exclude_st": True, "exclude_suspended": True, "min_list_days": 120},
        )
        self.assertEqual({row["symbol"] for row in universe}, {"600519.SH", "000001.SZ"})

        factors = client.get_factor(
            factors=["momentum_20d", "roe_ttm"],
            universe="hs300",
            start_date="2024-01-02",
            end_date="2024-01-02",
            format="wide",
        )
        self.assertEqual(len(factors), 2)
        self.assertTrue({"momentum_20d", "roe_ttm"}.issubset(factors[0]))

    def test_tradable_universe_returns_trade_ready_symbols(self) -> None:
        client = Client(default_format="records")

        rows = client.get_tradable_universe(
            asof_date="2024-01-02",
            universe="hs300",
            min_list_days=120,
        )

        self.assertEqual({row["symbol"] for row in rows}, {"600519.SH", "000001.SZ"})
        self.assertTrue(all(row["can_buy"] for row in rows))

    def test_index_and_industry_asof(self) -> None:
        client = Client(default_format="records")

        members = client.get_index_members_asof(
            index_code="000300.SH",
            asof_date="2024-06-28",
        )
        self.assertEqual({row["symbol"] for row in members}, {"600519.SH", "000001.SZ"})

        industry = client.get_industry_asof(
            symbols=["600519.SH"],
            industry_system="sw",
            level=1,
            asof_date="2024-12-31",
        )
        self.assertEqual(industry[0]["industry_name"], "食品饮料")

    def test_invalid_date_raises_validation_error(self) -> None:
        client = Client(default_format="records")

        with self.assertRaisesRegex(QDataValidationError, "YYYY-MM-DD"):
            client.get_trading_calendar(exchange="SH", start_date="2024/01/01", end_date="2024-01-31")


if __name__ == "__main__":
    unittest.main()
