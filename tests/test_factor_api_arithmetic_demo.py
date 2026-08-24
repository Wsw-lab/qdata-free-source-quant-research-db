import unittest

from examples.factor_api_arithmetic_demo import format_report, run_demo


class FactorApiArithmeticDemoTest(unittest.TestCase):
    def test_demo_uses_forward_adjusted_references_without_execution_claims(self) -> None:
        result = run_demo()

        self.assertEqual(result["universe"], "hs300")
        self.assertEqual(result["factor"], "momentum_20d")
        self.assertEqual(result["signal_timing"], "after_close")
        self.assertEqual(
            result.get("reference_timing"),
            "next_session_forward_adjusted_open_to_close",
        )
        self.assertGreater(result["reference_date"], result["signal_date"])
        self.assertIs(result["next_session_tradability_verified"], False)
        self.assertEqual(result["signal_universe_symbol_count"], 2)
        self.assertEqual(result["highest_factor_symbols"], ["600519.SH"])
        self.assertEqual(result["lowest_factor_symbols"], ["000001.SZ"])
        self.assertAlmostEqual(
            result["highest_factor_marked_change"], 0.005306603773584906
        )
        self.assertAlmostEqual(
            result["lowest_factor_marked_change"], 0.010460251046025105
        )

        forbidden_result_fields = {
            "execution_date",
            "exit_date",
            "fill_timing",
            "long_symbols",
            "short_symbols",
            "long_return",
            "short_return",
            "benchmark_return",
            "active_return",
            "factor_spread",
        }
        self.assertTrue(forbidden_result_fields.isdisjoint(result))

        self.assertEqual(len(result["research_rows"]), 2)
        for row in result["research_rows"]:
            self.assertIn("adjusted_open_reference", row)
            self.assertIn("adjusted_close_mark", row)
            self.assertIn("marked_change", row)
            self.assertNotIn("entry_open", row)
            self.assertNotIn("exit_close", row)
            self.assertNotIn("next_return", row)

        report = format_report(result)
        self.assertIn(
            "reference_timing=next_session_forward_adjusted_open_to_close", report
        )
        self.assertIn("next_session_tradability_verified=false", report)
        self.assertNotIn("fill", report.lower())
        self.assertNotIn("return", report.lower())
        self.assertNotIn("execution", report.lower())


if __name__ == "__main__":
    unittest.main()
