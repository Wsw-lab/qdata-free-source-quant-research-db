import unittest

from examples.factor_backtest_demo import run_demo


class FactorBacktestDemoTest(unittest.TestCase):
    def test_demo_runs_on_mock_backend(self) -> None:
        result = run_demo()

        self.assertEqual(result["universe"], "hs300")
        self.assertEqual(result["factor"], "momentum_20d")
        self.assertEqual(result["tradable_symbol_count"], 2)
        self.assertEqual(result["long_symbols"], ["600519.SH"])
        self.assertEqual(result["short_symbols"], ["000001.SZ"])
        self.assertLess(result["active_return"], 0)
        self.assertEqual(len(result["research_rows"]), 2)


if __name__ == "__main__":
    unittest.main()
