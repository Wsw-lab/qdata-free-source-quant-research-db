from datetime import date
from decimal import Decimal
import unittest

from qdata.exceptions import QDataValidationError
from qdata.omicron_billing import build_invoice_lines, invoice_period_window, invoice_status


class OmicronBillingTest(unittest.TestCase):
    def test_invoice_period_window_validates_order(self) -> None:
        self.assertEqual(invoice_period_window("2026-07-01", "2026-07-31"), (date(2026, 7, 1), date(2026, 7, 31)))
        with self.assertRaises(QDataValidationError):
            invoice_period_window("2026-08-01", "2026-07-31")

    def test_invoice_status_tracks_receivable_and_payment_state(self) -> None:
        self.assertEqual(invoice_status("1.00", "0", "2026-07-31", "2026-07-26"), "issued")
        self.assertEqual(invoice_status("1.00", "0.40", "2026-07-31", "2026-07-26"), "partially_paid")
        self.assertEqual(invoice_status("1.00", "1.00", "2026-07-31", "2026-07-26"), "paid")
        self.assertEqual(invoice_status("1.00", "0", "2026-07-31", "2026-08-01"), "overdue")
        self.assertEqual(invoice_status("1.00", "0", "2026-07-31", "2026-08-01", current_status="draft"), "draft")

    def test_build_invoice_lines_uses_base_fee_exact_rule_and_generic_rule(self) -> None:
        lines, summary = build_invoice_lines(
            [
                {"api_name": "price", "request_count": 10, "row_count": 2000, "cost_units": Decimal("10.2")},
                {"api_name": "matrix", "request_count": 2, "row_count": 500, "cost_units": Decimal("2.05")},
            ],
            [
                {
                    "pricing_rule_id": 1,
                    "rule_code": "price_request",
                    "api_name": "price",
                    "metric_name": "request",
                    "unit_price": Decimal("0.02"),
                    "free_quantity": Decimal("0"),
                },
                {
                    "pricing_rule_id": 2,
                    "rule_code": "generic_cost_unit",
                    "api_name": None,
                    "metric_name": "cost_unit",
                    "unit_price": Decimal("0.01"),
                    "free_quantity": Decimal("0"),
                },
            ],
            base_fee=Decimal("0.5"),
            product_id=7,
            period_start="2026-07-01",
            period_end="2026-07-31",
        )

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["metric_name"], "base_fee")
        self.assertEqual(lines[1]["api_name"], "price")
        self.assertEqual(lines[1]["amount"], Decimal("0.20000000"))
        self.assertEqual(lines[2]["api_name"], "matrix")
        self.assertEqual(lines[2]["amount"], Decimal("0.02050000"))
        self.assertEqual(summary["subtotal_amount"], Decimal("0.72050000"))
        self.assertEqual(summary["request_count"], 12)
        self.assertEqual(summary["row_count"], 2500)
        self.assertEqual(summary["cost_units"], Decimal("12.25000000"))


if __name__ == "__main__":
    unittest.main()
