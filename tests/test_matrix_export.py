import unittest

from scripts.export_price_matrix import _to_matrix


class MatrixExportTest(unittest.TestCase):
    def test_to_matrix_preserves_symbol_order_and_dates(self) -> None:
        rows = [
            {"symbol": "000001.SZ", "trade_date": "2024-01-04", "close": 9.11},
            {"symbol": "600519.SH", "trade_date": "2024-01-04", "close": 912.55},
            {"symbol": "600519.SH", "trade_date": "2024-01-05", "close": 900.0},
        ]

        matrix = _to_matrix(rows, ["600519.SH", "000001.SZ"], "close")

        self.assertEqual(matrix[0]["trade_date"], "2024-01-04")
        self.assertEqual(list(matrix[0]), ["trade_date", "600519.SH", "000001.SZ"])
        self.assertEqual(matrix[0]["600519.SH"], 912.55)
        self.assertIsNone(matrix[1]["000001.SZ"])


if __name__ == "__main__":
    unittest.main()
