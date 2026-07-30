import unittest

from qdata.sources.field_mapping import FieldMappingRule, normalize_vendor_row, rules_to_mapping
from qdata.theta import build_vendor_decision, load_vendor_runtime_config, run_sharded_provider_benchmark


class ThetaTest(unittest.TestCase):
    def test_field_mapping_rules_transform_vendor_row(self) -> None:
        mapping, transforms = rules_to_mapping(
            [
                FieldMappingRule("tradeDate", "trade_date", "date_yyyymmdd"),
                FieldMappingRule("vol", "volume", "volume_hand_to_share"),
                FieldMappingRule("turnover_pct", "turnover_rate", "pct_to_ratio"),
            ]
        )

        row = normalize_vendor_row(
            {"tradeDate": "20240104", "vol": 2, "turnover_pct": 1.5},
            mapping,
            transforms,
        )

        self.assertEqual(row["trade_date"], "2024-01-04")
        self.assertEqual(row["volume"], 200)
        self.assertEqual(row["turnover_rate"], 0.015)

    def test_sharded_benchmark_aggregates_fixture_vendor(self) -> None:
        suite = run_sharded_provider_benchmark(
            primary_provider="csv",
            secondary_provider="vendor_http",
            start_date="2024-01-04",
            end_date="2024-01-04",
            symbols=["600519.SH", "000001.SZ"],
            fields=["close"],
            shard_size=1,
            secondary_kwargs={
                "fixture_daily_bar_path": "raw/samples/daily_bar.csv",
                "close_offset_bps": 10,
            },
        )

        self.assertEqual(suite.symbol_count, 2)
        self.assertEqual(suite.shard_count, 2)
        self.assertEqual(suite.benchmark_count, 2)
        self.assertEqual(suite.primary_row_count, 2)
        self.assertEqual(suite.secondary_row_count, 2)
        self.assertEqual(suite.conflict_count, 2)
        self.assertEqual(suite.coverage_rate, 1.0)
        self.assertEqual(suite.status, "warning")

    def test_vendor_decision_keeps_high_score_conflicting_vendor_as_backup(self) -> None:
        decision = build_vendor_decision(
            {
                "source_code": "vendor_http",
                "dataset_code": "daily_bar",
                "score_date": "2024-01-04",
                "total_score": 93.8,
                "rating": "A",
                "conflict_rate": 0.16666667,
                "failure_rate": 0,
                "latency_ms": 100,
                "license_risk_score": 80,
            }
        )

        self.assertEqual(decision.recommendation, "approve_backup")
        self.assertEqual(decision.recommended_role, "backup")
        self.assertTrue(decision.blocking_issues)

    def test_vendor_runtime_config_reads_environment_without_leaking_secret(self) -> None:
        config = load_vendor_runtime_config(
            environ={
                "QDATA_VENDOR_BASE_URL": "https://vendor.example",
                "QDATA_VENDOR_TOKEN": "secret",
                "QDATA_VENDOR_AUTH_MODE": "bearer",
                "QDATA_VENDOR_RATE_LIMIT_PER_MIN": "120",
            }
        )

        self.assertEqual(config.base_url, "https://vendor.example")
        self.assertEqual(config.token, "secret")
        self.assertEqual(config.auth_mode, "bearer")
        self.assertEqual(config.rate_limit_per_min, 120)


if __name__ == "__main__":
    unittest.main()
