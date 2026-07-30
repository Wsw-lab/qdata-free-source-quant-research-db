from datetime import date
from decimal import Decimal
import unittest

from qdata.rho_revenue import (
    ar_aging_status,
    build_reconciliation_lines,
    customer_health_status,
)


class RhoRevenueTest(unittest.TestCase):
    def test_build_reconciliation_lines_flags_amount_mismatch(self) -> None:
        rows = build_reconciliation_lines(
            [
                {
                    "line_id": 7,
                    "product_id": 1,
                    "pricing_rule_id": 2,
                    "api_name": "price",
                    "metric_name": "cost_unit",
                    "quantity": Decimal("10.00000000"),
                    "unit_price": Decimal("0.0100000000"),
                    "amount": Decimal("0.12000000"),
                    "request_count": 10,
                    "row_count": 100,
                    "cost_units": Decimal("10.00000000"),
                }
            ],
            [
                {
                    "product_id": 1,
                    "pricing_rule_id": 2,
                    "api_name": "price",
                    "metric_name": "cost_unit",
                    "quantity": Decimal("10.00000000"),
                    "unit_price": Decimal("0.0100000000"),
                    "amount": Decimal("0.10000000"),
                    "request_count": 10,
                    "row_count": 100,
                    "cost_units": Decimal("10.00000000"),
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "mismatch")
        self.assertEqual(rows[0]["amount_delta"], Decimal("0.02000000"))

    def test_build_reconciliation_lines_detects_missing_and_extra_lines(self) -> None:
        rows = build_reconciliation_lines(
            [
                {
                    "line_id": 8,
                    "product_id": 1,
                    "pricing_rule_id": 3,
                    "api_name": "matrix",
                    "metric_name": "request",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("0.0200000000"),
                    "amount": Decimal("0.02000000"),
                }
            ],
            [
                {
                    "product_id": 1,
                    "pricing_rule_id": 2,
                    "api_name": "price",
                    "metric_name": "cost_unit",
                    "quantity": Decimal("10"),
                    "unit_price": Decimal("0.0100000000"),
                    "amount": Decimal("0.10000000"),
                }
            ],
        )

        statuses = {row["status"] for row in rows}
        self.assertEqual(statuses, {"missing_invoice_line", "extra_invoice_line"})

    def test_ar_aging_status_prioritizes_overdue_buckets(self) -> None:
        self.assertEqual(ar_aging_status(outstanding_amount="0"), "current")
        self.assertEqual(ar_aging_status(outstanding_amount="10", bucket_1_30_amount="10"), "overdue")
        self.assertEqual(ar_aging_status(outstanding_amount="10", bucket_90_plus_amount="1"), "critical")
        self.assertEqual(ar_aging_status(outstanding_amount="10"), "watch")

    def test_customer_health_status_uses_usage_recency_and_payment_risk(self) -> None:
        self.assertEqual(customer_health_status(date(2026, 7, 20), date(2026, 7, 26))[0], "active")
        self.assertEqual(
            customer_health_status(date(2026, 7, 20), date(2026, 7, 26), overdue_invoice_count=1)[:2],
            ("at_risk", "payment_risk"),
        )
        self.assertEqual(customer_health_status(date(2026, 5, 1), date(2026, 7, 26))[0], "dormant")
        self.assertEqual(customer_health_status(None, date(2026, 7, 26))[:2], ("churned", "no_usage"))


if __name__ == "__main__":
    unittest.main()
