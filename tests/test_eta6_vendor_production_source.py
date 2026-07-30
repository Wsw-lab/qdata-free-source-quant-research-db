from __future__ import annotations

import unittest

from qdata.eta6_vendor_production_source import (
    build_production_dataset_checks,
    build_production_decisions,
    build_production_source_run,
    evaluate_production_dataset,
    format_eta6_rows,
)


def _runtime(**overrides):
    data = {
        "source_code": "vendor_http",
        "provider_name": "vendor_http",
        "auth_mode": "bearer",
        "live_base_url_present": True,
        "live_token_present": True,
        "token_digest": "abc123def456",
        "token_digest_tail": "123def456",
        "redacted_config": {"token": "***", "base_url": "https://vendor.example/api"},
    }
    data.update(overrides)
    return data


def _row(**overrides):
    data = {
        "source_id": 1,
        "source_code": "vendor_http",
        "profile_id": 2,
        "vendor_profile_status": "active",
        "primary_source_id": 3,
        "primary_source_code": "csv",
        "dataset_id": 4,
        "dataset_code": "daily_bar",
        "contract_id": 5,
        "contract_code": "contract-active",
        "procurement_contract_status": "active",
        "contract_status": "active",
        "commercial_clearance": "clear",
        "contract_production_use_allowed": True,
        "entitlement_id": 6,
        "entitlement_code": "entitlement-active",
        "entitlement_status": "active",
        "allowed_role": "primary_candidate",
        "entitlement_commercial_use_allowed": True,
        "entitlement_redistribution_allowed": "yes",
        "entitlement_production_use_allowed": True,
        "schema_status": "validated",
        "field_mapping_status": "validated",
        "procurement_snapshot_id": 7,
        "procurement_snapshot_code": "proc-ready",
        "procurement_status": "ready",
        "procurement_role": "primary_candidate",
        "canary_pilot_id": 8,
        "canary_pilot_code": "canary",
        "canary_status": "success",
        "canary_signoff_status": "approved",
        "canary_recommendation": "primary_candidate",
        "canary_recommended_role": "primary_candidate",
        "full_market_pilot_id": 9,
        "full_market_pilot_code": "full",
        "full_market_status": "success",
        "full_market_signoff_status": "approved",
        "full_market_recommendation": "primary_candidate",
        "full_market_recommended_role": "primary_candidate",
        "promotion_id": 10,
        "promotion_code": "promotion",
        "promotion_result_id": 11,
        "promotion_result_code": "promotion-result",
        "promotion_status": "approved_for_primary",
        "promotion_result_status": "approved_for_primary",
        "stability_snapshot_id": 12,
        "stability_snapshot_code": "stability",
        "stability_status": "healthy",
        "stability_score": 95,
        "optimization_id": 13,
        "optimization_code": "optimization",
        "optimization_status": "optimized",
        "route_execution_id": 14,
        "route_execution_code": "route-execution",
        "route_execution_status": "staged",
        "route_policy_status": None,
        "current_primary_source_code": "csv",
        "is_primary_route": False,
        "recommended_primary_weight_pct": 90,
        "applied_primary_weight_pct": 10,
        "post_promotion_status": "healthy",
        "source_route_health_status": "healthy",
    }
    data.update(overrides)
    return data


class Eta6VendorProductionSourceTest(unittest.TestCase):
    def test_missing_real_vendor_env_blocks_before_contract(self) -> None:
        result = evaluate_production_dataset(
            _row(),
            runtime=_runtime(live_base_url_present=False, live_token_present=False),
            require_real_vendor_env=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_env:QDATA_VENDOR_BASE_URL", result["blocking_issues"])
        self.assertIn("missing_env:QDATA_VENDOR_TOKEN", result["blocking_issues"])

    def test_complete_evidence_is_production_ready_before_active_policy(self) -> None:
        result = evaluate_production_dataset(_row(), runtime=_runtime())

        self.assertEqual(result["status"], "production_ready")
        self.assertEqual(result["production_role"], "primary_candidate")
        self.assertEqual(result["production_score"], 100.0)

    def test_active_route_policy_moves_to_monitoring(self) -> None:
        checks = build_production_dataset_checks(
            [_row(route_execution_status="applied", route_policy_status="active", is_primary_route=True)],
            as_of_date="2026-07-30",
            runtime=_runtime(),
        )
        decisions = build_production_decisions(checks, runtime=_runtime())
        run = build_production_source_run(
            checks,
            decisions,
            runtime=_runtime(token_digest="super-secret-digest", token_digest_tail="cret-digest"),
            source_code="vendor_http",
            primary_source_code="csv",
            as_of_date="2026-07-30",
        )
        report = format_eta6_rows("runs", [run])

        self.assertEqual(checks[0]["status"], "monitoring")
        self.assertEqual(run["status"], "monitoring")
        self.assertEqual(run["production_role"], "primary")
        self.assertEqual(run["applied_dataset_count"], 1)
        self.assertIn("eta6 resource=runs rows=1", report)
        self.assertIn("status=monitoring", report)
        self.assertNotIn("super-secret", report)


if __name__ == "__main__":
    unittest.main()
