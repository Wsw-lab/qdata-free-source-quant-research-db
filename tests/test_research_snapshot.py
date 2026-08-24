from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import localcontext
from pathlib import Path
from unittest.mock import patch

import qdata.research_snapshot as research_snapshot_module
from examples.build_research_snapshot import (
    FIXTURE_CUTOFF_TS,
    FIXTURE_DATA_VERSION,
    FIXTURE_QUALITY_STATUS,
    FIXTURE_SOURCE,
    FIXTURE_TIMEZONE,
    run,
    synthetic_datasets,
)
from qdata.research_snapshot import (
    SCHEMA_VERSION,
    SnapshotImmutableError,
    SnapshotValidationError,
    SnapshotVerificationError,
    build_research_snapshot,
    verify_research_snapshot,
)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _rewrite_and_resign_dataset(
    root: Path,
    dataset_name: str,
    old_value: bytes,
    new_value: bytes,
) -> None:
    dataset_path = root / f"{dataset_name}.csv"
    original_payload = dataset_path.read_bytes()
    rewritten_payload = original_payload.replace(old_value, new_value, 1)
    if rewritten_payload == original_payload:
        raise AssertionError(f"fixture value not found in {dataset_name}.csv")
    dataset_path.write_bytes(rewritten_payload)

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["datasets"][dataset_name]["sha256"] = hashlib.sha256(
        rewritten_payload
    ).hexdigest()
    manifest_without_id = dict(manifest)
    manifest_without_id.pop("snapshot_id")
    manifest["snapshot_id"] = "sha256:" + hashlib.sha256(
        _canonical_json(manifest_without_id)
    ).hexdigest()
    manifest_path.write_bytes(_canonical_json(manifest))


