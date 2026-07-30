import unittest

from qdata.xi5_free_source_admission import (
    build_admission_snapshots,
    build_required_actions,
    evaluate_source_admission,
    format_xi5_rows,
)


def _row(**overrides):
    values = {
        "source_id": 1,
        "dataset_id": 3,
        "profile_id": 10,
        "reliability_snapshot_id": 20,
        "source_code": "vendor_free",
        "source_type": "vendor",
        "source_license_scope": "contracted",
        "dataset_code": "daily_bar",
        "profile_code": "xi5-profile-vendor_free",
        "license_type": "paid_contract",
        "license_status": "contracted",
        "commercial_clearance": "clear",
        "redistribution_allowed": "yes",
        "contract_status": "active",
        "contract_ref": "contract-001",
        "terms_review_status": "approved",
        "api_terms_url": "https://example.invalid/terms",
        "rate_limit_per_min": 120,
        "daily_quota": 50000,
        "max_allowed_role": "primary_candidate",
        "profile_status": "active",
        "reviewed_by": "legal",
        "reviewed_at": "2026-07-28T00:00:00+00:00",
        "expires_at": None,
        "profile_evidence": {"contract_ref": "contract-001"},
        "reliability_snapshot_code": "kappa5-free-source-demo",
        "reliability_status": "ready",
        "reliability_score": 94.0,
        "success_rate": 1.0,
        "coverage_rate": 0.99,
        "conflict_rate_bps": 1.0,
        "observation_count": 6,
        "reliability_evidence": {"observation_samples": [{"fabric_code": "iota5-demo", "status": "success"}]},
    }
    values.update(overrides)
    return values


class Xi5FreeSourceAdmissionTest(unittest.TestCase):
    def test_evaluate_approves_primary_candidate_only_when_legal_and_reliable(self) -> None:
        result = evaluate_source_admission(_row())

        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["admission_role"], "primary_candidate")
        self.assertIn("controlled primary-candidate pilot", " ".join(result["required_actions"]))

    def test_evaluate_requires_review_for_reliable_free_source_without_rights(self) -> None:
        result = evaluate_source_admission(
            _row(
                source_code="akshare",
                license_type="open_source",
                license_status="research_only",
                commercial_clearance="blocked",
                redistribution_allowed="no",
                contract_status="none",
                terms_review_status="pending",
                rate_limit_per_min=None,
                daily_quota=None,
                max_allowed_role="validator",
                reliability_score=82.0,
            )
        )

        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["admission_role"], "validator")
        self.assertIn("license_status_research_only", result["blocking_issues"])
        self.assertIn("redistribution_allowed_no", result["blocking_issues"])

    def test_evaluate_blocks_no_data_from_routing(self) -> None:
        result = evaluate_source_admission(_row(reliability_status="no_data", observation_count=0, reliability_score=0))

        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["admission_role"], "blocked")
        self.assertIn("no_recent_reliability_snapshot", result["blocking_issues"])

    def test_build_admission_snapshots_keeps_evidence_and_fabric(self) -> None:
        snapshots = build_admission_snapshots([_row()], as_of_date="2026-07-28", requested_by="test", trigger_mode="smoke")

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["latest_fabric_code"], "iota5-demo")
        self.assertTrue(snapshots[0]["evidence"]["policy"]["free_source_requires_contract_for_primary"])

    def test_required_actions_names_legal_and_quota_work(self) -> None:
        actions = build_required_actions(
            [
                "commercial_clearance_blocked",
                "redistribution_allowed_unknown",
                "contract_status_none",
                "terms_review_status_pending",
                "rate_limit_per_min_missing",
            ],
            "review_required",
            "validator",
        )

        joined = " ".join(actions)
        self.assertIn("commercial-use clearance", joined)
        self.assertIn("redistribution/cache rights", joined)
        self.assertIn("active contract_ref", joined)
        self.assertIn("rate limit", joined)

    def test_format_xi5_rows_prefers_admission_fields(self) -> None:
        report = format_xi5_rows(
            "snapshots",
            [
                {
                    "snapshot_code": "xi5-admission-demo",
                    "source_code": "akshare",
                    "dataset_code": "daily_bar",
                    "status": "review_required",
                    "admission_role": "validator",
                    "blocking_issues": ["commercial_clearance_blocked"],
                }
            ],
        )

        self.assertIn("xi5 resource=snapshots rows=1", report)
        self.assertIn("snapshot_code=xi5-admission-demo", report)
        self.assertIn("admission_role=validator", report)


if __name__ == "__main__":
    unittest.main()
