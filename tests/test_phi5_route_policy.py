import tempfile
import unittest
from unittest.mock import patch

from qdata.phi5_route_policy import (
    build_route_candidates,
    deterministic_bucket,
    finalize_route_decision,
    resolve_source_route,
    select_route_candidate,
)
from qdata.sources.sync import sync_daily_market


class Phi5RoutePolicyTest(unittest.TestCase):
    def test_weighted_selection_is_deterministic(self) -> None:
        candidates = build_route_candidates(
            {
                "source_code": "vendor_http",
                "backup_source_code": "csv",
                "primary_weight_pct": 100,
                "backup_weight_pct": 0,
                "free_source_weight_pct": 0,
            },
            requested_source_code="csv",
        )

        first = select_route_candidate(candidates, "daily_bar:2024-01-04:600519.SH")
        second = select_route_candidate(candidates, "daily_bar:2024-01-04:600519.SH")

        self.assertEqual(first, second)
        self.assertEqual(first["source_code"], "vendor_http")
        self.assertGreaterEqual(deterministic_bucket("stable"), 0)
        self.assertLess(deterministic_bucket("stable"), 100)

    def test_resolve_without_dsn_preserves_requested_source(self) -> None:
        decision = resolve_source_route(
            None,
            dataset_code="daily_bar",
            requested_source_code="csv",
            as_of_date="2024-01-04",
            request_key="demo",
            decision_context="sync",
        )

        self.assertEqual(decision["route_mode"], "default")
        self.assertEqual(decision["selected_source_code"], "csv")

    def test_resolve_skips_open_circuit_candidate(self) -> None:
        policy = {
            "policy_id": 1,
            "policy_code": "phi5-policy",
            "dataset_id": 10,
            "dataset_code": "daily_bar",
            "source_id": 20,
            "source_code": "vendor_http",
            "backup_source_id": 21,
            "backup_source_code": "csv",
            "primary_weight_pct": 80,
            "backup_weight_pct": 20,
            "free_source_weight_pct": 0,
        }

        with patch("qdata.phi5_route_policy.load_active_route_policies", return_value=[policy]), patch(
            "qdata.phi5_route_policy.load_source_route_circuit_states",
            return_value={("daily_bar", "vendor_http"): {"status": "open", "open_until": None}},
        ):
            decision = resolve_source_route(
                "postgresql://unused",
                dataset_code="daily_bar",
                requested_source_code="csv",
                as_of_date="2024-01-04",
                request_key="demo",
                decision_context="sync",
            )

        self.assertEqual(decision["selected_source_code"], "csv")
        self.assertEqual(decision["details"]["circuit_skipped_sources"], ["vendor_http"])

    def test_finalize_marks_fallback_when_final_source_changes(self) -> None:
        decision = _decision(selected_source_code="csv_mirror", fallback_source_codes=["csv"])

        finalized = finalize_route_decision(
            decision,
            final_source_code="csv",
            status="fallback_success",
            attempt_sources=["csv_mirror", "csv"],
            row_count=1,
            duration_ms=12,
            fallback_reason="csv_mirror daily market fetch failed by configuration",
        )

        self.assertEqual(finalized["route_mode"], "fallback")
        self.assertTrue(finalized["fallback_applied"])
        self.assertEqual(finalized["final_source_code"], "csv")

    def test_sync_daily_market_uses_selected_route_source(self) -> None:
        audits = []

        with tempfile.TemporaryDirectory() as directory:
            result = sync_daily_market(
                provider_name="csv",
                trade_date="2024-01-04",
                symbols=["600519.SH"],
                postgres_dsn="postgresql://unused",
                clickhouse_dsn="http://unused",
                raw_root=directory,
                dry_run=True,
                provider_kwargs=_csv_kwargs(),
                route_provider_kwargs={"csv_mirror": {**_csv_kwargs(), "provider_name": "csv_mirror"}},
                use_route_policy=True,
                route_resolver=lambda *args, **kwargs: _decision(selected_source_code="csv_mirror"),
                route_audit_writer=lambda postgres_dsn, decision, **kwargs: audits.append(decision),
            )

        self.assertEqual(result["bundle"].provider, "csv_mirror")
        self.assertEqual(result["route_decision"]["selected_source_code"], "csv_mirror")
        self.assertEqual(audits[0]["decision_status"], "success")

    def test_sync_daily_market_falls_back_after_selected_source_failure(self) -> None:
        audits = []

        with tempfile.TemporaryDirectory() as directory:
            result = sync_daily_market(
                provider_name="csv",
                trade_date="2024-01-04",
                symbols=["600519.SH"],
                postgres_dsn="postgresql://unused",
                clickhouse_dsn="http://unused",
                raw_root=directory,
                dry_run=True,
                provider_kwargs=_csv_kwargs(),
                route_provider_kwargs={
                    "csv_mirror": {**_csv_kwargs(), "provider_name": "csv_mirror", "fail_daily": True},
                    "csv": _csv_kwargs(),
                },
                use_route_policy=True,
                route_resolver=lambda *args, **kwargs: _decision(selected_source_code="csv_mirror", fallback_source_codes=["csv"]),
                route_audit_writer=lambda postgres_dsn, decision, **kwargs: audits.append(decision),
            )

        self.assertEqual(result["bundle"].provider, "csv")
        self.assertTrue(result["route_decision"]["fallback_applied"])
        self.assertEqual(result["route_decision"]["final_source_code"], "csv")
        self.assertEqual(audits[0]["decision_status"], "fallback_success")
        self.assertEqual(audits[0]["attempt_sources"], ["csv_mirror", "csv"])


def _csv_kwargs() -> dict:
    return {
        "security_master_path": "raw/samples/security_master.csv",
        "trading_calendar_path": "raw/samples/trading_calendar.csv",
        "daily_bar_path": "raw/samples/daily_bar.csv",
    }


def _decision(selected_source_code: str = "csv_mirror", fallback_source_codes=None) -> dict:
    return {
        "decision_code": "phi5-route-test",
        "policy_code": "phi5-policy-test",
        "dataset_code": "daily_bar",
        "requested_source_code": "csv",
        "selected_source_code": selected_source_code,
        "final_source_code": selected_source_code,
        "decision_context": "sync",
        "route_mode": "policy_weighted",
        "decision_status": "selected",
        "selected_role": "primary",
        "primary_weight_pct": 100,
        "backup_weight_pct": 0,
        "free_source_weight_pct": 0,
        "selected_weight_pct": 100,
        "deterministic_bucket": 1,
        "candidate_sources": [selected_source_code] + list(fallback_source_codes or []),
        "fallback_source_codes": list(fallback_source_codes or []),
        "attempt_sources": [],
        "request_key": "test",
        "source_ids_by_code": {},
        "details": {},
    }


if __name__ == "__main__":
    unittest.main()