def _remove_market_date_and_resign(root: Path, trade_date: str) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for dataset_name in ("daily_bar", "tradability"):
        dataset_path = root / f"{dataset_name}.csv"
        with dataset_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames
            rows = list(reader)
        if fieldnames is None:
            raise AssertionError(f"{dataset_name}.csv has no header")
        retained = [row for row in rows if row["trade_date"] != trade_date]
        if len(rows) - len(retained) != 2:
            raise AssertionError(
                f"expected exactly two {dataset_name} rows for {trade_date}"
            )

        output = io.StringIO(newline="")
        writer = csv.DictWriter(
            output,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(retained)
        payload = output.getvalue().encode("utf-8")
        dataset_path.write_bytes(payload)

        metadata = manifest["datasets"][dataset_name]
        metadata["sha256"] = hashlib.sha256(payload).hexdigest()
        metadata["row_count"] = 4
        metadata["date_range"] = {
            "start": "2024-01-02",
            "end": "2024-01-04",
        }

    manifest_without_id = dict(manifest)
    manifest_without_id.pop("snapshot_id")
    manifest["snapshot_id"] = "sha256:" + hashlib.sha256(
        _canonical_json(manifest_without_id)
    ).hexdigest()
    manifest_path.write_bytes(_canonical_json(manifest))


def _add_daily_bar_end_timestamps(datasets) -> None:
    for row in datasets["daily_bar"]:
        row["bar_end_at"] = f"{row['trade_date']}T15:00:00+08:00"


def _market_row(datasets, dataset_name: str, symbol: str, trade_date: str):
    return next(
        row
        for row in datasets[dataset_name]
        if row["symbol"] == symbol and row.get("trade_date") == trade_date
    )


def _remove_market_key(datasets, symbol: str, trade_date: str) -> None:
    for dataset_name in ("daily_bar", "tradability"):
        datasets[dataset_name] = [
            row
            for row in datasets[dataset_name]
            if (row["symbol"], row["trade_date"]) != (symbol, trade_date)
        ]


def _membership_row(datasets, symbol: str):
    return next(
        row for row in datasets["security_membership"] if row["symbol"] == symbol
    )


class ResearchSnapshotTest(unittest.TestCase):
    def _build(self, path: Path, datasets=None):
        return build_research_snapshot(
            path,
            synthetic_datasets() if datasets is None else datasets,
            cutoff_ts=FIXTURE_CUTOFF_TS,
            timezone_name=FIXTURE_TIMEZONE,
            source=FIXTURE_SOURCE,
            data_version=FIXTURE_DATA_VERSION,
            quality_status=FIXTURE_QUALITY_STATUS,
        )

    def test_build_and_verify_complete_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            manifest = run(root)
            verified = verify_research_snapshot(root)

            self.assertEqual(verified, manifest)
            self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
            self.assertEqual(manifest["cutoff_ts"], "2024-05-01T08:00:00Z")
            self.assertEqual(manifest["timezone"], "Asia/Shanghai")
            self.assertEqual(manifest["source"], FIXTURE_SOURCE)
            self.assertEqual(manifest["data_version"], FIXTURE_DATA_VERSION)
            self.assertEqual(
                manifest["snapshot_id"],
                "sha256:0b7a9697ceccc81cf74e131b74e9377c106160919da990910725011ad39c342b",
            )
            self.assertEqual(manifest["datasets"]["daily_bar"]["row_count"], 6)
            self.assertEqual(
                manifest["datasets"]["daily_bar"]["date_range"],
                {"start": "2024-01-02", "end": "2024-01-04"},
            )
            self.assertEqual(manifest["datasets"]["fundamental_pit"]["row_count"], 3)

            for name, metadata in manifest["datasets"].items():
                payload = (root / metadata["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), metadata["sha256"])
                self.assertEqual(metadata["path"], f"{name}.csv")

    def test_repeated_build_is_byte_deterministic_and_same_path_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            manifest_one = self._build(first)

            reversed_rows = synthetic_datasets()
            for rows in reversed_rows.values():
                rows.reverse()
            manifest_two = self._build(second, reversed_rows)
            manifest_three = self._build(first)

            self.assertEqual(manifest_one, manifest_two)
            self.assertEqual(manifest_one, manifest_three)
            for filename in (
                "daily_bar.csv",
                "tradability.csv",
                "security_membership.csv",
                "fundamental_pit.csv",
                "manifest.json",
            ):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

    def test_verify_rejects_file_hash_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            daily_path = root / "daily_bar.csv"
            original = daily_path.read_bytes()
            tampered = original.replace(b"1728", b"1729", 1)
            self.assertNotEqual(tampered, original)
            daily_path.write_bytes(tampered)

            with self.assertRaisesRegex(SnapshotVerificationError, "SHA256 mismatch"):
                verify_research_snapshot(root)

    def test_verify_rejects_duplicate_even_when_file_hash_is_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            daily_path = root / "daily_bar.csv"
            lines = daily_path.read_bytes().splitlines(keepends=True)
            payload = b"".join(lines + [lines[1]])
            daily_path.write_bytes(payload)

            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["datasets"]["daily_bar"]["sha256"] = hashlib.sha256(
                payload
            ).hexdigest()
            manifest_path.write_bytes(_canonical_json(manifest))

            with self.assertRaisesRegex(SnapshotVerificationError, "duplicate daily_bar"):
                verify_research_snapshot(root)

    def test_verify_rejects_late_row_even_when_file_hash_is_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            daily_path = root / "daily_bar.csv"
            payload = daily_path.read_bytes().replace(
                b"2024-01-02T07:05:00Z",
                b"2024-05-02T07:05:00Z",
                1,
            )
            self.assertNotEqual(payload, daily_path.read_bytes())
            daily_path.write_bytes(payload)

            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["datasets"]["daily_bar"]["sha256"] = hashlib.sha256(
                payload
            ).hexdigest()
            manifest_path.write_bytes(_canonical_json(manifest))

            with self.assertRaisesRegex(SnapshotVerificationError, "exceeds cutoff_ts"):
                verify_research_snapshot(root)

    def test_verify_rejects_resigned_next_local_date_signal_inputs(self) -> None:
        cases = {
            "daily_bar": b"2024-01-03T07:05:00Z",
            "tradability": b"2024-01-03T01:15:00Z",
        }

        for dataset_name, original_available_at in cases.items():
            with self.subTest(dataset_name=dataset_name):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / "snapshot"
                    self._build(root)
                    _rewrite_and_resign_dataset(
                        root,
                        dataset_name,
                        original_available_at,
                        b"2024-01-03T16:05:00Z",
                    )

                    with self.assertRaisesRegex(
                        SnapshotVerificationError,
                        "signal_available_at local date 2024-01-04.*trade_date 2024-01-03",
                    ):
                        verify_research_snapshot(root)

    def test_builder_accepts_signal_when_later_input_is_on_trade_date(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "600519.SH", "2024-01-03"
        )
        tradability["available_at"] = "2024-01-02T23:59:00+08:00"

        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._build(Path(tmp) / "snapshot", datasets)

        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)

    def test_verify_accepts_resigned_snapshot_with_whole_market_date_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            _remove_market_date_and_resign(root, "2024-01-03")

            verified = verify_research_snapshot(root)

        self.assertEqual(verified["datasets"]["daily_bar"]["row_count"], 4)
        self.assertEqual(verified["datasets"]["tradability"]["row_count"], 4)

    def test_verify_rejects_unknown_schema_even_with_canonical_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = "research_snapshot_v999"
            manifest_path.write_bytes(_canonical_json(manifest))

            with self.assertRaisesRegex(SnapshotVerificationError, "unsupported schema_version"):
                verify_research_snapshot(root)

    def test_builder_rejects_missing_required_field(self) -> None:
        datasets = synthetic_datasets()
        del datasets["daily_bar"][0]["available_at"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "fields mismatch"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_duplicate_symbol_date(self) -> None:
        datasets = synthetic_datasets()
        datasets["daily_bar"].append(copy.deepcopy(datasets["daily_bar"][0]))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "duplicate daily_bar"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_available_at_after_cutoff(self) -> None:
        datasets = synthetic_datasets()
        datasets["tradability"][0]["available_at"] = "2024-05-02T09:15:00+08:00"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "exceeds cutoff_ts"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_naive_available_at(self) -> None:
        datasets = synthetic_datasets()
        datasets["daily_bar"][0]["available_at"] = "2024-01-03T15:05:00"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "explicit UTC offset"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_missing_tradability_row(self) -> None:
        datasets = synthetic_datasets()
        datasets["tradability"].pop()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "keys must match"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_jointly_missing_active_membership_market_key(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        _remove_market_key(datasets, "600519.SH", "2024-01-03")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError,
                "missing explicit daily_bar/tradability coverage.*600519.SH.*2024-01-03",
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_missing_membership_diagnostics_stop_after_five_missing_keys(
        self,
    ) -> None:
        class LookupBudget:
            def __init__(self) -> None:
                self.lookups = 0

            def __contains__(self, key) -> bool:
                self.lookups += 1
                if self.lookups > 5:
                    raise AssertionError("coverage validation scanned past its bound")
                return False

        start = date(2024, 1, 1)
        market_dates = [
            (start + timedelta(days=offset), f"2024-01-{offset + 1:02d}")
            for offset in range(10)
        ]
        present_keys = LookupBudget()

        missing = research_snapshot_module._first_missing_membership_keys(
            {"600519.SH": [(start, None)]},
            market_dates,
            present_keys,
            limit=5,
        )

        self.assertEqual(
            missing,
            [
                ("600519.SH", "2024-01-01"),
                ("600519.SH", "2024-01-02"),
                ("600519.SH", "2024-01-03"),
                ("600519.SH", "2024-01-04"),
                ("600519.SH", "2024-01-05"),
            ],
        )
        self.assertEqual(present_keys.lookups, 5)

    def test_builder_does_not_require_market_keys_outside_membership_interval(
        self,
    ) -> None:
        cases = {
            "before_new_listing": {
                "membership": {
                    "list_date": "2024-01-03",
                    "valid_from": "2024-01-03",
                },
                "removed_dates": ("2024-01-02",),
            },
            "exclusive_valid_to_and_after": {
                "membership": {
                    "delist_date": "2024-01-03",
                    "valid_to": "2024-01-03",
                },
                "removed_dates": ("2024-01-03", "2024-01-04"),
            },
        }

        for case_name, case in cases.items():
            with self.subTest(case_name=case_name):
                datasets = synthetic_datasets()
                membership = _membership_row(datasets, "000001.SZ")
                membership.update(case["membership"])
                for trade_date in case["removed_dates"]:
                    _remove_market_key(datasets, "000001.SZ", trade_date)

                with tempfile.TemporaryDirectory() as tmp:
                    manifest = self._build(Path(tmp) / "snapshot", datasets)

                self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)

    def test_builder_allows_membership_only_symbol_outside_market_date_range(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        datasets["security_membership"].append(
            {
                "symbol": "300001.SZ",
                "list_date": "2024-01-05",
                "delist_date": None,
                "valid_from": "2024-01-05",
                "valid_to": None,
                "board": "CHINEXT",
                "asset_type": "stock",
                "status": "active",
                "available_at": "2024-01-04T18:00:00+08:00",
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._build(Path(tmp) / "snapshot", datasets)

        self.assertEqual(manifest["datasets"]["security_membership"]["row_count"], 3)

    def test_builder_rejects_active_membership_only_symbol(self) -> None:
        datasets = synthetic_datasets()
        datasets["security_membership"].append(
            {
                "symbol": "300001.SZ",
                "list_date": "2024-01-02",
                "delist_date": None,
                "valid_from": "2024-01-02",
                "valid_to": None,
                "board": "CHINEXT",
                "asset_type": "stock",
                "status": "active",
                "available_at": "2024-01-01T18:00:00+08:00",
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError,
                "missing explicit daily_bar/tradability coverage.*300001.SZ.*2024-01-02",
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_uncovered_historical_membership(self) -> None:
        datasets = synthetic_datasets()
        datasets["security_membership"][0]["valid_from"] = "2024-02-01"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "no active security membership"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_failed_quality_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "requires passed"):
                build_research_snapshot(
                    Path(tmp) / "snapshot",
                    synthetic_datasets(),
                    cutoff_ts=FIXTURE_CUTOFF_TS,
                    timezone_name=FIXTURE_TIMEZONE,
                    source=FIXTURE_SOURCE,
                    data_version=FIXTURE_DATA_VERSION,
                    quality_status={
                        "status": "failed",
                        "error_count": 1,
                        "warning_count": 0,
                    },
                )

    def test_builder_never_overwrites_different_existing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            datasets = synthetic_datasets()
            datasets["daily_bar"][0]["close_raw"] = "1729"

            with self.assertRaisesRegex(SnapshotImmutableError, "different content"):
                self._build(root, datasets)

            # The original remains independently valid after the refused build.
            self.assertEqual(verify_research_snapshot(root)["data_version"], FIXTURE_DATA_VERSION)

    def test_verify_rejects_unexpected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            (root / "notes.txt").write_text("mutable sidecar", encoding="utf-8")

            with self.assertRaisesRegex(SnapshotVerificationError, "file set mismatch"):
                verify_research_snapshot(root)

    def test_cli_builds_and_verifies_fixture(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        script = repository_root / "examples" / "build_research_snapshot.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            built = subprocess.run(
                [sys.executable, str(script), "build", str(root)],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
            )
            verified = subprocess.run(
                [sys.executable, str(script), "verify", str(root)],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(json.loads(built.stdout), json.loads(verified.stdout))

    def test_adjacent_decimals_beyond_context_precision_do_not_collide(self) -> None:
        first_datasets = synthetic_datasets()
        second_datasets = synthetic_datasets()
        first_value = "1234567890123456789012345678901"
        second_value = "1234567890123456789012345678902"
        first_datasets["fundamental_pit"][0]["field_value"] = first_value
        second_datasets["fundamental_pit"][0]["field_value"] = second_value

        with tempfile.TemporaryDirectory() as tmp:
            first_root = Path(tmp) / "first"
            second_root = Path(tmp) / "second"
            first_manifest = self._build(first_root, first_datasets)
            second_manifest = self._build(second_root, second_datasets)
            first_payload = (first_root / "fundamental_pit.csv").read_text(
                encoding="utf-8"
            )
            second_payload = (second_root / "fundamental_pit.csv").read_text(
                encoding="utf-8"
            )

            self.assertIn(first_value, first_payload)
            self.assertIn(second_value, second_payload)
            self.assertNotEqual(first_payload, second_payload)
            self.assertNotEqual(
                first_manifest["snapshot_id"], second_manifest["snapshot_id"]
            )

    def test_decimal_rendering_is_independent_of_ambient_context_precision(self) -> None:
        datasets = synthetic_datasets()
        exact_value = "123456789012345678901234567890.123456789"
        datasets["fundamental_pit"][0]["field_value"] = exact_value

        with tempfile.TemporaryDirectory() as tmp:
            low_root = Path(tmp) / "low-precision"
            high_root = Path(tmp) / "high-precision"
            with localcontext() as context:
                context.prec = 6
                low_manifest = self._build(low_root, copy.deepcopy(datasets))
            with localcontext() as context:
                context.prec = 80
                high_manifest = self._build(high_root, copy.deepcopy(datasets))

            self.assertEqual(low_manifest["snapshot_id"], high_manifest["snapshot_id"])
            self.assertEqual(
                (low_root / "fundamental_pit.csv").read_bytes(),
                (high_root / "fundamental_pit.csv").read_bytes(),
            )
            self.assertIn(
                exact_value,
                (low_root / "fundamental_pit.csv").read_text(encoding="utf-8"),
            )

    def test_integer_rendering_is_canonical_across_equivalent_exponents(self) -> None:
        plain_datasets = synthetic_datasets()
        exponent_datasets = synthetic_datasets()
        exponent_datasets["tradability"][0]["lot_size"] = "1E+2"

        with tempfile.TemporaryDirectory() as tmp:
            plain_root = Path(tmp) / "plain"
            exponent_root = Path(tmp) / "exponent"
            plain_manifest = self._build(plain_root, plain_datasets)
            exponent_manifest = self._build(exponent_root, exponent_datasets)

            self.assertEqual(
                (plain_root / "tradability.csv").read_bytes(),
                (exponent_root / "tradability.csv").read_bytes(),
            )
            self.assertEqual(
                plain_manifest["snapshot_id"], exponent_manifest["snapshot_id"]
            )

    def test_decimal_renderer_preserves_extreme_exponents_and_canonicalizes_negative_zero(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        rows = datasets["fundamental_pit"]
        rows[0]["field_name"] = "large_exact"
        rows[0]["field_value"] = "1E+30"
        rows[1]["field_name"] = "small_exact"
        rows[1]["field_value"] = "1E-30"
        negative_zero = copy.deepcopy(rows[0])
        negative_zero["field_name"] = "negative_zero"
        negative_zero["field_value"] = "-0E+20"
        rows.append(negative_zero)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root, datasets)
            with (root / "fundamental_pit.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                values = {
                    row["field_name"]: row["field_value"]
                    for row in csv.DictReader(handle)
                }

            self.assertEqual(values["large_exact"], "1000000000000000000000000000000")
            self.assertEqual(values["small_exact"], "0.000000000000000000000000000001")
            self.assertEqual(values["negative_zero"], "0")

    def test_decimal_renderer_uses_exact_scientific_form_for_huge_exponents(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        rows = datasets["fundamental_pit"]
        rows[0]["field_name"] = "huge_positive_exponent"
        rows[0]["field_value"] = "1E+100000"
        rows[1]["field_name"] = "huge_negative_exponent"
        rows[1]["field_value"] = "1E-100000"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root, datasets)
            with (root / "fundamental_pit.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                values = {
                    row["field_name"]: row["field_value"]
                    for row in csv.DictReader(handle)
                }

            self.assertEqual(values["huge_positive_exponent"], "1e100000")
            self.assertEqual(values["huge_negative_exponent"], "1e-100000")

    def test_builder_requires_daily_bar_end_at(self) -> None:
        datasets = synthetic_datasets()
        datasets["daily_bar"][0].pop("bar_end_at", None)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "bar_end_at"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_daily_bar_end_without_timezone_offset(self) -> None:
        datasets = synthetic_datasets()
        _add_daily_bar_end_timestamps(datasets)
        datasets["daily_bar"][0]["bar_end_at"] = "2024-01-03T15:00:00"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "explicit UTC offset"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_daily_bar_end_on_different_trade_date(self) -> None:
        datasets = synthetic_datasets()
        _add_daily_bar_end_timestamps(datasets)
        datasets["daily_bar"][0]["bar_end_at"] = "2024-01-04T15:00:00+08:00"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SnapshotValidationError, "bar_end_at date"):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_daily_bar_available_before_bar_end(self) -> None:
        datasets = synthetic_datasets()
        _add_daily_bar_end_timestamps(datasets)
        datasets["daily_bar"][0]["available_at"] = "2024-01-03T14:59:59+08:00"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "available_at precedes bar_end_at"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_daily_bar_available_on_next_manifest_local_date(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        daily = _market_row(datasets, "daily_bar", "600519.SH", "2024-01-03")
        daily["available_at"] = "2024-01-03T16:05:00Z"

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError,
                "signal_available_at local date 2024-01-04.*trade_date 2024-01-03",
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_tradability_available_on_next_manifest_local_date(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "600519.SH", "2024-01-03"
        )
        tradability["available_at"] = "2024-01-03T16:05:00Z"

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError,
                "signal_available_at local date 2024-01-04.*trade_date 2024-01-03",
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_report_period_after_each_disclosure_local_date(
        self,
    ) -> None:
        cases = {
            "published_at": {
                "published_at": "2024-01-03T23:30:00+08:00",
                "first_seen_at": "2024-01-04T00:05:00+08:00",
                "available_at": "2024-01-04T00:10:00+08:00",
            },
            "first_seen_at": {
                "published_at": "2024-01-04T00:01:00+08:00",
                "first_seen_at": "2024-01-03T23:30:00+08:00",
                "available_at": "2024-01-04T00:10:00+08:00",
            },
            "available_at": {
                "published_at": "2024-01-03T23:00:00+08:00",
                "first_seen_at": "2024-01-03T23:30:00+08:00",
                "available_at": "2024-01-03T23:45:00+08:00",
            },
        }

        for field, timestamps in cases.items():
            with self.subTest(field=field):
                datasets = synthetic_datasets()
                fundamental = datasets["fundamental_pit"][0]
                fundamental["report_period_end"] = "2024-01-04"
                fundamental.update(timestamps)

                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaisesRegex(
                        SnapshotValidationError,
                        rf"report_period_end 2024-01-04.*{field} local date 2024-01-03",
                    ):
                        self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_uses_manifest_local_date_for_fundamental_disclosures(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        fundamental = datasets["fundamental_pit"][0]
        fundamental.update(
            {
                "report_period_end": "2024-01-04",
                "published_at": "2024-01-03T16:00:00Z",
                "first_seen_at": "2024-01-03T16:05:00Z",
                "available_at": "2024-01-03T16:10:00Z",
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._build(Path(tmp) / "snapshot", datasets)

        self.assertEqual(manifest["timezone"], "Asia/Shanghai")

    def test_builder_rejects_limit_up_not_above_limit_down(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "600519.SH", "2024-01-03"
        )
        tradability["limit_up"] = "1700"
        tradability["limit_down"] = "1700"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "limit_up must exceed limit_down"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_both_limit_flags_true(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "600519.SH", "2024-01-03"
        )
        tradability.update(
            {
                "is_limit_up": True,
                "is_limit_down": True,
                "can_buy": False,
                "can_sell": False,
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "limit flags are mutually exclusive"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_true_limit_up_flag_when_close_is_below_limit(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "600519.SH", "2024-01-03"
        )
        tradability["is_limit_up"] = True
        tradability["can_buy"] = False
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "is_limit_up disagrees with close_raw"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_false_limit_up_flag_when_close_equals_limit(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "600519.SH", "2024-01-03"
        )
        daily = _market_row(datasets, "daily_bar", "600519.SH", "2024-01-03")
        tradability["limit_up"] = daily["close_raw"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "is_limit_up disagrees with close_raw"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_false_limit_down_flag_when_close_equals_limit(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "000001.SZ", "2024-01-02"
        )
        daily = _market_row(datasets, "daily_bar", "000001.SZ", "2024-01-02")
        tradability["limit_down"] = daily["close_raw"]
        tradability["is_limit_down"] = False
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "is_limit_down disagrees with close_raw"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_close_outside_declared_limit_range(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "600519.SH", "2024-01-03"
        )
        tradability["limit_up"] = "1700"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "close_raw is outside declared limit range"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_suspended_bar_with_nonzero_volume(self) -> None:
        datasets = synthetic_datasets()
        tradability = _market_row(
            datasets, "tradability", "000001.SZ", "2024-01-03"
        )
        tradability.update(
            {"is_suspended": True, "can_buy": False, "can_sell": False}
        )
        daily = _market_row(datasets, "daily_bar", "000001.SZ", "2024-01-03")
        daily["volume"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError,
                "suspended daily bar must have zero volume and amount",
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_open_membership_for_delisted_security(self) -> None:
        datasets = synthetic_datasets()
        membership = _membership_row(datasets, "000001.SZ")
        membership["delist_date"] = "2024-01-04"
        membership["valid_to"] = None
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "delist_date requires exclusive valid_to"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_membership_extending_after_delist_date(self) -> None:
        datasets = synthetic_datasets()
        membership = _membership_row(datasets, "000001.SZ")
        membership["delist_date"] = "2024-01-03"
        membership["valid_to"] = "2024-01-04"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "valid_to cannot exceed delist_date"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_empty_exclusive_membership_interval(self) -> None:
        datasets = synthetic_datasets()
        membership = _membership_row(datasets, "000001.SZ")
        membership["valid_to"] = membership["valid_from"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "valid_to must be after valid_from"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_membership_valid_to_is_exclusive(self) -> None:
        datasets = synthetic_datasets()
        membership = _membership_row(datasets, "000001.SZ")
        membership["valid_to"] = "2024-01-03"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError,
                "2024-01-03.*no active security membership",
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_overlapping_membership_intervals(self) -> None:
        datasets = synthetic_datasets()
        overlapping = copy.deepcopy(_membership_row(datasets, "600519.SH"))
        overlapping["valid_from"] = "2024-01-01"
        datasets["security_membership"].append(overlapping)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError,
                "overlapping security membership intervals",
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_builder_rejects_membership_start_before_listing(self) -> None:
        datasets = synthetic_datasets()
        membership = _membership_row(datasets, "000001.SZ")
        membership["valid_from"] = "1991-04-02"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                SnapshotValidationError, "valid_from precedes list_date"
            ):
                self._build(Path(tmp) / "snapshot", datasets)

    def test_verify_rejects_symlinked_dataset_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            daily_path = root / "daily_bar.csv"
            external = Path(tmp) / "external-daily.csv"
            external.write_bytes(daily_path.read_bytes())
            daily_path.unlink()
            daily_path.symlink_to(external)

            with self.assertRaisesRegex(SnapshotVerificationError, "regular file"):
                verify_research_snapshot(root)

    def test_verify_rejects_hardlinked_dataset_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            daily_path = root / "daily_bar.csv"
            external = Path(tmp) / "external-daily.csv"
            external.write_bytes(daily_path.read_bytes())
            daily_path.unlink()
            os.link(external, daily_path)

            with self.assertRaisesRegex(SnapshotVerificationError, "hard link"):
                verify_research_snapshot(root)

    def test_failed_publication_preserves_all_entries_and_refuses_rebuild(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            intruder_payload = b"not-created-by-the-snapshot-builder\n"
            original_mkdir = Path.mkdir

            def mkdir_with_concurrent_entry(path, *args, **kwargs):
                result = original_mkdir(path, *args, **kwargs)
                if path == root:
                    (root / "fundamental_pit.csv").write_bytes(intruder_payload)
                return result

            with patch.object(Path, "mkdir", new=mkdir_with_concurrent_entry):
                with self.assertRaisesRegex(
                    SnapshotImmutableError, "concurrent entry"
                ):
                    self._build(root)

            self.assertEqual(
                (root / "fundamental_pit.csv").read_bytes(), intruder_payload
            )
            daily_path = root / "daily_bar.csv"
            self.assertTrue(
                daily_path.exists(),
                "a reserved destination must retain builder-created entries",
            )
            builder_payload = daily_path.read_bytes()
            self.assertIn(b"symbol,trade_date", builder_payload)
            self.assertFalse((root / "manifest.json").exists())

            with self.assertRaisesRegex(
                SnapshotVerificationError, "file set mismatch"
            ):
                verify_research_snapshot(root)
            with self.assertRaisesRegex(SnapshotImmutableError, "unverifiable"):
                self._build(root)

            self.assertEqual(
                (root / "fundamental_pit.csv").read_bytes(), intruder_payload
            )
            self.assertEqual(daily_path.read_bytes(), builder_payload)

    def test_verify_rejects_same_inode_rewrite_with_restored_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            self._build(root)
            daily_path = root / "daily_bar.csv"
            original_payload = daily_path.read_bytes()
            tampered_payload = original_payload.replace(b"1728", b"1729", 1)
            self.assertNotEqual(tampered_payload, original_payload)
            self.assertEqual(len(tampered_payload), len(original_payload))
            original_stat = daily_path.stat()
            original_validator = (
                research_snapshot_module._validate_cross_dataset_contract
            )
            mutation_happened = False

            def mutate_after_semantic_validation(rows_by_dataset):
                nonlocal mutation_happened
                original_validator(rows_by_dataset)
                if mutation_happened:
                    return
                with daily_path.open("r+b") as handle:
                    handle.write(tampered_payload)
                    handle.truncate()
                os.utime(
                    daily_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )
                mutation_happened = True

            with patch.object(
                research_snapshot_module,
                "_validate_cross_dataset_contract",
                side_effect=mutate_after_semantic_validation,
            ):
                with self.assertRaisesRegex(
                    SnapshotVerificationError, "changed during verification"
                ):
                    verify_research_snapshot(root)

            tampered_stat = daily_path.stat()
            self.assertTrue(mutation_happened)
            self.assertEqual(tampered_stat.st_ino, original_stat.st_ino)
            self.assertEqual(tampered_stat.st_size, original_stat.st_size)
            self.assertEqual(tampered_stat.st_mtime_ns, original_stat.st_mtime_ns)
            self.assertNotEqual(tampered_stat.st_ctime_ns, original_stat.st_ctime_ns)
            self.assertEqual(daily_path.read_bytes(), tampered_payload)

    def test_fixture_manifest_labels_contract_demo_as_non_performance_evidence(
        self,
    ) -> None:
        expected_notice = (
            "Deterministic synthetic format/contract demonstration; not market data, "
            "strategy, or performance evidence."
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            manifest = run(root)

            self.assertEqual(manifest.get("artifact_notice"), expected_notice)
            self.assertEqual(manifest["source"], "deterministic_synthetic_fixture")

    def test_fixture_has_three_contiguous_sessions_and_a_next_session_fill_path(
        self,
    ) -> None:
        datasets = synthetic_datasets()
        trade_dates = sorted(
            {row["trade_date"] for row in datasets["daily_bar"]}
        )

        self.assertEqual(trade_dates, ["2024-01-02", "2024-01-03", "2024-01-04"])
        jan_four = [
            row
            for row in datasets["tradability"]
            if row["trade_date"] == "2024-01-04"
        ]
        self.assertTrue(any(row["can_buy"] for row in jan_four))

    def test_fixture_contains_st_suspension_and_both_limit_directions(self) -> None:
        datasets = synthetic_datasets()
        rows = datasets["tradability"]

        self.assertTrue(any(row["is_st"] for row in rows))
        self.assertTrue(any(row["is_suspended"] for row in rows))
        self.assertTrue(any(row["is_limit_up"] for row in rows))
        self.assertTrue(any(row["is_limit_down"] for row in rows))
        for tradability in (row for row in rows if row["is_suspended"]):
            daily = _market_row(
                datasets,
                "daily_bar",
                tradability["symbol"],
                tradability["trade_date"],
            )
            self.assertFalse(tradability["can_buy"])
            self.assertFalse(tradability["can_sell"])
            self.assertEqual(daily["volume"], "0")
            self.assertEqual(daily["amount"], "0")

    def test_fixture_contains_pre_signal_fundamental_and_later_revision(self) -> None:
        datasets = synthetic_datasets()
        rows = [
            row
            for row in datasets["fundamental_pit"]
            if row["symbol"] == "600519.SH"
            and row["field_name"] == "roe_ttm"
            and row["report_period_end"] == "2023-09-30"
        ]
        by_revision = {row["revision_id"]: row for row in rows}

        self.assertEqual(set(by_revision), {"original", "restatement-1"})
        self.assertEqual(
            by_revision["original"]["available_at"],
            "2023-10-23T09:00:00+08:00",
        )
        self.assertEqual(
            by_revision["restatement-1"]["available_at"],
            "2024-01-04T09:00:00+08:00",
        )
        self.assertTrue(by_revision["restatement-1"]["is_restated"])

    def test_fixture_contains_legal_exclusive_delisting_boundary(self) -> None:
        datasets = synthetic_datasets()
        membership = _membership_row(datasets, "000001.SZ")
        symbol_dates = [
            row["trade_date"]
            for row in datasets["daily_bar"]
            if row["symbol"] == "000001.SZ"
        ]

        self.assertEqual(membership["valid_to"], membership["delist_date"])
        self.assertIsNotNone(membership["valid_to"])
        self.assertTrue(all(day < membership["valid_to"] for day in symbol_dates))


if __name__ == "__main__":
    unittest.main()
