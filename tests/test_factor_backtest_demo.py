import unittest

from examples.factor_backtest_demo import run_demo


class FactorBacktestDemoTest(unittest.TestCase):
    def test_demo_uses_after_close_signal_and_next_open_arithmetic(self) -> None:
        result = run_demo()

        self.assertEqual(result["universe"], "hs300")
        self.assertEqual(result["factor"], "momentum_20d")
        self.assertEqual(result.get("signal_timing"), "after_close")
        self.assertEqual(result.get("fill_timing"), "next_session_open")
        self.assertEqual(result.get("mark_timing"), "next_session_close")
        self.assertGreater(result.get("execution_date", ""), result["signal_date"])
        self.assertEqual(result["exit_date"], result["execution_date"])
        self.assertEqual(result["tradable_symbol_count"], 2)
        self.assertEqual(result["long_symbols"], ["600519.SH"])
        self.assertEqual(result["short_symbols"], ["000001.SZ"])
        self.assertAlmostEqual(result["long_return"], 0.005306603773584906)
        self.assertAlmostEqual(result["short_return"], 0.010460251046025105)
        self.assertEqual(len(result["research_rows"]), 2)


if __name__ == "__main__":
    unittest.main()
