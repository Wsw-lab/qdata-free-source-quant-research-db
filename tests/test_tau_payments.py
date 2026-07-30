from __future__ import annotations

from decimal import Decimal
import unittest

from qdata.exceptions import QDataValidationError
from qdata.tau_payments import (
    extract_invoice_code,
    format_payment_import,
    format_payment_matches,
    import_payment_records,
    payment_match_decision,
)


class TauPaymentsTest(unittest.TestCase):
    def test_payment_match_decision_handles_exact_partial_overpay_and_unmatched(self) -> None:
        exact = payment_match_decision(invoice_outstanding_amount="100.00000000", payment_amount="100.00000000")
        self.assertEqual(exact["status"], "matched")
        self.assertEqual(exact["match_type"], "auto_exact")
        self.assertEqual(exact["matched_amount"], Decimal("100.00000000"))

        partial = payment_match_decision(invoice_outstanding_amount="100.00000000", payment_amount="40.00000000")
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["matched_amount"], Decimal("40.00000000"))

        overpaid = payment_match_decision(invoice_outstanding_amount="100.00000000", payment_amount="120.00000000")
        self.assertEqual(overpaid["status"], "overpaid")
        self.assertEqual(overpaid["unmatched_amount"], Decimal("20.00000000"))

        unmatched = payment_match_decision(invoice_outstanding_amount="0", payment_amount="120.00000000")
        self.assertEqual(unmatched["status"], "unmatched")
        self.assertEqual(unmatched["matched_amount"], Decimal("0E-8"))

    def test_payment_match_decision_rejects_non_positive_payment(self) -> None:
        with self.assertRaises(QDataValidationError):
            payment_match_decision(invoice_outstanding_amount="100", payment_amount="0")

    def test_extract_invoice_code_from_reference_text(self) -> None:
        self.assertEqual(
            extract_invoice_code("付款 for inv-demo-quant-research-a_share_daily_core-tau-20260727 已到账"),
            "inv-demo-quant-research-a_share_daily_core-tau-20260727",
        )
        self.assertIsNone(extract_invoice_code("no invoice here"))

    def test_import_payment_records_dry_run_normalizes_batch_and_transactions(self) -> None:
        payload = import_payment_records(
            "postgresql://unused",
            [
                {
                    "external_transaction_id": "bank-001",
                    "transaction_time": "2026-07-27T09:30:00+00:00",
                    "value_date": "2026-07-27",
                    "amount": "88.12000000",
                    "currency": "CNY",
                    "payment_channel": "bank",
                    "direction": "inbound",
                    "reference_text": "payment for inv-demo-quant",
                }
            ],
            batch_code="tau-test-batch",
            source_type="bank_csv",
            account_code="bank-cny",
            statement_start="2026-07-27",
            statement_end="2026-07-27",
            write_db=False,
        )

        self.assertEqual(payload["batch"]["batch_code"], "tau-test-batch")
        self.assertEqual(payload["batch"]["transaction_count"], 1)
        self.assertEqual(payload["batch"]["total_amount"], "88.12000000")
        self.assertEqual(payload["transactions"][0]["details"]["invoice_code_hint"], "inv-demo-quant")
        self.assertIn("tau_import batch=tau-test-batch", format_payment_import(payload))
        self.assertIn("tau_matches rows=1", format_payment_matches([{"status": "matched"}]))


if __name__ == "__main__":
    unittest.main()
