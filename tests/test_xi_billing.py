from datetime import date
from decimal import Decimal
import unittest

from qdata.xi_billing import (
    budget_status,
    check_budget_allowed,
    period_window,
    priced_usage_amount,
)


class XiBillingTest(unittest.TestCase):
    def test_period_window_supports_daily_and_monthly(self) -> None:
        self.assertEqual(period_window("daily", "2026-07-26"), (date(2026, 7, 26), date(2026, 7, 26)))
        self.assertEqual(period_window("monthly", "2026-07-26"), (date(2026, 7, 1), date(2026, 7, 31)))

    def test_budget_status_thresholds(self) -> None:
        self.assertEqual(budget_status("0.69", "1.0", "0.7", "1.0", hard_limit_enabled=False)[0], "normal")
        self.assertEqual(budget_status("0.70", "1.0", "0.7", "1.0", hard_limit_enabled=False)[0], "warning")
        self.assertEqual(budget_status("1.00", "1.0", "0.7", "1.0", hard_limit_enabled=False)[0], "exceeded")
        self.assertEqual(budget_status("1.00", "1.0", "0.7", "1.0", hard_limit_enabled=True)[0], "blocked")

    def test_priced_usage_amount_uses_matching_api_rule_or_generic_rule(self) -> None:
        amount, details = priced_usage_amount(
            [
                {"api_name": "price", "request_count": 10, "row_count": 2000, "cost_units": Decimal("10.2")},
                {"api_name": "matrix", "request_count": 2, "row_count": 500, "cost_units": Decimal("2.05")},
            ],
            [
                {"api_name": "price", "metric_name": "request", "unit_price": Decimal("0.02"), "free_quantity": Decimal("0")},
                {"api_name": None, "metric_name": "cost_unit", "unit_price": Decimal("0.01"), "free_quantity": Decimal("0")},
            ],
            base_fee=Decimal("0.5"),
        )

        self.assertEqual(amount, Decimal("0.7205"))
        self.assertEqual(details["request_count"], 12)
        self.assertEqual(details["row_count"], 2500)
        self.assertEqual(details["cost_units"], Decimal("12.25"))

    def test_budget_check_skips_when_no_database_is_configured(self) -> None:
        identity = type("Identity", (), {"tenant_id": 1, "project_id": 1, "principal_id": 1, "cost_center": "research"})()
        decision = check_budget_allowed(None, identity=identity, api_name="price")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "not_configured")


if __name__ == "__main__":
    unittest.main()
