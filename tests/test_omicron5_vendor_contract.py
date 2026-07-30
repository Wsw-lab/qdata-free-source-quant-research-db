import unittest

from qdata.omicron5_vendor_contract import (
    build_vendor_contract_required_actions,
    build_vendor_contract_snapshots,
    evaluate_vendor_contract_readiness,
    format_omicron5_rows,
)


def _row(**overrides):
    values = {
        "source_id": 2,
        "dataset_id": 3,
        "contract_id": 11,
        "entitlement_id": 21,
        "profile_id": 31,
        "source_code": "vendor_http",
        "dataset_code": "daily_bar",
        "contract_code": "omicron5-contract-vendor_http-active",
        "entitlement_code": "omicron5-entitlement-vendor_http-daily_bar",
        "provider_name": "Commercial HTTP Vendor",
        "procurement_status": "active",
        "contract_status": "active",
        "commercial_clearance": "clear",
        "redistribution_allowed": "yes",
        "contract_production_use_allowed": True,
        "contract_ref": "msa-2026-001",
        "contract_end_date": "2027-07-28",
        "next_review_at": None,
        "contract_rate_limit_per_min": 120,
        "contract_daily_quota": 200000,
        "contract_monthly_quota": 5000000,
        "contract_sla_uptime_pct": 99.9,
        "contract_profile_status": "active",
        "contract_evidence": {"contract_ref": "msa-2026-001"},
        "entitlement_status": "active",
        "entitlement_allowed_role": "primary_candidate",
        "entitlement_commercial_use_allowed": True,
        "entitlement_redistribution_allowed": "yes",
        "entitlement_production_use_allowed": True,
        "schema_status": "validated",
        "field_mapping_status": "validated",
        "entitlement_rate_limit_per_min": 120,
        "entitlement_daily_quota": 200000,
        "entitlement_sla_uptime_pct": 99.9,
        "max_delay_minutes": 30,
        "entitlement_profile_status": "active",
        "entitlement_evidence": {"schema_status": "validated"},
        "vendor_profile_status": "active",
        "latest_review_code": "pi-ready-demo",
        "pi_readiness_status": "ready",
        "pi_recommendation": "approve_primary",
        "latest_gate_code": "epsilon3-ready-demo",
        "live_gate_status": "success",
        "latest_onboarding_code": "zeta3-ready-demo",
        "onboarding_status": "success",
        "latest_closure_code": "eta3-ready-demo",
        "live_closure_status": "success",
        "latest_pilot_code": "theta3-ready-demo",
        "live_pilot_status": "success",
    }
    values.update(overrides)
    return values


class Omicron5VendorContractTest(unittest.TestCase):
    def test_evaluate_ready_primary_candidate_when_rights_sla_and_schema_are_clear(self) -> None:
        result = evaluate_vendor_contract_readiness(_row(), {"min_sla_uptime_pct": 99.5, "min_rate_limit_per_min": 60, "require_live_evidence": True})

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["procurement_role"], "primary_candidate")
        self.assertEqual(result["readiness_score"], 100.0)

    def test_evaluate_review_required_for_draft_contract(self) -> None:
        result = evaluate_vendor_contract_readiness(
            _row(
                procurement_status="review_required",
                contract_status="draft",
                commercial_clearance="review_required",
                redistribution_allowed="unknown",
                contract_production_use_allowed=False,
                contract_ref=None,
                entitlement_status="review_required",
                entitlement_commercial_use_allowed=False,
                entitlement_redistribution_allowed="unknown",
                entitlement_production_use_allowed=False,
                schema_status="pending",
                field_mapping_status="pending",
                entitlement_daily_quota=None,
                entitlement_sla_uptime_pct=None,
                max_delay_minutes=None,
                vendor_profile_status="testing",
                pi_readiness_status=None,
                live_gate_status=None,
                live_pilot_status=None,
            )
        )

        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["procurement_role"], "validator")
        self.assertIn("contract_status_draft", result["blocking_issues"])
        self.assertIn("entitlement_commercial_use_not_allowed", result["blocking_issues"])

    def test_evaluate_blocks_expired_or_denied_redistribution(self) -> None:
        result = evaluate_vendor_contract_readiness(_row(redistribution_allowed="no", entitlement_redistribution_allowed="no"))

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["procurement_role"], "blocked")
        self.assertIn("redistribution_allowed_no", result["blocking_issues"])

    def test_build_snapshots_preserves_evidence_policy(self) -> None:
        snapshots = build_vendor_contract_snapshots([_row()], as_of_date="2026-07-28", requested_by="test", trigger_mode="smoke")

        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0]["evidence"]["policy"]["primary_candidate_requires_active_contract"])
        self.assertEqual(snapshots[0]["latest_pilot_code"], "theta3-ready-demo")

    def test_required_actions_name_contract_rights_and_sla_work(self) -> None:
        actions = build_vendor_contract_required_actions(
            [
                "contract_status_draft",
                "commercial_clearance_review_required",
                "redistribution_allowed_unknown",
                "rate_limit_per_min_missing",
                "sla_uptime_pct_missing",
                "schema_status_pending",
            ],
            "review_required",
            "validator",
        )

        joined = " ".join(actions)
        self.assertIn("signed master data contract", joined)
        self.assertIn("commercial-use clearance", joined)
        self.assertIn("redistribution/cache rights", joined)
        self.assertIn("SLA uptime", joined)

    def test_format_omicron5_rows_prefers_contract_fields(self) -> None:
        report = format_omicron5_rows(
            "readiness",
            [
                {
                    "snapshot_code": "omicron5-procurement-demo",
                    "source_code": "vendor_http",
                    "dataset_code": "daily_bar",
                    "status": "review_required",
                    "procurement_role": "validator",
                    "contract_status": "draft",
                }
            ],
        )

        self.assertIn("omicron5 resource=readiness rows=1", report)
        self.assertIn("snapshot_code=omicron5-procurement-demo", report)
        self.assertIn("procurement_role=validator", report)


if __name__ == "__main__":
    unittest.main()
