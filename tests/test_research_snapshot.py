from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
                "sha256:31aa3ced6519ca05aecca5accf7dc7cc4393d4c962dc4c0bc34b7d81dce9b926",
            )
            self.assertEqual(manifest["datasets"]["daily_bar"]["row_count"], 4)
            self.assertEqual(
                manifest["datasets"]["daily_bar"]["date_range"],
                {"start": "2024-01-02", "end": "2024-01-03"},
            )
            self.assertEqual(manifest["datasets"]["fundamental_pit"]["row_count"], 2)

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
            daily_path.write_bytes(daily_path.read_bytes().replace(b"1715", b"1716", 1))

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


if __name__ == "__main__":
    unittest.main()
